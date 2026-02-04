#!/usr/bin/env python3
"""
scripts/collect_dividend_data.py
================================
KOSPI 고배당주의 배당락일/배당금 데이터를 수집하여 DB에 저장합니다.

사용법:
    # 전체 수집 (KOSPI 상위 200, 최근 10년)
    python scripts/collect_dividend_data.py
    
    # 제한 수집 (테스트용)
    python scripts/collect_dividend_data.py --limit=10 --start-year=2023
    
    # 드라이런 (DB 저장 없이 출력만)
    python scripts/collect_dividend_data.py --dry-run --limit=5

의존성:
    pip install pykrx pandas sqlalchemy pymysql
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# shared 모듈 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from pykrx import stock as krx_stock

from shared.db.connection import get_session, init_engine
from shared.db.models import DividendHistory

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def get_kospi_top_stocks(limit: int = 200) -> List[Dict]:
    """
    KOSPI 시가총액 상위 종목 조회
    """
    logger.info(f"📊 KOSPI 시총 상위 {limit}개 종목 조회 중...")
    
    today = datetime.now().strftime("%Y%m%d")
    
    try:
        # KOSPI 전체 종목의 시가총액 조회
        df = krx_stock.get_market_cap_by_ticker(today, market="KOSPI")
        
        if df.empty:
            # 오늘 데이터가 없으면 최근 영업일 조회
            for i in range(1, 10):
                prev_day = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
                df = krx_stock.get_market_cap_by_ticker(prev_day, market="KOSPI")
                if not df.empty:
                    break
        
        # 시가총액 기준 정렬 후 상위 N개
        df = df.sort_values("시가총액", ascending=False).head(limit)
        
        stocks = []
        for ticker in df.index:
            name = krx_stock.get_market_ticker_name(ticker)
            market_cap = df.loc[ticker, "시가총액"]
            stocks.append({
                "stock_code": ticker,
                "stock_name": name,
                "market_cap": market_cap
            })
        
        logger.info(f"✅ {len(stocks)}개 종목 조회 완료")
        return stocks
        
    except Exception as e:
        logger.error(f"❌ 종목 조회 실패: {e}")
        return []


def get_dividend_info(stock_code: str, start_year: int, end_year: int) -> List[Dict]:
    """
    특정 종목의 연도별 배당 정보 조회
    pykrx의 get_market_fundamental_by_date API를 사용하여 DPS(주당배당금) 추출
    """
    dividends = []
    
    for year in range(start_year, end_year + 1):
        try:
            # 해당 연도의 연말 fundamental 데이터 조회 (12월)
            start_date = f"{year}1201"
            end_date = f"{year}1231"
            
            df = krx_stock.get_market_fundamental_by_date(start_date, end_date, stock_code)
            
            if df is None or df.empty:
                continue
            
            # 마지막 거래일의 DPS(주당배당금) 확인
            last_row = df.iloc[-1]
            dps = float(last_row.get("DPS", 0) or 0)
            div_yield = float(last_row.get("DIV", 0) or 0)
            
            if dps <= 0:
                continue
            
            # 배당락일 추정: 한국은 보통 다음해 1월 첫 거래일
            # 정확한 배당락일은 KRX 공시를 확인해야 하지만, 추정값 사용
            ex_date = datetime(year + 1, 1, 2)  # 1월 2일로 추정 (첫 거래일)
            
            dividends.append({
                "year": year,
                "ex_dividend_date": ex_date,
                "dividend_per_share": dps,
                "dividend_yield": div_yield,
                "dividend_type": "YEAR_END"
            })
            
        except Exception as e:
            logger.debug(f"  {year}년 배당 조회 실패: {e}")
            continue
    
    return dividends


def get_price_around_ex_date(stock_code: str, ex_date: datetime) -> Dict:
    """
    배당락일 전후 주가 정보 조회
    """
    price_info = {
        "prev_close_price": None,
        "ex_date_open_price": None,
        "ex_date_close_price": None,
        "ex_date_volume": None,
        "prev_avg_volume_20d": None,
        "recovery_d1": None,
        "recovery_d3": None,
        "recovery_d5": None,
        "recovery_d10": None,
        "recovery_d20": None,
    }
    
    try:
        # 배당락일 전후 40일 데이터 조회
        start = (ex_date - timedelta(days=30)).strftime("%Y%m%d")
        end = (ex_date + timedelta(days=30)).strftime("%Y%m%d")
        
        df = krx_stock.get_market_ohlcv_by_date(start, end, stock_code)
        
        if df.empty:
            return price_info
        
        # 인덱스를 datetime으로 변환
        df.index = pd.to_datetime(df.index)
        ex_date_dt = pd.Timestamp(ex_date)
        
        # 배당락일 및 전일 찾기
        if ex_date_dt in df.index:
            price_info["ex_date_open_price"] = float(df.loc[ex_date_dt, "시가"])
            price_info["ex_date_close_price"] = float(df.loc[ex_date_dt, "종가"])
            price_info["ex_date_volume"] = float(df.loc[ex_date_dt, "거래량"])
        
        # 배당락일 전일 (가장 가까운 이전 거래일)
        prev_dates = df.index[df.index < ex_date_dt]
        if len(prev_dates) > 0:
            prev_date = prev_dates[-1]
            price_info["prev_close_price"] = float(df.loc[prev_date, "종가"])
            
            # 전 20일 평균 거래량
            if len(prev_dates) >= 20:
                vol_20d = df.loc[prev_dates[-20:], "거래량"].mean()
                price_info["prev_avg_volume_20d"] = float(vol_20d)
        
        # 회복 패턴 (D+1, D+3, D+5, D+10, D+20)
        future_dates = df.index[df.index > ex_date_dt].tolist()
        recovery_map = {1: "recovery_d1", 3: "recovery_d3", 5: "recovery_d5", 10: "recovery_d10", 20: "recovery_d20"}
        
        for offset, key in recovery_map.items():
            if len(future_dates) >= offset:
                price_info[key] = float(df.loc[future_dates[offset - 1], "종가"])
        
    except Exception as e:
        logger.debug(f"  주가 조회 실패: {e}")
    
    return price_info


def collect_dividend_data(
    limit: int = 200,
    start_year: int = 2015,
    end_year: int = None,
    dry_run: bool = False
) -> int:
    """
    메인 수집 함수
    """
    if end_year is None:
        # 12월 데이터가 없으면 이전 연도까지만 조회
        now = datetime.now()
        if now.month < 12:
            end_year = now.year - 1
        else:
            end_year = now.year
    
    logger.info("=" * 60)
    logger.info("📈 배당 데이터 수집 시작")
    logger.info(f"   기간: {start_year} ~ {end_year}")
    logger.info(f"   종목 수: {limit}개")
    logger.info(f"   드라이런: {dry_run}")
    logger.info("=" * 60)
    
    # 1. KOSPI 상위 종목 조회
    stocks = get_kospi_top_stocks(limit)
    if not stocks:
        logger.error("❌ 종목 조회 실패. 종료합니다.")
        return 0
    
    # 2. 각 종목별 배당 정보 수집
    total_records = 0
    
    session = None
    if not dry_run:
        init_engine()  # DB 연결 초기화
        session = get_session()
    
    try:
        for i, stock in enumerate(stocks, 1):
            stock_code = stock["stock_code"]
            stock_name = stock["stock_name"]
            
            logger.info(f"[{i}/{len(stocks)}] {stock_name}({stock_code}) 배당 정보 수집 중...")
            
            # 배당 정보 조회
            dividends = get_dividend_info(stock_code, start_year, end_year)
            
            if not dividends:
                logger.debug(f"  → 배당 이력 없음")
                continue
            
            for div in dividends:
                ex_date = div["ex_dividend_date"]
                
                # 주가 정보 조회
                price_info = get_price_around_ex_date(stock_code, ex_date)
                
                record = DividendHistory(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    ex_dividend_date=ex_date,
                    dividend_per_share=div["dividend_per_share"],
                    dividend_yield=div["dividend_yield"],
                    dividend_type=div["dividend_type"],
                    **price_info
                )
                
                if dry_run:
                    logger.info(f"  [DRY-RUN] {ex_date.strftime('%Y-%m-%d')}: "
                               f"배당금 {div['dividend_per_share']:,.0f}원, "
                               f"수익률 {div['dividend_yield']:.2f}%")
                else:
                    session.merge(record)
                
                total_records += 1
            
            # 중간 커밋 (50개마다)
            if not dry_run and i % 50 == 0:
                session.commit()
                logger.info(f"  💾 중간 저장 완료 ({total_records}건)")
        
        # 최종 커밋
        if not dry_run and session:
            session.commit()
            logger.info(f"✅ 최종 저장 완료")
        
    except Exception as e:
        logger.error(f"❌ 수집 중 오류 발생: {e}")
        if session:
            session.rollback()
        raise
    finally:
        if session:
            session.close()
    
    logger.info("=" * 60)
    logger.info(f"📊 수집 완료: 총 {total_records}건")
    logger.info("=" * 60)
    
    return total_records


def main():
    parser = argparse.ArgumentParser(description="KOSPI 배당 데이터 수집기")
    parser.add_argument("--limit", type=int, default=200, help="수집할 종목 수 (기본: 200)")
    parser.add_argument("--start-year", type=int, default=2015, help="시작 연도 (기본: 2015)")
    parser.add_argument("--end-year", type=int, default=None, help="종료 연도 (기본: 현재)")
    parser.add_argument("--dry-run", action="store_true", help="DB 저장 없이 테스트 실행")
    
    args = parser.parse_args()
    
    collect_dividend_data(
        limit=args.limit,
        start_year=args.start_year,
        end_year=args.end_year,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()
