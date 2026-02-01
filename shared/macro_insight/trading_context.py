#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_insight/trading_context.py
---------------------------------------
트레이딩 서비스용 통합 매크로 컨텍스트.

글로벌 매크로 스냅샷 + 3현자 Council 분석 결과를 통합하여
트레이딩 서비스에서 사용하기 쉬운 형태로 제공합니다.

3현자 Council 권고사항:
- 외부 정보 가중치 ≤10%
- RISK_OFF 단독 발동 금지 (다중 지표 확인 필수)
- 편향 필터링 및 다중 검증 필수
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import redis

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")


@dataclass
class EnhancedTradingContext:
    """
    트레이딩 서비스용 통합 매크로 컨텍스트.

    scout-job, buy-scanner, price-monitor 등에서 사용합니다.

    Usage:
        ctx = get_enhanced_trading_context()
        if ctx.risk_off_level >= 2:
            # 신규 진입 제한
        position_size = base_size * ctx.position_multiplier
    """

    # 기본 정보
    context_date: date
    last_updated: datetime

    # VIX 기반 리스크 레벨
    vix_value: Optional[float] = None
    vix_regime: str = "normal"  # low_vol, normal, elevated, crisis

    # 포지션 사이징
    position_multiplier: float = 1.0  # 0.5 ~ 1.3
    max_position_count: int = 10      # 동시 보유 종목 수 제한

    # Risk-Off 상태
    risk_off_level: int = 0           # 0=정상, 1=주의, 2=경계, 3=위험
    risk_off_reasons: List[str] = field(default_factory=list)

    # 섹터 신호
    sector_signals: Dict[str, float] = field(default_factory=dict)  # -1.0 ~ 1.0
    avoid_sectors: List[str] = field(default_factory=list)
    favor_sectors: List[str] = field(default_factory=list)

    # 전략 힌트
    strategy_hints: List[str] = field(default_factory=list)
    # 예: ["momentum_ok", "avoid_breakout", "prefer_pullback"]

    # 손절/익절 조정
    stop_loss_multiplier: float = 1.0   # 1.0 ~ 1.5
    take_profit_multiplier: float = 1.0 # 0.8 ~ 1.2

    # 원본 데이터 참조
    sentiment: str = "neutral"
    sentiment_score: int = 50
    regime_hint: str = ""

    # 글로벌 지표 (참고용)
    fed_rate: Optional[float] = None
    treasury_spread: Optional[float] = None
    usd_krw: Optional[float] = None
    kospi_index: Optional[float] = None

    # 데이터 품질
    data_completeness: float = 0.0
    data_sources: List[str] = field(default_factory=list)
    has_global_data: bool = False
    has_council_analysis: bool = False

    def is_risk_off(self) -> bool:
        """Risk-Off 상태 여부 (레벨 2 이상)"""
        return self.risk_off_level >= 2

    def should_reduce_exposure(self) -> bool:
        """노출 축소 필요 여부 (레벨 1 이상 또는 VIX elevated)"""
        return self.risk_off_level >= 1 or self.vix_regime in ["elevated", "crisis"]

    def get_allowed_strategies(self) -> List[str]:
        """현재 컨텍스트에서 허용되는 전략 목록"""
        if self.vix_regime == "crisis" or self.risk_off_level >= 3:
            # 위기 시: 보수적 전략만
            return ["RSI_REBOUND", "BULL_PULLBACK"]
        elif self.vix_regime == "elevated" or self.risk_off_level >= 2:
            # 경계 시: 공격적 전략 제외
            return [
                "GOLDEN_CROSS", "RSI_REBOUND", "MOMENTUM",
                "BULL_PULLBACK", "INSTITUTIONAL_ENTRY"
            ]
        else:
            # 정상: 모든 전략
            return [
                "RECON_BULL_ENTRY", "MOMENTUM_CONTINUATION",
                "SHORT_TERM_HIGH_BREAKOUT", "VOLUME_BREAKOUT_1MIN",
                "BULL_PULLBACK", "VCP_BREAKOUT", "INSTITUTIONAL_ENTRY",
                "GOLDEN_CROSS", "RSI_REBOUND", "MOMENTUM"
            ]

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환"""
        return {
            "context_date": self.context_date.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "vix_value": self.vix_value,
            "vix_regime": self.vix_regime,
            "position_multiplier": self.position_multiplier,
            "max_position_count": self.max_position_count,
            "risk_off_level": self.risk_off_level,
            "risk_off_reasons": self.risk_off_reasons,
            "sector_signals": self.sector_signals,
            "avoid_sectors": self.avoid_sectors,
            "favor_sectors": self.favor_sectors,
            "strategy_hints": self.strategy_hints,
            "stop_loss_multiplier": self.stop_loss_multiplier,
            "take_profit_multiplier": self.take_profit_multiplier,
            "sentiment": self.sentiment,
            "sentiment_score": self.sentiment_score,
            "data_completeness": self.data_completeness,
            "has_global_data": self.has_global_data,
            "has_council_analysis": self.has_council_analysis,
        }


def calculate_risk_off_level(
    vix: Optional[float],
    vix_regime: str,
    treasury_spread: Optional[float],
    sentiment_score: int,
    news_sentiment: Optional[float],
) -> Tuple[int, List[str]]:
    """
    Risk-Off 레벨 계산.

    3현자 권고: RISK_OFF 단독 발동 금지 (다중 지표 확인 필수)

    Args:
        vix: VIX 값 (또는 VXX proxy)
        vix_regime: VIX 레짐
        treasury_spread: 10Y-2Y 스프레드
        sentiment_score: Council 감성 점수 (0-100)
        news_sentiment: 뉴스 감성 (-1.0 ~ 1.0)

    Returns:
        (level 0-3, reasons)
    """
    signals = []

    # 1. VIX 기반 (단독으로 RISK_OFF 불가)
    if vix_regime == "crisis" or (vix and vix >= 35):
        signals.append(("vix_crisis", 2))
    elif vix_regime == "elevated" or (vix and vix >= 25):
        signals.append(("vix_elevated", 1))

    # 2. 금리 역전 (경기침체 선행지표)
    if treasury_spread is not None and treasury_spread < 0:
        signals.append(("yield_curve_inverted", 2))
    elif treasury_spread is not None and treasury_spread < 0.3:
        signals.append(("yield_curve_flat", 1))

    # 3. Council sentiment
    if sentiment_score < 30:
        signals.append(("sentiment_very_bearish", 2))
    elif sentiment_score < 40:
        signals.append(("sentiment_bearish", 1))

    # 4. 뉴스 감성
    if news_sentiment is not None:
        if news_sentiment < -0.3:
            signals.append(("news_very_negative", 1))
        elif news_sentiment < -0.15:
            signals.append(("news_negative", 1))

    # 다중 지표 확인: 2개 이상이어야 RISK_OFF
    total_score = sum(s[1] for s in signals)
    reasons = [s[0] for s in signals]

    if len(signals) >= 3 and total_score >= 4:
        return (3, reasons)  # 위험 (3개 이상 강한 신호)
    elif len(signals) >= 2 and total_score >= 3:
        return (2, reasons)  # 경계
    elif len(signals) >= 2 or total_score >= 2:
        return (1, reasons)  # 주의
    else:
        return (0, reasons)  # 정상


def calculate_position_multiplier(
    vix_regime: str,
    risk_off_level: int,
    sentiment_score: int,
) -> float:
    """
    포지션 사이즈 배율 계산.

    3현자 권고: 외부 정보 가중치 ≤10%

    Args:
        vix_regime: VIX 레짐
        risk_off_level: Risk-Off 레벨 (0-3)
        sentiment_score: Council 감성 점수 (0-100)

    Returns:
        0.5 ~ 1.3 배율
    """
    base = 1.0

    # 1. VIX Regime 조정 (±15%)
    vix_adj = {
        "low_vol": 0.10,    # Risk-On: +10%
        "normal": 0.0,
        "elevated": -0.10,  # 주의: -10%
        "crisis": -0.20,    # 위기: -20%
    }.get(vix_regime, 0.0)

    # 2. Risk-Off 레벨 조정 (±20%)
    risk_adj = {
        0: 0.0,
        1: -0.10,  # 주의: -10%
        2: -0.20,  # 경계: -20%
        3: -0.30,  # 위험: -30%
    }.get(risk_off_level, 0.0)

    # 3. Sentiment 조정 (최대 ±10%, 외부 가중치 제한)
    if sentiment_score >= 70:
        sent_adj = 0.10
    elif sentiment_score >= 60:
        sent_adj = 0.05
    elif sentiment_score <= 30:
        sent_adj = -0.10
    elif sentiment_score <= 40:
        sent_adj = -0.05
    else:
        sent_adj = 0.0

    # 최종 배율 (0.5 ~ 1.3 범위 제한)
    multiplier = base + vix_adj + risk_adj + sent_adj
    return max(0.5, min(1.3, round(multiplier, 2)))


def calculate_stop_loss_multiplier(
    vix_regime: str,
    risk_off_level: int,
) -> float:
    """
    손절폭 배율 계산.

    변동성 높을 때 손절폭 확대하여 노이즈에 의한 조기 청산 방지.

    Args:
        vix_regime: VIX 레짐
        risk_off_level: Risk-Off 레벨

    Returns:
        1.0 ~ 1.5 배율
    """
    base = 1.0

    # VIX 높을 때 손절폭 확대
    if vix_regime == "crisis":
        base = 1.5
    elif vix_regime == "elevated":
        base = 1.3
    elif vix_regime == "low_vol":
        base = 0.9  # 변동성 낮을 때 손절폭 축소

    # Risk-Off 시 추가 확대
    if risk_off_level >= 2:
        base = min(1.5, base * 1.1)

    return round(base, 2)


def calculate_max_positions(
    vix_regime: str,
    risk_off_level: int,
    base_max: int = 10,
) -> int:
    """
    최대 동시 보유 종목 수 계산.

    Args:
        vix_regime: VIX 레짐
        risk_off_level: Risk-Off 레벨
        base_max: 기본 최대 종목 수

    Returns:
        조정된 최대 종목 수
    """
    if risk_off_level >= 3 or vix_regime == "crisis":
        return max(3, base_max // 3)  # 1/3로 축소
    elif risk_off_level >= 2 or vix_regime == "elevated":
        return max(5, base_max // 2)  # 1/2로 축소
    elif risk_off_level >= 1:
        return max(7, int(base_max * 0.7))  # 70%로 축소
    else:
        return base_max


def extract_sector_signals(
    sector_signals_raw: Dict[str, Any],
    threshold: float = 0.3,
) -> Tuple[Dict[str, float], List[str], List[str]]:
    """
    섹터 신호 추출 및 분류.

    Args:
        sector_signals_raw: Council 분석의 섹터 신호
        threshold: 선호/회피 판단 임계값

    Returns:
        (normalized_signals, avoid_sectors, favor_sectors)
    """
    normalized = {}
    avoid = []
    favor = []

    for sector, signal in sector_signals_raw.items():
        # 신호값 정규화 (다양한 형식 처리)
        if isinstance(signal, (int, float)):
            value = float(signal)
        elif isinstance(signal, str):
            signal_lower = signal.lower()
            if "강세" in signal_lower or "bullish" in signal_lower:
                value = 0.5
            elif "약세" in signal_lower or "bearish" in signal_lower:
                value = -0.5
            elif "중립" in signal_lower or "neutral" in signal_lower:
                value = 0.0
            else:
                value = 0.0
        elif isinstance(signal, dict):
            value = signal.get("score", 0.0)
        else:
            value = 0.0

        # -1.0 ~ 1.0 범위로 제한
        value = max(-1.0, min(1.0, value))
        normalized[sector] = value

        # 분류
        if value <= -threshold:
            avoid.append(sector)
        elif value >= threshold:
            favor.append(sector)

    return normalized, avoid, favor


def get_strategy_hints(
    vix_regime: str,
    risk_off_level: int,
    sentiment: str,
    regime_hint: str,
) -> List[str]:
    """
    전략 힌트 생성.

    Args:
        vix_regime: VIX 레짐
        risk_off_level: Risk-Off 레벨
        sentiment: Council sentiment (bullish/neutral/bearish)
        regime_hint: Council regime hint

    Returns:
        전략 힌트 목록
    """
    hints = []

    # VIX 기반 힌트
    if vix_regime == "crisis":
        hints.extend(["avoid_breakout", "prefer_pullback", "reduce_position"])
    elif vix_regime == "elevated":
        hints.extend(["cautious_breakout", "prefer_pullback"])
    elif vix_regime == "low_vol":
        hints.extend(["momentum_ok", "breakout_ok"])

    # Risk-Off 기반 힌트
    if risk_off_level >= 2:
        hints.extend(["defensive_only", "no_new_entry"])
    elif risk_off_level >= 1:
        hints.append("reduce_aggression")

    # Sentiment 기반 힌트
    if sentiment == "bullish":
        hints.append("momentum_ok")
    elif sentiment == "bearish":
        hints.append("prefer_rebound")

    # Regime hint 반영
    if regime_hint:
        regime_lower = regime_hint.lower()
        if "bull" in regime_lower:
            hints.append("trend_following_ok")
        elif "bear" in regime_lower:
            hints.append("counter_trend_ok")

    return list(set(hints))  # 중복 제거


def build_trading_context(
    global_snapshot: Optional[Dict[str, Any]] = None,
    council_insight: Optional[Dict[str, Any]] = None,
) -> EnhancedTradingContext:
    """
    글로벌 스냅샷 + Council 인사이트로 트레이딩 컨텍스트 생성.

    Args:
        global_snapshot: GlobalMacroSnapshot.to_dict()
        council_insight: DailyMacroInsight (dict 형태)

    Returns:
        EnhancedTradingContext
    """
    now = datetime.now(KST)
    today = now.date()

    # 기본값
    vix = None
    vix_regime = "normal"
    treasury_spread = None
    sentiment = "neutral"
    sentiment_score = 50
    news_sentiment = None
    sector_signals_raw = {}
    regime_hint = ""
    data_sources = []
    fed_rate = None
    usd_krw = None
    kospi_index = None
    data_completeness = 0.0

    # 글로벌 스냅샷에서 추출
    has_global = False
    if global_snapshot:
        has_global = True
        vix = global_snapshot.get("vix")
        vix_regime = global_snapshot.get("vix_regime", "normal")
        treasury_spread = global_snapshot.get("treasury_spread")
        news_sentiment = global_snapshot.get("korea_news_sentiment")
        fed_rate = global_snapshot.get("fed_rate")
        usd_krw = global_snapshot.get("usd_krw")
        kospi_index = global_snapshot.get("kospi_index")
        data_sources = global_snapshot.get("data_sources", [])
        data_completeness = global_snapshot.get("completeness_score", 0.0)

    # Council 인사이트에서 추출
    has_council = False
    if council_insight:
        has_council = True
        sentiment = council_insight.get("sentiment", "neutral")
        sentiment_score = council_insight.get("sentiment_score", 50)
        sector_signals_raw = council_insight.get("sector_signals", {})
        regime_hint = council_insight.get("regime_hint", "")

    # Risk-Off 계산
    risk_off_level, risk_off_reasons = calculate_risk_off_level(
        vix=vix,
        vix_regime=vix_regime,
        treasury_spread=treasury_spread,
        sentiment_score=sentiment_score,
        news_sentiment=news_sentiment,
    )

    # 포지션 배율 계산
    position_multiplier = calculate_position_multiplier(
        vix_regime=vix_regime,
        risk_off_level=risk_off_level,
        sentiment_score=sentiment_score,
    )

    # 손절 배율 계산
    stop_loss_multiplier = calculate_stop_loss_multiplier(
        vix_regime=vix_regime,
        risk_off_level=risk_off_level,
    )

    # 최대 포지션 수 계산
    max_positions = calculate_max_positions(
        vix_regime=vix_regime,
        risk_off_level=risk_off_level,
    )

    # 섹터 신호 추출
    sector_signals, avoid_sectors, favor_sectors = extract_sector_signals(
        sector_signals_raw
    )

    # 전략 힌트 생성
    strategy_hints = get_strategy_hints(
        vix_regime=vix_regime,
        risk_off_level=risk_off_level,
        sentiment=sentiment,
        regime_hint=regime_hint,
    )

    return EnhancedTradingContext(
        context_date=today,
        last_updated=now,
        vix_value=vix,
        vix_regime=vix_regime,
        position_multiplier=position_multiplier,
        max_position_count=max_positions,
        risk_off_level=risk_off_level,
        risk_off_reasons=risk_off_reasons,
        sector_signals=sector_signals,
        avoid_sectors=avoid_sectors,
        favor_sectors=favor_sectors,
        strategy_hints=strategy_hints,
        stop_loss_multiplier=stop_loss_multiplier,
        take_profit_multiplier=1.0,  # 기본값
        sentiment=sentiment,
        sentiment_score=sentiment_score,
        regime_hint=regime_hint,
        fed_rate=fed_rate,
        treasury_spread=treasury_spread,
        usd_krw=usd_krw,
        kospi_index=kospi_index,
        data_completeness=data_completeness,
        data_sources=data_sources,
        has_global_data=has_global,
        has_council_analysis=has_council,
    )


# 캐시된 컨텍스트
_cached_context: Optional[EnhancedTradingContext] = None
_cache_time: Optional[datetime] = None
_CACHE_TTL_MINUTES = 30


def get_enhanced_trading_context(
    force_refresh: bool = False,
) -> EnhancedTradingContext:
    """
    통합 트레이딩 컨텍스트 조회.

    글로벌 스냅샷 + Council 인사이트를 결합한 컨텍스트를 반환합니다.
    30분 캐싱됩니다.

    Args:
        force_refresh: True면 캐시 무시하고 새로 로드

    Returns:
        EnhancedTradingContext

    Usage:
        ctx = get_enhanced_trading_context()
        if ctx.is_risk_off():
            # 신규 진입 제한
        position_size = base_size * ctx.position_multiplier
    """
    global _cached_context, _cache_time

    now = datetime.now(KST)

    # 캐시 확인
    if (
        not force_refresh
        and _cached_context is not None
        and _cache_time is not None
        and (now - _cache_time).total_seconds() < _CACHE_TTL_MINUTES * 60
    ):
        return _cached_context

    # 글로벌 스냅샷 로드 (오늘 → 최근 3일 폴백)
    global_snapshot = None
    try:
        from shared.macro_data import get_today_snapshot, load_recent_snapshots
        snapshot = get_today_snapshot()

        # 오늘 데이터가 없으면 최근 3일 중 가장 최신 사용
        if not snapshot:
            recent = load_recent_snapshots(days=3)
            if recent:
                snapshot = recent[0]  # 가장 최신
                logger.info(f"[TradingContext] Using recent snapshot from {snapshot.snapshot_date}")

        if snapshot:
            global_snapshot = snapshot.to_dict()
            logger.debug(f"[TradingContext] Global snapshot loaded: completeness={snapshot.get_completeness_score():.0%}")
    except ImportError:
        logger.debug("[TradingContext] macro_data module not available")
    except Exception as e:
        logger.warning(f"[TradingContext] Failed to load global snapshot: {e}")

    # Council 인사이트 로드
    council_insight = None
    try:
        from shared.macro_insight import get_today_insight
        insight = get_today_insight()
        if insight:
            council_insight = {
                "sentiment": insight.sentiment,
                "sentiment_score": insight.sentiment_score,
                "sector_signals": insight.sector_signals,
                "regime_hint": insight.regime_hint,
            }
            logger.debug(f"[TradingContext] Council insight loaded: {insight.sentiment}")
    except ImportError:
        logger.debug("[TradingContext] macro_insight module not available")
    except Exception as e:
        logger.warning(f"[TradingContext] Failed to load council insight: {e}")

    # 컨텍스트 생성
    context = build_trading_context(
        global_snapshot=global_snapshot,
        council_insight=council_insight,
    )

    # 캐시 업데이트
    _cached_context = context
    _cache_time = now

    logger.info(
        f"[TradingContext] Built: risk_off={context.risk_off_level}, "
        f"vix_regime={context.vix_regime}, pos_mult={context.position_multiplier}"
    )

    return context


def clear_trading_context_cache() -> None:
    """트레이딩 컨텍스트 캐시 초기화"""
    global _cached_context, _cache_time
    _cached_context = None
    _cache_time = None
    logger.info("[TradingContext] Cache cleared")
