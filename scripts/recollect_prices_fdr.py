"""
FinanceDataReader를 이용한 일봉 데이터 재수집 (최근 90일)
- KIS API 불필요, 주말에도 실행 가능
- STOCK_MASTER 기준 전종목 대상
- 기존 데이터 덮어쓰기 (ON DUPLICATE KEY UPDATE)

사용법:
    .venv/bin/python scripts/recollect_prices_fdr.py
    .venv/bin/python scripts/recollect_prices_fdr.py --days 120
    .venv/bin/python scripts/recollect_prices_fdr.py --code 005930  # 단일 종목
"""
import os
import sys
import time
import logging
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import FinanceDataReader as fdr
from shared.db.connection import init_engine, session_scope
from shared.db.models import StockMaster
import shared.database as database

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def collect_single_stock(code, start_date, end_date, conn):
    """단일 종목 FDR 수집 → DB 저장"""
    try:
        df = fdr.DataReader(code, start_date, end_date)
        if df is None or df.empty:
            return 0

        cur = conn.cursor()
        sql = """
        INSERT INTO STOCK_DAILY_PRICES_3Y
            (STOCK_CODE, PRICE_DATE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, VOLUME)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            OPEN_PRICE = VALUES(OPEN_PRICE),
            HIGH_PRICE = VALUES(HIGH_PRICE),
            LOW_PRICE = VALUES(LOW_PRICE),
            CLOSE_PRICE = VALUES(CLOSE_PRICE),
            VOLUME = VALUES(VOLUME)
        """

        count = 0
        for date_idx, row in df.iterrows():
            date_str = date_idx.strftime('%Y-%m-%d')
            cur.execute(sql, (
                code,
                date_str,
                float(row['Open']),
                float(row['High']),
                float(row['Low']),
                float(row['Close']),
                int(row['Volume']),
            ))
            count += 1

        conn.commit()
        cur.close()
        return count

    except Exception as e:
        logger.error(f"[{code}] 수집 실패: {e}")
        if conn:
            conn.rollback()
        return -1


def main():
    parser = argparse.ArgumentParser(description='FDR 기반 일봉 데이터 재수집')
    parser.add_argument('--days', type=int, default=90, help='수집 기간 (일)')
    parser.add_argument('--code', type=str, default=None, help='단일 종목 코드')
    args = parser.parse_args()

    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=args.days)).strftime('%Y-%m-%d')

    logger.info(f"FDR 일봉 재수집: {start_date} ~ {end_date} ({args.days}일)")

    init_engine()

    # 대상 종목 확정
    if args.code:
        codes = [args.code]
    else:
        with session_scope(readonly=True) as session:
            masters = session.query(StockMaster.stock_code).all()
            codes = [m.stock_code for m in masters]

    logger.info(f"대상 종목: {len(codes)}개")

    conn = database.get_db_connection()
    if not conn:
        logger.error("DB 연결 실패")
        return

    success = 0
    fail = 0
    total_rows = 0

    for i, code in enumerate(codes):
        result = collect_single_stock(code, start_date, end_date, conn)
        if result > 0:
            success += 1
            total_rows += result
        elif result == 0:
            logger.warning(f"[{code}] 데이터 없음")
            fail += 1
        else:
            fail += 1

        if (i + 1) % 20 == 0:
            logger.info(f"진행: {i+1}/{len(codes)} (성공: {success}, 실패: {fail}, 총 {total_rows:,}건)")

        # FDR rate limit 방지
        time.sleep(0.3)

    conn.close()
    logger.info(f"완료: 성공 {success}, 실패 {fail}, 총 {total_rows:,}건 저장")


if __name__ == '__main__':
    main()
