#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_insight/daily_insight.py
-------------------------------------
일일 매크로 인사이트 저장/조회 모듈.

3현자 Council 분석 결과를 DB에 저장하고,
각 서비스(scout-worker, buy-scanner 등)에서 조회하여 활용합니다.
"""

import json
import logging
import redis
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import shared.database as database

logger = logging.getLogger(__name__)

# 한국 시간대
KST = ZoneInfo("Asia/Seoul")

# Redis 키
REDIS_KEY_DAILY_INSIGHT = "macro:daily_insight"
REDIS_KEY_INSIGHT_PREFIX = "macro:insight:"  # macro:insight:2026-01-30


# ==============================================================================
# Data Classes
# ==============================================================================

@dataclass
class SectorSignal:
    """섹터별 신호"""
    sector: str
    signal: str  # bullish, neutral, bearish
    confidence: int = 50  # 0-100
    drivers: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)


@dataclass
class KeyTheme:
    """핵심 테마"""
    rank: int
    theme: str
    description: str
    impact: str = "medium"  # high, medium, low
    duration: str = "short_term"  # short_term, medium_term, long_term


@dataclass
class DailyMacroInsight:
    """일일 매크로 인사이트"""
    insight_date: date
    source_channel: str
    source_analyst: str

    # 핵심 지표
    sentiment: str  # bullish, neutral_to_bullish, neutral, bearish, etc.
    sentiment_score: int  # 0-100
    regime_hint: str  # MarketRegimeDetector용

    # 상세 데이터
    sector_signals: Dict[str, SectorSignal] = field(default_factory=dict)
    key_themes: List[KeyTheme] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    opportunity_factors: List[str] = field(default_factory=list)
    key_stocks: List[str] = field(default_factory=list)

    # 원본 데이터
    raw_message: str = ""
    raw_council_output: Dict[str, Any] = field(default_factory=dict)
    council_cost_usd: float = 0.0

    # Enhanced fields (글로벌 매크로 데이터 통합)
    global_snapshot: Optional[Dict[str, Any]] = None  # GlobalMacroSnapshot.to_dict()
    data_sources_used: List[str] = field(default_factory=list)
    data_citations: List[Dict[str, Any]] = field(default_factory=list)  # 3현자 요구사항
    vix_regime: str = ""  # low_vol, normal, elevated, crisis
    rate_differential: Optional[float] = None  # Fed Rate - BOK Rate

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환"""
        return {
            "insight_date": self.insight_date.isoformat(),
            "source_channel": self.source_channel,
            "source_analyst": self.source_analyst,
            "sentiment": self.sentiment,
            "sentiment_score": self.sentiment_score,
            "regime_hint": self.regime_hint,
            "sector_signals": {
                k: asdict(v) if isinstance(v, SectorSignal) else v
                for k, v in self.sector_signals.items()
            },
            "key_themes": [
                asdict(t) if isinstance(t, KeyTheme) else t
                for t in self.key_themes
            ],
            "risk_factors": self.risk_factors,
            "opportunity_factors": self.opportunity_factors,
            "key_stocks": self.key_stocks,
            "council_cost_usd": self.council_cost_usd,
            # Enhanced fields
            "global_snapshot": self.global_snapshot,
            "data_sources_used": self.data_sources_used,
            "data_citations": self.data_citations,
            "vix_regime": self.vix_regime,
            "rate_differential": self.rate_differential,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DailyMacroInsight":
        """딕셔너리에서 생성"""
        insight_date = data.get("insight_date")
        if isinstance(insight_date, str):
            insight_date = date.fromisoformat(insight_date)

        return cls(
            insight_date=insight_date,
            source_channel=data.get("source_channel", ""),
            source_analyst=data.get("source_analyst", ""),
            sentiment=data.get("sentiment", "neutral"),
            sentiment_score=data.get("sentiment_score", 50),
            regime_hint=data.get("regime_hint", ""),
            sector_signals=data.get("sector_signals", {}),
            key_themes=data.get("key_themes", []),
            risk_factors=data.get("risk_factors", []),
            opportunity_factors=data.get("opportunity_factors", []),
            key_stocks=data.get("key_stocks", []),
            raw_message=data.get("raw_message", ""),
            raw_council_output=data.get("raw_council_output", {}),
            council_cost_usd=data.get("council_cost_usd", 0.0),
            # Enhanced fields
            global_snapshot=data.get("global_snapshot"),
            data_sources_used=data.get("data_sources_used", []),
            data_citations=data.get("data_citations", []),
            vix_regime=data.get("vix_regime", ""),
            rate_differential=data.get("rate_differential"),
        )


# ==============================================================================
# DB Operations
# ==============================================================================

def save_insight_to_db(insight: DailyMacroInsight, conn=None) -> bool:
    """
    매크로 인사이트를 DB에 저장 (UPSERT).

    Args:
        insight: DailyMacroInsight 객체
        conn: DB 커넥션 (없으면 새로 생성)

    Returns:
        저장 성공 여부
    """
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        sql = """
        INSERT INTO DAILY_MACRO_INSIGHT (
            INSIGHT_DATE, SOURCE_CHANNEL, SOURCE_ANALYST,
            SENTIMENT, SENTIMENT_SCORE, REGIME_HINT,
            SECTOR_SIGNALS, KEY_THEMES, RISK_FACTORS,
            OPPORTUNITY_FACTORS, KEY_STOCKS,
            RAW_MESSAGE, RAW_COUNCIL_OUTPUT, COUNCIL_COST_USD
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        ) ON DUPLICATE KEY UPDATE
            SOURCE_CHANNEL = VALUES(SOURCE_CHANNEL),
            SOURCE_ANALYST = VALUES(SOURCE_ANALYST),
            SENTIMENT = VALUES(SENTIMENT),
            SENTIMENT_SCORE = VALUES(SENTIMENT_SCORE),
            REGIME_HINT = VALUES(REGIME_HINT),
            SECTOR_SIGNALS = VALUES(SECTOR_SIGNALS),
            KEY_THEMES = VALUES(KEY_THEMES),
            RISK_FACTORS = VALUES(RISK_FACTORS),
            OPPORTUNITY_FACTORS = VALUES(OPPORTUNITY_FACTORS),
            KEY_STOCKS = VALUES(KEY_STOCKS),
            RAW_MESSAGE = VALUES(RAW_MESSAGE),
            RAW_COUNCIL_OUTPUT = VALUES(RAW_COUNCIL_OUTPUT),
            COUNCIL_COST_USD = VALUES(COUNCIL_COST_USD),
            UPDATED_AT = CURRENT_TIMESTAMP
        """

        # JSON 직렬화
        sector_signals_json = json.dumps(
            {k: asdict(v) if isinstance(v, SectorSignal) else v
             for k, v in insight.sector_signals.items()},
            ensure_ascii=False
        )
        key_themes_json = json.dumps(
            [asdict(t) if isinstance(t, KeyTheme) else t for t in insight.key_themes],
            ensure_ascii=False
        )
        risk_factors_json = json.dumps(insight.risk_factors, ensure_ascii=False)
        opportunity_factors_json = json.dumps(insight.opportunity_factors, ensure_ascii=False)
        key_stocks_json = json.dumps(insight.key_stocks, ensure_ascii=False)
        raw_council_json = json.dumps(insight.raw_council_output, ensure_ascii=False, default=str)

        params = (
            insight.insight_date,
            insight.source_channel,
            insight.source_analyst,
            insight.sentiment,
            insight.sentiment_score,
            insight.regime_hint,
            sector_signals_json,
            key_themes_json,
            risk_factors_json,
            opportunity_factors_json,
            key_stocks_json,
            insight.raw_message,
            raw_council_json,
            insight.council_cost_usd,
        )

        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            conn.commit()

        logger.info(f"[MacroInsight] DB 저장 완료: {insight.insight_date}")
        return True

    except Exception as e:
        logger.error(f"[MacroInsight] DB 저장 실패: {e}", exc_info=True)
        return False
    finally:
        if close_conn:
            conn.close()


def load_insight_from_db(
    insight_date: date,
    conn=None
) -> Optional[DailyMacroInsight]:
    """
    특정 날짜의 매크로 인사이트 조회.

    Args:
        insight_date: 조회할 날짜
        conn: DB 커넥션

    Returns:
        DailyMacroInsight 또는 None
    """
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        sql = """
        SELECT
            INSIGHT_DATE, SOURCE_CHANNEL, SOURCE_ANALYST,
            SENTIMENT, SENTIMENT_SCORE, REGIME_HINT,
            SECTOR_SIGNALS, KEY_THEMES, RISK_FACTORS,
            OPPORTUNITY_FACTORS, KEY_STOCKS,
            RAW_MESSAGE, RAW_COUNCIL_OUTPUT, COUNCIL_COST_USD
        FROM DAILY_MACRO_INSIGHT
        WHERE INSIGHT_DATE = %s
        """

        with conn.cursor() as cursor:
            cursor.execute(sql, (insight_date,))
            row = cursor.fetchone()

        if not row:
            return None

        return DailyMacroInsight(
            insight_date=row[0],
            source_channel=row[1],
            source_analyst=row[2],
            sentiment=row[3],
            sentiment_score=row[4],
            regime_hint=row[5],
            sector_signals=json.loads(row[6]) if row[6] else {},
            key_themes=json.loads(row[7]) if row[7] else [],
            risk_factors=json.loads(row[8]) if row[8] else [],
            opportunity_factors=json.loads(row[9]) if row[9] else [],
            key_stocks=json.loads(row[10]) if row[10] else [],
            raw_message=row[11] or "",
            raw_council_output=json.loads(row[12]) if row[12] else {},
            council_cost_usd=float(row[13]) if row[13] else 0.0,
        )

    except Exception as e:
        logger.error(f"[MacroInsight] DB 조회 실패: {e}", exc_info=True)
        return None
    finally:
        if close_conn:
            conn.close()


def load_recent_insights(
    days: int = 7,
    conn=None
) -> List[DailyMacroInsight]:
    """
    최근 N일간의 매크로 인사이트 조회.

    Args:
        days: 조회 기간 (일)
        conn: DB 커넥션

    Returns:
        DailyMacroInsight 리스트 (최신순)
    """
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        sql = """
        SELECT
            INSIGHT_DATE, SOURCE_CHANNEL, SOURCE_ANALYST,
            SENTIMENT, SENTIMENT_SCORE, REGIME_HINT,
            SECTOR_SIGNALS, KEY_THEMES, RISK_FACTORS,
            OPPORTUNITY_FACTORS, KEY_STOCKS,
            RAW_MESSAGE, RAW_COUNCIL_OUTPUT, COUNCIL_COST_USD
        FROM DAILY_MACRO_INSIGHT
        WHERE INSIGHT_DATE >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        ORDER BY INSIGHT_DATE DESC
        """

        with conn.cursor() as cursor:
            cursor.execute(sql, (days,))
            rows = cursor.fetchall()

        insights = []
        for row in rows:
            insights.append(DailyMacroInsight(
                insight_date=row[0],
                source_channel=row[1],
                source_analyst=row[2],
                sentiment=row[3],
                sentiment_score=row[4],
                regime_hint=row[5],
                sector_signals=json.loads(row[6]) if row[6] else {},
                key_themes=json.loads(row[7]) if row[7] else [],
                risk_factors=json.loads(row[8]) if row[8] else [],
                opportunity_factors=json.loads(row[9]) if row[9] else [],
                key_stocks=json.loads(row[10]) if row[10] else [],
                raw_message=row[11] or "",
                raw_council_output=json.loads(row[12]) if row[12] else {},
                council_cost_usd=float(row[13]) if row[13] else 0.0,
            ))

        return insights

    except Exception as e:
        logger.error(f"[MacroInsight] 최근 인사이트 조회 실패: {e}", exc_info=True)
        return []
    finally:
        if close_conn:
            conn.close()


# ==============================================================================
# Redis Operations (실시간 조회용)
# ==============================================================================

def _get_redis_client() -> redis.Redis:
    """Redis 클라이언트 반환"""
    import os
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.from_url(redis_url)


def save_insight_to_redis(insight: DailyMacroInsight, ttl_hours: int = 24) -> bool:
    """
    매크로 인사이트를 Redis에 캐시.

    Args:
        insight: DailyMacroInsight 객체
        ttl_hours: TTL (시간)

    Returns:
        저장 성공 여부
    """
    try:
        r = _get_redis_client()

        # 오늘의 인사이트 키
        key = REDIS_KEY_DAILY_INSIGHT
        date_key = f"{REDIS_KEY_INSIGHT_PREFIX}{insight.insight_date.isoformat()}"

        data = json.dumps(insight.to_dict(), ensure_ascii=False, default=str)

        # 현재 인사이트 저장 (실시간 조회용)
        r.set(key, data, ex=ttl_hours * 3600)

        # 날짜별 인사이트 저장 (이력 조회용)
        r.set(date_key, data, ex=7 * 24 * 3600)  # 7일 보관

        logger.info(f"[MacroInsight] Redis 캐시 저장: {insight.insight_date}")
        return True

    except Exception as e:
        logger.error(f"[MacroInsight] Redis 저장 실패: {e}")
        return False


def get_today_insight() -> Optional[DailyMacroInsight]:
    """
    오늘의 매크로 인사이트 조회 (Redis 우선, DB fallback).

    Returns:
        DailyMacroInsight 또는 None
    """
    try:
        r = _get_redis_client()

        # Redis에서 먼저 조회
        data = r.get(REDIS_KEY_DAILY_INSIGHT)
        if data:
            insight_dict = json.loads(data)
            return DailyMacroInsight.from_dict(insight_dict)

        # Redis에 없으면 DB에서 조회
        today = datetime.now(KST).date()
        insight = load_insight_from_db(today)

        if insight:
            # Redis에 캐시
            save_insight_to_redis(insight)

        return insight

    except Exception as e:
        logger.error(f"[MacroInsight] 오늘 인사이트 조회 실패: {e}")
        return None


def get_insight_by_date(target_date: date) -> Optional[DailyMacroInsight]:
    """
    특정 날짜의 매크로 인사이트 조회.

    Args:
        target_date: 조회할 날짜

    Returns:
        DailyMacroInsight 또는 None
    """
    try:
        r = _get_redis_client()

        # Redis에서 먼저 조회
        date_key = f"{REDIS_KEY_INSIGHT_PREFIX}{target_date.isoformat()}"
        data = r.get(date_key)
        if data:
            insight_dict = json.loads(data)
            return DailyMacroInsight.from_dict(insight_dict)

        # DB에서 조회
        return load_insight_from_db(target_date)

    except Exception as e:
        logger.error(f"[MacroInsight] 인사이트 조회 실패 ({target_date}): {e}")
        return None


# ==============================================================================
# Convenience Functions (서비스에서 사용)
# ==============================================================================

def get_position_multiplier(insight: Optional[DailyMacroInsight] = None) -> float:
    """
    매크로 인사이트 기반 포지션 사이즈 배율.

    Args:
        insight: DailyMacroInsight (없으면 오늘 인사이트 조회)

    Returns:
        0.7 ~ 1.3 배율
    """
    if insight is None:
        insight = get_today_insight()

    if insight is None:
        return 1.0  # 인사이트 없으면 기본값

    score = insight.sentiment_score

    if score >= 70:
        return 1.2   # 강세장: +20%
    elif score >= 60:
        return 1.1   # 약강세: +10%
    elif score <= 30:
        return 0.7   # 약세장: -30%
    elif score <= 40:
        return 0.85  # 약약세: -15%
    else:
        return 1.0   # 중립


def get_sector_signal(
    sector: str,
    insight: Optional[DailyMacroInsight] = None
) -> str:
    """
    특정 섹터의 신호 조회.

    Args:
        sector: 섹터명 (반도체, 자동차, 바이오 등)
        insight: DailyMacroInsight

    Returns:
        "bullish", "neutral", "bearish"
    """
    if insight is None:
        insight = get_today_insight()

    if insight is None or not insight.sector_signals:
        return "neutral"

    # 섹터명 매칭 (유연하게)
    sector_lower = sector.lower()
    for key, signal_data in insight.sector_signals.items():
        if sector_lower in key.lower() or key.lower() in sector_lower:
            if isinstance(signal_data, dict):
                return signal_data.get("signal", "neutral")
            elif isinstance(signal_data, SectorSignal):
                return signal_data.signal

    return "neutral"


def get_sector_score_adjustment(
    sector: str,
    insight: Optional[DailyMacroInsight] = None
) -> float:
    """
    섹터별 점수 조정 배율.

    Args:
        sector: 섹터명
        insight: DailyMacroInsight

    Returns:
        0.9 ~ 1.1 배율
    """
    signal = get_sector_signal(sector, insight)

    if signal == "bullish":
        return 1.10  # +10%
    elif signal == "bearish":
        return 0.90  # -10%
    else:
        return 1.0


def is_high_volatility_regime(
    insight: Optional[DailyMacroInsight] = None
) -> bool:
    """
    고변동성 국면 여부 확인.

    Args:
        insight: DailyMacroInsight

    Returns:
        True if high volatility regime
    """
    if insight is None:
        insight = get_today_insight()

    if insight is None:
        return False

    regime_hint = insight.regime_hint.lower() if insight.regime_hint else ""
    return "volatility" in regime_hint or "high" in regime_hint


def get_stop_loss_multiplier(
    insight: Optional[DailyMacroInsight] = None
) -> float:
    """
    손절 폭 조정 배율.

    Args:
        insight: DailyMacroInsight

    Returns:
        1.0 ~ 1.5 배율 (고변동성 시 넓은 손절)
    """
    if is_high_volatility_regime(insight):
        return 1.5  # 손절 폭 50% 확대
    return 1.0


def should_skip_sector(
    sector: str,
    insight: Optional[DailyMacroInsight] = None
) -> bool:
    """
    특정 섹터 진입 스킵 여부.

    Args:
        sector: 섹터명
        insight: DailyMacroInsight

    Returns:
        True if sector should be skipped
    """
    signal = get_sector_signal(sector, insight)
    return signal == "bearish"
