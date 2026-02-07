#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Version: v1.0
# 작업 LLM: Claude Opus 4.5
"""
scripts/collect_full_market_data_parallel.py
KOSPI 전 종목의 700일치 데이터를 병렬로 수집합니다.
- MariaDB 단일 지원 (Oracle/분기 제거)
"""

import os
import sys
import logging
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import FinanceDataReader as fdr
from dotenv import load_dotenv


# 프로젝트 루트 경로 설정
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from sqlalchemy import text  # [Patch] for DB query
from shared.db.connection import init_engine, session_scope  # [Patch]

import shared.auth as auth
import shared.database as database
from shared.kis import KISGatewayClient
from shared.kis.market_data import MarketData

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 전역 설정
# [Patch] KIS Rate Limit 준수를 위해 1로 축소 (모의투자 초당 2건 제한)
MAX_WORKERS = 1
# [Patch] QuantScorer 요구사항(30일) 충족을 위해 100일로 상향
DAYS_TO_COLLECT = 100

def _is_mariadb() -> bool:
    """단일화: MariaDB만 사용"""
    return True

def collect_stock_data(code, kis_client):
    """단일 종목 데이터 수집 및 저장 (스레드에서 실행)"""
    conn = None
    try:
        # DB 연결 (스레드별 독립 연결)
        conn = database.get_db_connection()
        if not conn:
            logger.error(f"❌ [{code}] DB 연결 실패")
            return False
            
        cur = conn.cursor()
        
        market_data = MarketData(kis_client)
        
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=DAYS_TO_COLLECT)).strftime("%Y%m%d")
        
        # 데이터 조회 (KIS Gateway 프록시 사용)
        rows = kis_client.get_stock_daily_prices(code, num_days_to_fetch=DAYS_TO_COLLECT)
        
        # rows가 DataFrame인 경우 list(dict)로 변환
        if hasattr(rows, 'to_dict'):
            rows = rows.to_dict('records')
        
        if not rows:
            logger.warning(f"⚠️ [{code}] 데이터 없음")
            return False
            
        # DB 저장 (MariaDB: INSERT ... ON DUPLICATE KEY UPDATE)
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
        skipped = 0
        for row in rows:
            # 주말/공휴일 필터링: 거래량 0 또는 토/일 데이터 제외
            try:
                row_date = row['date']
                if isinstance(row_date, str):
                    row_date = datetime.strptime(row_date.replace('-', ''), '%Y%m%d')
                if hasattr(row_date, 'weekday') and row_date.weekday() >= 5:
                    skipped += 1
                    continue
            except (ValueError, TypeError):
                pass

            if row.get('volume', 0) == 0:
                skipped += 1
                continue

            cur.execute(sql, (
                code, row['date'], row['open'], row['high'],
                row['low'], row['close'], row['volume']
            ))

        if skipped > 0:
            logger.debug(f"[{code}] 주말/비거래일 {skipped}건 스킵")
        
        conn.commit()
        cur.close()
        
        # Rate Limit 방지를 위한 추가 대기
        time.sleep(0.2)
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
    load_dotenv()
    
    # 200개 종목 우선 순위 (필요 시 인자로 받을 수 있음)
    CODE_LIMIT = 200

    # KIS Gateway 초기화 (로컬 우선)
    gateway_url = os.getenv("KIS_GATEWAY_URL", "http://127.0.0.1:8080")
    kis_api = KISGatewayClient(gateway_url=gateway_url)
    
    logger.info(f"🚀 KIS Gateway 기반 가격 데이터 수집 시작: {gateway_url}")
    logger.info(f"📅 수집 기간: 최근 {DAYS_TO_COLLECT}일")

    # DB 설정: MariaDB 단일화로 스레드에 별도 설정을 전달하지 않습니다.

    # KOSPI 종목 리스트 가져오기
    logger.info("DB(STOCK_MASTER)에서 종목 리스트를 로드합니다...")
    
    # DB 엔진 초기화 (메인 스레드용)
    init_engine()
    
    codes = []
    try:
        # DB 연결
        conn = database.get_db_connection()
        codes = database.get_all_stock_codes(conn)
        conn.close()
        
        # 200개로 제한 (유니버스 유지)
        if len(codes) > CODE_LIMIT:
            codes = codes[:CODE_LIMIT]
            
    except Exception as e:
        logger.error(f"❌ DB 종목 리스트 조회 실패: {e}")
        return

    logger.info(f"✅ 대상 종목 {len(codes)}개 확보 완료.")
    
    logger.info(f"=== KOSPI 전 종목({len(codes)}개) 병렬 수집 시작 (Workers: {MAX_WORKERS}) ===")
    
    success_count = 0
    fail_count = 0
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_code = {executor.submit(collect_stock_data, code, kis_api): code for code in codes}
        
        for i, future in enumerate(as_completed(future_to_code)):
            code = future_to_code[future]
            try:
                result = future.result()
                if result:
                    success_count += 1
                    if success_count % 10 == 0:
                        logger.info(f"[{i+1}/{len(codes)}] 진행 중... 성공: {success_count}, 실패: {fail_count}")
                else:
                    fail_count += 1
            except Exception as e:
                logger.error(f"❌ [{code}] 예외 발생: {e}")
                fail_count += 1
                
    logger.info(f"=== 수집 완료: 성공 {success_count}, 실패 {fail_count} ===")

if __name__ == "__main__":
    main()
