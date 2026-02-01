#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_minute_realistic.py
----------------------------

분봉 데이터(STOCK_MINUTE_PRICE)를 활용한 현실적 백테스트

- 기존 buy-scanner/opportunity_watcher.py의 진입 로직 최대한 재현
- price-monitor의 청산 로직 (sell_logic_unified.py) 재현
- 분봉 단위 시뮬레이션 (BarAggregator 동작 모사)

데이터:
- STOCK_MINUTE_PRICE: 5분봉 데이터 (2025-12-17 ~ )
- WATCHLIST_HISTORY: Scout 선정 종목 히스토리

Usage:
    python utilities/backtest_minute_realistic.py
    python utilities/backtest_minute_realistic.py --start-date 2026-01-01 --end-date 2026-01-30
    python utilities/backtest_minute_realistic.py --stocks 005930 000660 --verbose
    python utilities/backtest_minute_realistic.py --use-watchlist-history
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, time as dt_time
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import csv

import pandas as pd
import numpy as np

# 프로젝트 루트 추가
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from shared import strategy, database
from shared.config import ConfigManager
from shared.market_regime import MarketRegimeDetector

from utilities.minute_data_loader import (
    load_minute_prices_batch,
    load_scout_history,
)
from utilities.sell_logic_unified import (
    SellConfig,
    PositionState,
    check_sell_conditions,
)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# =============================================================================
# 상수
# =============================================================================

# 수수료/슬리피지 (backtest_gpt_v2.py 참조)
BUY_SLIPPAGE_PCT = 0.3      # 매수 슬리피지 +0.3%
SELL_SLIPPAGE_PCT = 0.3     # 매도 슬리피지 -0.3%
BUY_FEE_PCT = 0.00841       # 매수 수수료
SELL_FEE_PCT = 0.05841      # 매도 수수료

# 시장 운영 시간
MARKET_OPEN = dt_time(9, 0)
MARKET_CLOSE = dt_time(15, 30)

# Risk Gate 설정
MIN_BARS_REQUIRED = 20
NO_TRADE_START = dt_time(9, 0)
NO_TRADE_END = dt_time(9, 15)
DANGER_ZONE_START = dt_time(14, 0)
DANGER_ZONE_END = dt_time(15, 0)
RSI_MAX_THRESHOLD = 75
VOLUME_RATIO_LIMIT = 2.0
VWAP_DEVIATION_LIMIT = 0.02
COOLDOWN_MINUTES = 10
GOLDEN_CROSS_MIN_VOLUME_RATIO = 1.5


# =============================================================================
# 데이터 클래스
# =============================================================================

@dataclass
class BacktestPosition:
    """백테스트용 포지션"""
    stock_code: str
    stock_name: str
    quantity: int
    buy_price: float
    buy_time: datetime
    signal_type: str

    # 청산 관련
    high_watermark: float = 0.0
    profit_floor: Optional[float] = None
    scale_out_level: int = 0
    rsi_overbought_sold: bool = False

    def __post_init__(self):
        self.high_watermark = self.buy_price


@dataclass
class Trade:
    """거래 기록"""
    stock_code: str
    stock_name: str
    entry_time: datetime
    entry_price: float
    entry_signal: str
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    quantity: int = 0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    holding_minutes: int = 0


@dataclass
class BacktestBar:
    """1분봉 데이터"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


# =============================================================================
# BarAggregator 시뮬레이션
# =============================================================================

class BacktestBarAggregator:
    """
    실시간 BarAggregator 동작 시뮬레이션
    - VWAP 계산 (일별 리셋)
    - 거래량 비율 추적
    - 바 히스토리 관리
    """

    def __init__(self, max_history: int = 60):
        self.max_history = max_history
        # {stock_code: [BacktestBar, ...]}
        self.bars: Dict[str, List[BacktestBar]] = defaultdict(list)
        # {stock_code: {'date': date, 'cum_pv': float, 'cum_vol': int, 'vwap': float}}
        self.vwap_store: Dict[str, dict] = defaultdict(
            lambda: {'date': None, 'cum_pv': 0.0, 'cum_vol': 0, 'vwap': 0.0}
        )
        # {stock_code: [volume, ...]}
        self.volume_history: Dict[str, List[int]] = defaultdict(list)

    def add_bar(self, stock_code: str, bar: BacktestBar):
        """새 바 추가"""
        bar_date = bar.timestamp.date()

        # VWAP 업데이트
        vwap_info = self.vwap_store[stock_code]
        if vwap_info['date'] != bar_date:
            # 새로운 날짜 - 리셋
            vwap_info['date'] = bar_date
            vwap_info['cum_pv'] = 0.0
            vwap_info['cum_vol'] = 0
            vwap_info['vwap'] = bar.close

        if bar.volume > 0:
            typical_price = (bar.high + bar.low + bar.close) / 3
            vwap_info['cum_pv'] += typical_price * bar.volume
            vwap_info['cum_vol'] += bar.volume
            vwap_info['vwap'] = vwap_info['cum_pv'] / vwap_info['cum_vol']

        # 바 히스토리 관리
        self.bars[stock_code].append(bar)
        if len(self.bars[stock_code]) > self.max_history:
            self.bars[stock_code].pop(0)

        # 거래량 히스토리 관리
        self.volume_history[stock_code].append(bar.volume)
        if len(self.volume_history[stock_code]) > self.max_history:
            self.volume_history[stock_code].pop(0)

    def get_recent_bars(self, stock_code: str, count: int = 30) -> List[BacktestBar]:
        """최근 바 반환"""
        return self.bars.get(stock_code, [])[-count:]

    def get_vwap(self, stock_code: str) -> float:
        """현재 VWAP 반환"""
        return self.vwap_store[stock_code]['vwap']

    def get_volume_info(self, stock_code: str) -> dict:
        """거래량 정보 반환"""
        volumes = self.volume_history.get(stock_code, [])
        if not volumes:
            return {'current': 0, 'avg': 0, 'ratio': 0}

        current_vol = volumes[-1] if volumes else 0
        avg_vol = sum(volumes) / len(volumes) if volumes else 1
        ratio = current_vol / avg_vol if avg_vol > 0 else 0

        return {'current': current_vol, 'avg': avg_vol, 'ratio': ratio}

    def reset_day(self, stock_code: str):
        """일별 리셋 (바 히스토리는 유지, VWAP만 리셋)"""
        self.vwap_store[stock_code] = {
            'date': None, 'cum_pv': 0.0, 'cum_vol': 0, 'vwap': 0.0
        }


# =============================================================================
# 진입 로직 (opportunity_watcher.py 재현)
# =============================================================================

class EntrySignalChecker:
    """
    매수 진입 신호 체크 (opportunity_watcher.py 로직 재현)
    """

    def __init__(self, config: Optional[ConfigManager] = None):
        self.config = config or ConfigManager()
        # {stock_code: datetime} - 쿨다운 추적
        self.cooldown_cache: Dict[str, datetime] = {}

    def check_risk_gates(
        self,
        current_time: datetime,
        bars: List[BacktestBar],
        current_price: float,
        vwap: float,
        volume_info: dict,
        stock_code: str,
    ) -> Tuple[bool, str]:
        """
        Risk Gate 순차 체크 (8개)

        Returns:
            (passed, reason)
        """
        # 1. Min Bars
        if len(bars) < MIN_BARS_REQUIRED:
            return False, f"Min Bars: {len(bars)} < {MIN_BARS_REQUIRED}"

        # 2. No-Trade Window (09:00~09:15)
        bar_time = current_time.time()
        if NO_TRADE_START <= bar_time <= NO_TRADE_END:
            return False, "No-Trade Window (09:00~09:15)"

        # 3. Danger Zone (14:00~15:00)
        if DANGER_ZONE_START <= bar_time < DANGER_ZONE_END:
            return False, "Danger Zone (14:00~15:00)"

        # 4. RSI Guard
        closes = [b.close for b in bars]
        rsi = self._calculate_rsi(closes)
        if rsi is not None and rsi > RSI_MAX_THRESHOLD:
            return False, f"RSI Guard: {rsi:.1f} > {RSI_MAX_THRESHOLD}"

        # 5 & 6. Volume Gate & VWAP Gate (Combined Risk)
        risk_conditions = 0

        # Volume Gate
        if volume_info['ratio'] > VOLUME_RATIO_LIMIT:
            risk_conditions += 1

        # VWAP Gate
        if vwap > 0 and current_price > vwap * (1 + VWAP_DEVIATION_LIMIT):
            risk_conditions += 1

        # 7. Combined Risk
        if risk_conditions >= 2:
            return False, f"Combined Risk: {risk_conditions} flags"

        # 8. Cooldown
        last_signal_time = self.cooldown_cache.get(stock_code)
        if last_signal_time:
            elapsed = (current_time - last_signal_time).total_seconds() / 60
            if elapsed < COOLDOWN_MINUTES:
                return False, f"Cooldown: {elapsed:.0f}m < {COOLDOWN_MINUTES}m"

        return True, "PASSED"

    def check_entry_signal(
        self,
        stock_code: str,
        stock_info: dict,
        current_time: datetime,
        current_price: float,
        bars: List[BacktestBar],
        market_regime: str,
        vwap: float,
        volume_info: dict,
    ) -> Optional[Tuple[str, str]]:
        """
        진입 신호 체크

        Returns:
            (signal_type, reason) or None
        """
        # Risk Gates 체크
        passed, reason = self.check_risk_gates(
            current_time, bars, current_price, vwap, volume_info, stock_code
        )
        if not passed:
            return None

        closes = [b.close for b in bars]

        # Bull Market 전용 전략
        if market_regime in ['BULL', 'STRONG_BULL']:
            # 1. RECON_BULL_ENTRY
            result = self._check_recon_bull_entry(stock_info, market_regime)
            if result:
                self._set_cooldown(stock_code, current_time)
                return result

            # 2. MOMENTUM_CONTINUATION
            result = self._check_momentum_continuation(stock_info, bars, market_regime)
            if result:
                self._set_cooldown(stock_code, current_time)
                return result

            # 3. SHORT_TERM_HIGH_BREAKOUT
            result = self._check_short_term_high_breakout(bars)
            if result:
                self._set_cooldown(stock_code, current_time)
                return result

            # 4. VOLUME_BREAKOUT_1MIN
            result = self._check_volume_breakout_1min(bars)
            if result:
                self._set_cooldown(stock_code, current_time)
                return result

            # 5. BULL_PULLBACK
            result = self._check_bull_pullback(bars)
            if result:
                self._set_cooldown(stock_code, current_time)
                return result

            # 6. VCP_BREAKOUT
            result = self._check_vcp_breakout(bars)
            if result:
                self._set_cooldown(stock_code, current_time)
                return result

            # 7. INSTITUTIONAL_ENTRY
            result = self._check_institutional_buying(bars)
            if result:
                self._set_cooldown(stock_code, current_time)
                return result

        # Universal 전략
        is_bull_market = market_regime in ['BULL', 'STRONG_BULL']

        # GOLDEN_CROSS
        result = self._check_golden_cross(bars, volume_info)
        if result:
            self._set_cooldown(stock_code, current_time)
            return result

        # RSI_REBOUND (Bear/Sideways만)
        if not is_bull_market:
            result = self._check_rsi_rebound(bars, market_regime)
            if result:
                self._set_cooldown(stock_code, current_time)
                return result

        # MOMENTUM
        result = self._check_momentum(bars)
        if result:
            self._set_cooldown(stock_code, current_time)
            return result

        return None

    def _set_cooldown(self, stock_code: str, current_time: datetime):
        """쿨다운 설정"""
        self.cooldown_cache[stock_code] = current_time

    def _calculate_rsi(self, prices: List[float], period: int = 14) -> Optional[float]:
        """RSI 계산"""
        if len(prices) < period + 1:
            return None

        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        recent_deltas = deltas[-period:]

        gains = [d for d in recent_deltas if d > 0]
        losses = [-d for d in recent_deltas if d < 0]

        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 0

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    # =========================================================================
    # Bull Market 전략
    # =========================================================================

    def _check_recon_bull_entry(self, stock_info: dict, market_regime: str) -> Optional[Tuple[str, str]]:
        """RECON_BULL_ENTRY"""
        if market_regime not in ['BULL', 'STRONG_BULL']:
            return None

        llm_score = stock_info.get('llm_score', 0)
        if llm_score < 70:
            return None

        trade_tier = stock_info.get('trade_tier', '')
        if trade_tier != 'RECON':
            return None

        reason = f"LLM Score {llm_score:.1f} + RECON Tier + {market_regime}"
        return ("RECON_BULL_ENTRY", reason)

    def _check_momentum_continuation(
        self, stock_info: dict, bars: List[BacktestBar], market_regime: str
    ) -> Optional[Tuple[str, str]]:
        """MOMENTUM_CONTINUATION_BULL"""
        if market_regime not in ['BULL', 'STRONG_BULL']:
            return None

        llm_score = stock_info.get('llm_score', 0)
        if llm_score < 65:
            return None

        if len(bars) < 20:
            return None

        closes = [b.close for b in bars]
        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20

        if ma5 <= ma20:
            return None

        first_price = bars[0].open
        current_price = bars[-1].close
        price_change = ((current_price - first_price) / first_price) * 100

        if price_change < 2.0:
            return None

        reason = f"MA5({ma5:.0f}) > MA20({ma20:.0f}) + 상승률 {price_change:.1f}%"
        return ("MOMENTUM_CONTINUATION_BULL", reason)

    def _check_short_term_high_breakout(self, bars: List[BacktestBar]) -> Optional[Tuple[str, str]]:
        """SHORT_TERM_HIGH_BREAKOUT"""
        if len(bars) < 30:
            return None

        recent_highs = [b.high for b in bars[:-1]]
        if not recent_highs:
            return None

        period_high = max(recent_highs)
        current_bar = bars[-1]
        current_price = current_bar.close

        if current_price <= period_high:
            return None

        recent_volumes = [b.volume for b in bars[:-1]][-30:]
        avg_volume = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0

        if avg_volume == 0:
            return None

        current_volume = current_bar.volume
        volume_ratio = current_volume / avg_volume

        if volume_ratio < 2.0:
            return None

        reason = f"60분 신고가 돌파 ({current_price:,.0f} > {period_high:,.0f}) + 거래량 {volume_ratio:.1f}배"
        return ("SHORT_TERM_HIGH_BREAKOUT", reason)

    def _check_volume_breakout_1min(self, bars: List[BacktestBar]) -> Optional[Tuple[str, str]]:
        """VOLUME_BREAKOUT_1MIN"""
        if len(bars) < 20:
            return None

        recent_closes = [b.close for b in bars[:-1]][-20:]
        if not recent_closes:
            return None

        resistance_price = max(recent_closes)
        current_bar = bars[-1]
        current_price = current_bar.close

        if current_price <= resistance_price:
            return None

        recent_volumes = [b.volume for b in bars[:-1]]
        avg_volume = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0

        if avg_volume == 0:
            return None

        current_volume = current_bar.volume
        volume_ratio = current_volume / avg_volume

        if volume_ratio < 3.0:
            return None

        reason = f"20분 저항 돌파 ({current_price:,.0f} > {resistance_price:,.0f}) + 거래량 {volume_ratio:.1f}배"
        return ("VOLUME_BREAKOUT_1MIN", reason)

    def _check_bull_pullback(self, bars: List[BacktestBar]) -> Optional[Tuple[str, str]]:
        """BULL_PULLBACK"""
        if len(bars) < 20:
            return None

        closes = [b.close for b in bars]
        current_bar = bars[-1]
        current_price = current_bar.close

        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20

        if ma5 <= ma20:
            return None

        if current_price <= ma20:
            return None

        recent_3_bars = bars[-4:-1]
        bearish_count = sum(1 for b in recent_3_bars if b.close < b.open)
        if bearish_count < 2:
            return None

        if current_bar.close <= current_bar.open:
            return None

        recent_volumes = [b.volume for b in bars[-6:-1]]
        if not recent_volumes or recent_volumes[-1] == 0:
            return None

        avg_recent_volume = sum(recent_volumes) / len(recent_volumes)
        current_volume = current_bar.volume

        if current_volume <= avg_recent_volume * 0.8:
            return None

        reason = f"MA5({ma5:.0f}) > MA20({ma20:.0f}) + 조정 {bearish_count}음봉 → 양봉 전환"
        return ("BULL_PULLBACK", reason)

    def _check_vcp_breakout(self, bars: List[BacktestBar]) -> Optional[Tuple[str, str]]:
        """VCP_BREAKOUT"""
        if len(bars) < 21:
            return None

        current_bar = bars[-1]
        current_price = current_bar.close
        current_volume = current_bar.volume

        analysis_bars = bars[-21:-1]
        if len(analysis_bars) < 20:
            return None

        first_half = analysis_bars[:10]
        second_half = analysis_bars[10:]

        first_half_ranges = [(b.high - b.low) for b in first_half]
        second_half_ranges = [(b.high - b.low) for b in second_half]

        avg_first = sum(first_half_ranges) / len(first_half_ranges) if first_half_ranges else 1
        avg_second = sum(second_half_ranges) / len(second_half_ranges) if second_half_ranges else 1

        if avg_first == 0 or avg_second / avg_first > 0.7:
            return None

        recent_volumes = [b.volume for b in analysis_bars]
        avg_volume = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0

        if avg_volume == 0:
            return None

        volume_ratio = current_volume / avg_volume
        if volume_ratio < 3.0:
            return None

        period_high = max(b.high for b in analysis_bars)
        if current_price <= period_high:
            return None

        contraction_pct = (1 - avg_second / avg_first) * 100
        reason = f"Range 축소 {contraction_pct:.0f}% + 거래량 {volume_ratio:.1f}배 + 고가 돌파"
        return ("VCP_BREAKOUT", reason)

    def _check_institutional_buying(self, bars: List[BacktestBar]) -> Optional[Tuple[str, str]]:
        """INSTITUTIONAL_ENTRY"""
        if len(bars) < 5:
            return None

        current_bar = bars[-1]
        prev_bar = bars[-2]

        if current_bar.close <= current_bar.open:
            return None

        current_range = current_bar.high - current_bar.low
        if current_range <= 0:
            return None

        upper_wick = current_bar.high - current_bar.close
        upper_wick_ratio = upper_wick / current_range

        if upper_wick_ratio >= 0.1:
            return None

        current_body = abs(current_bar.close - current_bar.open)
        prev_body = abs(prev_bar.close - prev_bar.open)

        if prev_body == 0:
            prev_body = 1

        body_ratio = current_body / prev_body
        if body_ratio < 2.0:
            return None

        if current_bar.volume <= prev_bar.volume:
            return None

        reason = f"Marubozu (윗꼬리 {upper_wick_ratio*100:.1f}%) + 몸통 {body_ratio:.1f}배"
        return ("INSTITUTIONAL_ENTRY", reason)

    # =========================================================================
    # Universal 전략
    # =========================================================================

    def _check_golden_cross(self, bars: List[BacktestBar], volume_info: dict) -> Optional[Tuple[str, str]]:
        """GOLDEN_CROSS"""
        closes = [b.close for b in bars]
        short_w, long_w = 5, 20

        if len(closes) < long_w:
            return None

        ma_short = sum(closes[-short_w:]) / short_w
        ma_long = sum(closes[-long_w:]) / long_w

        prev_closes = closes[:-1]
        prev_ma_short = sum(prev_closes[-short_w:]) / short_w if len(prev_closes) >= short_w else ma_short

        cross_triggered = (prev_ma_short <= ma_long) and (ma_short > ma_long)

        if cross_triggered:
            volume_ratio = volume_info.get('ratio', 0)
            if volume_ratio < GOLDEN_CROSS_MIN_VOLUME_RATIO:
                return None

            reason = f"MA({short_w}) > MA({long_w}) w/ Vol {volume_ratio:.1f}x"
            return ("GOLDEN_CROSS", reason)

        return None

    def _check_rsi_rebound(self, bars: List[BacktestBar], market_regime: str) -> Optional[Tuple[str, str]]:
        """RSI_REBOUND"""
        closes = [b.close for b in bars]

        # 시장 국면별 동적 RSI 기준
        if market_regime in ['BULL', 'STRONG_BULL']:
            threshold = 50
        elif market_regime == 'SIDEWAYS':
            threshold = 40
        else:  # BEAR
            threshold = 30

        curr_rsi = self._calculate_rsi(closes, period=14)
        if curr_rsi is None:
            return None

        if len(closes) < 2:
            return None

        prev_closes = closes[:-1]
        prev_rsi = self._calculate_rsi(prev_closes, period=14)
        if prev_rsi is None:
            return None

        if prev_rsi < threshold and curr_rsi >= threshold:
            reason = f"RSI Rebound: {prev_rsi:.1f} -> {curr_rsi:.1f} (CrossUp {threshold})"
            return ("RSI_REBOUND", reason)

        return None

    def _check_momentum(self, bars: List[BacktestBar]) -> Optional[Tuple[str, str]]:
        """MOMENTUM"""
        closes = [b.close for b in bars]
        threshold = 3.0

        if len(closes) < 2:
            return None

        if closes[0] <= 0:
            return None

        momentum = ((closes[-1] - closes[0]) / closes[0]) * 100
        if momentum >= threshold:
            reason = f"Momentum={momentum:.1f}% >= {threshold}%"
            return ("MOMENTUM", reason)

        return None


# =============================================================================
# 메인 백테스터
# =============================================================================

class MinuteRealisticBacktester:
    """
    분봉 기반 현실적 백테스트 엔진
    """

    def __init__(
        self,
        initial_capital: float = 10_000_000,  # 1천만원
        max_positions: int = 5,
        position_size_pct: float = 20.0,  # 20%씩 투자
        verbose: bool = False,
    ):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.max_positions = max_positions
        self.position_size_pct = position_size_pct
        self.verbose = verbose

        # 컴포넌트
        self.bar_aggregator = BacktestBarAggregator(max_history=60)
        self.entry_checker = EntrySignalChecker()
        self.sell_config = SellConfig()
        self.regime_detector = MarketRegimeDetector()

        # 상태
        self.positions: Dict[str, BacktestPosition] = {}
        self.trades: List[Trade] = []
        self.daily_equity: List[dict] = []

        # 시장 데이터 캐시
        self.minute_data: Dict[str, pd.DataFrame] = {}
        self.daily_data: Dict[str, pd.DataFrame] = {}
        self.watchlist_history: Dict[date, List[dict]] = {}
        self.kospi_data: Optional[pd.DataFrame] = None

        # 결과 집계
        self.signal_stats: Dict[str, dict] = defaultdict(
            lambda: {'count': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0}
        )

    def load_data(
        self,
        connection,
        start_date: datetime,
        end_date: datetime,
        stock_codes: Optional[List[str]] = None,
        use_watchlist_history: bool = True,
    ):
        """데이터 로드"""
        logger.info("📊 데이터 로딩 시작...")

        # 1. Watchlist History 로드
        if use_watchlist_history:
            self.watchlist_history = load_scout_history(connection, start_date, end_date)

            # 워치리스트에서 종목 코드 추출
            if stock_codes is None:
                stock_codes = set()
                for day_stocks in self.watchlist_history.values():
                    for item in day_stocks:
                        stock_codes.add(item['code'])
                stock_codes = list(stock_codes)

        if not stock_codes:
            logger.warning("⚠️ 백테스트할 종목이 없습니다.")
            return False

        logger.info(f"   → 대상 종목: {len(stock_codes)}개")

        # 2. 분봉 데이터 로드
        self.minute_data = load_minute_prices_batch(
            connection, stock_codes, start_date, end_date
        )
        logger.info(f"   → 분봉 데이터: {len(self.minute_data)}개 종목 로드")

        # 3. 일봉 데이터 로드 (청산 로직용)
        self._load_daily_data(connection, stock_codes)

        # 4. KOSPI 데이터 로드 (시장 국면 감지용)
        self._load_kospi_data(connection)

        return True

    def _load_daily_data(self, connection, stock_codes: List[str]):
        """일봉 데이터 로드"""
        if not stock_codes:
            return

        placeholders = ','.join(['%s'] * len(stock_codes))
        query = f"""
            SELECT STOCK_CODE, PRICE_DATE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, VOLUME
            FROM STOCK_DAILY_PRICES_3Y
            WHERE STOCK_CODE IN ({placeholders})
            ORDER BY STOCK_CODE, PRICE_DATE ASC
        """

        cursor = connection.cursor()
        try:
            cursor.execute(query, stock_codes)
            rows = cursor.fetchall()
        finally:
            cursor.close()

        if not rows:
            return

        if isinstance(rows[0], dict):
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame(
                rows,
                columns=["STOCK_CODE", "PRICE_DATE", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE", "VOLUME"]
            )

        df["PRICE_DATE"] = pd.to_datetime(df["PRICE_DATE"])

        for code in stock_codes:
            code_df = df[df["STOCK_CODE"] == code].copy()
            if not code_df.empty:
                code_df = code_df.drop(columns=["STOCK_CODE"]).sort_values("PRICE_DATE")
                self.daily_data[code] = code_df

        logger.info(f"   → 일봉 데이터: {len(self.daily_data)}개 종목 로드")

    def _load_kospi_data(self, connection):
        """KOSPI 지수 데이터 로드"""
        query = """
            SELECT PRICE_DATE, CLOSE_PRICE
            FROM STOCK_DAILY_PRICES_3Y
            WHERE STOCK_CODE = '0001'
            ORDER BY PRICE_DATE ASC
        """

        cursor = connection.cursor()
        try:
            cursor.execute(query)
            rows = cursor.fetchall()
        finally:
            cursor.close()

        if not rows:
            logger.warning("⚠️ KOSPI 데이터 없음")
            return

        if isinstance(rows[0], dict):
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame(rows, columns=["PRICE_DATE", "CLOSE_PRICE"])

        df["PRICE_DATE"] = pd.to_datetime(df["PRICE_DATE"])
        self.kospi_data = df.sort_values("PRICE_DATE")
        logger.info(f"   → KOSPI 데이터: {len(self.kospi_data)}일치 로드")

    def run(self) -> dict:
        """백테스트 실행"""
        if not self.minute_data:
            logger.error("❌ 분봉 데이터가 없습니다.")
            return {}

        # 거래일 추출 (분봉 데이터에서)
        all_dates = set()
        for df in self.minute_data.values():
            dates = df.index.date
            all_dates.update(dates)

        trading_days = sorted(all_dates)
        logger.info(f"📈 백테스트 시작: {trading_days[0]} ~ {trading_days[-1]} ({len(trading_days)}일)")

        for day_idx, trade_date in enumerate(trading_days):
            self._process_day(trade_date)

            # 진행률 표시
            if (day_idx + 1) % 5 == 0 or day_idx == len(trading_days) - 1:
                logger.info(
                    f"   [{day_idx + 1}/{len(trading_days)}] "
                    f"Capital: {self.capital:,.0f}원, "
                    f"Positions: {len(self.positions)}, "
                    f"Trades: {len(self.trades)}"
                )

        # 잔여 포지션 청산
        self._close_all_positions(
            datetime.combine(trading_days[-1], dt_time(15, 30)),
            "BACKTEST_END"
        )

        return self._generate_results()

    def _process_day(self, trade_date: date):
        """하루 처리"""
        # 당일 워치리스트 가져오기
        watchlist = self.watchlist_history.get(trade_date, [])
        watchlist_dict = {item['code']: item for item in watchlist}

        # 워치리스트가 비어있으면 모든 분봉 데이터 종목을 기본 설정으로 추가
        if not watchlist_dict:
            for code in self.minute_data.keys():
                watchlist_dict[code] = {
                    'code': code,
                    'name': code,
                    'llm_score': 65,  # 기본 점수
                    'is_tradable': True,
                }

        # 시장 국면 감지
        market_regime = self._get_market_regime(trade_date)

        # 당일 분봉 데이터 수집 및 시간순 정렬
        day_bars = []
        for stock_code, minute_df in self.minute_data.items():
            day_start = datetime.combine(trade_date, dt_time.min)
            day_end = day_start + timedelta(days=1)

            day_df = minute_df[(minute_df.index >= day_start) & (minute_df.index < day_end)]

            for idx, row in day_df.iterrows():
                bar = BacktestBar(
                    timestamp=idx,
                    open=float(row['OPEN_PRICE']),
                    high=float(row['HIGH_PRICE']),
                    low=float(row['LOW_PRICE']),
                    close=float(row['CLOSE_PRICE']),
                    volume=int(row['VOLUME']),
                )
                day_bars.append((stock_code, bar))

        # 시간순 정렬
        day_bars.sort(key=lambda x: x[1].timestamp)

        # 분봉별 처리
        for stock_code, bar in day_bars:
            self._process_bar(stock_code, bar, trade_date, watchlist_dict, market_regime)

        # 일별 자산 기록
        total_equity = self.capital
        for pos in self.positions.values():
            latest_price = self._get_latest_price(pos.stock_code, trade_date)
            if latest_price:
                total_equity += pos.quantity * latest_price

        self.daily_equity.append({
            'date': trade_date.isoformat(),
            'equity': total_equity,
            'capital': self.capital,
            'positions': len(self.positions),
        })

    def _process_bar(
        self,
        stock_code: str,
        bar: BacktestBar,
        trade_date: date,
        watchlist_dict: dict,
        market_regime: str,
    ):
        """분봉 처리"""
        # BarAggregator 업데이트
        self.bar_aggregator.add_bar(stock_code, bar)

        current_price = bar.close
        current_time = bar.timestamp

        # 1. 보유 포지션 청산 체크
        if stock_code in self.positions:
            self._check_exit(stock_code, current_price, current_time, trade_date)

        # 2. 진입 체크 (워치리스트에 있고, 포지션이 없을 때)
        if (
            stock_code in watchlist_dict
            and stock_code not in self.positions
            and len(self.positions) < self.max_positions
        ):
            self._check_entry(
                stock_code,
                watchlist_dict[stock_code],
                current_price,
                current_time,
                market_regime,
            )

    def _check_entry(
        self,
        stock_code: str,
        stock_info: dict,
        current_price: float,
        current_time: datetime,
        market_regime: str,
    ):
        """진입 체크"""
        bars = self.bar_aggregator.get_recent_bars(stock_code, count=30)
        vwap = self.bar_aggregator.get_vwap(stock_code)
        volume_info = self.bar_aggregator.get_volume_info(stock_code)

        signal = self.entry_checker.check_entry_signal(
            stock_code=stock_code,
            stock_info=stock_info,
            current_time=current_time,
            current_price=current_price,
            bars=bars,
            market_regime=market_regime,
            vwap=vwap,
            volume_info=volume_info,
        )

        if signal:
            signal_type, reason = signal
            self._execute_entry(stock_code, stock_info, current_price, current_time, signal_type, reason)

    def _execute_entry(
        self,
        stock_code: str,
        stock_info: dict,
        current_price: float,
        current_time: datetime,
        signal_type: str,
        reason: str,
    ):
        """진입 실행"""
        # 매수 비용 계산 (슬리피지 + 수수료)
        buy_price = current_price * (1 + BUY_SLIPPAGE_PCT / 100)

        # 투자 금액 계산
        invest_amount = self.capital * (self.position_size_pct / 100)
        invest_amount = min(invest_amount, self.capital)

        # 수량 계산
        quantity = int(invest_amount / buy_price)
        if quantity <= 0:
            return

        # 실제 매수 금액
        total_cost = quantity * buy_price * (1 + BUY_FEE_PCT / 100)

        if total_cost > self.capital:
            return

        # 포지션 생성
        position = BacktestPosition(
            stock_code=stock_code,
            stock_name=stock_info.get('name', stock_code),
            quantity=quantity,
            buy_price=buy_price,
            buy_time=current_time,
            signal_type=signal_type,
        )

        self.positions[stock_code] = position
        self.capital -= total_cost

        # 통계 업데이트
        self.signal_stats[signal_type]['count'] += 1

        if self.verbose:
            logger.info(
                f"   🔔 진입 [{stock_code}] {signal_type}: "
                f"가격 {current_price:,.0f}원, 수량 {quantity}주"
            )

    def _check_exit(
        self,
        stock_code: str,
        current_price: float,
        current_time: datetime,
        trade_date: date,
    ):
        """청산 체크"""
        position = self.positions.get(stock_code)
        if not position:
            return

        # 일봉 데이터 가져오기 (청산 로직에 필요)
        daily_df = self.daily_data.get(stock_code, pd.DataFrame())
        if not daily_df.empty:
            # 현재 날짜 이전 데이터만 사용
            daily_df = daily_df[daily_df['PRICE_DATE'] < datetime.combine(trade_date, dt_time.min)]

        # PositionState 구성
        position_state = PositionState(
            high_price=position.high_watermark,
            scale_out_level=position.scale_out_level,
            rsi_overbought_sold=position.rsi_overbought_sold,
            profit_floor=position.profit_floor,
        )

        # 청산 조건 체크
        result = check_sell_conditions(
            stock_code=stock_code,
            buy_price=position.buy_price,
            current_price=current_price,
            quantity=position.quantity,
            buy_date=position.buy_time.strftime('%Y%m%d'),
            daily_prices=daily_df,
            position_state=position_state,
            config=self.sell_config,
            market_regime=self._get_market_regime(trade_date),
            current_date=trade_date.strftime('%Y%m%d'),
        )

        # High Watermark 업데이트
        if current_price > position.high_watermark:
            position.high_watermark = current_price

        # 상태 업데이트
        position.scale_out_level = position_state.scale_out_level
        position.rsi_overbought_sold = position_state.rsi_overbought_sold
        position.profit_floor = position_state.profit_floor

        if result.should_sell:
            sell_qty = int(position.quantity * result.quantity_pct / 100)
            if sell_qty > 0:
                self._execute_exit(
                    stock_code, current_price, current_time, result.reason, sell_qty
                )

    def _execute_exit(
        self,
        stock_code: str,
        current_price: float,
        current_time: datetime,
        reason: str,
        quantity: int,
    ):
        """청산 실행"""
        position = self.positions.get(stock_code)
        if not position:
            return

        # 매도 비용 계산 (슬리피지 + 수수료)
        sell_price = current_price * (1 - SELL_SLIPPAGE_PCT / 100)
        proceeds = quantity * sell_price * (1 - SELL_FEE_PCT / 100)

        # P&L 계산
        cost_basis = quantity * position.buy_price * (1 + BUY_FEE_PCT / 100)
        pnl = proceeds - cost_basis
        pnl_pct = (pnl / cost_basis) * 100 if cost_basis > 0 else 0

        # 거래 기록
        holding_minutes = int((current_time - position.buy_time).total_seconds() / 60)

        trade = Trade(
            stock_code=stock_code,
            stock_name=position.stock_name,
            entry_time=position.buy_time,
            entry_price=position.buy_price,
            entry_signal=position.signal_type,
            exit_time=current_time,
            exit_price=sell_price,
            exit_reason=reason,
            quantity=quantity,
            pnl=pnl,
            pnl_pct=pnl_pct,
            holding_minutes=holding_minutes,
        )
        self.trades.append(trade)

        # 통계 업데이트
        signal_type = position.signal_type
        if pnl > 0:
            self.signal_stats[signal_type]['wins'] += 1
        else:
            self.signal_stats[signal_type]['losses'] += 1
        self.signal_stats[signal_type]['pnl'] += pnl

        # 자본 업데이트
        self.capital += proceeds

        # 포지션 업데이트
        remaining = position.quantity - quantity
        if remaining <= 0:
            del self.positions[stock_code]
        else:
            position.quantity = remaining

        if self.verbose:
            logger.info(
                f"   {'✅' if pnl >= 0 else '❌'} 청산 [{stock_code}] {reason}: "
                f"P&L {pnl:,.0f}원 ({pnl_pct:.1f}%)"
            )

    def _close_all_positions(self, current_time: datetime, reason: str):
        """모든 포지션 청산"""
        for stock_code in list(self.positions.keys()):
            position = self.positions[stock_code]
            latest_price = self._get_latest_price(stock_code, current_time.date())
            if latest_price:
                self._execute_exit(
                    stock_code, latest_price, current_time, reason, position.quantity
                )

    def _get_market_regime(self, trade_date: date) -> str:
        """시장 국면 감지"""
        if self.kospi_data is None or self.kospi_data.empty:
            return "SIDEWAYS"

        # 해당 날짜까지의 KOSPI 데이터
        date_dt = datetime.combine(trade_date, dt_time.min)
        kospi_slice = self.kospi_data[self.kospi_data['PRICE_DATE'] <= date_dt].tail(30)

        if kospi_slice.empty:
            return "SIDEWAYS"

        current_price = float(kospi_slice['CLOSE_PRICE'].iloc[-1])

        regime, _ = self.regime_detector.detect_regime(kospi_slice, current_price, quiet=True)
        return regime

    def _get_latest_price(self, stock_code: str, trade_date: date) -> Optional[float]:
        """최신 가격 조회"""
        minute_df = self.minute_data.get(stock_code)
        if minute_df is None or minute_df.empty:
            return None

        day_start = datetime.combine(trade_date, dt_time.min)
        day_end = day_start + timedelta(days=1)

        day_df = minute_df[(minute_df.index >= day_start) & (minute_df.index < day_end)]

        if day_df.empty:
            return None

        return float(day_df['CLOSE_PRICE'].iloc[-1])

    def _generate_results(self) -> dict:
        """결과 생성"""
        if not self.trades:
            return {
                'summary': {
                    'total_trades': 0,
                    'total_pnl': 0,
                    'total_return_pct': 0,
                    'win_rate': 0,
                },
                'trades': [],
                'signal_stats': {},
                'daily_equity': self.daily_equity,
            }

        # 기본 통계
        total_trades = len(self.trades)
        winning_trades = sum(1 for t in self.trades if t.pnl > 0)
        losing_trades = sum(1 for t in self.trades if t.pnl <= 0)
        total_pnl = sum(t.pnl for t in self.trades)

        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0

        # 수익률
        total_return_pct = (total_pnl / self.initial_capital) * 100

        # MDD 계산
        mdd = 0.0
        if self.daily_equity:
            equities = [d['equity'] for d in self.daily_equity]
            peak = equities[0]
            for eq in equities:
                if eq > peak:
                    peak = eq
                drawdown = (peak - eq) / peak * 100
                if drawdown > mdd:
                    mdd = drawdown

        # 평균 보유 시간
        avg_holding_minutes = (
            sum(t.holding_minutes for t in self.trades) / total_trades
            if total_trades > 0 else 0
        )

        # 신호별 통계
        signal_summary = {}
        for signal_type, stats in self.signal_stats.items():
            count = stats['count']
            wins = stats['wins']
            losses = stats['losses']
            pnl = stats['pnl']

            win_rate_sig = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

            signal_summary[signal_type] = {
                'count': count,
                'wins': wins,
                'losses': losses,
                'win_rate': round(win_rate_sig, 1),
                'pnl': round(pnl, 0),
            }

        summary = {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': round(win_rate, 1),
            'total_pnl': round(total_pnl, 0),
            'total_return_pct': round(total_return_pct, 2),
            'avg_pnl_per_trade': round(avg_pnl, 0),
            'mdd_pct': round(mdd, 2),
            'avg_holding_minutes': round(avg_holding_minutes, 0),
            'final_capital': round(self.capital, 0),
        }

        # 거래 내역
        trades_list = []
        for t in self.trades:
            trades_list.append({
                'stock_code': t.stock_code,
                'stock_name': t.stock_name,
                'entry_time': t.entry_time.isoformat() if t.entry_time else None,
                'entry_price': round(t.entry_price, 0),
                'entry_signal': t.entry_signal,
                'exit_time': t.exit_time.isoformat() if t.exit_time else None,
                'exit_price': round(t.exit_price, 0) if t.exit_price else None,
                'exit_reason': t.exit_reason,
                'quantity': t.quantity,
                'pnl': round(t.pnl, 0),
                'pnl_pct': round(t.pnl_pct, 2),
                'holding_minutes': t.holding_minutes,
            })

        return {
            'summary': summary,
            'signal_stats': signal_summary,
            'trades': trades_list,
            'daily_equity': self.daily_equity,
        }


# =============================================================================
# CLI
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="분봉 데이터 기반 현실적 백테스트"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="2025-12-17",
        help="시작일 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="종료일 (YYYY-MM-DD, 기본: 오늘)",
    )
    parser.add_argument(
        "--stocks",
        nargs="+",
        default=None,
        help="특정 종목만 백테스트 (예: 005930 000660)",
    )
    parser.add_argument(
        "--use-watchlist-history",
        action="store_true",
        help="워치리스트 히스토리 사용",
    )
    parser.add_argument(
        "--initial-capital",
        type=float,
        default=10_000_000,
        help="초기 자본금 (기본: 10,000,000원)",
    )
    parser.add_argument(
        "--max-positions",
        type=int,
        default=5,
        help="최대 동시 포지션 수 (기본: 5)",
    )
    parser.add_argument(
        "--position-size",
        type=float,
        default=20.0,
        help="포지션 크기 %% (기본: 20%%)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="상세 로그 출력",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="데이터 로드만 확인 (실제 백테스트 안 함)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="logs/backtest",
        help="결과 파일 저장 디렉토리",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    # 날짜 파싱
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
    if args.end_date:
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
    else:
        end_date = datetime.now()

    logger.info("=" * 60)
    logger.info("📊 분봉 데이터 백테스트 (Realistic)")
    logger.info("=" * 60)
    logger.info(f"   기간: {start_date.date()} ~ {end_date.date()}")
    logger.info(f"   초기 자본: {args.initial_capital:,.0f}원")
    logger.info(f"   최대 포지션: {args.max_positions}개")
    logger.info(f"   포지션 크기: {args.position_size}%")

    # DB 연결
    connection = database.get_db_connection()
    if not connection:
        logger.error("❌ DB 연결 실패")
        return 1

    try:
        # 백테스터 생성
        backtester = MinuteRealisticBacktester(
            initial_capital=args.initial_capital,
            max_positions=args.max_positions,
            position_size_pct=args.position_size,
            verbose=args.verbose,
        )

        # 데이터 로드
        success = backtester.load_data(
            connection=connection,
            start_date=start_date,
            end_date=end_date,
            stock_codes=args.stocks,
            use_watchlist_history=args.use_watchlist_history,
        )

        if not success:
            logger.error("❌ 데이터 로드 실패")
            return 1

        if args.dry_run:
            logger.info("✅ Dry-run 완료 (데이터 로드 성공)")
            return 0

        # 백테스트 실행
        results = backtester.run()

        # 결과 출력
        logger.info("")
        logger.info("=" * 60)
        logger.info("📈 백테스트 결과")
        logger.info("=" * 60)

        summary = results.get('summary', {})
        logger.info(f"   총 거래: {summary.get('total_trades', 0)}건")
        logger.info(f"   승률: {summary.get('win_rate', 0):.1f}%")
        logger.info(f"   총 P&L: {summary.get('total_pnl', 0):,.0f}원")
        logger.info(f"   총 수익률: {summary.get('total_return_pct', 0):.2f}%")
        logger.info(f"   MDD: {summary.get('mdd_pct', 0):.2f}%")
        logger.info(f"   평균 보유시간: {summary.get('avg_holding_minutes', 0):.0f}분")
        logger.info(f"   최종 자본: {summary.get('final_capital', 0):,.0f}원")

        # 신호별 통계
        signal_stats = results.get('signal_stats', {})
        if signal_stats:
            logger.info("")
            logger.info("📊 신호별 통계:")
            for signal_type, stats in sorted(signal_stats.items(), key=lambda x: -x[1]['pnl']):
                logger.info(
                    f"   {signal_type}: "
                    f"{stats['count']}건, "
                    f"승률 {stats['win_rate']:.1f}%, "
                    f"P&L {stats['pnl']:,.0f}원"
                )

        # 결과 파일 저장
        os.makedirs(args.output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # JSON
        json_path = os.path.join(args.output_dir, f"backtest_minute_{timestamp}.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.info(f"\n📁 결과 저장: {json_path}")

        # CSV (거래 내역)
        if results.get('trades'):
            csv_path = os.path.join(args.output_dir, f"trades_{timestamp}.csv")
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=results['trades'][0].keys())
                writer.writeheader()
                writer.writerows(results['trades'])
            logger.info(f"📁 거래 내역: {csv_path}")

        # CSV (자산 곡선)
        if results.get('daily_equity'):
            equity_path = os.path.join(args.output_dir, f"equity_{timestamp}.csv")
            with open(equity_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=results['daily_equity'][0].keys())
                writer.writeheader()
                writer.writerows(results['daily_equity'])
            logger.info(f"📁 자산 곡선: {equity_path}")

        return 0

    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
