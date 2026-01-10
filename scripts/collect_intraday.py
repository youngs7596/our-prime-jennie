#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collect_intraday.py
-------------------
Watchlist 및 거래대금 상위 종목의 실시간 시세를 수집하여
STOCK_MINUTE_PRICE 테이블에 저장하는 스크립트.

주기: 5분 (Scheduler 또는 Cron에 의해 실행됨)
대상: WatchList + Top 50 Trading Value
"""

import os
import sys
import logging
from datetime import datetime
from typing import List, Dict, Set
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from shared.kis.gateway_client import KISGatewayClient
from shared import database
from shared.db.models import StockMinutePrice, resolve_table_name, WatchList
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, text

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# DB 접속 정보 (Env 없을 시 Fallback)
if not os.getenv("MARIADB_PASSWORD"):
    os.environ["MARIADB_PASSWORD"] = "q1w2e3R$"

# Docker Compose에서 3307:3306으로 매핑되어 있음 (Host에서 실행 시)
if not os.getenv("MARIADB_PORT"):
    os.environ["MARIADB_PORT"] = "3307"

if not os.getenv("MARIADB_HOST"):
    os.environ["MARIADB_HOST"] = "127.0.0.1"

# Gateway 설정 (로컬 실행 시)
if not os.getenv("KIS_GATEWAY_URL"):
    os.environ["KIS_GATEWAY_URL"] = "http://127.0.0.1:8080"

if not os.getenv("USE_GATEWAY_AUTH"):
    os.environ["USE_GATEWAY_AUTH"] = "false"
    
TOP_LIQUID_LIMIT = 50

def get_db_session():
    """DB 세션 생성"""
    from shared.db.connection import get_engine, init_engine
    
    try:
        engine = get_engine()
    except RuntimeError:
        # 엔진이 초기화되지 않았다면 초기화 시도
        init_engine()
        engine = get_engine()
        
    return Session(bind=engine)

def fetch_top_liquid_codes(session: Session, limit: int = 50) -> List[str]:
    """
    최근 거래대금 상위 종목 추출
    (StockDailyPrice 테이블 활용)
    """
    try:
        # MariaDB: STOCK_DAILY_PRICES_3Y에서 최근 일자 기준 평균 거래대금 상위
        # 간단하게 최근 하루치 거래대금 순으로 정렬
        query = text(f"""
            SELECT STOCK_CODE 
            FROM {resolve_table_name("STOCK_DAILY_PRICES_3Y")}
            WHERE PRICE_DATE = (
                SELECT MAX(PRICE_DATE) 
                FROM {resolve_table_name("STOCK_DAILY_PRICES_3Y")}
            )
            ORDER BY (CLOSE_PRICE * VOLUME) DESC
            LIMIT :limit
        """)
        result = session.execute(query, {"limit": limit}).fetchall()
        return [row[0] for row in result]
    except Exception as e:
        logger.error(f"Top Liquid 조회 실패: {e}")
        return []

def get_target_universe(session: Session) -> List[str]:
    """수집 대상 종목 리스트 생성 (Watchlist + Top Liquid)"""
    targets: Set[str] = set()
    
    # 1. Watchlist (ORM 사용)
    try:
        watchlist_items = session.query(WatchList.stock_code).all()
        if watchlist_items:
            targets.update([item.stock_code for item in watchlist_items])
    except Exception as e:
        logger.error(f"Watchlist 조회 실패: {e}")

    # 2. Top Liquid
    top_liquid = fetch_top_liquid_codes(session, TOP_LIQUID_LIMIT)
    targets.update(top_liquid)
    
    # KOSPI 지수 등 제외 (필요 시)
    if "0001" in targets:
        targets.remove("0001")
        
    return sorted(list(targets))

def collect_snapshot(gateway: KISGatewayClient, code: str) -> Dict:
    """단일 종목 스냅샷 조회"""
    data = gateway.get_stock_snapshot(code)
    if not data:
        return None
        
    # KIS Gateway Snapshot 응답 구조에 따라 파싱
    # 예상: { "current_price": 1234, "volume": 12345, ... }
    # 실제 필드명을 확인해야 함. 일단 일반적인 키 사용.
    # GatewayClient는 raw dictonary를 반환함.
    
    return data

def save_to_db(session: Session, snapshots: List[Dict]):
    """DB 저장"""
    try:
        timestamp = datetime.now() # 수집 시점
        
        records = []
        for item in snapshots:
            code = item.get('stock_code')
            if not code:
                continue
                
            # Snapshot 데이터 매핑
            # Gateway 응답이 {'stock_code':..., 'price':..., 'volume':...} 형태라고 가정
            # 만약 OHLC 정보가 없다면 current_price로 채움
            price = float(item.get('price', item.get('current_price', 0)))
            vol = float(item.get('volume', item.get('accum_volume', 0)))
            
            # 5분 주기로 수집하므로 Snapshot 가격을 해당 시점의 OHLC로 간주 (Sampling)
            record = StockMinutePrice(
                price_time=timestamp,
                stock_code=code,
                open_price=price,
                high_price=price,
                low_price=price,
                close_price=price,
                volume=0, # 틱 볼륨은 알 수 없음. 0으로 처리.
                accum_volume=vol # 당일 누적 거래량
            )
            records.append(record)
            
        if records:
            session.bulk_save_objects(records)
            session.commit()
            logger.info(f"✅ {len(records)}개 종목 시세 저장 완료 ({timestamp})")
            
    except Exception as e:
        session.rollback()
        logger.error(f"DB 저장 실패: {e}")

def main():
    gateway = KISGatewayClient()
    
    # 장 운영 시간 체크 (선택 사항, 일단 수집은 항상 시도하거나 스케줄러에 위임)
    # if not gateway.check_market_open():
    #     logger.info("장이 열리지 않았습니다.")
    #     return

    session = get_db_session()
    
    try:
        targets = get_target_universe(session)
        logger.info(f"🎯 수집 대상: 총 {len(targets)}개 종목 (Watchlist + Top {TOP_LIQUID_LIMIT})")
        
        snapshots = []
        for i, code in enumerate(targets):
            # Rate Limit은 GatewayClient 내부에서 처리됨 (sleep)
            data = collect_snapshot(gateway, code)
            
            # 진행 상황 로깅 (10개 단위)
            if (i+1) % 10 == 0:
                print(".", end="", flush=True)
                
            if data:
                # Stock Code가 응답에 없을 수 있으므로 주입
                if 'stock_code' not in data:
                    data['stock_code'] = code
                snapshots.append(data)
        
        print("") # 줄바꿈
        
        if snapshots:
            save_to_db(session, snapshots)
        else:
            logger.warning("수집된 데이터가 없습니다.")
            
    finally:
        session.close()

if __name__ == "__main__":
    main()
