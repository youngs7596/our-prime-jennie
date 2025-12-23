#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Version: v1.0
# 작업 LLM: GPT-5.1 Codex
"""
scripts/collect_dart_filings.py

DART(OpenDartReader) API를 사용해 최근 공시 메타데이터를 수집하여
`STOCK_DISCLOSURES` 테이블에 저장합니다. (MariaDB 단일 지원)
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List

from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

import shared.auth as auth
import shared.database as database
from shared.hybrid_scoring.schema import execute_upsert

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TABLE_NAME = "STOCK_DISCLOSURES"

REPORT_CODE_CATEGORY = {
    "A001": "정기공시",
    "A002": "정정공시",
    "A003": "연장신고",
    "B001": "주요사항보고",
    "B002": "주요보고사항",
    "C001": "발행공시",
    "D001": "지분공시",
    "E001": "기타공시",
    "F001": "외부감사",
}


def _is_mariadb() -> bool:
    # 단일화: MariaDB만 사용
    return True


def ensure_table_exists(connection):
    cursor = connection.cursor()
    try:
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                ID INT AUTO_INCREMENT PRIMARY KEY,
                RECEIPT_NO VARCHAR(20) UNIQUE,
                STOCK_CODE VARCHAR(20) NOT NULL,
                COMPANY_NAME VARCHAR(255),
                DISCLOSURE_DATE DATETIME,
                REPORT_CODE VARCHAR(10),
                CATEGORY VARCHAR(50),
                TITLE VARCHAR(1000),
                LINK VARCHAR(2000),
                SCRAPED_AT DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        connection.commit()
        logger.info(f"✅ 테이블 확인 완료: {TABLE_NAME}")
    except Exception as e:
        connection.rollback()
        raise
    finally:
        cursor.close()


def get_db_config():
    # 레거시 호환용(현재 미사용): MariaDB 단일화로 더 이상 외부 설정 dict를 만들 필요가 없습니다.
    return {}


def load_stock_codes(limit: int = None) -> List[str]:
    import FinanceDataReader as fdr
    codes = fdr.StockListing("KOSPI")["Code"].tolist()
    if limit:
        return codes[:limit]
    return codes


def fetch_filings(dart_client, stock_code: str, start: str, end: str) -> List[Dict]:
    """
    DART 공시 목록 조회
    
    OpenDartReader.list() 파라미터:
    - corp: 종목코드 또는 회사명
    - start: 시작일 (YYYY-MM-DD)
    - end: 종료일 (YYYY-MM-DD)
    """
    try:
        # 날짜 형식 변환 (YYYYMMDD -> YYYY-MM-DD)
        start_formatted = f"{start[:4]}-{start[4:6]}-{start[6:8]}"
        end_formatted = f"{end[:4]}-{end[4:6]}-{end[6:8]}"
        
        df = dart_client.list(corp=stock_code, start=start_formatted, end=end_formatted)
        if df is None or len(df) == 0:
            return []
        return df.to_dict("records")
    except Exception as e:
        logger.debug(f"⚠️ [{stock_code}] DART 조회 실패: {e}")
        return []


def normalize_report(record: Dict, stock_code: str = None) -> Dict:
    """DART API 응답을 정규화"""
    report_code = record.get("report_code")
    category = REPORT_CODE_CATEGORY.get(report_code, "기타")
    receipt_no = record.get("rcept_no")
    link = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_no}" if receipt_no else None
    disclosure_date = record.get("rcept_dt")
    if disclosure_date:
        disclosure_dt = datetime.strptime(str(disclosure_date), "%Y%m%d")
    else:
        disclosure_dt = None
    
    # stock_code는 파라미터로 전달받거나, API 응답에서 가져옴
    code = stock_code or record.get("stock_code") or record.get("corp_code", "")
    
    return {
        "receipt_no": receipt_no,
        "stock_code": code,
        "company_name": record.get("corp_name"),
        "disclosure_date": disclosure_dt,
        "report_code": report_code,
        "category": category,
        "title": record.get("report_nm"),
        "link": link,
    }


def save_reports(connection, reports: List[Dict]):
    if not reports:
        return 0
    cursor = connection.cursor()
    saved = 0
    for report in reports:
        if not report["receipt_no"]:
            continue
        columns = [
            "RECEIPT_NO", "STOCK_CODE", "COMPANY_NAME", "DISCLOSURE_DATE",
            "REPORT_CODE", "CATEGORY", "TITLE", "LINK", "SCRAPED_AT",
        ]
        values = (
            report["receipt_no"],
            report["stock_code"],
            report["company_name"],
            report["disclosure_date"],
            report["report_code"],
            report["category"],
            report["title"],
            report["link"],
            datetime.utcnow(),
        )
        execute_upsert(
            cursor,
            TABLE_NAME,
            columns,
            values,
            unique_keys=["RECEIPT_NO"],
            update_columns=[
                "STOCK_CODE", "COMPANY_NAME", "DISCLOSURE_DATE",
                "REPORT_CODE", "CATEGORY", "TITLE", "LINK", "SCRAPED_AT",
            ],
        )
        saved += 1
    connection.commit()
    cursor.close()
    return saved


def parse_args():
    parser = argparse.ArgumentParser(description="DART 공시 수집기")
    parser.add_argument("--days", type=int, default=180, help="수집 기간(일)")
    parser.add_argument("--codes", type=int, default=50, help="KOSPI 상위 N개 종목만 수집")
    parser.add_argument("--api-key", type=str, default=None, help="OpenDartReader API Key (.env 우선)")
    return parser.parse_args()


def main():
    load_dotenv()
    args = parse_args()
    
    # secrets.json 경로 설정 (프로젝트 루트)
    if not os.getenv("SECRETS_FILE"):
        os.environ["SECRETS_FILE"] = os.path.join(PROJECT_ROOT, "secrets.json")
    
    # API 키 우선순위: CLI 인자 > 환경변수 > secrets.json
    api_key = args.api_key or os.getenv("DART_API_KEY")
    if not api_key:
        # secrets.json에서 읽기 시도
        api_key = auth.get_secret("dart-api-key")
    
    if not api_key:
        logger.error("❌ DART_API_KEY가 설정되지 않았습니다.")
        logger.error("   secrets.json에 'dart-api-key'를 추가하거나,")
        logger.error("   환경변수 DART_API_KEY를 설정하세요.")
        return
    
    logger.info(f"✅ DART API 키 로드 완료 (길이: {len(api_key)})")

    try:
        import OpenDartReader
    except ImportError:
        logger.error("OpenDartReader 라이브러리가 필요합니다. (pip install OpenDartReader)")
        return

    dart = OpenDartReader(api_key)  # OpenDartReader 모듈 자체가 클래스
    conn = database.get_db_connection()
    if not conn:
        logger.error("DB 연결 실패")
        return

    ensure_table_exists(conn)

    end_date = datetime.now()
    start_date = end_date - timedelta(days=args.days)
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")

    stock_codes = load_stock_codes(args.codes)
    total_saved = 0

    for idx, code in enumerate(stock_codes, start=1):
        logger.info(f"[{idx}/{len(stock_codes)}] {code} 공시 수집 ({start_str} ~ {end_str})")
        filings = fetch_filings(dart, stock_code=code, start=start_str, end=end_str)
        # stock_code를 함께 전달하여 정규화
        normalized = [normalize_report(rec, stock_code=code) for rec in filings]
        saved = save_reports(conn, normalized)
        total_saved += saved
        logger.info(f"   ↳ {len(normalized)}건 중 {saved}건 저장 (누적 {total_saved})")

    conn.close()
    logger.info(f"✅ DART 공시 수집 완료 (총 {total_saved}건)")


if __name__ == "__main__":
    main()

