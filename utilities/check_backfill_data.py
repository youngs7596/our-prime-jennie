
import sys
import os
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import text

# 프로젝트 루트를 경로에 추가
sys.path.append(os.getcwd())
load_dotenv()

from shared import database
from shared.db.connection import session_scope, ensure_engine_initialized

def check_data_coverage():
    ensure_engine_initialized()
    print("🔍 백필 데이터 커버리지 점검 (2025-07-01 ~ 2026-01-09)")
    print("=" * 60)
    
    start_date = '2025-07-01'
    end_date = '2026-01-09'
    
    with session_scope() as session:
        # 1. 주가 데이터 (STOCK_DAILY_PRICES_3Y)
        print("\n1. [주가] STOCK_DAILY_PRICES_3Y")
        query_price = text("""
            SELECT MIN(PRICE_DATE), MAX(PRICE_DATE), COUNT(*)
            FROM STOCK_DAILY_PRICES_3Y
            WHERE PRICE_DATE BETWEEN :start AND :end
        """)
        res_price = session.execute(query_price, {'start': start_date, 'end': end_date}).fetchone()
        print(f"   - 범위: {res_price[0]} ~ {res_price[1]}")
        print(f"   - 데이터 수: {res_price[2]} rows")
        
        # 2. 펀더멘털 데이터 (STOCK_FUNDAMENTALS)
        print("\n2. [펀더멘털] STOCK_FUNDAMENTALS (PER, PBR, 시총)")
        query_fund = text("""
            SELECT MIN(TRADE_DATE), MAX(TRADE_DATE), COUNT(*)
            FROM STOCK_FUNDAMENTALS
            WHERE TRADE_DATE BETWEEN :start AND :end
        """)
        res_fund = session.execute(query_fund, {'start': start_date, 'end': end_date}).fetchone()
        print(f"   - 범위: {res_fund[0]} ~ {res_fund[1]}")
        print(f"   - 데이터 수: {res_fund[2]} rows")
        if res_fund[2] == 0:
            print("   ❌ 해당 기간 데이터 전멸 (PER/PBR 0.0 원인)")

        # 3. 수급 데이터 (STOCK_INVESTOR_TRADING)
        print("\n3. [수급] STOCK_INVESTOR_TRADING (외인/기관 순매수)")
        query_invest = text("""
            SELECT MIN(TRADE_DATE), MAX(TRADE_DATE), COUNT(*)
            FROM STOCK_INVESTOR_TRADING
            WHERE TRADE_DATE BETWEEN :start AND :end
        """)
        res_invest = session.execute(query_invest, {'start': start_date, 'end': end_date}).fetchone()
        print(f"   - 범위: {res_invest[0]} ~ {res_invest[1]}")
        print(f"   - 데이터 수: {res_invest[2]} rows")
        if res_invest[2] == 0:
            print("   ❌ 해당 기간 데이터 전멸 (외인순매수 0.0% 원인)")

        # 4. 뉴스 데이터 (NEWS_SENTIMENT)
        print("\n4. [뉴스] NEWS_SENTIMENT")
        query_news = text("""
            SELECT MIN(PUBLISHED_AT), MAX(PUBLISHED_AT), COUNT(*)
            FROM NEWS_SENTIMENT
            WHERE PUBLISHED_AT BETWEEN :start AND :end
        """)
        res_news = session.execute(query_news, {'start': start_date, 'end': end_date}).fetchone()
        print(f"   - 범위: {res_news[0]} ~ {res_news[1]}")
        print(f"   - 데이터 수: {res_news[2]} rows")
        
    print("=" * 60)

if __name__ == "__main__":
    check_data_coverage()
