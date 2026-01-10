#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/collect_prices_fdr.py
FinanceDataReader를 사용하여 KOSPI/KOSDAQ 종목 가격 데이터를 수집합니다.
KIS API 없이 동작하는 간소화 버전입니다.
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import FinanceDataReader as fdr
import mysql.connector

# 프로젝트 루트 경로 설정
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 설정
MAX_WORKERS = 5
DAYS_TO_COLLECT = 30  # 최근 30일만 수집 (빠른 실행)

# MariaDB 연결 정보
DB_HOST = os.getenv("MARIADB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("MARIADB_PORT", 3307))
DB_USER = os.getenv("MARIADB_USER", "jennie")
DB_PASSWORD = os.getenv("MARIADB_PASSWORD", "q1w2e3R$")
DB_NAME = os.getenv("MARIADB_DATABASE", "jennie_db")


def get_db_connection():
    """MariaDB 연결 생성"""
    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )


def collect_stock_data(code):
    """단일 종목 데이터 수집 및 저장"""
    conn = None
    try:
        # FinanceDataReader로 데이터 조회
        end_date = datetime.now()
        start_date = end_date - timedelta(days=DAYS_TO_COLLECT)
        
        df = fdr.DataReader(code, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
        
        if df.empty:
            return False
            
        # DB 연결
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 데이터 저장
        sql = """
        INSERT INTO stock_daily_prices_3y 
            (STOCK_CODE, PRICE_DATE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, VOLUME)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            OPEN_PRICE = VALUES(OPEN_PRICE),
            HIGH_PRICE = VALUES(HIGH_PRICE),
            LOW_PRICE = VALUES(LOW_PRICE),
            CLOSE_PRICE = VALUES(CLOSE_PRICE),
            VOLUME = VALUES(VOLUME)
        """
        
        for date, row in df.iterrows():
            cur.execute(sql, (
                code, 
                date.strftime('%Y-%m-%d'),
                float(row['Open']),
                float(row['High']),
                float(row['Low']),
                float(row['Close']),
                float(row['Volume'])
            ))
        
        conn.commit()
        cur.close()
        return True
        
    except Exception as e:
        logger.error(f"❌ [{code}] 처리 실패: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


def main():
    logger.info("=== FinanceDataReader 기반 가격 데이터 수집 ===")
    logger.info(f"DB: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    logger.info(f"수집 기간: 최근 {DAYS_TO_COLLECT}일")
    
    # KOSPI 종목 리스트
    logger.info("KOSPI 종목 리스트 조회 중...")
    df_kospi = fdr.StockListing('KOSPI')
    codes = df_kospi['Code'].tolist()
    logger.info(f"✅ KOSPI {len(codes)}개 종목 확보")
    
    success_count = 0
    fail_count = 0
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_code = {executor.submit(collect_stock_data, code): code for code in codes}
        
        for i, future in enumerate(as_completed(future_to_code)):
            code = future_to_code[future]
            try:
                if future.result():
                    success_count += 1
                else:
                    fail_count += 1
                    
                if (i + 1) % 50 == 0:
                    logger.info(f"[{i+1}/{len(codes)}] 진행 중... 성공: {success_count}, 실패: {fail_count}")
                    
            except Exception as e:
                logger.error(f"❌ [{code}] 예외: {e}")
                fail_count += 1
    
    logger.info(f"=== 수집 완료: 성공 {success_count}, 실패 {fail_count} ===")


if __name__ == "__main__":
    main()
