"""
shared/db/factor_repository.py - FactorAnalyzer용 SQLAlchemy Repository
========================================================================

factor_analyzer.py의 DB 접근 로직을 SQLAlchemy ORM으로 분리합니다.
테스트 가능하고 DB 독립적인 데이터 접근 레이어를 제공합니다.

사용 예시:
---------
>>> from shared.db.factor_repository import FactorRepository
>>> 
>>> repo = FactorRepository(session)
>>> prices = repo.get_historical_prices('005930', 504)
>>> financials = repo.get_financial_data(['005930', '000660'])
"""

import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
import pandas as pd
from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from .models import (
    StockDailyPrice,
    StockMaster,
    FinancialMetricsQuarterly,
    StockInvestorTrading,
    StockNewsSentiment,
    StockDisclosures,
    FactorMetadata,
    FactorPerformance,
    NewsFactorStats,
    DailyQuantScore,
)

logger = logging.getLogger(__name__)


class FactorRepository:
    """
    FactorAnalyzer용 SQLAlchemy Repository
    
    DB 접근 로직을 ORM으로 캡슐화하여 테스트 용이성을 높입니다.
    """
    
    def __init__(self, session: Session):
        """
        Args:
            session: SQLAlchemy 세션
        """
        self.session = session
    
    def _rows_to_df(self, rows, columns) -> pd.DataFrame:
        """
        SQLAlchemy 결과를 안전하게 DataFrame으로 변환
        """
        try:
            if not rows:
                return pd.DataFrame()
            data = []
            for r in rows:
                try:
                    # SQLAlchemy Row/RowMapping 대응
                    record = {}
                    for col, key in zip(columns, r.keys() if hasattr(r, "keys") else range(len(columns))):
                        record[col] = r[key] if hasattr(r, "__getitem__") else getattr(r, key, None)
                    data.append(record)
                except Exception:
                    data.append({col: None for col in columns})
            return pd.DataFrame(data, columns=columns)
        except Exception as e:
            logger.error(f"❌ [FactorRepo] DataFrame 변환 실패: {e}")
            return pd.DataFrame()
    
    # =========================================================================
    # 주가 데이터 조회
    # =========================================================================
    
    def get_historical_prices(
        self, 
        stock_code: str, 
        days: int = 504
    ) -> pd.DataFrame:
        """
        종목의 과거 주가 데이터 조회
        
        Args:
            stock_code: 종목 코드
            days: 조회할 일수 (기본 504일 = 약 2년)
        
        Returns:
            DataFrame with columns: [PRICE_DATE, CLOSE_PRICE, VOLUME, HIGH_PRICE, LOW_PRICE]
        """
        try:
            stmt = (
                select(
                    StockDailyPrice.price_date,
                    StockDailyPrice.close_price,
                    StockDailyPrice.volume,
                    StockDailyPrice.high_price,
                    StockDailyPrice.low_price
                )
                .where(StockDailyPrice.stock_code == stock_code)
                .order_by(desc(StockDailyPrice.price_date))
                .limit(days)
            )
            results = self.session.execute(stmt).all()
            
            if not results:
                return pd.DataFrame()
            
            df = self._rows_to_df(results, [
                'PRICE_DATE', 'CLOSE_PRICE', 'VOLUME', 'HIGH_PRICE', 'LOW_PRICE'
            ])
            df['PRICE_DATE'] = pd.to_datetime(df['PRICE_DATE'])
            df = df.sort_values('PRICE_DATE').reset_index(drop=True)
            
            return df
            
        except Exception as e:
            logger.error(f"❌ [FactorRepo] 주가 데이터 조회 실패 ({stock_code}): {e}")
            return pd.DataFrame()
    
    def get_historical_prices_bulk(
        self, 
        stock_codes: List[str], 
        days: int = 504
    ) -> Dict[str, pd.DataFrame]:
        """
        여러 종목의 과거 주가 데이터 일괄 조회
        
        Args:
            stock_codes: 종목 코드 리스트
            days: 조회할 일수
        
        Returns:
            {stock_code: DataFrame} 딕셔너리
        """
        result = {}
        for code in stock_codes:
            result[code] = self.get_historical_prices(code, days)
        return result
    
    # =========================================================================
    # 종목 마스터 조회
    # =========================================================================
    
    def get_market_cap(self, stock_code: str) -> Optional[int]:
        """
        종목 시가총액 조회
        
        Args:
            stock_code: 종목 코드
        
        Returns:
            시가총액 (원) 또는 None
        """
        try:
            stmt = select(StockMaster.market_cap).where(StockMaster.stock_code == stock_code)
            result = self.session.execute(stmt).first()
            
            if result and result[0]:
                return int(result[0])
            return None
            
        except Exception as e:
            logger.warning(f"⚠️ [FactorRepo] 시가총액 조회 실패 ({stock_code}): {e}")
            return None
    
    def get_stock_sector_naver(self, stock_code: str) -> Optional[str]:
        """
        네이버 업종 세분류 조회

        Args:
            stock_code: 종목 코드

        Returns:
            네이버 업종명 또는 None
        """
        try:
            stmt = select(StockMaster.sector_naver).where(
                StockMaster.stock_code == stock_code
            )
            result = self.session.scalar(stmt)
            return result if result else None
        except Exception as e:
            logger.warning(f"⚠️ [FactorRepo] 네이버 섹터 조회 실패 ({stock_code}): {e}")
            return None

    def get_stock_sector(self, stock_code: str) -> Tuple[Optional[str], Optional[str]]:
        """
        종목 섹터 정보 조회

        Args:
            stock_code: 종목 코드

        Returns:
            (sector_kospi200, industry_code) 튜플
        """
        try:
            stmt = select(
                StockMaster.sector_kospi200,
            ).where(StockMaster.stock_code == stock_code)
            result = self.session.execute(stmt).first()

            if result:
                return result[0], None
            return None, None

        except Exception as e:
            logger.warning(f"⚠️ [FactorRepo] 섹터 조회 실패 ({stock_code}): {e}")
            return None, None
    
    # =========================================================================
    # 재무 데이터 조회
    # =========================================================================
    
    def get_financial_data(
        self, 
        stock_codes: List[str]
    ) -> Dict[str, Dict]:
        """
        여러 종목의 재무 데이터 조회 (PER, PBR, ROE)
        
        Args:
            stock_codes: 종목 코드 리스트
        
        Returns:
            {stock_code: {quarter_date: {per, pbr, roe}}} 딕셔너리
        """
        try:
            stmt = (
                select(
                    FinancialMetricsQuarterly.stock_code,
                    FinancialMetricsQuarterly.quarter_date,
                    FinancialMetricsQuarterly.per,
                    FinancialMetricsQuarterly.pbr,
                    FinancialMetricsQuarterly.roe
                )
                .where(FinancialMetricsQuarterly.stock_code.in_(stock_codes))
                .order_by(
                    FinancialMetricsQuarterly.stock_code,
                    desc(FinancialMetricsQuarterly.quarter_date)
                )
            )
            results = self.session.execute(stmt).all()
            
            financial_data = {}
            for row in results:
                code = row[0]
                quarter_date = row[1]
                
                if code not in financial_data:
                    financial_data[code] = {}
                
                # date 객체를 문자열로 변환
                quarter_key = quarter_date.strftime('%Y-%m-%d') if isinstance(quarter_date, date) else str(quarter_date)
                
                financial_data[code][quarter_key] = {
                    'per': row[2],
                    'pbr': row[3],
                    'roe': row[4]
                }
            
            return financial_data
            
        except Exception as e:
            logger.error(f"❌ [FactorRepo] 재무 데이터 조회 실패: {e}")
            return {}
    
    # =========================================================================
    # 수급 데이터 조회
    # =========================================================================
    
    def get_supply_demand_data(
        self, 
        stock_codes: List[str], 
        days: int = 504
    ) -> Dict[str, pd.DataFrame]:
        """
        여러 종목의 투자자별 매매 동향 조회
        
        Args:
            stock_codes: 종목 코드 리스트
            days: 조회할 일수
        
        Returns:
            {stock_code: DataFrame} 딕셔너리
        """
        result = {}
        
        try:
            for code in stock_codes:
                stmt = (
                    select(
                        StockInvestorTrading.trade_date,
                        StockInvestorTrading.foreign_net_buy,
                        StockInvestorTrading.institution_net_buy
                    )
                    .where(StockInvestorTrading.stock_code == code)
                    .order_by(desc(StockInvestorTrading.trade_date))
                    .limit(days)
                )
                rows = self.session.execute(stmt).all()
                
                df = self._rows_to_df(rows, ['TRADE_DATE', 'FOREIGN_NET_BUY', 'INSTITUTION_NET_BUY'])
                if not df.empty:
                    df['TRADE_DATE'] = pd.to_datetime(df['TRADE_DATE'])
                    df = df.sort_values('TRADE_DATE').reset_index(drop=True)
                result[code] = df
            
            return result
            
        except Exception as e:
            logger.error(f"❌ [FactorRepo] 수급 데이터 조회 실패: {e}")
            return {code: pd.DataFrame() for code in stock_codes}
    
    # =========================================================================
    # 뉴스 감성 데이터 조회
    # =========================================================================
    
    def get_news_sentiment_history(
        self, 
        stock_codes: List[str], 
        days: int = 504
    ) -> Dict[str, pd.DataFrame]:
        """
        여러 종목의 뉴스 감성 히스토리 조회
        
        Args:
            stock_codes: 종목 코드 리스트
            days: 조회할 일수
        
        Returns:
            {stock_code: DataFrame} 딕셔너리
        """
        result = {}
        
        try:
            for code in stock_codes:
                stmt = (
                    select(
                        StockNewsSentiment.news_date,
                        StockNewsSentiment.sentiment_score,
                        StockNewsSentiment.category
                    )
                    .where(StockNewsSentiment.stock_code == code)
                    .order_by(desc(StockNewsSentiment.news_date))
                    .limit(days)
                )
                rows = self.session.execute(stmt).all()
                
                df = self._rows_to_df(rows, ['NEWS_DATE', 'SENTIMENT_SCORE', 'CATEGORY'])
                if not df.empty:
                    df['NEWS_DATE'] = pd.to_datetime(df['NEWS_DATE'])
                    df = df.sort_values('NEWS_DATE').reset_index(drop=True)
                result[code] = df
            
            return result
            
        except Exception as e:
            logger.error(f"❌ [FactorRepo] 뉴스 감성 데이터 조회 실패: {e}")
            return {code: pd.DataFrame() for code in stock_codes}
    
    # =========================================================================
    # 공시 데이터 조회
    # =========================================================================
    
    def get_disclosures(
        self, 
        stock_codes: List[str], 
        lookback_days: int = 365
    ) -> Dict[str, List[Dict]]:
        """
        여러 종목의 공시 정보 조회
        
        Args:
            stock_codes: 종목 코드 리스트
            lookback_days: 조회할 기간 (일)
        
        Returns:
            {stock_code: [{'date': ..., 'category': ...}]} 딕셔너리
        """
        result = {code: [] for code in stock_codes}
        
        try:
            cutoff_date = datetime.now().date() - timedelta(days=lookback_days)
            
            stmt = (
                select(
                    StockDisclosures.stock_code,
                    StockDisclosures.disclosure_date,
                    StockDisclosures.category
                )
                .where(
                    and_(
                        StockDisclosures.stock_code.in_(stock_codes),
                        StockDisclosures.disclosure_date >= cutoff_date
                    )
                )
                .order_by(desc(StockDisclosures.disclosure_date))
            )
            rows = self.session.execute(stmt).all()
            
            for row in rows:
                code = row[0]
                if code in result:
                    result[code].append({
                        'date': row[1],
                        'category': row[2]
                    })
            
            return result
            
        except Exception as e:
            logger.error(f"❌ [FactorRepo] 공시 데이터 조회 실패: {e}")
            return result
    
    # =========================================================================
    # 팩터 메타데이터 저장/조회
    # =========================================================================
    
    def save_factor_metadata(
        self,
        factor_key: str,
        factor_name: str,
        market_regime: str,
        ic_mean: float,
        ic_std: float,
        ir: float,
        hit_rate: float,
        recommended_weight: float,
        sample_count: int,
        analysis_start_date: date = None,
        analysis_end_date: date = None
    ) -> bool:
        """
        팩터 메타데이터 저장 (UPSERT)
        
        Returns:
            성공 여부
        """
        try:
            # 기존 레코드 조회
            stmt = select(FactorMetadata).where(
                and_(
                    FactorMetadata.factor_key == factor_key,
                    FactorMetadata.market_regime == market_regime
                )
            )
            existing = self.session.scalars(stmt).first()
            
            if existing:
                # UPDATE
                existing.factor_name = factor_name
                existing.ic_mean = ic_mean
                existing.ic_std = ic_std
                existing.ir = ir
                existing.hit_rate = hit_rate
                existing.recommended_weight = recommended_weight
                existing.sample_count = sample_count
                existing.analysis_start_date = analysis_start_date
                existing.analysis_end_date = analysis_end_date
                existing.updated_at = datetime.now()
            else:
                # INSERT
                new_record = FactorMetadata(
                    factor_key=factor_key,
                    factor_name=factor_name,
                    market_regime=market_regime,
                    ic_mean=ic_mean,
                    ic_std=ic_std,
                    ir=ir,
                    hit_rate=hit_rate,
                    recommended_weight=recommended_weight,
                    sample_count=sample_count,
                    analysis_start_date=analysis_start_date,
                    analysis_end_date=analysis_end_date
                )
                self.session.add(new_record)
            
            self.session.commit()
            logger.debug(f"✅ [FactorRepo] 팩터 메타데이터 저장: {factor_key}")
            return True
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"❌ [FactorRepo] 팩터 메타데이터 저장 실패: {e}")
            return False
    
    def get_factor_metadata(
        self, 
        factor_key: str, 
        market_regime: str = 'ALL'
    ) -> Optional[FactorMetadata]:
        """
        팩터 메타데이터 조회
        """
        try:
            stmt = select(FactorMetadata).where(
                and_(
                    FactorMetadata.factor_key == factor_key,
                    FactorMetadata.market_regime == market_regime
                )
            )
            return self.session.scalars(stmt).first()
        except Exception as e:
            logger.warning(f"⚠️ [FactorRepo] 팩터 메타데이터 조회 실패: {e}")
            return None
    
    # =========================================================================
    # 팩터 성과 저장/조회
    # =========================================================================
    
    def save_factor_performance(
        self,
        target_type: str,
        target_code: str,
        target_name: str,
        condition_key: str,
        condition_desc: str,
        win_rate: float,
        avg_return: float,
        sample_count: int,
        holding_days: int = 5,
        recent_win_rate: float = None,
        recent_sample_count: int = None,
        analysis_date: date = None
    ) -> bool:
        """
        팩터 성과 저장 (UPSERT)
        
        Returns:
            성공 여부
        """
        try:
            # 기존 레코드 조회
            stmt = select(FactorPerformance).where(
                and_(
                    FactorPerformance.target_type == target_type,
                    FactorPerformance.target_code == target_code,
                    FactorPerformance.condition_key == condition_key,
                    FactorPerformance.holding_days == holding_days
                )
            )
            existing = self.session.scalars(stmt).first()
            
            # 신뢰도 계산
            confidence_level = 'HIGH' if sample_count >= 30 else ('MID' if sample_count >= 15 else 'LOW')
            
            if existing:
                # UPDATE
                existing.target_name = target_name
                existing.condition_desc = condition_desc
                existing.win_rate = win_rate
                existing.avg_return = avg_return
                existing.sample_count = sample_count
                existing.confidence_level = confidence_level
                existing.recent_win_rate = recent_win_rate
                existing.recent_sample_count = recent_sample_count
                existing.analysis_date = analysis_date or datetime.now().date()
                existing.updated_at = datetime.now()
            else:
                # INSERT
                new_record = FactorPerformance(
                    target_type=target_type,
                    target_code=target_code,
                    target_name=target_name,
                    condition_key=condition_key,
                    condition_desc=condition_desc,
                    win_rate=win_rate,
                    avg_return=avg_return,
                    sample_count=sample_count,
                    holding_days=holding_days,
                    confidence_level=confidence_level,
                    recent_win_rate=recent_win_rate,
                    recent_sample_count=recent_sample_count,
                    analysis_date=analysis_date or datetime.now().date()
                )
                self.session.add(new_record)
            
            self.session.commit()
            logger.debug(f"✅ [FactorRepo] 팩터 성과 저장: {target_code}/{condition_key}")
            return True
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"❌ [FactorRepo] 팩터 성과 저장 실패: {e}")
            return False
    
    def get_factor_performance(
        self, 
        target_type: str, 
        target_code: str, 
        condition_key: str,
        holding_days: int = 5
    ) -> Optional[FactorPerformance]:
        """
        팩터 성과 조회
        """
        try:
            stmt = select(FactorPerformance).where(
                and_(
                    FactorPerformance.target_type == target_type,
                    FactorPerformance.target_code == target_code,
                    FactorPerformance.condition_key == condition_key,
                    FactorPerformance.holding_days == holding_days
                )
            )
            return self.session.scalars(stmt).first()
        except Exception as e:
            logger.warning(f"⚠️ [FactorRepo] 팩터 성과 조회 실패: {e}")
            return None
    
    # =========================================================================
    # 뉴스 팩터 통계 저장
    # =========================================================================
    
    def save_news_factor_stats(
        self,
        target_type: str,
        target_code: str,
        news_category: str,
        sentiment: str,
        win_rate: float,
        avg_excess_return: float,
        avg_absolute_return: float,
        sample_count: int,
        return_d1: float = None,
        return_d5: float = None,
        return_d20: float = None,
        win_rate_d1: float = None,
        win_rate_d5: float = None,
        win_rate_d20: float = None,
        analysis_date: date = None
    ) -> bool:
        """
        뉴스 팩터 통계 저장 (UPSERT)
        
        Returns:
            성공 여부
        """
        try:
            # 기존 레코드 조회
            stmt = select(NewsFactorStats).where(
                and_(
                    NewsFactorStats.target_type == target_type,
                    NewsFactorStats.target_code == target_code,
                    NewsFactorStats.news_category == news_category,
                    NewsFactorStats.sentiment == sentiment
                )
            )
            existing = self.session.scalars(stmt).first()
            
            confidence_level = 'HIGH' if sample_count >= 30 else ('MID' if sample_count >= 15 else 'LOW')
            
            if existing:
                # UPDATE
                existing.win_rate = win_rate
                existing.avg_excess_return = avg_excess_return
                existing.avg_absolute_return = avg_absolute_return
                existing.sample_count = sample_count
                existing.confidence_level = confidence_level
                existing.return_d1 = return_d1
                existing.return_d5 = return_d5
                existing.return_d20 = return_d20
                existing.win_rate_d1 = win_rate_d1
                existing.win_rate_d5 = win_rate_d5
                existing.win_rate_d20 = win_rate_d20
                existing.analysis_date = analysis_date or datetime.now().date()
                existing.updated_at = datetime.now()
            else:
                # INSERT
                new_record = NewsFactorStats(
                    target_type=target_type,
                    target_code=target_code,
                    news_category=news_category,
                    sentiment=sentiment,
                    win_rate=win_rate,
                    avg_excess_return=avg_excess_return,
                    avg_absolute_return=avg_absolute_return,
                    sample_count=sample_count,
                    confidence_level=confidence_level,
                    return_d1=return_d1,
                    return_d5=return_d5,
                    return_d20=return_d20,
                    win_rate_d1=win_rate_d1,
                    win_rate_d5=win_rate_d5,
                    win_rate_d20=win_rate_d20,
                    analysis_date=analysis_date or datetime.now().date()
                )
                self.session.add(new_record)
            
            self.session.commit()
            logger.debug(f"✅ [FactorRepo] 뉴스 팩터 통계 저장: {target_code}/{news_category}")
            return True

        except Exception as e:
            self.session.rollback()
            logger.error(f"❌ [FactorRepo] 뉴스 팩터 통계 저장 실패: {e}")
            return False

    # =========================================================================
    # v2: 분기별 재무 트렌드 조회
    # =========================================================================

    def get_financial_trend(
        self,
        stock_codes: List[str],
    ) -> Dict[str, Dict]:
        """
        최근 4분기 재무 지표 트렌드 조회 (Quant Scorer v2용)

        Args:
            stock_codes: 종목 코드 리스트

        Returns:
            {stock_code: {
                'roe_trend': [Q-3, Q-2, Q-1, Q0],
                'per_trend': [Q-3, Q-2, Q-1, Q0],
                'eps_trend': [Q-3, Q-2, Q-1, Q0],
                'net_income_trend': [Q-3, Q-2, Q-1, Q0],
            }}
            데이터 미보유 종목은 빈 딕셔너리
        """
        result: Dict[str, Dict] = {}

        if not stock_codes:
            return result

        try:
            stmt = (
                select(
                    FinancialMetricsQuarterly.stock_code,
                    FinancialMetricsQuarterly.quarter_date,
                    FinancialMetricsQuarterly.roe,
                    FinancialMetricsQuarterly.per,
                    FinancialMetricsQuarterly.eps,
                )
                .where(FinancialMetricsQuarterly.stock_code.in_(stock_codes))
                .order_by(
                    FinancialMetricsQuarterly.stock_code,
                    FinancialMetricsQuarterly.quarter_date,
                )
            )
            rows = self.session.execute(stmt).all()

            # 종목별로 그룹핑
            from collections import defaultdict
            grouped: Dict[str, list] = defaultdict(list)
            for row in rows:
                grouped[row[0]].append(row)

            for code, quarters in grouped.items():
                # 최근 4분기만 (시간순 정렬된 상태)
                recent = quarters[-4:] if len(quarters) >= 4 else quarters

                trend: Dict[str, list] = {
                    'roe_trend': [],
                    'per_trend': [],
                    'eps_trend': [],
                }

                for q in recent:
                    trend['roe_trend'].append(float(q[2]) if q[2] is not None else None)
                    trend['per_trend'].append(float(q[3]) if q[3] is not None else None)
                    trend['eps_trend'].append(float(q[4]) if q[4] is not None else None)

                result[code] = trend

            logger.debug(f"[FactorRepo] 재무 트렌드 조회: {len(result)}/{len(stock_codes)}개 종목")
            return result

        except Exception as e:
            logger.error(f"[FactorRepo] 재무 트렌드 조회 실패: {e}")
            return result

    def get_investor_trading_with_ratio(
        self,
        stock_codes: List[str],
        days: int = 25,
    ) -> Dict[str, pd.DataFrame]:
        """
        여러 종목의 투자자별 매매 동향 + 외인보유비율 조회 (v2용)

        Args:
            stock_codes: 종목 코드 리스트
            days: 조회할 일수

        Returns:
            {stock_code: DataFrame} with columns:
                TRADE_DATE, FOREIGN_NET_BUY, INSTITUTION_NET_BUY,
                INDIVIDUAL_NET_BUY, FOREIGN_HOLDING_RATIO
        """
        result = {}
        try:
            for code in stock_codes:
                stmt = (
                    select(
                        StockInvestorTrading.trade_date,
                        StockInvestorTrading.foreign_net_buy,
                        StockInvestorTrading.institution_net_buy,
                        StockInvestorTrading.individual_net_buy,
                        StockInvestorTrading.foreign_holding_ratio,
                    )
                    .where(StockInvestorTrading.stock_code == code)
                    .order_by(desc(StockInvestorTrading.trade_date))
                    .limit(days)
                )
                rows = self.session.execute(stmt).all()

                df = self._rows_to_df(rows, [
                    'TRADE_DATE', 'FOREIGN_NET_BUY', 'INSTITUTION_NET_BUY',
                    'INDIVIDUAL_NET_BUY', 'FOREIGN_HOLDING_RATIO',
                ])
                if not df.empty:
                    df['TRADE_DATE'] = pd.to_datetime(df['TRADE_DATE'])
                    df = df.sort_values('TRADE_DATE').reset_index(drop=True)
                result[code] = df

            return result

        except Exception as e:
            logger.error(f"[FactorRepo] 수급+보유비율 조회 실패: {e}")
            return {code: pd.DataFrame() for code in stock_codes}

    def get_sentiment_momentum_bulk(
        self,
        stock_codes: List[str],
    ) -> Dict[str, float]:
        """
        종목별 센티먼트 모멘텀 계산 (v2용)
        최근 7일 평균 vs 8~37일전 평균 차이

        Args:
            stock_codes: 종목 코드 리스트

        Returns:
            {stock_code: sentiment_momentum} 딕셔너리
            데이터 미보유 종목은 포함되지 않음
        """
        result: Dict[str, float] = {}

        if not stock_codes:
            return result

        try:
            cutoff_37d = datetime.now().date() - timedelta(days=37)

            stmt = (
                select(
                    StockNewsSentiment.stock_code,
                    StockNewsSentiment.news_date,
                    StockNewsSentiment.sentiment_score,
                )
                .where(
                    and_(
                        StockNewsSentiment.stock_code.in_(stock_codes),
                        StockNewsSentiment.news_date >= cutoff_37d,
                    )
                )
                .order_by(StockNewsSentiment.stock_code, StockNewsSentiment.news_date)
            )
            rows = self.session.execute(stmt).all()

            from collections import defaultdict
            grouped: Dict[str, list] = defaultdict(list)
            for row in rows:
                grouped[row[0]].append((row[1], float(row[2]) if row[2] is not None else None))

            cutoff_7d = datetime.now().date() - timedelta(days=7)

            for code, entries in grouped.items():
                recent_scores = [s for d, s in entries if d >= cutoff_7d and s is not None]
                past_scores = [s for d, s in entries if d < cutoff_7d and s is not None]

                if recent_scores and past_scores:
                    recent_avg = sum(recent_scores) / len(recent_scores)
                    past_avg = sum(past_scores) / len(past_scores)
                    result[code] = recent_avg - past_avg

            logger.debug(f"[FactorRepo] 센티먼트 모멘텀 계산: {len(result)}/{len(stock_codes)}개 종목")
            return result

        except Exception as e:
            logger.error(f"[FactorRepo] 센티먼트 모멘텀 계산 실패: {e}")
            return result

