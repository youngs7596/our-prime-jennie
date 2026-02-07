"""
shared/hybrid_scoring/quant_constants.py

QuantScorer의 가중치/상수/섹터 매핑을 분리해 유지관리와 후속 제거를 용이하게 합니다.

v2 (2026-02-07): 잠재력 기반 스코어링 상수 추가
- "현재 수준" → "변화/개선" 중심 팩터 전환
- QUANT_SCORER_VERSION 환경변수로 v1/v2 토글
"""

import os
from enum import Enum


class StrategyMode(Enum):
    SHORT_TERM = "SHORT_TERM"
    LONG_TERM = "LONG_TERM"
    DUAL = "DUAL"


# 기본값
DEFAULT_FILTER_CUTOFF = 0.6  # 하위 60% 탈락 → 상위 40% 통과 (LLM 부담 경감)
DEFAULT_HOLDING_DAYS = 5

# 섹터별 RSI 가중치
SECTOR_RSI_MULTIPLIER = {
    "조선운송": 1.3,
    "금융": 1.25,
    "자유소비재": 1.1,
    "정보통신": 1.1,
    "에너지화학": 1.05,
    "etc": 1.05,
    "미분류": 1.05,
    "필수소비재": 0.9,
    "건설기계": 0.7,
}

# 장기 호재 뉴스 카테고리
NEWS_LONG_TERM_POSITIVE = {"수주", "실적", "배당"}

# 단기/장기 가중치
SHORT_TERM_WEIGHTS = {
    "rsi_compound": 0.35,
    "technical_rsi": 0.15,
    "supply_demand": 0.20,
    "quality_roe": 0.10,
    "momentum": 0.05,
    "value": 0.05,
    "news": 0.05,
    "llm_qualitative": 0.05,
}

LONG_TERM_WEIGHTS = {
    "quality_roe": 0.30,
    "news_long_term": 0.25,
    "technical_rsi": 0.15,
    "value": 0.10,
    "supply_demand": 0.10,
    "momentum": 0.03,
    "llm_qualitative": 0.07,
}

# 점수 임계값
GRADE_THRESHOLDS = {
    "S": 90,
    "A": 80,
    "B": 70,
    "C": 60,
}

# 모멘텀/품질/가치 랭킹 컷오프 (예시)
RANK_CUTOFF = {
    "momentum": 0.3,
    "value": 0.4,
    "quality": 0.3,
}

# 뉴스 카테고리별 시간축 효과 (팩터 분석 결과)
NEWS_TIME_EFFECT = {
    "수주": {"d5_win_rate": 0.437, "d60_win_rate": 0.727, "d60_return": 0.1936},
    "실적": {"d5_win_rate": 0.484, "d60_win_rate": 0.648, "d60_return": 0.1403},
    "배당": {"d5_win_rate": 0.376, "d60_win_rate": 0.540, "d60_return": 0.0998},
    "신사업": {"d5_win_rate": 0.469, "d60_win_rate": 0.571, "d60_return": 0.0636},
    "M&A": {"d5_win_rate": 0.483, "d60_win_rate": 0.571, "d60_return": 0.0795},
}


# ============================================================================
# v2: 잠재력 기반 스코어링 상수 (2026-02-07)
# ============================================================================

# A/B 테스트 토글: v1 (현재 수준 기반) | v2 (잠재력/변화 기반)
QUANT_SCORER_VERSION = os.getenv("QUANT_SCORER_VERSION", "v1")

# v2 팩터 배점 (100점 만점)
V2_WEIGHTS = {
    "momentum": 20,       # 잠재력 모멘텀 (v1: 25)
    "quality": 20,        # 개선 품질 (v1: 20)
    "value": 20,          # 상대 가치 (v1: 15)
    "technical": 10,      # 축적 신호 (v1: 10)
    "news": 10,           # 센티먼트 전환 (v1: 15)
    "supply_demand": 20,  # 스마트머니 신호 (v1: 15)
}

# v2 모멘텀 서브팩터
V2_MOMENTUM = {
    "relative_6m": 5,         # 6M 상대 모멘텀 (v1: 15 → 대폭 축소)
    "short_1m": 5,            # 1M 단기 모멘텀 (유지)
    "bottom_bounce": 5,       # 바닥 반등 감지 (신규)
    "base_breakout": 5,       # 베이스 탈출 (신규)
}

# v2 품질 서브팩터
V2_QUALITY = {
    "roe_level": 4,           # ROE 절대 수준 (v1: 10 → 축소)
    "roe_trend": 8,           # ROE 개선 트렌드 (신규)
    "eps_growth": 5,          # EPS 성장률 (v1: 3.5 → 확대)
    "stability": 3,           # 이익 안정성 (유지)
}

# v2 가치 서브팩터
V2_VALUE = {
    "pbr": 5,                 # PBR 절대값 (v1: 7.5 → 축소)
    "per": 5,                 # PER 절대값 (v1: 7.5 → 축소)
    "per_historical": 5,      # PER 역사적 할인 (신규)
    "peg_like": 5,            # EPS 대비 PER (신규)
}

# v2 기술적 서브팩터
V2_TECHNICAL = {
    "volume_trend": 3,        # 거래량 추세 (v1: 4 → 약간 축소)
    "rsi": 3,                 # RSI (유지)
    "accumulation": 4,        # 거래량 축적 패턴 (신규)
}

# v2 뉴스 서브팩터
V2_NEWS = {
    "sentiment_level": 4,     # 센티먼트 절대값 (v1: 8 → 축소)
    "sentiment_momentum": 6,  # 센티먼트 모멘텀 (신규)
}

# v2 수급 서브팩터
V2_SUPPLY_DEMAND = {
    "foreign_net_buy": 5,     # 외인 순매수 (v1: 7 → 축소)
    "institution_net_buy": 3, # 기관 순매수 (v1: 5 → 축소)
    "flow_reversal": 3,       # 수급 반전 감지 (v1: ±2 → ±3)
    "foreign_ratio_trend": 5, # 외인 보유비율 추세 (신규)
    "smart_money_sync": 4,    # 기관+외인 동시매수 (신규)
}

# v2 데이터 미보유 시 중립 기본값
V2_NEUTRAL_DEFAULTS = {
    "roe_trend": 4.0,
    "per_historical": 2.5,
    "peg_like": 2.5,
    "sentiment_momentum": 3.0,
    "foreign_ratio_trend": 1.0,
    "accumulation": 0.0,
}
