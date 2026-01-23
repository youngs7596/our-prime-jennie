# shared/hybrid_scoring/chart_phase.py
# Chart Phase Analyzer - Unified Context Layer for Trading Decisions
# Version: 1.0
# Authors: Prime Council (Jennie, Minji, Junho)

"""
차트 위상 분석 엔진.

[핵심 개념]
- Stan Weinstein의 4단계 이론을 이동평균선 배열로 수치화.
- Stage 1: 바닥 다지기 (Accumulation)
- Stage 2: 상승 추세 (Uptrend) - 최적 매수 구간
- Stage 3: 천정권 (Distribution) - 경계 구간
- Stage 4: 하락 추세 (Downtrend) - 매수 금지

[사용법]
analyzer = ChartPhaseAnalyzer()
result = analyzer.analyze(daily_prices_df)
if result.stage == 4:
    logger.warning("Stage 4: 매수 금지")
"""

import logging
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class Stage(Enum):
    """Weinstein-inspired Market Stages"""
    ACCUMULATION = 1      # 바닥 다지기
    UPTREND = 2           # 상승 추세 (정배열)
    DISTRIBUTION = 3      # 천정권 (꺾이기 시작)
    DOWNTREND = 4         # 하락 추세 (역배열)
    TRANSITION = 0        # 혼조세


@dataclass
class ChartPhaseResult:
    """
    차트 위상 분석 결과.
    
    Attributes:
        stage (int): 1~4 (Weinstein Stage), 0 for Transition.
        stage_name (str): Human-readable stage name.
        trend_direction (str): "UP", "DOWN", "SIDE".
        trend_strength (float): 0~100 (from ADX).
        exhaustion_score (float): 0~100 (higher = more tired).
        score_multiplier (float): 점수 가중치 (e.g., 1.2 for Stage 2).
        is_blocked (bool): True if Stage 4 (Hard Filter).
        notes (List[str]): Debug/explanation notes.
    """
    stage: int = 0
    stage_name: str = "TRANSITION"
    trend_direction: str = "SIDE"
    trend_strength: float = 0.0
    exhaustion_score: float = 0.0
    score_multiplier: float = 1.0
    is_blocked: bool = False
    notes: List[str] = field(default_factory=list)


class ChartPhaseAnalyzer:
    """
    차트 위상 분석 엔진.
    
    [Council Recommendations Integrated]
    - Minji: MA Alignment + Hybrid Filter (Block Stage 4, Weight Stage 2).
    - Jennie: Normalized Slope + ADX Fatigue + Phase-aware BBW.
    - Junho: Unified ChartPhaseResult + Centralized Logic.
    """
    
    # MA Periods
    MA_SHORT = 20
    MA_MID = 60
    MA_LONG = 120
    
    # ADX Thresholds
    ADX_TREND_THRESHOLD = 20      # Below this = no trend
    ADX_STRONG_TREND = 40         # Above this = strong trend
    
    # Slope Thresholds (normalized %)
    SLOPE_FLAT_THRESHOLD = 0.5    # < 0.5% change = flat
    SLOPE_RISING_THRESHOLD = 1.0  # > 1.0% change = meaningfully rising
    
    # Score Multipliers (from Council)
    MULTIPLIER_STAGE2 = 1.2       # Uptrend bonus
    MULTIPLIER_STAGE1_BREAKOUT = 1.1  # Accumulation with potential
    MULTIPLIER_STAGE3 = 0.8       # Distribution penalty
    MULTIPLIER_EXHAUSTED = 0.7    # Jennie's recommendation: strong penalty
    MULTIPLIER_BLOCKED = 0.0      # Stage 4 = no buy
    
    def __init__(self, adx_period: int = 14, slope_lookback: int = 5):
        """
        Args:
            adx_period: ADX 계산 기간 (default: 14).
            slope_lookback: 기울기 계산을 위한 과거 일수 (default: 5).
        """
        self.adx_period = adx_period
        self.slope_lookback = slope_lookback
    
    def analyze(self, df: pd.DataFrame) -> ChartPhaseResult:
        """
        주어진 일봉 데이터프레임을 분석하여 ChartPhaseResult 반환.
        
        Args:
            df: 일봉 데이터 (OHLCV). 컬럼: CLOSE_PRICE, HIGH_PRICE, LOW_PRICE 필수.
                날짜 오름차순 정렬 가정.
        
        Returns:
            ChartPhaseResult with stage, trend info, and multipliers.
        """
        result = ChartPhaseResult()
        
        if df is None or len(df) < self.MA_LONG + self.slope_lookback:
            result.notes.append(f"Insufficient data (need {self.MA_LONG + self.slope_lookback}+ rows)")
            return result
        
        try:
            # 1. Calculate MAs
            close = df['CLOSE_PRICE'].astype(float)
            ma_short = close.rolling(self.MA_SHORT).mean()
            ma_mid = close.rolling(self.MA_MID).mean()
            ma_long = close.rolling(self.MA_LONG).mean()
            
            # Current values
            price = close.iloc[-1]
            ma_s = ma_short.iloc[-1]
            ma_m = ma_mid.iloc[-1]
            ma_l = ma_long.iloc[-1]
            
            # 2. Calculate Normalized Slope (Jennie's recommendation)
            slope_s = self._calc_normalized_slope(ma_short)
            slope_m = self._calc_normalized_slope(ma_mid)
            slope_l = self._calc_normalized_slope(ma_long)
            
            result.notes.append(f"MA20={ma_s:,.0f}, MA60={ma_m:,.0f}, MA120={ma_l:,.0f}")
            result.notes.append(f"Slope(20)={slope_s:.2f}%, Slope(60)={slope_m:.2f}%, Slope(120)={slope_l:.2f}%")
            
            # 3. Calculate ADX (Trend Strength)
            adx = self._calc_adx(df)
            result.trend_strength = adx if adx else 0.0
            result.notes.append(f"ADX={adx:.1f}" if adx else "ADX=N/A")
            
            # 4. Determine Stage/Phase
            stage, stage_name, direction = self._determine_stage(
                price, ma_s, ma_m, ma_l, slope_s, slope_m, slope_l, adx
            )
            result.stage = stage
            result.stage_name = stage_name
            result.trend_direction = direction
            
            # 5. Calculate Exhaustion Score
            exhaustion = self._calc_exhaustion(df, ma_short, adx, stage)
            result.exhaustion_score = exhaustion
            result.notes.append(f"Exhaustion={exhaustion:.1f}")
            
            # 6. Determine Multiplier & Block Status
            result.score_multiplier, result.is_blocked = self._get_multiplier(stage, exhaustion)
            
            result.notes.append(f"Stage={stage_name}, Multiplier={result.score_multiplier:.2f}, Blocked={result.is_blocked}")
            
        except Exception as e:
            logger.error(f"ChartPhaseAnalyzer error: {e}", exc_info=True)
            result.notes.append(f"Error: {str(e)}")
        
        return result
    
    def _calc_normalized_slope(self, ma_series: pd.Series) -> float:
        """
        이동평균의 정규화된 기울기 계산 (%).
        
        Jennie's Recommendation: 가격 차이가 아닌 %로 정규화.
        """
        if len(ma_series) < self.slope_lookback + 1:
            return 0.0
        
        current = ma_series.iloc[-1]
        prev = ma_series.iloc[-1 - self.slope_lookback]
        
        if pd.isna(current) or pd.isna(prev) or prev == 0:
            return 0.0
        
        slope_pct = (current - prev) / prev * 100
        return slope_pct
    
    def _calc_adx(self, df: pd.DataFrame) -> Optional[float]:
        """
        ADX (Average Directional Index) 계산.
        
        Higher ADX = Stronger Trend (regardless of direction).
        """
        if len(df) < self.adx_period + 1:
            return None
        
        try:
            high = df['HIGH_PRICE'].astype(float)
            low = df['LOW_PRICE'].astype(float)
            close = df['CLOSE_PRICE'].astype(float)
            
            # True Range
            tr1 = high - low
            tr2 = abs(high - close.shift(1))
            tr3 = abs(low - close.shift(1))
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(self.adx_period).mean()
            
            # Directional Movement
            up_move = high - high.shift(1)
            down_move = low.shift(1) - low
            
            plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
            minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
            
            plus_di = 100 * pd.Series(plus_dm).rolling(self.adx_period).mean() / atr
            minus_di = 100 * pd.Series(minus_dm).rolling(self.adx_period).mean() / atr
            
            # DX and ADX
            dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
            adx = dx.rolling(self.adx_period).mean()
            
            return adx.iloc[-1] if not pd.isna(adx.iloc[-1]) else None
            
        except Exception as e:
            logger.warning(f"ADX calculation failed: {e}")
            return None
    
    def _determine_stage(
        self, price: float, ma_s: float, ma_m: float, ma_l: float,
        slope_s: float, slope_m: float, slope_l: float, adx: Optional[float]
    ) -> Tuple[int, str, str]:
        """
        Weinstein Stage 결정.
        
        Returns:
            (stage_int, stage_name, trend_direction)
        """
        # Perfect Alignment Check
        is_aligned_up = price > ma_s > ma_m > ma_l   # 정배열
        is_aligned_down = price < ma_s < ma_m < ma_l  # 역배열
        
        # Stage 2: Strong Uptrend (정배열)
        if is_aligned_up and slope_l > self.SLOPE_FLAT_THRESHOLD:
            return 2, "UPTREND", "UP"
        
        # Stage 4: Strong Downtrend (역배열)
        if is_aligned_down and slope_l < -self.SLOPE_FLAT_THRESHOLD:
            return 4, "DOWNTREND", "DOWN"
        
        # Stage 3: Distribution (20MA 붕괴, but 장기 MA 아직 상승 중)
        if price < ma_s and slope_m > 0 and slope_l > 0:
            return 3, "DISTRIBUTION", "SIDE"
        
        # Stage 1: Accumulation (장기 역배열 속 단기 반등)
        if price > ma_s and ma_m < ma_l:
            return 1, "ACCUMULATION", "SIDE"
        
        # Transition (혼조세)
        direction = "UP" if slope_m > 0 else ("DOWN" if slope_m < 0 else "SIDE")
        return 0, "TRANSITION", direction
    
    def _calc_exhaustion(
        self, df: pd.DataFrame, ma_short: pd.Series, adx: Optional[float], stage: int
    ) -> float:
        """
        추세 피로도(Exhaustion) 점수 계산 (0~100).
        
        Jennie's Recommendation: ADX Rollover + BBW Phase-aware.
        Minji's Recommendation: ADX + BB %B + RSI Slope.
        """
        exhaustion = 0.0
        
        try:
            # 1. ADX Rollover (35% weight) - Junho/Jennie
            if adx is not None:
                # Check if ADX was high and is now declining
                close = df['CLOSE_PRICE'].astype(float)
                # Simplified: if ADX high but declining
                if adx > self.ADX_STRONG_TREND:
                    # ADX is high -> exhaustion risk exists
                    exhaustion += 20
                elif adx > 25:
                    exhaustion += 10
            
            # 2. Distance from Mean (Z-Score) (25% weight) - Junho
            if len(df) >= 20:
                close = df['CLOSE_PRICE'].astype(float)
                sma20 = close.rolling(20).mean().iloc[-1]
                std20 = close.rolling(20).std().iloc[-1]
                if std20 and std20 > 0:
                    z_score = (close.iloc[-1] - sma20) / std20
                    if z_score > 2.5:
                        exhaustion += 25
                    elif z_score > 2.0:
                        exhaustion += 15
                    elif z_score > 1.5:
                        exhaustion += 5
            
            # 3. RSI Slope Reversal (20% weight) - Minji
            rsi = self._calc_rsi(df, 14)
            if rsi is not None and len(rsi) >= 3:
                rsi_curr = rsi.iloc[-1]
                rsi_prev = rsi.iloc[-3]
                rsi_slope = rsi_curr - rsi_prev
                # RSI 과매수 영역에서 기울기 하락
                if rsi_curr > 60 and rsi_slope < -5:
                    exhaustion += 20
                elif rsi_curr > 50 and rsi_slope < -3:
                    exhaustion += 10
            
            # 4. BBW Spike in Distribution (20% weight) - Jennie's Phase-aware
            if stage == 3:  # Only apply in Distribution phase
                bbw = self._calc_bbw(df, 20, 2)
                if bbw is not None:
                    bbw_percentile = self._get_percentile(df, bbw, 'bbw', 60)
                    if bbw_percentile and bbw_percentile > 80:
                        exhaustion += 20  # High BBW in Stage 3 = Climax risk
            
        except Exception as e:
            logger.warning(f"Exhaustion calculation error: {e}")
        
        return min(exhaustion, 100.0)
    
    def _calc_rsi(self, df: pd.DataFrame, period: int = 14) -> Optional[pd.Series]:
        """RSI 계산."""
        try:
            close = df['CLOSE_PRICE'].astype(float)
            delta = close.diff()
            gain = delta.where(delta > 0, 0).rolling(period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            return rsi
        except Exception:
            return None
    
    def _calc_bbw(self, df: pd.DataFrame, period: int = 20, std_mult: float = 2.0) -> Optional[float]:
        """Bollinger Band Width 계산."""
        try:
            close = df['CLOSE_PRICE'].astype(float)
            sma = close.rolling(period).mean()
            std = close.rolling(period).std()
            upper = sma + std_mult * std
            lower = sma - std_mult * std
            bbw = (upper - lower) / sma * 100  # As percentage
            return bbw.iloc[-1] if not pd.isna(bbw.iloc[-1]) else None
        except Exception:
            return None
    
    def _get_percentile(self, df: pd.DataFrame, current_val: float, metric: str, lookback: int) -> Optional[float]:
        """과거 N일 대비 현재 값의 백분위."""
        # Simplified: compare to recent history
        try:
            close = df['CLOSE_PRICE'].astype(float)
            std = close.rolling(20).std()
            if len(std) < lookback:
                return None
            recent = std.iloc[-lookback:].dropna()
            if len(recent) == 0:
                return None
            percentile = (recent < current_val).sum() / len(recent) * 100
            return percentile
        except Exception:
            return None
    
    def _get_multiplier(self, stage: int, exhaustion: float) -> Tuple[float, bool]:
        """
        Stage와 Exhaustion에 따른 점수 가중치 결정.
        
        Returns:
            (multiplier, is_blocked)
        """
        # Hard Block: Stage 4
        if stage == 4:
            return self.MULTIPLIER_BLOCKED, True
        
        # Exhaustion Penalty (Jennie: strong penalty)
        if exhaustion >= 50:
            return self.MULTIPLIER_EXHAUSTED, False  # 0.7x
        
        # Stage-based Multipliers
        if stage == 2:
            return self.MULTIPLIER_STAGE2, False  # 1.2x
        
        if stage == 1:
            return self.MULTIPLIER_STAGE1_BREAKOUT, False  # 1.1x
        
        if stage == 3:
            return self.MULTIPLIER_STAGE3, False  # 0.8x
        
        # Transition (Neutral)
        return 1.0, False


# Convenience function for external use
def analyze_chart_phase(df: pd.DataFrame) -> ChartPhaseResult:
    """
    편의 함수: DataFrame을 받아 ChartPhaseResult 반환.
    
    Usage:
        from shared.hybrid_scoring.chart_phase import analyze_chart_phase
        result = analyze_chart_phase(daily_prices_df)
    """
    analyzer = ChartPhaseAnalyzer()
    return analyzer.analyze(df)
