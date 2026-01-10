#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_kospi_index.py

KOSPI(0001) 일봉 데이터를 지정 구간으로 수집해 STOCK_DAILY_PRICES_3Y에 upsert합니다.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict

from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

import shared.auth as auth
import shared.database as database
from shared.kis.client import KISClient as KIS_API

from utilities.data_collector import ensure_table_exists, upsert_daily_prices

logger = logging.getLogger(__name__)

KOSPI_CODE = "0001"


def _fetch_index_ohlcv_range(
    kis_api: KIS_API,
    index_code: str,
    start_date: str,
    end_date: str,
) -> List[Dict]:
    url = f"{kis_api.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice"
    tr_id = "FHKUP03500100"
    params = {
        "FID_COND_MRKT_DIV_CODE": "U",
        "FID_INPUT_ISCD": index_code,
        "FID_INPUT_DATE_1": start_date,
        "FID_INPUT_DATE_2": end_date,
        "FID_PERIOD_DIV_CODE": "D",
    }

    if hasattr(kis_api, "API_CALL_DELAY"):
        time.sleep(kis_api.API_CALL_DELAY)

    res = kis_api.request("GET", url, params=params, tr_id=tr_id)
    output_list = res.get("output2") if res else None
    if not output_list:
        return []

    rows = []
    for day in output_list:
        try:
            date_raw = day.get("stck_bsop_date")
            if not date_raw:
                continue
            dt = datetime.strptime(date_raw, "%Y%m%d").strftime("%Y-%m-%d")
            open_price = float(day.get("bstp_nmix_oprc", 0) or 0)
            high_price = float(day.get("bstp_nmix_hgpr", 0) or 0)
            low_price = float(day.get("bstp_nmix_lwpr", 0) or 0)
            close_price = float(day.get("bstp_nmix_prpr", 0) or 0)
            if not open_price:
                open_price = close_price
            rows.append(
                {
                    "date": dt,
                    "code": index_code,
                    "open": open_price,
                    "high": high_price,
                    "low": low_price,
                    "close": close_price,
                    "volume": int(day.get("acml_vol", 0) or 0),
                }
            )
        except Exception:
            continue

    return rows


def _get_db_max_date(connection) -> datetime | None:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT MAX(PRICE_DATE) FROM STOCK_DAILY_PRICES_3Y WHERE STOCK_CODE = %s",
            (KOSPI_CODE,),
        )
        row = cursor.fetchone()
    finally:
        cursor.close()
    value = row[0] if row else None
    return value


def _chunk_dates(start_dt: datetime, end_dt: datetime, chunk_days: int = 180):
    cur_start = start_dt
    while cur_start <= end_dt:
        cur_end = min(cur_start + timedelta(days=chunk_days), end_dt)
        yield cur_start, cur_end
        cur_start = cur_end + timedelta(days=1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KOSPI(0001) 일봉 데이터 백필")
    parser.add_argument("--start-date", type=str, default=None, help="시작일 (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default=None, help="종료일 (YYYY-MM-DD)")
    return parser.parse_args()


def main() -> None:
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    args = parse_args()

    db_conn = database.get_db_connection()
    if not db_conn:
        raise SystemExit("DB 연결 실패")
    ensure_table_exists(db_conn)

    trading_mode = os.getenv("TRADING_MODE", "REAL")
    kis_api = KIS_API(
        app_key=auth.get_secret(os.getenv(f"{trading_mode}_SECRET_ID_APP_KEY"), os.getenv("GCP_PROJECT_ID")),
        app_secret=auth.get_secret(os.getenv(f"{trading_mode}_SECRET_ID_APP_SECRET"), os.getenv("GCP_PROJECT_ID")),
        base_url=os.getenv(f"KIS_BASE_URL_{trading_mode}"),
        account_prefix=auth.get_secret(os.getenv(f"{trading_mode}_SECRET_ID_ACCOUNT_PREFIX"), os.getenv("GCP_PROJECT_ID")),
        account_suffix=os.getenv("KIS_ACCOUNT_SUFFIX"),
        trading_mode=trading_mode,
    )
    if not kis_api.authenticate():
        raise SystemExit("KIS API 인증 실패")

    if args.start_date:
        start_dt = datetime.strptime(args.start_date, "%Y-%m-%d")
    else:
        max_dt = _get_db_max_date(db_conn)
        start_dt = max_dt + timedelta(days=1) if max_dt else datetime(2025, 11, 26)

    end_dt = datetime.strptime(args.end_date, "%Y-%m-%d") if args.end_date else datetime.now()

    if start_dt > end_dt:
        logger.info("이미 최신입니다. (시작일이 종료일 이후)")
        return

    total_saved = 0
    for s_dt, e_dt in _chunk_dates(start_dt, end_dt):
        rows = _fetch_index_ohlcv_range(
            kis_api,
            KOSPI_CODE,
            s_dt.strftime("%Y%m%d"),
            e_dt.strftime("%Y%m%d"),
        )
        if rows:
            upsert_daily_prices(db_conn, rows)
            total_saved += len(rows)
            logger.info("✅ KOSPI 저장: %s ~ %s (%d건)", s_dt.date(), e_dt.date(), len(rows))
        else:
            logger.warning("⚠️ 데이터 없음: %s ~ %s", s_dt.date(), e_dt.date())

    logger.info("완료: 총 %d건 저장", total_saved)
    db_conn.close()


if __name__ == "__main__":
    main()
