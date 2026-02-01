#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_data - 글로벌 매크로 데이터 수집 모듈
=================================================

다양한 소스에서 경제 지표와 시장 데이터를 수집하여
Enhanced Macro Insight 시스템에 제공합니다.

데이터 소스:
- Finnhub: 글로벌 시장 데이터, 경제 캘린더
- FRED: 미국 경제 지표 (금리, CPI, 실업률)
- BOK ECOS: 한국은행 경제통계 (기준금리, 환율, GDP)
- pykrx: KOSPI/KOSDAQ 시세, 수급 데이터
- RSS: 한국 경제뉴스 (매경, 한경)

3현자 Council 권고사항:
- 24시간 이상 지연 데이터 자동 필터링
- 다중 소스 검증 (최소 2개 소스)
- 외부 가중치 ≤10% 제한
"""

from .models import (
    MacroDataPoint,
    GlobalMacroSnapshot,
    EconomicIndicator,
    NewsItem,
    DataQuality,
    IndicatorCategory,
)

from .clients.base import MacroDataClient

from .rate_limiter import RateLimiter, RateLimitExceeded, get_rate_limiter

from .cache import MacroDataCache, get_macro_cache

from .validator import DataValidator, SnapshotValidator, ValidationResult

from .aggregator import EnhancedMacroAggregator, AggregatorConfig, CollectionResult

from .storage import (
    save_snapshot_to_db,
    load_snapshot_from_db,
    load_recent_snapshots,
    get_today_snapshot,
    get_snapshot_trends,
)

from .monitoring import (
    AccuracyTracker,
    AccuracyRecord,
    MacroInsightRollback,
    get_accuracy_tracker,
    get_rollback_manager,
    is_enhanced_macro_enabled,
)

__all__ = [
    # Models
    "MacroDataPoint",
    "GlobalMacroSnapshot",
    "EconomicIndicator",
    "NewsItem",
    "DataQuality",
    "IndicatorCategory",
    # Protocol
    "MacroDataClient",
    # Rate Limiter
    "RateLimiter",
    "RateLimitExceeded",
    "get_rate_limiter",
    # Cache
    "MacroDataCache",
    "get_macro_cache",
    # Validator
    "DataValidator",
    "SnapshotValidator",
    "ValidationResult",
    # Aggregator
    "EnhancedMacroAggregator",
    "AggregatorConfig",
    "CollectionResult",
    # Storage
    "save_snapshot_to_db",
    "load_snapshot_from_db",
    "load_recent_snapshots",
    "get_today_snapshot",
    "get_snapshot_trends",
    # Monitoring
    "AccuracyTracker",
    "AccuracyRecord",
    "MacroInsightRollback",
    "get_accuracy_tracker",
    "get_rollback_manager",
    "is_enhanced_macro_enabled",
]
