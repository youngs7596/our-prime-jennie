#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/collect_investor_trading.py

pykrx를 통해 외국인/기관/개인 순매수 데이터를 일괄 수집하여
`STOCK_INVESTOR_TRADING` 테이블에 저장합니다.

기존 KIS Gateway 종목별 순차호출(~530초) → pykrx 전종목 일괄 6 API calls(~2초)로 전환.

데이터 소스: KRX 정보데이터시스템 (pykrx 래퍼)
  - get_market_net_purchases_of_equities_by_ticker(date, date, market, investor)
  - get_market_ohlcv_by_ticker(date, market)

Usage:
    # 1일치 (DAG 일일 실행용, 기본값)
    python scripts/collect_investor_trading.py --days 1

    # 최근 30일 백필
    python scripts/collect_investor_trading.py --days 30
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from pykrx import stock as krx_stock

import shared.database as database
from shared.hybrid_scoring.schema import execute_upsert

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TABLE_NAME = "STOCK_INVESTOR_TRADING"

# pykrx investor 키 → DB 컬럼 prefix 매핑
INVESTOR_MAP = {
    "외국인": "foreign",
    "기관합계": "institution",
    "개인": "individual",
}


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
        logger.info(f"테이블 확인 완료: {TABLE_NAME}")
    except Exception as e:
        logger.error(f"테이블 생성 실패: {e}")
        connection.rollback()
        raise
    finally:
        cursor.close()


def fetch_investor_trading_pykrx(date_str: str) -> Dict[str, dict]:
    """
    pykrx로 특정 날짜의 전 종목 투자자 매매 데이터를 일괄 조회.

    Args:
        date_str: YYYYMMDD 형식

    Returns:
        {ticker: {trade_date, stock_code, stock_name, foreign_buy, ..., close_price, volume}} dict
    """
    stocks = {}  # ticker → merged dict

    # 1) 투자자별 순매수 데이터 (6 API calls: 2 markets × 3 investors)
    for market in ["KOSPI", "KOSDAQ"]:
        for investor_kr, col_prefix in INVESTOR_MAP.items():
            try:
                df = krx_stock.get_market_net_purchases_of_equities_by_ticker(
                    date_str, date_str, market=market, investor=investor_kr
                )
                if df is None or df.empty:
                    continue

                for ticker, row in df.iterrows():
                    if ticker not in stocks:
                        stocks[ticker] = {
                            "stock_code": ticker,
                            "stock_name": row.get("종목명", ""),
                            "foreign_buy": 0, "foreign_sell": 0, "foreign_net_buy": 0,
                            "institution_buy": 0, "institution_sell": 0, "institution_net_buy": 0,
                            "individual_buy": 0, "individual_sell": 0, "individual_net_buy": 0,
                            "close_price": 0, "volume": 0,
                        }

                    stocks[ticker][f"{col_prefix}_buy"] = int(row.get("매수거래량", 0))
                    stocks[ticker][f"{col_prefix}_sell"] = int(row.get("매도거래량", 0))
                    stocks[ticker][f"{col_prefix}_net_buy"] = int(row.get("순매수거래량", 0))
                    # 종목명 보충 (첫 번째 market/investor에서 이미 들어왔을 수 있으나 덮어써도 무방)
                    if row.get("종목명"):
                        stocks[ticker]["stock_name"] = row["종목명"]

            except Exception as e:
                logger.warning(f"  {market}/{investor_kr} 조회 실패: {e}")

    # 2) OHLCV로 종가/거래량 보충 (2 API calls: 2 markets)
    for market in ["KOSPI", "KOSDAQ"]:
        try:
            ohlcv = krx_stock.get_market_ohlcv_by_ticker(date_str, market=market)
            if ohlcv is None or ohlcv.empty:
                continue

            for ticker, row in ohlcv.iterrows():
                if ticker in stocks:
                    stocks[ticker]["close_price"] = int(row.get("종가", 0))
                    stocks[ticker]["volume"] = int(row.get("거래량", 0))
        except Exception as e:
            logger.warning(f"  {market} OHLCV 조회 실패: {e}")

    return stocks


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
            logger.debug(f"  저장 실패 ({data.get('stock_code')}): {e}")

    connection.commit()
    cursor.close()
    return saved


def get_trading_dates(days: int) -> List[str]:
    """최근 N일의 영업일(주말 제외) 날짜 리스트 반환"""
    dates = []
    current = datetime.now()
    while len(dates) < days:
        current -= timedelta(days=1)
        if current.weekday() >= 5:
            continue
        dates.append(current.strftime("%Y%m%d"))
    return list(reversed(dates))


def parse_args():
    parser = argparse.ArgumentParser(description="외국인/기관/개인 투자자 매매 데이터 수집기 (pykrx)")
    parser.add_argument("--days", type=int, default=1, help="최근 N영업일 수집 (기본: 1)")
    parser.add_argument("--date", type=str, default=None, help="특정 날짜만 수집 (YYYYMMDD)")
    return parser.parse_args()


def main():
    args = parse_args()

    if not os.getenv("SECRETS_FILE"):
        os.environ["SECRETS_FILE"] = os.path.join(PROJECT_ROOT, "secrets.json")

    logger.info("=" * 60)
    logger.info("외국인/기관/개인 매매 데이터 수집 시작 (pykrx)")
    if args.date:
        logger.info(f"  대상: {args.date}")
    else:
        logger.info(f"  기간: 최근 {args.days}영업일")
    logger.info("=" * 60)

    # DB 연결
    from shared.db.connection import init_engine
    init_engine()

    conn = database.get_db_connection()
    if not conn:
        logger.error("DB 연결 실패")
        return

    ensure_table_exists(conn)

    # 날짜 목록 결정
    if args.date:
        dates = [args.date]
    else:
        dates = get_trading_dates(args.days)

    total_saved = 0
    total_fetched = 0

    for idx, date_str in enumerate(dates, start=1):
        t0 = time.time()
        try:
            stocks = fetch_investor_trading_pykrx(date_str)
            fetched = len(stocks)
            total_fetched += fetched

            if fetched == 0:
                logger.info(f"[{idx}/{len(dates)}] {date_str}: 데이터 없음 (공휴일?)")
                continue

            # dict → list with trade_date 추가
            trade_date = datetime.strptime(date_str, "%Y%m%d").date()
            data_list = []
            for ticker_data in stocks.values():
                ticker_data["trade_date"] = trade_date
                data_list.append(ticker_data)

            saved = save_trading_data(conn, data_list)
            total_saved += saved
            elapsed = time.time() - t0

            logger.info(
                f"[{idx}/{len(dates)}] {date_str}: "
                f"{fetched}종목 조회, {saved}건 저장 ({elapsed:.1f}s)"
            )

        except Exception as e:
            logger.error(f"[{idx}/{len(dates)}] {date_str}: 실패 - {e}")

        # pykrx rate limit 방지 (날짜 간)
        if idx < len(dates):
            time.sleep(0.5)

    conn.close()

    logger.info("=" * 60)
    logger.info(
        f"외국인/기관/개인 매매 데이터 수집 완료: "
        f"총 {total_fetched}종목, {total_saved}건 저장"
    )
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
