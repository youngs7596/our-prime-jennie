#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_scout_e2e.py
---------------------

Scout 기반 E2E 백테스트 시뮬레이터

목적:
- Scout이 과거에 선정했을 법한 종목을 시뮬레이션
- 현재 시스템의 Buy/Sell Executor 로직으로 매매 시뮬레이션
- NEWS_SENTIMENT 테이블의 뉴스 감성 데이터 활용 (2017~2026, 49만건)

주요 기능:
1. ScoutSimulator: Factor Score + 뉴스 감성 기반 Scout 결과 추정
2. E2EBacktestEngine: Scout→Buy→Portfolio→Sell 전체 흐름 시뮬레이션
3. 기존 backtest_gpt_v2.py의 PortfolioEngine/ScannerLite 재사용
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv

# 프로젝트 루트 설정
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from shared import auth, database
from shared.config import ConfigManager
from shared.factor_scoring import FactorScorer
from shared.market_regime import MarketRegimeDetector, StrategySelector
from shared.strategy_presets import (
    get_param_defaults as get_strategy_defaults,
    get_preset as get_strategy_preset,
)

# backtest_gpt_v2에서 공통 클래스 임포트
from utilities.backtest_gpt_v2 import (
    Candidate,
    Position,
    SellAction,
    PortfolioEngine,
    ScannerLite,
    load_price_series,
    prepare_indicators,
    get_row_at_or_before,
    fetch_top_trading_value_codes,
    load_investor_trading,
    load_financial_metrics,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 뉴스 감성 데이터 로더
# =============================================================================

def load_news_sentiment_history(
    connection,
    stock_codes: List[str],
    start_date: datetime,
    end_date: datetime,
    lookback_days: int = 7
) -> Dict[str, pd.DataFrame]:
    """
    NEWS_SENTIMENT 테이블에서 종목별 뉴스 감성 히스토리 로드
    
    Args:
        connection: DB 연결
        stock_codes: 조회할 종목 코드 리스트
        start_date: 시작일
        end_date: 종료일
        lookback_days: 각 날짜에서 몇 일 이전까지 뉴스를 조회할지
        
    Returns:
        {stock_code: DataFrame(PUBLISHED_AT, SENTIMENT_SCORE, NEWS_TITLE)}
    """
    if not stock_codes:
        return {}
    
    # 조회 범위: start_date - lookback_days ~ end_date
    query_start = start_date - timedelta(days=lookback_days)
    
    placeholders = ','.join(['%s'] * len(stock_codes))
    query = f"""
        SELECT STOCK_CODE, PUBLISHED_AT, SENTIMENT_SCORE, NEWS_TITLE
        FROM NEWS_SENTIMENT
        WHERE STOCK_CODE IN ({placeholders})
          AND PUBLISHED_AT BETWEEN %s AND %s
        ORDER BY STOCK_CODE, PUBLISHED_AT
    """
    
    cursor = connection.cursor()
    try:
        cursor.execute(query, (*stock_codes, query_start, end_date))
        rows = cursor.fetchall()
    finally:
        cursor.close()
    
    if not rows:
        return {}
    
    # DataFrame으로 변환
    if isinstance(rows[0], dict):
        df = pd.DataFrame(rows)
    else:
        df = pd.DataFrame(rows, columns=["STOCK_CODE", "PUBLISHED_AT", "SENTIMENT_SCORE", "NEWS_TITLE"])
    
    df["PUBLISHED_AT"] = pd.to_datetime(df["PUBLISHED_AT"])
    
    # 종목별로 분리
    result = {}
    for code in stock_codes:
        code_df = df[df["STOCK_CODE"] == code].copy()
        if not code_df.empty:
            code_df.set_index("PUBLISHED_AT", inplace=True)
            result[code] = code_df
    
    logger.info(f"📰 뉴스 감성 데이터 로드: {len(result)}개 종목, {len(df)}건")
    return result


def get_sentiment_at_date(
    news_df: pd.DataFrame,
    target_date: datetime,
    lookback_days: int = 7,
    cutoff_hour: int = 9,
    cutoff_minute: int = 0,
) -> Tuple[float, int]:
    """
    특정 날짜 기준 뉴스 감성 점수 계산
    
    Args:
        news_df: 종목의 뉴스 DataFrame (index: PUBLISHED_AT)
        target_date: 기준일
        lookback_days: 조회할 기간 (일)
        
    Returns:
        (avg_sentiment, news_count): 평균 감성 점수, 뉴스 건수
    """
    if news_df is None or news_df.empty:
        return 50.0, 0  # 중립값 반환
    
    cutoff_time = target_date.replace(
        hour=cutoff_hour, minute=cutoff_minute, second=0, microsecond=0
    )
    start = cutoff_time - timedelta(days=lookback_days)
    mask = (news_df.index >= start) & (news_df.index <= cutoff_time)
    period_news = news_df.loc[mask]
    
    if period_news.empty:
        return 50.0, 0
    
    avg_score = period_news["SENTIMENT_SCORE"].mean()
    return float(avg_score), len(period_news)


# =============================================================================
# Regime 기반 동적 파라미터 (Phase A-2)
# =============================================================================

REGIME_PARAMS = {
    "STRONG_BULL": {
        "daily_buy_limit": 6,
        "target_profit_pct": 0.30,
        "stop_loss_pct": 0.10,
        "buy_signal_threshold": 65,
        "max_portfolio_size": 15,
    },
    "BULL": {
        "daily_buy_limit": 4,
        "target_profit_pct": 0.25,
        "stop_loss_pct": 0.08,
        "buy_signal_threshold": 68,
        "max_portfolio_size": 12,
    },
    "SIDEWAYS": {
        "daily_buy_limit": 3,
        "target_profit_pct": 0.15,
        "stop_loss_pct": 0.07,
        "buy_signal_threshold": 70,
        "max_portfolio_size": 10,
    },
    "BEAR": {
        "daily_buy_limit": 1,
        "target_profit_pct": 0.10,
        "stop_loss_pct": 0.05,
        "buy_signal_threshold": 75,
        "max_portfolio_size": 5,
    },
}


def get_regime_params(regime: str) -> dict:
    """시장 국면에 맞는 파라미터 반환"""
    return REGIME_PARAMS.get(regime, REGIME_PARAMS["SIDEWAYS"])


# =============================================================================
# 매수 타이밍 로직 (Phase A-1)
# =============================================================================

def check_technical_entry(
    df: pd.DataFrame,
    target_date: pd.Timestamp,
    min_signals: int = 1
) -> Tuple[bool, List[str]]:
    """
    기술적 매수 신호 확인 (실제 Buy Scanner 로직 재현)
    
    Args:
        df: 종목 가격 DataFrame (CLOSE_PRICE, RSI, BB_LOWER 등 포함)
        target_date: 매수 조건 확인 날짜
        min_signals: 최소 필요 신호 수 (기본 1)
        
    Returns:
        (is_entry, signals): 매수 조건 충족 여부, 발생한 신호 리스트
    """
    bars = df.loc[:target_date].tail(26)
    if len(bars) < 21:
        return False, []
    
    if target_date in bars.index and len(bars) >= 2:
        prev_row = bars.iloc[-2]
        prev_window = bars.iloc[:-1]
    else:
        prev_row = bars.iloc[-1]
        prev_window = bars
    signals = []
    
    # 1. Golden Cross: 전일 기준 MA5 > MA20 상향 돌파
    ma5 = prev_window['CLOSE_PRICE'].tail(5).mean()
    ma20 = prev_window['CLOSE_PRICE'].tail(20).mean()
    ma5_prev = prev_window['CLOSE_PRICE'].iloc[-6:-1].mean()
    ma20_prev = prev_window['CLOSE_PRICE'].iloc[-21:-1].mean()
    if ma5_prev <= ma20_prev and ma5 > ma20:
        signals.append('GOLDEN_CROSS')
    
    # 2. RSI Oversold: 전일 RSI 기준
    rsi = prev_row.get('RSI', 50) if not pd.isna(prev_row.get('RSI')) else 50
    if rsi < 35:
        signals.append('RSI_OVERSOLD')
    
    # 3. BB Lower: 전일 종가 기준 볼린저 하단 근처
    bb_lower = prev_row.get('BB_LOWER', 0) if not pd.isna(prev_row.get('BB_LOWER')) else 0
    if bb_lower and prev_row['CLOSE_PRICE'] < bb_lower * 1.02:
        signals.append('BB_LOWER')
    
    # 4. Momentum: 전일 기준 최근 5일 상승률 > 3%
    if len(prev_window) >= 5:
        prev_price = prev_window['CLOSE_PRICE'].iloc[-5]
        if prev_price > 0:
            momentum = (prev_window['CLOSE_PRICE'].iloc[-1] - prev_price) / prev_price
            if momentum > 0.03:
                signals.append('MOMENTUM')
    
    return len(signals) >= min_signals, signals


# =============================================================================
# Scout 시뮬레이터
# =============================================================================


@dataclass
class ScoutSnapshot:
    """특정 시점의 Scout 결과 스냅샷"""
    date: datetime
    regime: str  # BULL, BEAR, NEUTRAL/SIDEWAYS
    hot_watchlist: List[dict]  # code, name, score, strategy, factor_score, news_sentiment


class ScoutSimulator:
    """
    과거 시점 Scout 결과 시뮬레이션
    
    Scout이 특정 날짜에 선정했을 종목을 Factor Score + 뉴스 감성으로 추정
    """
    
    def __init__(
        self,
        connection,
        price_cache: Dict[str, pd.DataFrame],
        stock_names: Dict[str, str],
        news_cache: Dict[str, pd.DataFrame],
        investor_cache: Dict[str, pd.DataFrame] = None,
        financial_cache: Dict[str, pd.DataFrame] = None,
        top_n: int = 30,
        min_score: float = 60.0,
    ):
        """
        Args:
            connection: DB 연결
            price_cache: 종목별 가격 DataFrame 캐시
            stock_names: {code: name} 매핑
            news_cache: 종목별 뉴스 DataFrame 캐시
            investor_cache: 수급 데이터 캐시
            financial_cache: 재무 데이터 캐시
            top_n: Hot Watchlist 크기
            min_score: Scout 통과 최소 점수
        """
        self.connection = connection
        self.price_cache = price_cache
        self.stock_names = stock_names
        self.news_cache = news_cache
        self.investor_cache = investor_cache or {}
        self.financial_cache = financial_cache or {}
        self.top_n = top_n
        self.min_score = min_score
        
        # 시장 분석 도구
        self.regime_detector = MarketRegimeDetector()
        self.strategy_selector = StrategySelector()
        self.factor_scorer = FactorScorer()
        
    def simulate_scout_for_date(
        self,
        target_date: datetime,
        universe_codes: Optional[List[str]] = None,
    ) -> ScoutSnapshot:
        """
        지정 날짜에 Scout이 선정했을 종목 추정
        
        로직:
        1. 해당 일자의 시장 Regime 판단
        2. 전일까지의 데이터로 각 종목 Factor Score 계산
        3. 뉴스 감성 점수 조회 및 반영
        4. 최종 점수 상위 N개 종목을 Hot Watchlist로 반환
        """
        # 1. 시장 Regime 감지
        kospi_df = self.price_cache.get("0001")
        if kospi_df is None or kospi_df.empty:
            regime = "SIDEWAYS"
        else:
            kospi_slice = kospi_df.loc[:target_date].tail(60)
            if not kospi_slice.empty:
                if target_date in kospi_slice.index and len(kospi_slice) >= 2:
                    kospi_slice = kospi_slice.iloc[:-1]
                close_df = kospi_slice[["CLOSE_PRICE"]]
                current_price = float(close_df["CLOSE_PRICE"].iloc[-1])
                regime, _ = self.regime_detector.detect_regime(close_df, current_price, quiet=True)
            else:
                regime = "SIDEWAYS"
        
        strategies = self.strategy_selector.select_strategies(regime)
        
        # 2. 종목별 점수 계산
        candidates = []
        
        scan_codes = universe_codes or list(self.price_cache.keys())
        for code in sorted(scan_codes):
            if code == "0001":  # KOSPI 인덱스 제외
                continue
                
            df = self.price_cache[code]
            if df.empty:
                continue
            
            # 전일까지의 데이터만 사용 (Look-Ahead Bias 방지)
            df_window = df.loc[:target_date].tail(220)
            if df_window.empty or len(df_window) < 20:
                continue
            
            # 전일 데이터로 점수 계산
            prev_data = df_window.iloc[:-1] if target_date in df_window.index else df_window
            if prev_data.empty:
                continue
            
            try:
                # Factor Score 계산
                kospi_slice = kospi_df.loc[:target_date].tail(len(prev_data)) if kospi_df is not None else pd.DataFrame()
                
                momentum, _ = self.factor_scorer.calculate_momentum_score(prev_data, kospi_slice)
                quality, _ = self.factor_scorer.calculate_quality_score(
                    roe=None, sales_growth=None, eps_growth=None, daily_prices_df=prev_data
                )
                value, _ = self.factor_scorer.calculate_value_score(pbr=None, per=None)
                technical, _ = self.factor_scorer.calculate_technical_score(prev_data)
                
                # 수급 보너스
                investor_bonus = 0.0
                inv_df = self.investor_cache.get(code)
                if inv_df is not None and not inv_df.empty:
                    recent = inv_df.loc[:target_date].tail(5)
                    if not recent.empty:
                        f_sum = recent.get("FOREIGN_NET_BUY", pd.Series([0])).sum()
                        i_sum = recent.get("INSTITUTION_NET_BUY", pd.Series([0])).sum()
                        if f_sum > 0 and i_sum > 0:
                            investor_bonus = 50.0  # 쌍끌이 보너스
                
                final_score, _ = self.factor_scorer.calculate_final_score(
                    momentum, quality, value, technical, regime
                )
                factor_score = min(100.0, (final_score + investor_bonus) / 10.0)
                
                # 뉴스 감성 점수 조회
                news_df = self.news_cache.get(code)
                news_sentiment, news_count = get_sentiment_at_date(
                    news_df,
                    target_date,
                    lookback_days=7,
                    cutoff_hour=9,
                    cutoff_minute=0,
                )
                
                # === Phase B-1: 비선형 Scout 점수 추정 ===
                
                # 1. 과락: 뉴스 감성이 매우 부정적이면 탈락
                if news_sentiment < 40 and news_count > 0:
                    continue  # 악재 뉴스가 있으면 제외
                
                # 2. 기본 점수: 베이스(40) + Factor Score 기여(30%)
                # factor_score 범위: 0~100, 기여도: 0~30
                base_score = 40 + (factor_score * 0.3)
                
                # 3. 뉴스 가산점 (비선형)
                if news_sentiment > 85:
                    news_bonus = 20  # 강력한 호재
                elif news_sentiment > 70:
                    news_bonus = 10  # 긍정적
                elif news_sentiment > 55:
                    news_bonus = 5   # 약간 긍정
                else:
                    news_bonus = 0   # 중립 이하
                
                # 4. 수급 보너스 (쌍끌이)
                supply_bonus = 10 if investor_bonus > 0 else 0  # 쌍끌이 시 +10점
                
                # 최종 Scout 점수 (40 + 0~30 + 0~20 + 0~10 = 40~100)
                estimated_score = base_score + news_bonus + supply_bonus
                estimated_score = max(0, min(100, estimated_score))
                
                if estimated_score >= self.min_score:
                    candidates.append({
                        "code": code,
                        "name": self.stock_names.get(code, code),
                        "factor_score": factor_score,
                        "news_sentiment": news_sentiment,
                        "news_count": news_count,
                        "estimated_score": estimated_score,
                        "regime": regime,
                        "strategies": strategies,
                    })
                    
            except Exception as e:
                logger.debug(f"[{code}] Scout 시뮬레이션 실패: {e}")
                continue
        
        # 3. 상위 N개 선정
        candidates.sort(key=lambda x: x["estimated_score"], reverse=True)
        hot_watchlist = candidates[:self.top_n]
        
        logger.info(
            f"📊 [{target_date.strftime('%Y-%m-%d')}] Scout 시뮬레이션: "
            f"Regime={regime}, 후보={len(candidates)}, Hot Watchlist={len(hot_watchlist)}"
        )
        
        return ScoutSnapshot(
            date=target_date,
            regime=regime,
            hot_watchlist=hot_watchlist,
        )


# =============================================================================
# E2E 백테스트 엔진
# =============================================================================

class E2EBacktestEngine:
    """
    Scout→Buy Scanner→Buy Executor→Price Monitor→Sell Executor
    전체 흐름 시뮬레이션
    """
    
    def __init__(
        self,
        connection,
        start_date: datetime,
        end_date: datetime,
        initial_capital: float = 10_000_000,
        # Buy Executor 설정
        daily_buy_limit: int = 3,
        max_portfolio_size: int = 10,
        max_sector_pct: float = 0.3,
        max_stock_pct: float = 0.15,
        # Sell Executor 설정
        target_profit_pct: float = 0.15,
        stop_loss_pct: float = 0.07,
        rsi_overbought: float = 70,
        # Scout 설정
        scout_top_n: int = 30,
        scout_min_score: float = 60.0,
        # 매수 신호 임계값
        buy_signal_threshold: float = 70.0,
        # 시뮬레이션 옵션
        intraday_mode: str = "ohlc",
        dynamic_universe: bool = True,
        use_watchlist_history: bool = False,
        max_volume_pct: float = 0.01,
        volume_full_fill: int = 100000,
    ):
        self.connection = connection
        self.start_date = start_date
        self.end_date = end_date
        
        # 설정
        self.daily_buy_limit = daily_buy_limit
        self.max_portfolio_size = max_portfolio_size
        self.max_sector_pct = max_sector_pct
        self.max_stock_pct = max_stock_pct
        self.target_profit_pct = target_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.rsi_overbought = rsi_overbought
        self.scout_top_n = scout_top_n
        self.scout_min_score = scout_min_score
        self.buy_signal_threshold = buy_signal_threshold
        self.intraday_mode = intraday_mode
        self.dynamic_universe = dynamic_universe
        self.use_watchlist_history = use_watchlist_history
        self.max_volume_pct = max_volume_pct
        self.volume_full_fill = volume_full_fill
        
        # 일중 시뮬레이션 옵션
        self.use_intraday_sim = True  # 일중 시뮬레이션 사용
        self.intraday_slots = 72  # 하루 72슬롯 (5분 간격)
        self.slot_offsets = [timedelta(minutes=5 * i) for i in range(self.intraday_slots)]
        self.intraday_mode = intraday_mode  # ohlc, atr, 또는 brw
        
        # Portfolio Engine (기존 백테스트 재사용)
        self.portfolio = PortfolioEngine(
            initial_capital=initial_capital,
            max_position_pct=max_stock_pct,
            max_positions=max_portfolio_size,
            target_profit_pct=target_profit_pct,
            stop_loss_pct=stop_loss_pct,
            stop_loss_atr_mult=2.0,
            max_hold_days=60,
        )
        
        # 캐시 (나중에 로드)
        self.price_cache: Dict[str, pd.DataFrame] = {}
        self.stock_names: Dict[str, str] = {}
        self.news_cache: Dict[str, pd.DataFrame] = {}
        self.investor_cache: Dict[str, pd.DataFrame] = {}
        self.financial_cache: Dict[str, pd.DataFrame] = {}
        self.intraday_cache: Dict[str, List[float]] = {}  # 일중 가격 캐시
        self.regime_detector = MarketRegimeDetector()
        
        # 결과
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.scout_snapshots: List[ScoutSnapshot] = []
    
    def _simulate_intraday_path_v2(self, open_price: float, atr: float) -> List[float]:
        """시가 + 전일 ATR 기반 일중 경로 (look-ahead 제거)"""
        import math
        slots = self.intraday_slots
        if slots <= 1:
            return [open_price]

        path = [open_price]
        current = open_price
        step_volatility = atr * 0.05

        for i in range(1, slots):
            noise = math.sin(i * 1.618) * step_volatility
            mean_revert = (open_price - current) * 0.1
            current = current + noise + mean_revert
            current = max(current, open_price * 0.9)
            current = min(current, open_price * 1.1)
            path.append(max(0.0, current))

        return path

    def _simulate_intraday_path_ohlc(
        self,
        open_price: float,
        high_price: float,
        low_price: float,
        close_price: float,
    ) -> List[float]:
        """OHLC ZigZag 기반 일중 경로 (실제 범위 내 체결)"""
        slots = self.intraday_slots
        if slots <= 1:
            return [close_price]

        if close_price >= open_price:
            points = [(0.0, open_price), (0.3, low_price), (0.7, high_price), (1.0, close_price)]
        else:
            points = [(0.0, open_price), (0.3, high_price), (0.7, low_price), (1.0, close_price)]

        def interpolate(t: float) -> float:
            for i in range(len(points) - 1):
                t0, v0 = points[i]
                t1, v1 = points[i + 1]
                if t0 <= t <= t1:
                    if t1 == t0:
                        return v1
                    ratio = (t - t0) / (t1 - t0)
                    return v0 + (v1 - v0) * ratio
            return points[-1][1]

        path = []
        for i in range(slots):
            t = i / max(1, slots - 1)
            path.append(max(0.0, interpolate(t)))
        return path

    def _simulate_intraday_path_brw(
        self,
        open_price: float,
        high_price: float,
        low_price: float,
        close_price: float,
        prev_atr: float,
        regime: str = "SIDEWAYS",
    ) -> List[float]:
        """
        Bounded Random Walk 기반 일중 가격 경로
        
        Args:
            open_price: 시가
            high_price, low_price: 일별 고가/저가 (경계)
            close_price: 종가 (수렴 방향 참고용)
            prev_atr: 전일 ATR (변동성 기준)
            regime: 시장 국면 (변동성 가중치)
        
        Returns:
            List[float]: 슬롯별 가격 경로
        """
        import numpy as np
        
        slots = self.intraday_slots
        if slots <= 1:
            return [open_price]
        
        # 1. 변동성 설정 (시장 국면별)
        regime_volatility_mult = {
            "STRONG_BULL": 0.8,   # 상승장: 변동성 낮음
            "BULL": 1.0,
            "SIDEWAYS": 1.2,      # 박스권: 변동성 중간
            "BEAR": 1.5,          # 하락장: 변동성 높음
        }
        vol_mult = regime_volatility_mult.get(regime, 1.0)
        step_volatility = prev_atr * vol_mult / np.sqrt(slots)
        
        # 2. 드리프트 설정 (룩어헤드 방어: 방향만 참조)
        expected_direction = 1.0 if close_price > open_price else -1.0
        drift_strength = 0.05  # 5% 정도만 드리프트
        
        # 3. 경로 생성 (재현성을 위한 시드)
        seed = hash(f"{open_price}_{high_price}_{low_price}_{slots}") % (2**31)
        np.random.seed(seed)
        
        path = [open_price]
        current = open_price
        mid_price = (high_price + low_price) / 2
        
        for i in range(1, slots):
            # 정규분포 노이즈
            noise = np.random.normal(0, step_volatility)
            
            # 드리프트 (종가 방향, 약함)
            drift = expected_direction * drift_strength * prev_atr / slots
            
            # 평균 회귀 (범위 중심으로)
            mean_revert = (mid_price - current) * 0.02
            
            # 다음 가격
            next_price = current + noise + drift + mean_revert
            
            # 경계 조건: [low * 0.99, high * 1.01] 내로 클리핑
            next_price = max(low_price * 0.99, min(high_price * 1.01, next_price))
            
            path.append(max(0.0, next_price))
            current = next_price
        
        # 마지막 슬롯이 종가와 너무 멀면 50% 정도만 조정
        if len(path) > 1 and prev_atr > 0:
            last_gap = abs(path[-1] - close_price)
            if last_gap > prev_atr * 0.5:
                path[-1] = path[-1] * 0.5 + close_price * 0.5
        
        return path

    def _get_prev_atr(self, df: pd.DataFrame, date: datetime, fallback: float) -> float:
        if date in df.index:
            idx = df.index.get_loc(date) - 1
            if idx >= 0:
                prev_row = df.iloc[idx]
                atr = float(prev_row.get("ATR", fallback)) if not pd.isna(prev_row.get("ATR")) else fallback
                return atr
        return fallback
    
    def _get_intraday_price(self, code: str, date: datetime, slot_idx: int) -> float:
        """특정 슬롯의 일중 가격 반환"""
        key = f"{code}_{date.strftime('%Y%m%d')}"
        if key not in self.intraday_cache:
            df = self.price_cache.get(code)
            if df is None or df.empty:
                return 0.0
            row = df.loc[date] if date in df.index else get_row_at_or_before(df, date)
            if row is None:
                return 0.0
            open_price = float(row.get("OPEN_PRICE", row["CLOSE_PRICE"]))
            if open_price <= 0:
                open_price = float(row.get("CLOSE_PRICE", 0))

            high_price = float(row.get("HIGH_PRICE", row["CLOSE_PRICE"]))
            low_price = float(row.get("LOW_PRICE", row["CLOSE_PRICE"]))
            close_price = float(row["CLOSE_PRICE"])
            atr = self._get_prev_atr(df, date, fallback=open_price * 0.02)
            
            if self.intraday_mode == "ohlc":
                self.intraday_cache[key] = self._simulate_intraday_path_ohlc(
                    open_price, high_price, low_price, close_price,
                )
            elif self.intraday_mode == "brw":
                regime = self._detect_regime(date)
                self.intraday_cache[key] = self._simulate_intraday_path_brw(
                    open_price, high_price, low_price, close_price, atr, regime,
                )
            else:  # atr 모드
                self.intraday_cache[key] = self._simulate_intraday_path_v2(open_price, atr)
        path = self.intraday_cache.get(key, [])
        if 0 <= slot_idx < len(path):
            return path[slot_idx]
        return path[-1] if path else 0.0
        
    def load_data(self, stock_codes: List[str] = None):
        """
        시뮬레이션에 필요한 모든 데이터 로드
        """
        logger.info("📥 데이터 로딩 시작...")
        
        # 종목 코드 결정
        if stock_codes is None:
            stock_codes = fetch_top_trading_value_codes(self.connection, limit=200, as_of_date=self.start_date)
            stock_codes.insert(0, "0001")  # KOSPI 인덱스
        
        # 1. 가격 데이터 로드
        logger.info(f"   ... 가격 데이터 로드 ({len(stock_codes)}개 종목)")
        for code in stock_codes:
            df = load_price_series(self.connection, code)
            if not df.empty:
                df = prepare_indicators(df)
                self.price_cache[code] = df
        
        # 종목명 조회
        cursor = self.connection.cursor()
        cursor.execute("SELECT STOCK_CODE, STOCK_NAME FROM STOCK_MASTER")
        for row in cursor.fetchall():
            if isinstance(row, dict):
                self.stock_names[row["STOCK_CODE"]] = row["STOCK_NAME"]
            else:
                self.stock_names[row[0]] = row[1]
        cursor.close()
        
        # 2. 뉴스 감성 데이터 로드
        logger.info("   ... 뉴스 감성 데이터 로드")
        self.news_cache = load_news_sentiment_history(
            self.connection,
            stock_codes=[c for c in stock_codes if c != "0001"],
            start_date=self.start_date,
            end_date=self.end_date,
            lookback_days=7
        )
        
        # 3. 수급 데이터 로드
        logger.info("   ... 수급 데이터 로드")
        for code in stock_codes:
            if code == "0001":
                continue
            inv_df = load_investor_trading(self.connection, code, days=400)
            if not inv_df.empty:
                self.investor_cache[code] = inv_df
        
        # 4. 재무 데이터 로드
        logger.info("   ... 재무 데이터 로드")
        for code in stock_codes:
            if code == "0001":
                continue
            fin_df = load_financial_metrics(self.connection, code)
            if not fin_df.empty:
                self.financial_cache[code] = fin_df
        
        logger.info(
            f"✅ 데이터 로드 완료: "
            f"가격={len(self.price_cache)}, 뉴스={len(self.news_cache)}, "
            f"수급={len(self.investor_cache)}, 재무={len(self.financial_cache)}"
        )

    def _load_stock_name(self, code: str) -> None:
        if code in self.stock_names:
            return
        cursor = self.connection.cursor()
        try:
            cursor.execute("SELECT STOCK_NAME FROM STOCK_MASTER WHERE STOCK_CODE = %s", (code,))
            row = cursor.fetchone()
            if row:
                name = row["STOCK_NAME"] if isinstance(row, dict) else row[0]
                self.stock_names[code] = name
        finally:
            cursor.close()

    def _ensure_code_loaded(self, code: str) -> None:
        if code == "0001" or code in self.price_cache:
            return
        df = load_price_series(self.connection, code)
        if df.empty:
            return
        self.price_cache[code] = prepare_indicators(df)
        self.investor_cache[code] = load_investor_trading(self.connection, code, days=400)
        self.financial_cache[code] = load_financial_metrics(self.connection, code)
        news = load_news_sentiment_history(
            self.connection,
            stock_codes=[code],
            start_date=self.start_date,
            end_date=self.end_date,
            lookback_days=7,
        )
        if news:
            self.news_cache[code] = news.get(code)
        self._load_stock_name(code)

    def _get_daily_universe(self, current_date: datetime, trading_days: List[datetime], idx: int) -> List[str]:
        if not self.dynamic_universe:
            return fetch_top_trading_value_codes(self.connection, limit=200, as_of_date=self.start_date)
        if idx <= 0:
            as_of_date = current_date
        else:
            as_of_date = trading_days[idx - 1]
        return fetch_top_trading_value_codes(self.connection, limit=200, as_of_date=as_of_date)

    def _load_trading_days_from_db(self) -> List[datetime]:
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """
                SELECT DISTINCT PRICE_DATE
                FROM STOCK_DAILY_PRICES_3Y
                WHERE PRICE_DATE BETWEEN %s AND %s
                ORDER BY PRICE_DATE ASC
                """,
                (self.start_date.strftime("%Y-%m-%d"), self.end_date.strftime("%Y-%m-%d")),
            )
            rows = cursor.fetchall()
        finally:
            cursor.close()

        dates = []
        for row in rows:
            value = row["PRICE_DATE"] if isinstance(row, dict) else row[0]
            dates.append(pd.to_datetime(value))
        return dates

    def _detect_regime(self, target_date: datetime) -> str:
        kospi_df = self.price_cache.get("0001")
        if kospi_df is None or kospi_df.empty:
            return "SIDEWAYS"
        kospi_slice = kospi_df.loc[:target_date].tail(60)
        if kospi_slice.empty:
            return "SIDEWAYS"
        if target_date in kospi_slice.index and len(kospi_slice) >= 2:
            kospi_slice = kospi_slice.iloc[:-1]
        close_df = kospi_slice[["CLOSE_PRICE"]]
        current_price = float(close_df["CLOSE_PRICE"].iloc[-1])
        regime, _ = self.regime_detector.detect_regime(close_df, current_price, quiet=True)
        return regime

    def _load_watchlist_history_snapshot(self, snapshot_date: datetime) -> List[dict]:
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """
                SELECT STOCK_CODE, STOCK_NAME, IS_TRADABLE, LLM_SCORE, LLM_REASON
                FROM WATCHLIST_HISTORY
                WHERE SNAPSHOT_DATE = %s
                """,
                (snapshot_date.strftime("%Y-%m-%d"),),
            )
            rows = cursor.fetchall()
        finally:
            cursor.close()

        results = []
        for row in rows:
            if isinstance(row, dict):
                code = row.get("STOCK_CODE")
                name = row.get("STOCK_NAME", code)
                is_tradable = row.get("IS_TRADABLE", 1)
                llm_score = row.get("LLM_SCORE", 0) or 0
                llm_reason = row.get("LLM_REASON", "")
            else:
                code, name, is_tradable, llm_score, llm_reason = row
            results.append(
                {
                    "code": code,
                    "name": name,
                    "is_tradable": bool(is_tradable),
                    "estimated_score": float(llm_score),
                    "factor_score": 0.0,
                    "news_sentiment": 50.0,
                    "news_count": 0,
                    "llm_reason": llm_reason or "",
                }
            )
        return results
        
    def run_simulation(self) -> Dict:
        """
        E2E 시뮬레이션 실행
        
        Returns:
            결과 요약 dict
        """
        logger.info(f"🚀 E2E 시뮬레이션 시작: {self.start_date.strftime('%Y-%m-%d')} ~ {self.end_date.strftime('%Y-%m-%d')}")
        
        # Scout 시뮬레이터 초기화
        scout_sim = ScoutSimulator(
            connection=self.connection,
            price_cache=self.price_cache,
            stock_names=self.stock_names,
            news_cache=self.news_cache,
            investor_cache=self.investor_cache,
            financial_cache=self.financial_cache,
            top_n=self.scout_top_n,
            min_score=self.scout_min_score,
        )
        
        # 거래일 목록 추출
        kospi_df = self.price_cache.get("0001")
        trading_days = []
        if kospi_df is not None and not kospi_df.empty:
            trading_days = kospi_df.loc[self.start_date:self.end_date].index.tolist()
            if trading_days and trading_days[-1] < self.end_date:
                logger.warning("KOSPI 거래일 데이터가 종료일 이전에 끊겨 있습니다. DB 거래일로 대체합니다.")
                trading_days = []
        if not trading_days:
            logger.warning("KOSPI 거래일 데이터가 부족합니다. DB 거래일로 대체합니다.")
            trading_days = self._load_trading_days_from_db()
        if not trading_days:
            logger.error("거래일 데이터를 확인할 수 없습니다.")
            return {}

        logger.info(f"📅 거래일: {len(trading_days)}일")
        
        # 일별 시뮬레이션
        for i, current_date in enumerate(trading_days):
            daily_buys = 0
            daily_universe = self._get_daily_universe(current_date, trading_days, i)
            if daily_universe:
                for code in daily_universe:
                    self._ensure_code_loaded(code)
            
            # 1. Scout 시뮬레이션 (매일 아침)
            if self.use_watchlist_history and i > 0:
                snapshot_date = trading_days[i - 1]
                history_items = self._load_watchlist_history_snapshot(snapshot_date)
                if history_items:
                    for item in history_items:
                        self._ensure_code_loaded(item["code"])
                    regime = self._detect_regime(current_date)
                    scout_result = ScoutSnapshot(
                        date=current_date,
                        regime=regime,
                        hot_watchlist=history_items[: self.scout_top_n],
                    )
                else:
                    scout_result = scout_sim.simulate_scout_for_date(current_date, universe_codes=daily_universe)
            else:
                scout_result = scout_sim.simulate_scout_for_date(current_date, universe_codes=daily_universe)
            self.scout_snapshots.append(scout_result)
            
            # 1-2. Regime 기반 동적 파라미터 적용 (Phase A-2)
            regime = scout_result.regime
            regime_params = get_regime_params(regime)
            current_buy_limit = regime_params["daily_buy_limit"]
            current_buy_threshold = regime_params["buy_signal_threshold"]
            current_target_profit = regime_params["target_profit_pct"]
            current_stop_loss = regime_params["stop_loss_pct"]
            current_max_portfolio = regime_params["max_portfolio_size"]
            
            hot_watchlist_codes = {item["code"] for item in scout_result.hot_watchlist}
            
            # 2. Buy Scanner 시뮬레이션
            # Hot Watchlist 종목 중 매수 신호 발생한 종목 탐색
            for item in scout_result.hot_watchlist:
                if daily_buys >= current_buy_limit:
                    break
                if len(self.portfolio.positions) >= current_max_portfolio:
                    break
                if item["code"] in self.portfolio.positions:
                    continue  # 이미 보유 중
                    
                code = item["code"]
                df = self.price_cache.get(code)
                if df is None or current_date not in df.index:
                    continue
                
                row = df.loc[current_date]
                price = float(row["CLOSE_PRICE"])
                atr = self._get_prev_atr(df, current_date, fallback=price * 0.02)
                daily_volume = int(row.get("VOLUME", 0) or 0)
                
                # 매수 조건 1: Scout 점수가 임계값 이상
                # 매수 조건 1: 기술적 진입 신호 확인 (Phase A-1)
                is_entry, signals = check_technical_entry(df, current_date, min_signals=1)
                
                # 매수 조건 2: Scout 점수 + 기술적 신호 결합 판단
                # - 기술적 신호가 있으면: Scout 점수 요구치 5점 완화
                # - 기술적 신호가 없으면: Bull/Strong Bull에서만 높은 Scout 점수로 매수 허용
                effective_threshold = current_buy_threshold - 5 if is_entry else current_buy_threshold + 5
                
                # Bear/Sideways에서 기술적 신호 없으면 매수 안함
                if not is_entry and regime in ["BEAR", "SIDEWAYS"]:
                    continue
                
                if item["estimated_score"] < effective_threshold:
                    continue
                
                # 일중 시뮬레이션: 여러 슬롯에서 매수 시도
                if self.use_intraday_sim:
                    # 슬롯 3~8 (일중 저점 구간)에서 매수 시도
                    for slot_idx in range(3, min(9, self.intraday_slots)):
                        if daily_buys >= current_buy_limit:
                            break
                        
                        slot_price = self._get_intraday_price(code, current_date, slot_idx)
                        if slot_price <= 0:
                            continue
                        
                        slot_timestamp = current_date + self.slot_offsets[slot_idx]
                        atr = self._get_prev_atr(df, current_date, fallback=slot_price * 0.02)
                        
                        # 포지션 사이즈 계산
                        position_value = self.portfolio.cash * self.max_stock_pct
                        qty = int(position_value / slot_price)
                        if daily_volume > 0:
                            max_executable = int(daily_volume * self.max_volume_pct)
                            qty = min(qty, max_executable)
                        if qty <= 0:
                            continue
                        if daily_volume > 0:
                            fill_prob = min(1.0, daily_volume / self.volume_full_fill)
                            key = f"{code}:{current_date.strftime('%Y%m%d')}:{slot_idx}"
                            decision = (abs(hash(key)) % 10000) / 10000.0
                            if decision > fill_prob:
                                continue
                        
                        if qty > 0:
                            signal_str = "+".join(signals) if signals else "SCOUT"
                            candidate = Candidate(
                                code=code,
                                price=slot_price,
                                signal=f"SCOUT_{signal_str}",
                                score=item["estimated_score"],
                                factor_score=item["factor_score"],
                                llm_score=item["estimated_score"],
                            )
                            
                            risk_setting = {
                                "stop_loss_pct": current_stop_loss,
                                "target_profit_pct": current_target_profit,
                            }
                            
                            success = self.portfolio.execute_buy(
                                candidate=candidate,
                                qty=qty,
                                trade_date=current_date,
                                slot_timestamp=slot_timestamp,
                                atr=atr,
                                sector="기타",
                                risk_setting=risk_setting,
                            )
                            
                            if success:
                                daily_buys += 1
                                break  # 한 종목당 한 번만 매수
                else:
                    # 기존 종가 기준 매수
                    position_value = self.portfolio.cash * self.max_stock_pct
                    qty = int(position_value / price)
                    if daily_volume > 0:
                        max_executable = int(daily_volume * self.max_volume_pct)
                        qty = min(qty, max_executable)
                    if qty > 0 and daily_volume > 0:
                        fill_prob = min(1.0, daily_volume / self.volume_full_fill)
                        key = f"{code}:{current_date.strftime('%Y%m%d')}:close"
                        decision = (abs(hash(key)) % 10000) / 10000.0
                        if decision > fill_prob:
                            qty = 0
                
                    if qty > 0:
                        signal_str = "+".join(signals) if signals else "SCOUT"
                        candidate = Candidate(
                            code=code,
                            price=price,
                            signal=f"SCOUT_{signal_str}",
                            score=item["estimated_score"],
                            factor_score=item["factor_score"],
                            llm_score=item["estimated_score"],
                        )
                        
                        risk_setting = {
                            "stop_loss_pct": current_stop_loss,
                            "target_profit_pct": current_target_profit,
                        }
                        
                        success = self.portfolio.execute_buy(
                            candidate=candidate,
                            qty=qty,
                            trade_date=current_date,
                            slot_timestamp=current_date,
                            atr=atr,
                            sector="기타",
                            risk_setting=risk_setting,
                        )
                        
                        if success:
                            daily_buys += 1
            
            # 3. Sell 시뮬레이션
            # Phase B-2: 트레일링 스톱 적용 (Bull/Strong Bull에서)
            use_trailing_stop = regime in ["BULL", "STRONG_BULL"]
            trailing_stop_pct = 0.08 if regime == "BULL" else 0.10
            
            if self.use_intraday_sim:
                # 일중 슬롯별 매도 체크
                for slot_idx in range(self.intraday_slots):
                    slot_timestamp = current_date + self.slot_offsets[slot_idx]
                    
                    def slot_price_lookup(code: str, idx=slot_idx) -> float:
                        return self._get_intraday_price(code, current_date, idx)
                    
                    # 트레일링 스톱: 슬롯별로 고점 업데이트
                    if use_trailing_stop:
                        for code, position in list(self.portfolio.positions.items()):
                            slot_price = slot_price_lookup(code)
                            if slot_price <= 0:
                                continue
                            
                            if position.high_price <= 0:
                                position.high_price = position.avg_price
                            if slot_price > position.high_price:
                                position.high_price = slot_price
                                trailing_stop_price = position.high_price * (1 - trailing_stop_pct)
                                if trailing_stop_price > position.stop_loss_price:
                                    position.stop_loss_price = trailing_stop_price
                    
                    # 슬롯별 매도 체크
                    self.portfolio.process_slot(
                        slot_timestamp=slot_timestamp,
                        trade_date=current_date,
                        price_lookup=slot_price_lookup,
                        price_cache=self.price_cache,
                        risk_setting={
                            "stop_loss_pct": -current_stop_loss,
                            "target_profit_pct": current_target_profit,
                        },
                        rsi_thresholds=(70, 75, 80),
                    )
            else:
                # 기존 종가 기준 매도
                def price_lookup(code: str) -> float:
                    df = self.price_cache.get(code)
                    if df is None or current_date not in df.index:
                        return 0.0
                    return float(df.loc[current_date]["CLOSE_PRICE"])
                
                if use_trailing_stop:
                    for code, position in list(self.portfolio.positions.items()):
                        current_price = price_lookup(code)
                        if current_price <= 0:
                            continue
                        if position.high_price <= 0:
                            position.high_price = position.avg_price
                        if current_price > position.high_price:
                            position.high_price = current_price
                            trailing_stop_price = position.high_price * (1 - trailing_stop_pct)
                            if trailing_stop_price > position.stop_loss_price:
                                position.stop_loss_price = trailing_stop_price
                
                self.portfolio.process_slot(
                    slot_timestamp=current_date,
                    trade_date=current_date,
                    price_lookup=price_lookup,
                    price_cache=self.price_cache,
                    risk_setting={
                        "stop_loss_pct": -current_stop_loss,
                        "target_profit_pct": current_target_profit,
                    },
                    rsi_thresholds=(70, 75, 80),
                )
            
            # 4. 일일 자산 기록 (종가 기준)
            def closing_lookup(code: str) -> float:
                return self._get_intraday_price(code, current_date, self.intraday_slots - 1) if self.use_intraday_sim else (
                    float(self.price_cache.get(code, pd.DataFrame()).loc[current_date]["CLOSE_PRICE"]) 
                    if code in self.price_cache and current_date in self.price_cache[code].index else 0.0
                )
            
            # 일중 캐시 정리
            if self.use_intraday_sim:
                keys_to_remove = [k for k in self.intraday_cache.keys() if k.endswith(current_date.strftime('%Y%m%d'))]
                for k in keys_to_remove:
                    del self.intraday_cache[k]
            
            equity = self.portfolio.total_value(current_date, self.price_cache, closing_lookup)
            self.equity_curve.append((current_date, equity))
            
            if (i + 1) % 20 == 0:
                logger.info(
                    f"   [{current_date.strftime('%Y-%m-%d')}] "
                    f"자산: {equity:,.0f}원, 포지션: {len(self.portfolio.positions)}"
                )
        
        # 결과 계산
        initial = self.portfolio.initial_capital
        final = self.equity_curve[-1][1] if self.equity_curve else initial
        total_return = (final - initial) / initial * 100
        
        # MDD 계산
        peak = initial
        mdd = 0
        for _, equity in self.equity_curve:
            if equity > peak:
                peak = equity
            drawdown = (peak - equity) / peak
            if drawdown > mdd:
                mdd = drawdown
        
        result = {
            "start_date": self.start_date.strftime("%Y-%m-%d"),
            "end_date": self.end_date.strftime("%Y-%m-%d"),
            "trading_days": len(trading_days),
            "initial_capital": initial,
            "final_equity": final,
            "total_return_pct": total_return,
            "max_drawdown_pct": mdd * 100,
            "total_trades": len(self.portfolio.trade_log),
        }
        
        logger.info("=" * 60)
        logger.info(f"📈 시뮬레이션 완료")
        logger.info(f"   기간: {result['start_date']} ~ {result['end_date']} ({result['trading_days']}일)")
        logger.info(f"   초기 자본: {initial:,.0f}원")
        logger.info(f"   최종 자산: {final:,.0f}원")
        logger.info(f"   총 수익률: {total_return:.2f}%")
        logger.info(f"   최대 낙폭: {mdd * 100:.2f}%")
        logger.info(f"   총 거래: {result['total_trades']}건")
        logger.info("=" * 60)
        
        return result
    
    def save_results(self, output_dir: str = "logs"):
        """결과 저장"""
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        
        # 자산 곡선 저장
        equity_df = pd.DataFrame(self.equity_curve, columns=["date", "equity"])
        equity_path = os.path.join(output_dir, f"backtest_scout_e2e_equity_{timestamp}.csv")
        equity_df.to_csv(equity_path, index=False)
        
        # 거래 로그 저장
        if self.portfolio.trade_log:
            trades_df = pd.DataFrame(self.portfolio.trade_log)
            trades_path = os.path.join(output_dir, f"backtest_scout_e2e_trades_{timestamp}.csv")
            trades_df.to_csv(trades_path, index=False)
        
        logger.info(f"💾 결과 저장: {equity_path}")


# =============================================================================
# 메인
# =============================================================================

def parse_args():
    # 기본값: 최근 6개월
    from datetime import datetime, timedelta
    default_end = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")  # 어제
    default_start = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")  # 6개월 전
    
    parser = argparse.ArgumentParser(description="Scout 기반 E2E 백테스트 시뮬레이터")
    
    # 기본 설정
    parser.add_argument("--start-date", type=str, default=default_start, help=f"시작일 (YYYY-MM-DD, 기본: {default_start})")
    parser.add_argument("--end-date", type=str, default=default_end, help=f"종료일 (YYYY-MM-DD, 기본: {default_end})")
    parser.add_argument("--capital", type=float, default=210_000_000, help="초기 자본금")
    parser.add_argument("--verbose", action="store_true", help="상세 로그 출력")
    
    # === Scout 설정 (튜닝 대상) ===
    parser.add_argument("--scout-min-score", type=float, default=60.0, help="Scout 통과 최소 점수")
    parser.add_argument("--scout-top-n", type=int, default=30, help="Hot Watchlist 크기")
    
    # === Buy Executor 설정 (튜닝 대상) ===
    parser.add_argument("--daily-buy-limit", type=int, default=3, help="일일 매수 한도")
    parser.add_argument("--max-portfolio-size", type=int, default=10, help="최대 포트폴리오 크기")
    parser.add_argument("--max-stock-pct", type=float, default=0.15, help="종목당 최대 비중")
    parser.add_argument("--max-sector-pct", type=float, default=0.30, help="섹터당 최대 비중")
    
    # === Sell Executor 설정 (튜닝 대상) ===
    parser.add_argument("--target-profit-pct", type=float, default=0.15, help="목표 수익률")
    parser.add_argument("--stop-loss-pct", type=float, default=0.07, help="손절 비율")
    parser.add_argument("--rsi-overbought", type=float, default=70, help="RSI 과매수 기준")
    
    # === 매수 신호 임계값 (튜닝 대상) ===
    parser.add_argument("--buy-signal-threshold", type=float, default=70, help="매수 신호 트리거 점수")
    parser.add_argument(
        "--intraday-mode",
        type=str,
        choices=["ohlc", "atr", "brw"],
        default="ohlc",
        help="일중 경로 모드 (ohlc: ZigZag, atr: 시가+전일ATR, brw: Bounded Random Walk)",
    )
    parser.add_argument(
        "--static-universe",
        action="store_false",
        dest="dynamic_universe",
        help="유니버스를 고정(시뮬레이션 시작일 기준)합니다.",
    )
    parser.add_argument(
        "--use-watchlist-history",
        action="store_true",
        help="WATCHLIST_HISTORY 스냅샷을 리플레이에 사용합니다.",
    )
    parser.add_argument(
        "--max-volume-pct",
        type=float,
        default=0.01,
        help="일 거래량 대비 최대 체결 비율 (기본 0.01 = 1%)",
    )
    parser.add_argument(
        "--volume-full-fill",
        type=int,
        default=100000,
        help="체결 확률 100% 기준 거래량",
    )
    
    return parser.parse_args()



def main():
    load_dotenv()
    args = parse_args()
    
    # 로깅 설정
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
    
    logger.info("🔧 Scout E2E 백테스트 시뮬레이터")
    logger.info(f"   기간: {args.start_date} ~ {args.end_date}")
    logger.info(f"   초기 자본: {args.capital:,.0f}원")
    
    # DB 연결
    conn = database.get_db_connection()
    if not conn:
        logger.error("DB 연결 실패")
        return
    
    try:
        # 엔진 초기화 (CLI 파라미터 사용)
        engine = E2EBacktestEngine(
            connection=conn,
            start_date=start_date,
            end_date=end_date,
            initial_capital=args.capital,
            # Buy Executor 설정
            daily_buy_limit=args.daily_buy_limit,
            max_portfolio_size=args.max_portfolio_size,
            max_sector_pct=args.max_sector_pct,
            max_stock_pct=args.max_stock_pct,
            # Sell Executor 설정
            target_profit_pct=args.target_profit_pct,
            stop_loss_pct=args.stop_loss_pct,
            rsi_overbought=args.rsi_overbought,
            # Scout 설정
            scout_top_n=args.scout_top_n,
            scout_min_score=args.scout_min_score,
            intraday_mode=args.intraday_mode,
            dynamic_universe=args.dynamic_universe,
            use_watchlist_history=args.use_watchlist_history,
            max_volume_pct=args.max_volume_pct,
            volume_full_fill=args.volume_full_fill,
        )
        
        # 매수 신호 임계값 저장 (실행 시 사용)
        engine.buy_signal_threshold = args.buy_signal_threshold
        
        # 데이터 로드
        engine.load_data()
        
        # 시뮬레이션 실행
        result = engine.run_simulation()
        
        # 결과 저장
        engine.save_results()
        
    finally:
        conn.close()


if __name__ == "__main__":
    main()
