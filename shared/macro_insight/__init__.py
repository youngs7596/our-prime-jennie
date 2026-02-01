#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_insight - 매크로 인사이트 모듈
===========================================

텔레그램 증권사 리서치 채널의 매크로 정보를 분석하여
MarketRegimeDetector의 보조 입력으로 활용합니다.

3현자 Council 권고사항:
- 외부 정보 가중치 ≤10%
- RISK_OFF 단독 발동 금지
- 편향 필터링 및 다중 검증 필수
"""

from .macro_sentiment_analyzer import (
    MacroSentimentAnalyzer,
    SentimentResult,
    MacroSignal,
    SignalType,
)

from .macro_signal_aggregator import (
    MacroSignalAggregator,
    get_macro_regime_adjustment,
    process_telegram_message,
    apply_macro_adjustment_to_regime,
)

from .daily_insight import (
    # Data Classes
    DailyMacroInsight,
    SectorSignal,
    KeyTheme,
    # DB Operations
    save_insight_to_db,
    load_insight_from_db,
    load_recent_insights,
    # Redis Operations
    save_insight_to_redis,
    get_today_insight,
    get_insight_by_date,
    # Convenience Functions (서비스에서 사용)
    get_position_multiplier,
    get_sector_signal,
    get_sector_score_adjustment,
    is_high_volatility_regime,
    get_stop_loss_multiplier,
    should_skip_sector,
)

from .enhanced_analyzer import (
    EnhancedMacroAnalyzer,
    EnhancedMacroInsight,
    DataCitation,
    RiskOffAssessment,
    PositionSizeRecommendation,
    DataQualityNotes,
)

from .trading_context import (
    EnhancedTradingContext,
    get_enhanced_trading_context,
    build_trading_context,
    clear_trading_context_cache,
    calculate_risk_off_level,
    calculate_position_multiplier,
    calculate_stop_loss_multiplier,
)

__all__ = [
    # Analyzer
    "MacroSentimentAnalyzer",
    "SentimentResult",
    "MacroSignal",
    "SignalType",
    # Aggregator
    "MacroSignalAggregator",
    "get_macro_regime_adjustment",
    "process_telegram_message",
    "apply_macro_adjustment_to_regime",
    # Daily Insight - Data Classes
    "DailyMacroInsight",
    "SectorSignal",
    "KeyTheme",
    # Daily Insight - DB
    "save_insight_to_db",
    "load_insight_from_db",
    "load_recent_insights",
    # Daily Insight - Redis
    "save_insight_to_redis",
    "get_today_insight",
    "get_insight_by_date",
    # Daily Insight - Convenience
    "get_position_multiplier",
    "get_sector_signal",
    "get_sector_score_adjustment",
    "is_high_volatility_regime",
    "get_stop_loss_multiplier",
    "should_skip_sector",
    # Enhanced Analyzer
    "EnhancedMacroAnalyzer",
    "EnhancedMacroInsight",
    "DataCitation",
    "RiskOffAssessment",
    "PositionSizeRecommendation",
    "DataQualityNotes",
    # Trading Context (서비스 통합용)
    "EnhancedTradingContext",
    "get_enhanced_trading_context",
    "build_trading_context",
    "clear_trading_context_cache",
    "calculate_risk_off_level",
    "calculate_position_multiplier",
    "calculate_stop_loss_multiplier",
]
