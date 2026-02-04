#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collect_minute_chart.py
-----------------------
Watchlist 및 거래대금 상위 종목의 5분봉 데이터를 수집하여
STOCK_MINUTE_PRICE 테이블에 저장하는 스크립트.

특징:
- '현재가 스냅샷'이 아닌 '실제 분봉 차트' API를 사용 (OHLCV 정확도 보장)
- 당일 발생한 모든 5분봉을 수집하거나, 특정 시간 이후의 봉만 수집 가능
- 중복 방지 (Conflict Ignoring)

사용법:
    python scripts/collect_minute_chart.py
"""

import os
import sys
import logging
import argparse
from datetime import datetime, time as dtime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.kis.gateway_client import KISGatewayClient
from shared.db.connection import init_engine
from shared.database import get_db_connection_context
from shared.db.models import StockMinutePrice
from shared.crawlers.naver import get_kospi_top_stocks
from shared.utils import is_operating_hours
from dateutil import parser as date_parser

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def save_minute_data(conn, stock_code, chart_data):
    """
    수신된 분봉 데이터를 DB에 저장 (BULK INSERT)
    """
    if not chart_data:
        return 0
        
    records = []
    
    # 중복 방지를 위해 이미 DB에 있는지 확인하는 로직은 생략 (INSERT IGNORE 사용 권장)
    # SQLAlchemy Core를 사용하여 효율적으로 Bulk Insert
    
    for item in chart_data:
        # KIS API 응답 구조: {'datetime': datetime obj, 'open': ..., ...}
        # (gateway_client -> KISClient -> MarketData.get_stock_minute_prices 에서 파싱됨)
        
        # datetime 객체인지 확인
        dt = item.get('datetime')
        if isinstance(dt, str):
            try:
                # dateutil로 다양한 포맷 대응 (Gateway JSON 변환 시 포맷 불확실성 해결)
                dt = date_parser.parse(dt)
            except Exception as e:
                logger.warning(f"⚠️ 날짜 파싱 실패 ({stock_code}): {dt} - {e}")
                continue
                
        records.append({
            'stock_code': stock_code,
            'price_time': dt,
            'open_price': float(item['open']),
            'high_price': float(item['high']),
            'low_price': float(item['low']),
            'close_price': float(item['close']),
            'volume': int(item['volume']),
            'accum_volume': 0, # 분봉 API에서는 누적 거래량을 바로 주지 않을 수 있음 (필요 시 계산)
            'created_at': datetime.now()
        })

    if not records:
        return 0

    try:
        from sqlalchemy import text
        
        # MariaDB: INSERT IGNORE ...
        # 간단하게 ORM 대신 Core Query 사용
        # (models.py의 StockMinutePrice 테이블 정의를 따름)
        
        # 대량 데이터이므로 chunk 처리 권장하지만, 하루치 5분봉은 78개 정로도 작음.
        conn.execute(
            text("""
                INSERT IGNORE INTO STOCK_MINUTE_PRICE 
                (stock_code, price_time, open_price, high_price, low_price, close_price, volume, accum_volume, created_at)
                VALUES (:stock_code, :price_time, :open_price, :high_price, :low_price, :close_price, :volume, :accum_volume, :created_at)
            """),
            records
        )
        conn.commit()
        return len(records)
        
    except Exception as e:
        logger.error(f"❌ DB 저장 실패 ({stock_code}): {e}")
        conn.rollback()
        return 0

def process_stock(gateway, stock_code, stock_name):
    """개별 종목 처리 함수"""
    try:
        # 5분봉 조회 (오늘 날짜)
        today_str = datetime.now().strftime("%Y%m%d")
        chart_data = gateway.get_stock_minute_chart(stock_code, target_date=today_str, minute_interval=5)
        
        if not chart_data:
            logger.warning(f"⚠️ 데이터 없음: {stock_name} ({stock_code})")
            return 0
            
        # DB 저장
        with get_db_connection_context() as conn:
            params = {"stock_code": stock_code} # dummy for context
            count = save_minute_data(conn, stock_code, chart_data)
            
        logger.info(f"✅ {stock_name} ({stock_code}): {count}건 저장")
        return count
        
    except Exception as e:
        logger.error(f"❌ {stock_name} ({stock_code}) 처리 중 오류: {e}")
        return 0

def main():
    parser = argparse.ArgumentParser(description='Collect 5-minute stock chart data')
    parser.add_argument('--codes', help='Specific stock codes to collect (comma separated)', default=None)
    parser.add_argument('--workers', type=int, default=1, help='Number of concurrent workers (Default 1 for safety)')
    args = parser.parse_args()
    
    # 0. 초기화
    init_engine()
    gateway = KISGatewayClient()
    
    # 1. 수집 대상 선정
    stocks = []
    
    if args.codes:
        # 특정 종목 지정 시 (Time Check Skip)
        code_list = args.codes.split(',')
        stocks = [{'code': c.strip(), 'name': f"Manual-{c.strip()}"} for c in code_list]
        logger.info(f"🎯 수동 지정 종목: {len(stocks)}개 (시간 체크 건너뜀)")
    else:
        # 정규 실행 시 시간 체크 (09:00 ~ 15:35)
        if not is_operating_hours(start_hour=9, end_hour=15, end_minute=35):
             logger.info("⛔ 장 운영 시간이 아닙니다 (09:00 ~ 15:35). 스크립트를 종료합니다.")
             return

        # KOSPI 200 등 Universe 로드 (Scout Job과 동일 로직 사용 권장)
        # 여기서는 NaverFinanceCrawler로 Top 200 가져오기
        try:
            stock_list = get_kospi_top_stocks(limit=200)
            for item in stock_list:
                stocks.append({'code': item['code'], 'name': item['name']})
            logger.info(f"✅ KOSPI Top {len(stocks)} 로드 완료")
        except Exception as e:
            logger.error(f"❌ 종목 리스트 로드 실패: {e}")
            return
    
    # 2. 실행
    total_processed = 0
    total_saved = 0
    
    logger.info(f"🚀 수집 시작 (Workers: {args.workers})")
    start_time = datetime.now()
    
    # Gateway 사용 시 병렬 처리 가능 (Gateway Queue가 처리)
    # 단, GatewayClient 내부 Rate Limit(0.1s)이 있으므로 ThreadLocal한 Client가 아니면 병목 가능성.
    # 여기서는 단순하게 하나의 GatewayClient를 공유하되, 내부 Lock이 없다면 순차적임.
    # 안전하게 순차 처리하되, GatewayClient가 빠르므로 괜찮음.
    
    # ThreadPool 사용 여부: gateway_client.py의 requests.Session은 Thread safe하지 않을 수 있음.
    # 매번 Client 생성은 부담스럽지만, requests.Session은 스레드별로 만드는게 정석.
    # 간단히 순차 처리로 시작 (이미 0.1s delay면 충분히 빠름)
    
    for stock in stocks:
        count = process_stock(gateway, stock['code'], stock['name'])
        total_saved += count
        total_processed += 1
        
    duration = datetime.now() - start_time
    logger.info(f"🏁 완료: 총 {total_processed}종목, {total_saved}개 봉 저장 (소요시간: {duration})")

if __name__ == "__main__":
    main()
