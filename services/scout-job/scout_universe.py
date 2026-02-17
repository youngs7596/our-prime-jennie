# services/scout-job/scout_universe.py
# Version: v3.0 (네이버 업종 기반 DB 조회)
# Scout Job Universe Selection - 섹터 분석 및 종목 선별 함수
#
# scout.py에서 분리된 종목 유니버스 관리 함수들

import logging
import time
from typing import Dict, List, Optional
import pandas as pd
import shared.database as database
from shared.crawlers.naver import get_kospi_top_stocks as _get_naver_top_stocks

logger = logging.getLogger(__name__)

# 정적 우량주 목록 (Fallback용)
BLUE_CHIP_STOCKS = [
    {"code": "0001", "name": "KOSPI", "is_tradable": False},
    {"code": "005930", "name": "삼성전자", "is_tradable": True},
    {"code": "000660", "name": "SK하이닉스", "is_tradable": True},
    {"code": "035420", "name": "NAVER", "is_tradable": True},
    {"code": "035720", "name": "카카오", "is_tradable": True},
]

# 섹터 캐시 (DB 조회 결과 메모리 캐시)
_sector_cache: Dict[str, str] = {}


def _resolve_sector(code: str, name: str = '') -> str:
    """DB SECTOR_NAVER 기반 섹터 조회 (캐시 포함)"""
    if code in _sector_cache:
        return _sector_cache[code]
    try:
        from shared.db.connection import session_scope
        from shared.db.models import StockMaster
        from sqlalchemy import select
        with session_scope(readonly=True) as session:
            row = session.execute(
                select(StockMaster.sector_naver, StockMaster.sector_kospi200
                      ).where(StockMaster.stock_code == code)
            ).first()
            if row and row.sector_naver:
                result = row.sector_naver
            elif row and row.sector_kospi200 and row.sector_kospi200 not in ('etc', '미분류'):
                result = row.sector_kospi200
            else:
                result = '기타'
            _sector_cache[code] = result
            return result
    except Exception as e:
        logger.warning(f"섹터 조회 실패 [{code}]: {e}")
        return '기타'

def _scrape_naver_finance_top_stocks(limit: int = 200) -> list:
    """
    네이버 금융에서 KOSPI 시총 상위 종목을 스크래핑합니다.
    shared.crawlers.naver 공통 모듈 사용.
    반환값: [{"code", "name", "price", "change_pct", "sector", "rank"}]
    """
    logger.info(f"   (A) 네이버 금융 시총 스크래핑 (상위 {limit}개) 시도 중...")
    
    try:
        # shared.crawlers.naver 모듈 사용
        stocks = _get_naver_top_stocks(limit=limit)
        
        if stocks:
            # 섹터 정보 추가
            for stock in stocks:
                stock['sector'] = _resolve_sector(stock['code'])
            
            logger.info(f"   (A) ✅ 네이버 금융 스크래핑 완료: {len(stocks)}개 종목 로드.")
            return stocks
        else:
            logger.warning("   (A) ⚠️ 네이버 금융 스크래핑 결과 없음")
            return []
    
    except Exception as e:
        logger.warning(f"   (A) ⚠️ 네이버 금융 스크래핑 실패: {e}")
        return []

def analyze_sector_momentum(kis_api, db_conn, watchlist_snapshot=None):
    """
    섹터별 모멘텀 분석
    네이버 금융에서 스크래핑한 데이터(등락률)를 기반으로 핫 섹터를 식별합니다.
    """
    logger.info("   (E) 섹터별 모멘텀 분석 시작 (Naver Source)...")
    
    sector_data = {}
    
    try:
        # 네이버 스크래핑으로 현재 데이터 획득 (Top 200)
        top_stocks = _scrape_naver_finance_top_stocks(limit=200)

        # Pre-market 감지: 모든 change_pct가 0이면 DB 전일 대비 수익률로 대체
        all_zero = all(s.get('change_pct', 0.0) == 0.0 for s in top_stocks) if top_stocks else False
        if all_zero and top_stocks and db_conn:
            logger.info("   (E) ⚠️ 네이버 등락률 전부 0% (장 시작 전/데이터 미반영) → DB 전일 대비 수익률로 대체")
            codes = [s['code'] for s in top_stocks]
            try:
                prices_batch = database.get_daily_prices_batch(db_conn, codes, limit=2)
                replaced = 0
                for stock in top_stocks:
                    df = prices_batch.get(stock['code'])
                    if isinstance(df, pd.DataFrame) and len(df) >= 2:
                        latest = float(df.iloc[-1]['CLOSE_PRICE'])
                        prev = float(df.iloc[-2]['CLOSE_PRICE'])
                        if prev > 0:
                            stock['change_pct'] = round(((latest - prev) / prev) * 100, 2)
                            replaced += 1
                logger.info(f"   (E) ✅ DB 기반 수익률 대체 완료: {replaced}/{len(top_stocks)}개 종목")
            except Exception as e:
                logger.warning(f"   (E) ⚠️ DB 기반 수익률 계산 실패 (네이버 0% 데이터 유지): {e}")

        for stock in top_stocks:
            sector = stock.get('sector', '기타')
            change_pct = stock.get('change_pct', 0.0)
            
            if abs(change_pct) > 30: # 이상치 제거
                continue
                
            if sector not in sector_data:
                sector_data[sector] = {'stocks': [], 'returns': []}
            
            sector_data[sector]['stocks'].append({'code': stock['code'], 'name': stock['name']})
            sector_data[sector]['returns'].append(change_pct)
        
        # 섹터별 평균 수익률 계산
        hot_sectors = {}
        for sector, data in sector_data.items():
            if data['returns']:
                avg_return = sum(data['returns']) / len(data['returns'])
                hot_sectors[sector] = {
                    'avg_return': avg_return,
                    'stock_count': len(data['stocks']),
                    'stocks': data['stocks'][:5],
                    'penalty_score': 0, # Default
                    'trend_status': 'NEUTRAL'
                }

        # [NEW] 섹터별 추세 분석 (Penalty Calculation)
        # 상위 섹터나 하위 섹터에 대해서만 상세 분석 수행 (API 호출 최적화)
        # 여기서는 Penalty가 중요하므로, 수익률 하위 섹터에 대해 집중 분석
        sorted_sectors_by_return = sorted(hot_sectors.items(), key=lambda x: x[1]['avg_return'])
        
        # 하위 5개 섹터 (또는 수익률 음수인 모든 섹터) 검사
        target_sectors = [s for s, info in sorted_sectors_by_return if info['avg_return'] < -1.0][:5]
        
        if target_sectors:
            logger.info(f"   (E) 📉 하락세 섹터 상세 분석 중 ({len(target_sectors)}개)...")
            from datetime import timedelta, date
            
            for sector_name in target_sectors:
                info = hot_sectors[sector_name]
                # 대표 종목 3개의 5일치 데이터를 가져와서 섹터 지수 추정
                top_codes = [s['code'] for s in info['stocks'][:3]]
                
                sector_closes = [] # [day0_avg, day1_avg, ...]
                
                # 병렬 처리 대신 간단히 순차 처리 (종목 수가 적음)
                valid_stock_count = 0
                aggregated_history = {} # {date: [prices]}
                
                for code in top_codes:
                    try:
                        # DB에서 최근 30일치 조회 (MA20 계산 위해)
                        prices = database.get_daily_prices(db_conn, code, limit=30)
                        if not prices.empty and len(prices) >= 20:
                            for _, row in prices.iterrows():
                                d = row['PRICE_DATE'] # date object
                                p = float(row['CLOSE_PRICE'])
                                if d not in aggregated_history: aggregated_history[d] = []
                                aggregated_history[d].append(p)
                            valid_stock_count += 1
                    except (ValueError, TypeError) as e:
                        logger.debug(f"가격 집계 skip [{code}]: {e}")
                
                if valid_stock_count > 0:
                    # 날짜별 평균가 계산 (섹터 지수 대용)
                    sorted_dates = sorted(aggregated_history.keys())
                    if len(sorted_dates) < 20:
                        continue
                        
                    sector_index_series = []
                    for d in sorted_dates:
                        vals = aggregated_history[d]
                        if vals:
                            avg_p = sum(vals) / len(vals)
                            sector_index_series.append(avg_p)
                    
                    if len(sector_index_series) < 20:
                        continue

                    # 지표 계산
                    curr_price = sector_index_series[-1]
                    price_5d_ago = sector_index_series[-6] if len(sector_index_series) >= 6 else sector_index_series[0]
                    
                    return_5d = ((curr_price - price_5d_ago) / price_5d_ago) * 100
                    ma5 = sum(sector_index_series[-5:]) / 5
                    ma20 = sum(sector_index_series[-20:]) / 20
                    
                    # Penalty Condition: 5일 수익률 < -3% AND 역배열 (MA5 < MA20)
                    if return_5d < -3.0 and ma5 < ma20:
                        info['penalty_score'] = -10
                        info['trend_status'] = 'FALLING_KNIFE'
                        logger.info(f"       ⚠️ [Penalty] {sector_name}: 5일등락 {return_5d:.1f}%, 역배열 (Falling Knife)")
                    else:
                        info['trend_status'] = 'WEAK'

        sorted_sectors = sorted(hot_sectors.items(), key=lambda x: x[1]['avg_return'], reverse=True)
        
        logger.info(f"   (E) ✅ 섹터 분석 완료. 핫 섹터 TOP 3:")
        for i, (sector, info) in enumerate(sorted_sectors[:3]):
            logger.info(f"       {i+1}. {sector}: 평균 수익률 {info['avg_return']:.2f}% ({info['stock_count']}종목)")
        
        return dict(sorted_sectors)
        
    except Exception as e:
        logger.warning(f"   (E) ⚠️ 섹터 분석 실패: {e}")
        return {}

def get_hot_sector_stocks(sector_analysis, top_n=30):
    """
    핫 섹터의 종목들을 우선 후보로 반환
    """
    if not sector_analysis:
        return []
    
    hot_stocks = []
    sorted_sectors = list(sector_analysis.items())[:3]
    
    for sector, info in sorted_sectors:
        for stock in info.get('stocks', []):
            hot_stocks.append({
                'code': stock['code'],
                'name': stock['name'],
                'sector': sector,
                'sector_momentum': info['avg_return'],
            })
    
    return hot_stocks[:top_n]

def get_dynamic_blue_chips(limit=200):
    """
    KOSPI 시가총액 상위 종목을 수집합니다.
    """
    # 네이버 금융 스크래핑 사용
    return _scrape_naver_finance_top_stocks(limit=limit)

def get_momentum_stocks(kis_api, db_conn, period_months=6, top_n=30, watchlist_snapshot=None):
    """
    모멘텀 팩터 기반 종목 선별
    """
    logger.info(f"   (D) 모멘텀 팩터 계산 중 (기간: {period_months}개월, 상위 {top_n}개)...")
    momentum_scores = []
    
    try:
        # 1. KOSPI 수익률 계산 (DB 사용)
        kospi_code = "0001"
        period_days = period_months * 30
        kospi_prices = database.get_daily_prices(db_conn, kospi_code, limit=period_days)
        
        if kospi_prices.empty or len(kospi_prices) < period_days * 0.8:
            logger.warning(f"   (D) ⚠️ KOSPI 데이터 부족 ({len(kospi_prices)}일). 모멘텀 계산 건너뜀.")
            return []
        
        kospi_start_price = float(kospi_prices['CLOSE_PRICE'].iloc[0])
        kospi_end_price = float(kospi_prices['CLOSE_PRICE'].iloc[-1])
        kospi_return = (kospi_end_price / kospi_start_price - 1) * 100
        
        # 2. 전체 종목 또는 Watchlist에서 가져오기
        all_codes = database.get_all_stock_codes(db_conn)
        
        if not all_codes:
            watchlist = watchlist_snapshot or database.get_active_watchlist(db_conn)
            if not watchlist:
                stocks_to_check = [s for s in BLUE_CHIP_STOCKS if s.get('is_tradable', True)]
            else:
                stocks_to_check = [{'code': code, 'name': info.get('name', code)} for code, info in watchlist.items() if info.get('is_tradable', True)]
        else:
            stocks_to_check = [{'code': code, 'name': code} for code in all_codes]

        logger.info(f"   (D) {len(stocks_to_check)}개 종목의 모멘텀 계산 중... (전체 대상)")
        
        # 3. 각 종목의 모멘텀 계산
        for stock in stocks_to_check:
            try:
                code = stock['code']
                name = stock.get('name', code)
                
                stock_prices = database.get_daily_prices(db_conn, code, limit=period_days)
                
                if stock_prices.empty or len(stock_prices) < period_days * 0.8:
                    continue
                
                stock_start_price = float(stock_prices['CLOSE_PRICE'].iloc[0])
                stock_end_price = float(stock_prices['CLOSE_PRICE'].iloc[-1])
                stock_return = (stock_end_price / stock_start_price - 1) * 100
                
                relative_momentum = stock_return - kospi_return
                
                momentum_scores.append({
                    'code': code,
                    'name': name,
                    'momentum': relative_momentum,
                    'absolute_return': stock_return,
                    'kospi_return': kospi_return
                })
                # CPU sleep to prevent high load if loop is tight
                # time.sleep(0.001) 
                
            except Exception as e:
                continue
        
        momentum_scores.sort(key=lambda x: x['momentum'], reverse=True)
        return momentum_scores[:top_n]
        
    except Exception as e:
        logger.error(f"   (D) ❌ 모멘텀 팩터 계산 중 오류 발생: {e}", exc_info=True)
        return []

def filter_valid_stocks(candidate_stocks: dict, session) -> dict:
    """
    후보군 중 STOCK_MASTER에 존재하고 ETF가 아닌 종목만 필터링합니다.
    """
    if not candidate_stocks:
        return {}
        
    from sqlalchemy import text
    
    stock_codes = list(candidate_stocks.keys())
    # KOSPI 지수 등 특수 코드 제외
    stock_codes = [c for c in stock_codes if c != '0001']
    
    placeholders = ','.join([f"'{code}'" for code in stock_codes])
    
    query = text(f"""
        SELECT STOCK_CODE 
        FROM STOCK_MASTER 
        WHERE STOCK_CODE IN ({placeholders})
        AND IS_ETF = 0
    """)
    
    try:
        rows = session.execute(query).fetchall()
        valid_codes = {row[0] for row in rows}
        
        filtered = {
            code: info 
            for code, info in candidate_stocks.items() 
            if code in valid_codes
        }
        
        removed_count = len(candidate_stocks) - len(filtered)
        if removed_count > 0:
            logger.info(f"   (Filter) 🚫 {removed_count}개 종목 제외 (ETF 또는 시스템 미등록 종목)")
            
        return filtered
    except Exception as e:
        logger.warning(f"   (Filter) ⚠️ 종목 필터링 중 오류 발생: {e}")
        return candidate_stocks
