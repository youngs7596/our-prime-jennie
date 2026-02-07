#!/usr/bin/env python3
"""
scripts/collect_foreign_holding_ratio.py

pykrx를 통해 외국인 보유비율(지분율) 데이터를 수집하여
STOCK_INVESTOR_TRADING.FOREIGN_HOLDING_RATIO 컬럼에 업데이트합니다.

데이터 소스: KRX 정보데이터시스템 (pykrx)
  - get_exhaustion_rates_of_foreign_investment_by_ticker(date, market)
  - 반환 컬럼 중 '지분율' = 외국인 보유비율(%)

Usage:
    # 최근 30일 백필 (기본)
    python scripts/collect_foreign_holding_ratio.py --days 30

    # 특정 날짜만 수집
    python scripts/collect_foreign_holding_ratio.py --date 20260207

    # 1일치 (DAG 일일 실행용)
    python scripts/collect_foreign_holding_ratio.py --days 1
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from pykrx import stock as krx_stock

import shared.database as database

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TABLE_NAME = "STOCK_INVESTOR_TRADING"


def ensure_column_exists(connection):
    """FOREIGN_HOLDING_RATIO 컬럼이 없으면 추가"""
    cursor = connection.cursor()
    try:
        # 컬럼 존재 여부 확인
        cursor.execute(f"""
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = '{TABLE_NAME}'
              AND COLUMN_NAME = 'FOREIGN_HOLDING_RATIO'
        """)
        if cursor.fetchone() is None:
            logger.info("FOREIGN_HOLDING_RATIO 컬럼 추가 중...")
            cursor.execute(f"""
                ALTER TABLE {TABLE_NAME}
                ADD COLUMN FOREIGN_HOLDING_RATIO FLOAT DEFAULT NULL
                COMMENT '외국인 보유비율(%)'
            """)
            connection.commit()
            logger.info("FOREIGN_HOLDING_RATIO 컬럼 추가 완료")
        else:
            logger.info("FOREIGN_HOLDING_RATIO 컬럼 이미 존재")
    finally:
        cursor.close()


def fetch_foreign_holding_ratios(date_str: str) -> dict:
    """
    특정 날짜의 전 종목 외국인 보유비율 조회

    Args:
        date_str: YYYYMMDD 형식

    Returns:
        {ticker: ratio} dict, ratio는 지분율(%)
    """
    result = {}

    for market in ['KOSPI', 'KOSDAQ']:
        try:
            df = krx_stock.get_exhaustion_rates_of_foreign_investment_by_ticker(date_str, market)
            if df is not None and not df.empty and '지분율' in df.columns:
                for ticker, row in df.iterrows():
                    ratio = row['지분율']
                    if ratio is not None and ratio >= 0:
                        result[ticker] = float(ratio)
                logger.debug(f"  {market}: {len(df)}종목 조회")
        except Exception as e:
            logger.warning(f"  {market} 외인보유비율 조회 실패: {e}")

    return result


def update_foreign_holding_ratios(connection, date_str: str, ratios: dict) -> int:
    """
    STOCK_INVESTOR_TRADING 테이블의 기존 행에 FOREIGN_HOLDING_RATIO 업데이트

    Args:
        connection: DB 연결
        date_str: YYYYMMDD 형식
        ratios: {ticker: ratio} dict

    Returns:
        업데이트된 행 수
    """
    if not ratios:
        return 0

    trade_date = datetime.strptime(date_str, "%Y%m%d").date()
    cursor = connection.cursor()
    updated = 0

    try:
        for ticker, ratio in ratios.items():
            cursor.execute(f"""
                UPDATE {TABLE_NAME}
                SET FOREIGN_HOLDING_RATIO = %s
                WHERE STOCK_CODE = %s AND TRADE_DATE = %s
            """, (ratio, ticker, trade_date))
            if cursor.rowcount > 0:
                updated += 1

        connection.commit()
    except Exception as e:
        logger.error(f"  업데이트 실패: {e}")
        connection.rollback()
    finally:
        cursor.close()

    return updated


def get_trading_dates(days: int) -> list:
    """최근 N일의 영업일(주말 제외) 날짜 리스트 반환"""
    dates = []
    current = datetime.now()
    while len(dates) < days:
        current -= timedelta(days=1)
        # 주말 건너뛰기
        if current.weekday() >= 5:
            continue
        dates.append(current.strftime("%Y%m%d"))
    return list(reversed(dates))


def parse_args():
    parser = argparse.ArgumentParser(description="외국인 보유비율 수집기 (pykrx)")
    parser.add_argument("--days", type=int, default=30, help="최근 N일 백필 (기본: 30)")
    parser.add_argument("--date", type=str, default=None, help="특정 날짜만 수집 (YYYYMMDD)")
    return parser.parse_args()


def main():
    args = parse_args()

    # secrets.json 경로 설정 (프로젝트 루트)
    if not os.getenv("SECRETS_FILE"):
        os.environ["SECRETS_FILE"] = os.path.join(PROJECT_ROOT, "secrets.json")

    logger.info("=" * 60)
    logger.info("외국인 보유비율 수집 시작")
    if args.date:
        logger.info(f"  대상: {args.date}")
    else:
        logger.info(f"  기간: 최근 {args.days}일")
    logger.info("=" * 60)

    # DB 연결
    from shared.db.connection import init_engine
    init_engine()

    conn = database.get_db_connection()
    if not conn:
        logger.error("DB 연결 실패")
        return

    # 컬럼 존재 확인/추가
    ensure_column_exists(conn)

    # 날짜 목록 결정
    if args.date:
        dates = [args.date]
    else:
        dates = get_trading_dates(args.days)

    total_updated = 0
    total_fetched = 0

    for idx, date_str in enumerate(dates, start=1):
        try:
            ratios = fetch_foreign_holding_ratios(date_str)
            fetched = len(ratios)
            total_fetched += fetched

            if fetched == 0:
                logger.info(f"[{idx}/{len(dates)}] {date_str}: 데이터 없음 (공휴일?)")
                continue

            updated = update_foreign_holding_ratios(conn, date_str, ratios)
            total_updated += updated

            logger.info(
                f"[{idx}/{len(dates)}] {date_str}: "
                f"{fetched}종목 조회, {updated}건 업데이트"
            )

            # pykrx rate limit 방지
            time.sleep(0.5)

        except Exception as e:
            logger.error(f"[{idx}/{len(dates)}] {date_str}: 실패 - {e}")

    conn.close()

    logger.info("=" * 60)
    logger.info(
        f"외국인 보유비율 수집 완료: "
        f"총 {total_fetched}건 조회, {total_updated}건 업데이트"
    )
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
