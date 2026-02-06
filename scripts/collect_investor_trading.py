#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/collect_investor_trading.py

KRX(pykrx 라이브러리)를 통해 외국인/기관 순매수 데이터를 수집하여
`STOCK_INVESTOR_TRADING` 테이블에 저장합니다.

데이터 소스: KRX 정보데이터시스템 (pykrx 래퍼)

Usage:
    python3 scripts/collect_investor_trading.py --days 365 --codes 100
    python3 scripts/collect_investor_trading.py --days 730 --codes 200
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List

from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

import shared.database as database
from shared.hybrid_scoring.schema import execute_upsert
from shared.kis import KISGatewayClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TABLE_NAME = "STOCK_INVESTOR_TRADING"


def _is_mariadb() -> bool:
    # 단일화: MariaDB만 사용
    return True


def ensure_table_exists(connection):
    """테이블이 없으면 생성"""
    cursor = connection.cursor()
    try:
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                ID INT AUTO_INCREMENT PRIMARY KEY,
                TRADE_DATE DATE NOT NULL,
                STOCK_CODE VARCHAR(20) NOT NULL,
                STOCK_NAME VARCHAR(100),
                FOREIGN_BUY BIGINT DEFAULT 0 COMMENT '외국인 매수량',
                FOREIGN_SELL BIGINT DEFAULT 0 COMMENT '외국인 매도량',
                FOREIGN_NET_BUY BIGINT DEFAULT 0 COMMENT '외국인 순매수량',
                INSTITUTION_BUY BIGINT DEFAULT 0 COMMENT '기관 매수량',
                INSTITUTION_SELL BIGINT DEFAULT 0 COMMENT '기관 매도량',
                INSTITUTION_NET_BUY BIGINT DEFAULT 0 COMMENT '기관 순매수량',
                INDIVIDUAL_BUY BIGINT DEFAULT 0 COMMENT '개인 매수량',
                INDIVIDUAL_SELL BIGINT DEFAULT 0 COMMENT '개인 매도량',
                INDIVIDUAL_NET_BUY BIGINT DEFAULT 0 COMMENT '개인 순매수량',
                CLOSE_PRICE INT DEFAULT 0 COMMENT '종가',
                VOLUME BIGINT DEFAULT 0 COMMENT '거래량',
                SCRAPED_AT DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY UK_DATE_CODE (TRADE_DATE, STOCK_CODE)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='외국인/기관 투자자별 매매 데이터'
        """)
        connection.commit()
        logger.info(f"✅ 테이블 확인 완료: {TABLE_NAME}")
    except Exception as e:
        logger.error(f"❌ 테이블 생성 실패: {e}")
        connection.rollback()
        raise
    finally:
        cursor.close()


def get_db_config():
    # 레거시 호환용(현재 미사용): MariaDB 단일화로 더 이상 외부 설정 dict를 만들 필요가 없습니다.
    return {}


def load_stock_codes(limit: int = None, target_codes: List[str] = None) -> List[str]:
    """DB에서 종목 코드 로드 (KOSPI/KOSDAQ)"""
    # 타겟 코드가 있으면 바로 반환
    if target_codes:
        return target_codes

    conn = database.get_db_connection()
    try:
        cursor = conn.cursor()
        query = "SELECT DISTINCT STOCK_CODE FROM STOCK_DAILY_PRICES_3Y ORDER BY STOCK_CODE"
        if limit:
            query += f" LIMIT {limit}"
        cursor.execute(query)
        rows = cursor.fetchall()
        
        codes = []
        for row in rows:
            if isinstance(row, dict):
                codes.append(row['STOCK_CODE'])
            else:
                codes.append(row[0])
        return codes
    finally:
        conn.close()


def fetch_investor_trading_by_date(kis_api, date_str: str, stock_codes: List[str]) -> List[Dict]:
    """
    특정 날짜의 투자자별 매매 데이터 조회 (KIS Gateway 사용)
    참고: KIS API는 전 종목 통계보다 종목별 조회가 더 정확하고 게이트웨이에도 구현됨.
    날짜별 모드에서도 내부적으로 종목별 loop 호출을 수행합니다.
    """
    results = []
    for code in stock_codes:
        res = fetch_investor_trading_by_stock(kis_api, code, date_str, date_str)
        results.extend(res)
        # KIS Gateway rate limit(19/sec)이 속도를 제어하므로 별도 sleep 불필요
    return results


def fetch_investor_trading_by_stock(kis_api, stock_code: str, start_date: str, end_date: str) -> List[Dict]:
    """
    특정 종목의 기간별 투자자 매매 데이터 조회 (KIS Gateway 사용)
    """
    results = []
    
    try:
        # KIS API를 통해 투자자별 매매동향 조회
        # gateway_client.get_market_data().get_investor_trend() 반환 형식:
        # [{'date': '20260108', 'price': 50000.0, 'individual_net_buy': 100, 'foreigner_net_buy': -50, 'institution_net_buy': -50, ...}, ...]
        trends = kis_api.get_market_data().get_investor_trend(stock_code, start_date, end_date)
        
        if not trends:
            return results
        
        for item in trends:
            try:
                trade_date_str = item['date']
                trade_date = datetime.strptime(trade_date_str, "%Y%m%d").date()
                
                results.append({
                    'trade_date': trade_date,
                    'stock_code': stock_code,
                    'stock_name': '',  # 후속 처리에서 채워질 수도 있음
                    'foreign_buy': 0,   # KIS 상세 수량은 별도 tr_id 필요할 수 있음. 일단 순매수 중심.
                    'foreign_sell': 0,
                    'foreign_net_buy': int(item.get('foreigner_net_buy', 0)),
                    'institution_buy': 0,
                    'institution_sell': 0,
                    'institution_net_buy': int(item.get('institution_net_buy', 0)),
                    'individual_buy': 0,
                    'individual_sell': 0,
                    'individual_net_buy': int(item.get('individual_net_buy', 0)),
                    'close_price': int(item.get('price', 0)),
                    'volume': 0,
                })
            except Exception as e:
                logger.debug(f"   ⚠️ {stock_code} {item.get('date')} 파싱 실패: {e}")
                continue
    
    except Exception as e:
        logger.warning(f"   ⚠️ {stock_code} 데이터 조회 실패: {e}")
    
    return results


def save_trading_data(connection, data_list: List[Dict]) -> int:
    """투자자 매매 데이터 저장"""
    if not data_list:
        return 0
    
    cursor = connection.cursor()
    saved = 0
    
    for data in data_list:
        try:
            columns = [
                "TRADE_DATE", "STOCK_CODE", "STOCK_NAME",
                "FOREIGN_BUY", "FOREIGN_SELL", "FOREIGN_NET_BUY",
                "INSTITUTION_BUY", "INSTITUTION_SELL", "INSTITUTION_NET_BUY",
                "INDIVIDUAL_BUY", "INDIVIDUAL_SELL", "INDIVIDUAL_NET_BUY",
                "CLOSE_PRICE", "VOLUME", "SCRAPED_AT"
            ]
            values = (
                data['trade_date'],
                data['stock_code'],
                data.get('stock_name', ''),
                data.get('foreign_buy', 0),
                data.get('foreign_sell', 0),
                data.get('foreign_net_buy', 0),
                data.get('institution_buy', 0),
                data.get('institution_sell', 0),
                data.get('institution_net_buy', 0),
                data.get('individual_buy', 0),
                data.get('individual_sell', 0),
                data.get('individual_net_buy', 0),
                data.get('close_price', 0),
                data.get('volume', 0),
                datetime.now(),
            )
            
            execute_upsert(
                cursor,
                TABLE_NAME,
                columns,
                values,
                unique_keys=["TRADE_DATE", "STOCK_CODE"],
                update_columns=[
                    "STOCK_NAME", "FOREIGN_BUY", "FOREIGN_SELL", "FOREIGN_NET_BUY",
                    "INSTITUTION_BUY", "INSTITUTION_SELL", "INSTITUTION_NET_BUY",
                    "INDIVIDUAL_BUY", "INDIVIDUAL_SELL", "INDIVIDUAL_NET_BUY",
                    "CLOSE_PRICE", "VOLUME", "SCRAPED_AT"
                ]
            )
            saved += 1
        except Exception as e:
            logger.debug(f"   ⚠️ 저장 실패 ({data.get('stock_code')}): {e}")
    
    connection.commit()
    cursor.close()
    return saved


def parse_args():
    parser = argparse.ArgumentParser(description="외국인/기관 투자자 매매 데이터 수집기")
    parser.add_argument("--days", type=int, default=365, help="수집 기간(일)")
    parser.add_argument("--codes", type=int, default=None, help="수집할 종목 수 (기본값: 전체)")
    parser.add_argument("--target-codes", type=str, default=None, help="수집할 종목 코드 리스트 (콤마 구분)")
    parser.add_argument("--mode", type=str, default="by_stock", 
                        choices=["by_stock", "by_date"],
                        help="수집 모드: by_stock(종목별), by_date(날짜별)")
    parser.add_argument("--sleep", type=float, default=0.5, help="요청 간 대기 시간(초)")
    return parser.parse_args()


def main():
    load_dotenv()
    args = parse_args()
    
    # secrets.json 경로 설정 (프로젝트 루트)
    if not os.getenv("SECRETS_FILE"):
        os.environ["SECRETS_FILE"] = os.path.join(PROJECT_ROOT, "secrets.json")
    
    logger.info("=" * 60)
    logger.info(f"📈 외국인/기관 매매 데이터 수집 시작")
    logger.info(f"   - 기간: {args.days}일")
    logger.info(f"   - 종목 수: {args.codes if args.codes else '전체'}")
    logger.info(f"   - 모드: {args.mode}")
    logger.info("=" * 60)
    
    # DB 연결
    # shared.database.get_db_connection handles config internally or via env vars
    from shared.db.connection import init_engine
    init_engine()
    
    conn = database.get_db_connection()
    if not conn:
        logger.error("❌ DB 연결 실패")
        return
    
    ensure_table_exists(conn)
    
    # 종목 코드 로드
    target_codes_list = args.target_codes.split(',') if args.target_codes else None
    stock_codes = load_stock_codes(args.codes, target_codes_list)
    logger.info(f"   📊 대상 종목: {len(stock_codes)}개")
    
    # 날짜 범위
    end_date = datetime.now()
    start_date = end_date - timedelta(days=args.days)
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    
    # KIS Gateway 클라이언트 초기화
    # 로컬에서 실행되므로 localhost:8080 시도
    gateway_url = os.getenv("KIS_GATEWAY_URL", "http://127.0.0.1:8080")
    kis_api = KISGatewayClient(gateway_url=gateway_url)
    
    total_saved = 0
    
    if args.mode == "by_stock":
        # 종목별로 수집 (더 안정적)
        for idx, code in enumerate(stock_codes, start=1):
            try:
                logger.info(f"[{idx}/{len(stock_codes)}] {code} 수급 데이터 수집 ({start_str} ~ {end_str})")
                
                data_list = fetch_investor_trading_by_stock(kis_api, code, start_str, end_str)
                saved = save_trading_data(conn, data_list)
                total_saved += saved
                
                logger.info(f"   ↳ {len(data_list)}건 조회, {saved}건 저장 (누적: {total_saved})")
                
                # KIS Gateway rate limit(19/sec)이 속도를 제어하므로 별도 sleep 불필요
            except Exception as e:
                logger.error(f"   ❌ {code} 수집 실패: {e}")
    else:
        # 날짜별로 수집
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime("%Y%m%d")
            
            # 주말 건너뛰기
            if current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue
            
            try:
                logger.info(f"📅 {date_str} 수급 데이터 수집")
                
                data_list = fetch_investor_trading_by_date(kis_api, date_str, stock_codes)
                saved = save_trading_data(conn, data_list)
                total_saved += saved
                
                logger.info(f"   ↳ {len(data_list)}건 조회, {saved}건 저장 (누적: {total_saved})")
                
            except Exception as e:
                logger.error(f"   ❌ {date_str} 수집 실패: {e}")
            
            current_date += timedelta(days=1)
    
    conn.close()
    
    logger.info("=" * 60)
    logger.info(f"✅ 외국인/기관 매매 데이터 수집 완료 (총 {total_saved}건)")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
