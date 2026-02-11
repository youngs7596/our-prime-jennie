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
    risk_stocks: List[str] = field(default_factory=list)
    opportunity_stocks: List[str] = field(default_factory=list)

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

    # Trading Recommendations (Council이 직접 판단)
    position_size_pct: int = 100  # 권장 포지션 사이즈 (50~130%)
    stop_loss_adjust_pct: int = 100  # 손절폭 조정 (80~150%)
    strategies_to_favor: List[str] = field(default_factory=list)  # 유리한 전략
    strategies_to_avoid: List[str] = field(default_factory=list)  # 피해야 할 전략
    sectors_to_favor: List[str] = field(default_factory=list)  # 유망 섹터
    sectors_to_avoid: List[str] = field(default_factory=list)  # 회피 섹터
    trading_reasoning: str = ""  # 권고 근거

    # Political Risk (Council이 판단)
    political_risk_level: str = "low"  # low, medium, high, critical
    political_risk_summary: str = ""  # 정치 리스크 요약

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환"""
        gs = self.global_snapshot or {}
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
            "risk_stocks": self.risk_stocks,
            "opportunity_stocks": self.opportunity_stocks,
            "council_cost_usd": self.council_cost_usd,
            # Enhanced fields
            "global_snapshot": self.global_snapshot,
            "data_sources_used": self.data_sources_used,
            "data_citations": self.data_citations,
            "vix_regime": gs.get("vix_regime") or self.vix_regime,
            "rate_differential": self.rate_differential,
            # Market Data (global_snapshot에서 추출, 프론트엔드 호환)
            "vix_value": gs.get("vix"),
            "usd_krw": gs.get("usd_krw"),
            "kospi_index": gs.get("kospi_index"),
            "kosdaq_index": gs.get("kosdaq_index"),
            "kospi_foreign_net": gs.get("kospi_foreign_net"),
            "kosdaq_foreign_net": gs.get("kosdaq_foreign_net"),
            "kospi_institutional_net": gs.get("kospi_institutional_net"),
            "kospi_retail_net": gs.get("kospi_retail_net"),
            "data_completeness_pct": round((gs.get("completeness_score") or 0) * 100),
            # Trading Recommendations
            "position_size_pct": self.position_size_pct,
            "stop_loss_adjust_pct": self.stop_loss_adjust_pct,
            "strategies_to_favor": self.strategies_to_favor,
            "strategies_to_avoid": self.strategies_to_avoid,
            "sectors_to_favor": self.sectors_to_favor,
            "sectors_to_avoid": self.sectors_to_avoid,
            "trading_reasoning": self.trading_reasoning,
            # Political Risk
            "political_risk_level": self.political_risk_level,
            "political_risk_summary": self.political_risk_summary,
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
            risk_stocks=data.get("risk_stocks", []),
            opportunity_stocks=data.get("opportunity_stocks", []),
            raw_message=data.get("raw_message", ""),
            raw_council_output=data.get("raw_council_output", {}),
            council_cost_usd=data.get("council_cost_usd", 0.0),
            # Enhanced fields
            global_snapshot=data.get("global_snapshot"),
            data_sources_used=data.get("data_sources_used", []),
            data_citations=data.get("data_citations", []),
            vix_regime=data.get("vix_regime", ""),
            rate_differential=data.get("rate_differential"),
            # Trading Recommendations (Council이 직접 판단)
            position_size_pct=data.get("position_size_pct", 100),
            stop_loss_adjust_pct=data.get("stop_loss_adjust_pct", 100),
            strategies_to_favor=data.get("strategies_to_favor", []),
            strategies_to_avoid=data.get("strategies_to_avoid", []),
            sectors_to_favor=data.get("sectors_to_favor", []),
            sectors_to_avoid=data.get("sectors_to_avoid", []),
            trading_reasoning=data.get("trading_reasoning", ""),
            # Political Risk
            political_risk_level=data.get("political_risk_level", "low"),
            political_risk_summary=data.get("political_risk_summary", ""),
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
            OPPORTUNITY_FACTORS, KEY_STOCKS, RISK_STOCKS, OPPORTUNITY_STOCKS,
            RAW_MESSAGE, RAW_COUNCIL_OUTPUT, COUNCIL_COST_USD,
            POSITION_SIZE_PCT, STOP_LOSS_ADJUST_PCT,
            STRATEGIES_TO_FAVOR, STRATEGIES_TO_AVOID,
            SECTORS_TO_FAVOR, SECTORS_TO_AVOID, TRADING_REASONING,
            POLITICAL_RISK_LEVEL, POLITICAL_RISK_SUMMARY,
            VIX_VALUE, VIX_REGIME, USD_KRW, KOSPI_INDEX, KOSDAQ_INDEX,
            KOSPI_FOREIGN_NET, KOSDAQ_FOREIGN_NET,
            KOSPI_INSTITUTIONAL_NET, KOSPI_RETAIL_NET,
            DATA_COMPLETENESS_PCT
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
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
            RISK_STOCKS = VALUES(RISK_STOCKS),
            OPPORTUNITY_STOCKS = VALUES(OPPORTUNITY_STOCKS),
            RAW_MESSAGE = VALUES(RAW_MESSAGE),
            RAW_COUNCIL_OUTPUT = VALUES(RAW_COUNCIL_OUTPUT),
            COUNCIL_COST_USD = VALUES(COUNCIL_COST_USD),
            POSITION_SIZE_PCT = VALUES(POSITION_SIZE_PCT),
            STOP_LOSS_ADJUST_PCT = VALUES(STOP_LOSS_ADJUST_PCT),
            STRATEGIES_TO_FAVOR = VALUES(STRATEGIES_TO_FAVOR),
            STRATEGIES_TO_AVOID = VALUES(STRATEGIES_TO_AVOID),
            SECTORS_TO_FAVOR = VALUES(SECTORS_TO_FAVOR),
            SECTORS_TO_AVOID = VALUES(SECTORS_TO_AVOID),
            TRADING_REASONING = VALUES(TRADING_REASONING),
            POLITICAL_RISK_LEVEL = VALUES(POLITICAL_RISK_LEVEL),
            POLITICAL_RISK_SUMMARY = VALUES(POLITICAL_RISK_SUMMARY),
            VIX_VALUE = VALUES(VIX_VALUE),
            VIX_REGIME = VALUES(VIX_REGIME),
            USD_KRW = VALUES(USD_KRW),
            KOSPI_INDEX = VALUES(KOSPI_INDEX),
            KOSDAQ_INDEX = VALUES(KOSDAQ_INDEX),
            KOSPI_FOREIGN_NET = VALUES(KOSPI_FOREIGN_NET),
            KOSDAQ_FOREIGN_NET = VALUES(KOSDAQ_FOREIGN_NET),
            KOSPI_INSTITUTIONAL_NET = VALUES(KOSPI_INSTITUTIONAL_NET),
            KOSPI_RETAIL_NET = VALUES(KOSPI_RETAIL_NET),
            DATA_COMPLETENESS_PCT = VALUES(DATA_COMPLETENESS_PCT),
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
        risk_stocks_json = json.dumps(insight.risk_stocks, ensure_ascii=False)
        opportunity_stocks_json = json.dumps(insight.opportunity_stocks, ensure_ascii=False)
        raw_council_json = json.dumps(insight.raw_council_output, ensure_ascii=False, default=str)
        strategies_favor_json = json.dumps(insight.strategies_to_favor, ensure_ascii=False)
        strategies_avoid_json = json.dumps(insight.strategies_to_avoid, ensure_ascii=False)
        sectors_favor_json = json.dumps(insight.sectors_to_favor, ensure_ascii=False)
        sectors_avoid_json = json.dumps(insight.sectors_to_avoid, ensure_ascii=False)

        # 글로벌 스냅샷에서 데이터 추출
        gs = insight.global_snapshot or {}
        vix_value = gs.get("vix")
        vix_regime = gs.get("vix_regime") or insight.vix_regime
        usd_krw = gs.get("usd_krw")
        kospi_index = gs.get("kospi_index")  # Fixed: was "kospi"
        kosdaq_index = gs.get("kosdaq_index")  # Fixed: was "kosdaq"
        kospi_foreign_net = gs.get("kospi_foreign_net")
        kosdaq_foreign_net = gs.get("kosdaq_foreign_net")
        kospi_institutional_net = gs.get("kospi_institutional_net")
        kospi_retail_net = gs.get("kospi_retail_net")
        data_completeness_pct = round((gs.get("completeness_score") or 0) * 100)  # 0.71 → 71

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
            risk_stocks_json,
            opportunity_stocks_json,
            insight.raw_message,
            raw_council_json,
            insight.council_cost_usd,
            insight.position_size_pct,
            insight.stop_loss_adjust_pct,
            strategies_favor_json,
            strategies_avoid_json,
            sectors_favor_json,
            sectors_avoid_json,
            insight.trading_reasoning,
            insight.political_risk_level,
            insight.political_risk_summary,
            vix_value,
            vix_regime,
            usd_krw,
            kospi_index,
            kosdaq_index,
            kospi_foreign_net,
            kosdaq_foreign_net,
            kospi_institutional_net,
            kospi_retail_net,
            data_completeness_pct,
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
            RISK_STOCKS, OPPORTUNITY_STOCKS,
            RAW_MESSAGE, RAW_COUNCIL_OUTPUT, COUNCIL_COST_USD,
            POSITION_SIZE_PCT, STOP_LOSS_ADJUST_PCT,
            STRATEGIES_TO_FAVOR, STRATEGIES_TO_AVOID,
            SECTORS_TO_FAVOR, SECTORS_TO_AVOID, TRADING_REASONING,
            POLITICAL_RISK_LEVEL, POLITICAL_RISK_SUMMARY
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
            risk_stocks=json.loads(row[11]) if row[11] else [],
            opportunity_stocks=json.loads(row[12]) if row[12] else [],
            raw_message=row[13] or "",
            raw_council_output=json.loads(row[14]) if row[14] else {},
            council_cost_usd=float(row[15]) if row[15] else 0.0,
            # Trading Recommendations
            position_size_pct=int(row[16]) if row[16] else 100,
            stop_loss_adjust_pct=int(row[17]) if row[17] else 100,
            strategies_to_favor=json.loads(row[18]) if row[18] else [],
            strategies_to_avoid=json.loads(row[19]) if row[19] else [],
            sectors_to_favor=json.loads(row[20]) if row[20] else [],
            sectors_to_avoid=json.loads(row[21]) if row[21] else [],
            trading_reasoning=row[22] or "",
            # Political Risk
            political_risk_level=row[23] or "low",
            political_risk_summary=row[24] or "",
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
            RISK_STOCKS, OPPORTUNITY_STOCKS,
            RAW_MESSAGE, RAW_COUNCIL_OUTPUT, COUNCIL_COST_USD,
            POSITION_SIZE_PCT, STOP_LOSS_ADJUST_PCT,
            STRATEGIES_TO_FAVOR, STRATEGIES_TO_AVOID,
            SECTORS_TO_FAVOR, SECTORS_TO_AVOID, TRADING_REASONING,
            POLITICAL_RISK_LEVEL, POLITICAL_RISK_SUMMARY
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
                risk_stocks=json.loads(row[11]) if row[11] else [],
                opportunity_stocks=json.loads(row[12]) if row[12] else [],
                raw_message=row[13] or "",
                raw_council_output=json.loads(row[14]) if row[14] else {},
                council_cost_usd=float(row[15]) if row[15] else 0.0,
                # Trading Recommendations
                position_size_pct=int(row[16]) if row[16] else 100,
                stop_loss_adjust_pct=int(row[17]) if row[17] else 100,
                strategies_to_favor=json.loads(row[18]) if row[18] else [],
                strategies_to_avoid=json.loads(row[19]) if row[19] else [],
                sectors_to_favor=json.loads(row[20]) if row[20] else [],
                sectors_to_avoid=json.loads(row[21]) if row[21] else [],
                trading_reasoning=row[22] or "",
                # Political Risk
                political_risk_level=row[23] or "low",
                political_risk_summary=row[24] or "",
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

    Council이 권고한 position_size_pct를 우선 사용하고,
    없으면 sentiment_score 기반 폴백 계산.

    Args:
        insight: DailyMacroInsight (없으면 오늘 인사이트 조회)

    Returns:
        0.5 ~ 1.3 배율
    """
    if insight is None:
        insight = get_today_insight()

    if insight is None:
        return 1.0  # 인사이트 없으면 기본값

    # Council 권고값 우선 사용 (position_size_pct: 50~130)
    if insight.position_size_pct and insight.position_size_pct != 100:
        return insight.position_size_pct / 100.0

    # 폴백: sentiment_score 기반 계산
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

    Council이 권고한 stop_loss_adjust_pct를 우선 사용하고,
    없으면 regime 기반 폴백 계산.

    Args:
        insight: DailyMacroInsight

    Returns:
        0.8 ~ 1.5 배율 (변동성 높을수록 넓은 손절)
    """
    if insight is None:
        insight = get_today_insight()

    if insight is None:
        return 1.0

    # Council 권고값 우선 사용 (stop_loss_adjust_pct: 80~150)
    if insight.stop_loss_adjust_pct and insight.stop_loss_adjust_pct != 100:
        return insight.stop_loss_adjust_pct / 100.0

    # 폴백: regime 기반 계산
    if is_high_volatility_regime(insight):
        return 1.5  # 손절 폭 50% 확대
    return 1.0


def should_skip_sector(
    sector: str,
    insight: Optional[DailyMacroInsight] = None
) -> bool:
    """
    특정 섹터 진입 스킵 여부.

    Council의 sectors_to_avoid를 우선 확인하고,
    없으면 sector_signals 기반으로 판단.

    Args:
        sector: 섹터명
        insight: DailyMacroInsight

    Returns:
        True if sector should be skipped
    """
    if insight is None:
        insight = get_today_insight()

    if insight is None:
        return False

    # Council의 sectors_to_avoid 우선 확인
    if insight.sectors_to_avoid:
        sector_lower = sector.lower()
        for avoid_sector in insight.sectors_to_avoid:
            if sector_lower in avoid_sector.lower() or avoid_sector.lower() in sector_lower:
                return True

    # 폴백: sector_signals 기반 판단
    signal = get_sector_signal(sector, insight)
    return signal == "bearish"


def is_strategy_favored(
    strategy: str,
    insight: Optional[DailyMacroInsight] = None
) -> bool:
    """
    Council이 권고한 유리한 전략인지 확인.

    Args:
        strategy: 전략명 (예: "MOMENTUM_CONTINUATION")
        insight: DailyMacroInsight

    Returns:
        True if strategy is favored by Council
    """
    if insight is None:
        insight = get_today_insight()

    if insight is None or not insight.strategies_to_favor:
        return False

    strategy_upper = strategy.upper()
    return strategy_upper in [s.upper() for s in insight.strategies_to_favor]


def should_avoid_strategy(
    strategy: str,
    insight: Optional[DailyMacroInsight] = None
) -> bool:
    """
    Council이 권고한 피해야 할 전략인지 확인.

    Args:
        strategy: 전략명 (예: "SHORT_TERM_HIGH_BREAKOUT")
        insight: DailyMacroInsight

    Returns:
        True if strategy should be avoided per Council
    """
    if insight is None:
        insight = get_today_insight()

    if insight is None or not insight.strategies_to_avoid:
        return False

    strategy_upper = strategy.upper()
    return strategy_upper in [s.upper() for s in insight.strategies_to_avoid]


def get_trading_reasoning(
    insight: Optional[DailyMacroInsight] = None
) -> str:
    """
    Council의 트레이딩 권고 근거 조회.

    Args:
        insight: DailyMacroInsight

    Returns:
        권고 근거 문자열 (없으면 빈 문자열)
    """
    if insight is None:
        insight = get_today_insight()

    if insight is None:
        return ""

    return insight.trading_reasoning or ""
