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
from shared.kis.client import KISClient
from shared.kis.market_data import MarketData

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 전역 설정
# [Patch] KIS Rate Limit 준수를 위해 1로 축소 (모의투자 초당 2건 제한)
MAX_WORKERS = 1
# [Patch] 사용자 요청: 2주치 데이터 복구 (여유있게 21일)
DAYS_TO_COLLECT = 21

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
        
        # 데이터 조회 (페이지네이션 적용됨)
        rows = market_data.get_stock_history_by_chart(code, start_date=start_date, end_date=end_date)
        
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
        for row in rows:
            cur.execute(sql, (
                code, row['date'], row['open'], row['high'], 
                row['low'], row['close'], row['volume']
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
    load_dotenv()
    
    # KIS Client 초기화 (공유)
    project_id = os.getenv("GCP_PROJECT_ID")
    trading_mode = os.getenv("TRADING_MODE", "MOCK")
    
    if trading_mode == "REAL":
        app_key = auth.get_secret(os.getenv("REAL_SECRET_ID_APP_KEY"), project_id)
        app_secret = auth.get_secret(os.getenv("REAL_SECRET_ID_APP_SECRET"), project_id)
        account_prefix = auth.get_secret(os.getenv("REAL_SECRET_ID_ACCOUNT_PREFIX"), project_id)
        base_url = os.getenv("KIS_BASE_URL_REAL")
    else:
        app_key = auth.get_secret(os.getenv("MOCK_SECRET_ID_APP_KEY"), project_id)
        app_secret = auth.get_secret(os.getenv("MOCK_SECRET_ID_APP_SECRET"), project_id)
        account_prefix = auth.get_secret(os.getenv("MOCK_SECRET_ID_ACCOUNT_PREFIX"), project_id)
        base_url = os.getenv("KIS_BASE_URL_MOCK")
        
    account_suffix = os.getenv("KIS_ACCOUNT_SUFFIX")
    
    kis_client = KISClient(
        app_key=app_key,
        app_secret=app_secret,
        base_url=base_url,
        account_prefix=account_prefix,
        account_suffix=account_suffix,
        trading_mode=trading_mode
    )
    
    if not kis_client.authenticate():
        logger.error("KIS API 인증 실패")
        return

    # DB 설정: MariaDB 단일화로 스레드에 별도 설정을 전달하지 않습니다.

    # KOSPI 종목 리스트 가져오기
    # [Patch] FinanceDataReader 오류(JSONDecodeError) 회피를 위해 DB에서 기존 종목 로드
    logger.info("DB(STOCK_DAILY_PRICES_3Y)에서 관리 중인 종목 리스트를 로드합니다... (FDR 우회)")
    
    # DB 엔진 초기화 (메인 스레드용)
    init_engine()
    
    codes = []
    try:
        with session_scope() as session:
            # 3년치 테이블에 데이터가 있는 종목만 대상으로 함 (기존 유니버스 유지)
            # distinct stock_code 조회
            result = session.execute(text("SELECT DISTINCT STOCK_CODE FROM STOCK_DAILY_PRICES_3Y"))
            codes = [row[0] for row in result.fetchall()]
    except Exception as e:
        logger.error(f"❌ DB 종목 리스트 조회 실패: {e}")
        return

    # df_krx = fdr.StockListing('KOSPI')
    # codes = df_krx['Code'].tolist()
    logger.info(f"✅ KOSPI 종목 {len(codes)}개 확보 완료.")
    
    logger.info(f"=== KOSPI 전 종목({len(codes)}개) 병렬 수집 시작 (Workers: {MAX_WORKERS}) ===")
    
    success_count = 0
    fail_count = 0
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_code = {executor.submit(collect_stock_data, code, kis_client): code for code in codes}
        
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
