"""
shared/llm_constants.py

LLM 관련 공통 상수와 JSON 스키마를 한곳에 모아 관리합니다.
기존 llm.py에서 분리하여 이후 교체/정리 시 영향을 최소화합니다.
"""

LLM_MODEL_NAME = "gemini-2.5-flash"  # 로컬/클라우드 공통 프리미엄 모델 (Jennie)

# LLM이 반환할 JSON의 구조를 정의합니다.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["APPROVE", "REJECT", "SELL", "HOLD"]},
        "reason": {"type": "string"},
        "quantity": {
            "type": "integer",
            "description": "매수를 승인(APPROVE)할 경우, 매수할 주식의 수량. 그 외 결정에서는 0을 반환해야 합니다.",
        },
    },
    "required": ["decision", "reason", "quantity"],
}

# Top-N 랭킹 결재용 JSON 스키마
RANKING_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "best_stock_code": {
            "type": "string",
            "description": "후보 중에서 선택한 '단 하나의' 최고 종목 코드. 모든 후보가 부적절하면 'REJECT_ALL'.",
        },
        "reason": {
            "type": "string",
            "description": "선정 이유 (비교/뉴스 분석 포함)",
        },
        "quantity": {
            "type": "integer",
            "description": "LLM이 제안하는 최종 매수 수량. (REJECT_ALL이면 0)",
        },
    },
    "required": ["best_stock_code", "reason", "quantity"],
}

# 종목 심층 분석 및 점수 산출용 JSON 스키마
ANALYSIS_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {
            "type": "integer",
            "description": "매수 적합도 점수 (0~100점). 80점 이상 적극 매수.",
        },
        "grade": {
            "type": "string",
            "enum": ["S", "A", "B", "C", "D"],
            "description": "종합 등급 (S:90+, A:80+, B:70+, C:60+, D:60미만)",
        },
        "risk_tag": {
            "type": "string",
            "enum": ["BULLISH", "NEUTRAL", "CAUTION", "DISTRIBUTION_RISK"],
            "description": "리스크 태그 - 점수와 독립적으로 판단. DISTRIBUTION_RISK: 세력 물량 분배 의심, 고점 매물대 형성",
        },
        "reason": {
            "type": "string",
            "description": "점수 산정 근거 (RAG 뉴스, 펀더멘털, 기술적 지표 종합)",
        },
    },
    "required": ["score", "grade", "risk_tag", "reason"],
}

# 통합 Analyst 응답 스키마 (risk_tag 없음 — 코드에서 결정)
ANALYST_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {
            "type": "integer",
            "description": "매수 적합도 점수 (0~100점). 정량 점수 ±15점 범위 내.",
        },
        "grade": {
            "type": "string",
            "enum": ["S", "A", "B", "C", "D"],
            "description": "종합 등급 (S:80+, A:70+, B:60+, C:50+, D:50미만)",
        },
        "reason": {
            "type": "string",
            "description": "점수 산정 근거 (정량 보정 이유, 뉴스 해석 등)",
        },
    },
    "required": ["score", "grade", "reason"],
}

# 실시간 뉴스 감성 분석용 스키마
SENTIMENT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {
            "type": "integer",
            "description": "뉴스 감성 점수 (0~100). 80이상: 강력호재, 20이하: 강력악재, 40~60: 중립.",
        },
        "reason": {
            "type": "string",
            "description": "점수 부여 사유 (한 문장 요약)",
        },
    },
    "required": ["score", "reason"],
}

GENERATION_CONFIG = {
    "temperature": 0.2,  # 낮을수록 일관성/사실 기반
    "response_mime_type": "application/json",  # 응답을 JSON으로 강제
    "response_schema": RESPONSE_SCHEMA,  # 기본 스키마
}

SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]


# ==============================================================================
# Macro Council JSON Schemas (3현자 구조화 파이프라인)
# ==============================================================================

# 시스템에 등록된 매수 전략 목록 (buy-scanner에서 사용)
TRADING_STRATEGIES = [
    "GOLDEN_CROSS",
    "RSI_REBOUND",
    "MOMENTUM",
    "RECON_BULL_ENTRY",
    "MOMENTUM_CONTINUATION",
    "SHORT_TERM_HIGH_BREAKOUT",
    "VOLUME_BREAKOUT_1MIN",
    "BULL_PULLBACK",
    "VCP_BREAKOUT",
    "INSTITUTIONAL_ENTRY",
]

# 섹터 대분류 14개 (sector_taxonomy.py NAVER_TO_GROUP 기반)
SECTOR_GROUPS = [
    "반도체/IT",
    "자동차/운송",
    "바이오/헬스케어",
    "2차전지/에너지",
    "금융",
    "조선/기계",
    "방산/우주",
    "철강/화학",
    "건설/부동산",
    "미디어/엔터",
    "유통/소비재",
    "통신/인터넷",
    "음식료/농업",
    "기타",
]

# Step 1: 전략가 (Claude Opus 4.6) 출력 스키마
MACRO_STRATEGIST_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_sentiment": {
            "type": "string",
            "enum": ["bullish", "neutral_to_bullish", "neutral", "neutral_to_bearish", "bearish"],
        },
        "sentiment_score": {
            "type": "integer",
            "description": "시장 심리 점수 (0-100, 50=중립)",
        },
        "regime_hint": {
            "type": "string",
            "description": "시장 레짐 힌트 (예: KOSDAQ_Momentum, Trend_Following, Mean_Reversion, Defensive)",
        },
        "risk_factors": {
            "type": "array",
            "items": {"type": "string"},
            "description": "리스크 요인 3-5개",
        },
        "opportunity_factors": {
            "type": "array",
            "items": {"type": "string"},
            "description": "기회 요인 3-5개",
        },
        "sector_signals": {
            "type": "object",
            "description": "섹터별 신호 (14개 대분류 중 유의미한 변화가 있는 섹터만)",
            "additionalProperties": {"type": "string", "enum": ["bullish", "neutral", "bearish"]},
        },
        "investor_flow_analysis": {
            "type": "string",
            "description": "투자자별 수급 분석 요약 (외국인/기관/개인)",
        },
    },
    "required": [
        "overall_sentiment", "sentiment_score", "regime_hint",
        "sector_signals", "risk_factors", "opportunity_factors", "investor_flow_analysis",
    ],
}

# Step 2: 리스크분석가 (DeepSeek v3.2) 출력 스키마
MACRO_RISK_ANALYST_SCHEMA = {
    "type": "object",
    "properties": {
        "risk_assessment": {
            "type": "object",
            "properties": {
                "agree_with_sentiment": {"type": "boolean"},
                "adjusted_sentiment_score": {
                    "type": "integer",
                    "description": "조정된 심리 점수 (0-100)",
                },
                "adjustment_reason": {"type": "string"},
            },
            "required": ["agree_with_sentiment", "adjusted_sentiment_score", "adjustment_reason"],
        },
        "political_risk_level": {
            "type": "string",
            "enum": ["low", "medium", "high", "critical"],
        },
        "political_risk_summary": {
            "type": "string",
            "description": "정치/지정학 리스크 요약 (1-2문장)",
        },
        "additional_risk_factors": {
            "type": "array",
            "items": {"type": "string"},
            "description": "전략가가 놓친 추가 리스크",
        },
        "position_size_pct": {
            "type": "integer",
            "description": "권장 포지션 사이즈 (50-130, 기본 100)",
        },
        "stop_loss_adjust_pct": {
            "type": "integer",
            "description": "손절폭 조정 (80-150, 기본 100)",
        },
        "risk_reasoning": {
            "type": "string",
            "description": "리스크 평가 근거 (2-3문장)",
        },
    },
    "required": [
        "risk_assessment", "political_risk_level", "political_risk_summary",
        "additional_risk_factors", "position_size_pct", "stop_loss_adjust_pct",
        "risk_reasoning",
    ],
}

# Step 3: 수석심판 (Gemini 3.0 Pro) 출력 스키마
MACRO_CHIEF_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "final_sentiment": {
            "type": "string",
            "enum": ["bullish", "neutral_to_bullish", "neutral", "neutral_to_bearish", "bearish"],
        },
        "final_sentiment_score": {
            "type": "integer",
            "description": "최종 심리 점수 (0-100)",
        },
        "final_regime_hint": {
            "type": "string",
            "description": "최종 시장 레짐 힌트",
        },
        "strategies_to_favor": {
            "type": "array",
            "items": {"type": "string"},
            "description": "오늘 유리한 전략 (시스템 전략 목록에서 선택)",
        },
        "strategies_to_avoid": {
            "type": "array",
            "items": {"type": "string"},
            "description": "오늘 피해야 할 전략",
        },
        "sectors_to_favor": {
            "type": "array",
            "items": {"type": "string"},
            "description": "유망 섹터 (14개 대분류에서 선택)",
        },
        "sectors_to_avoid": {
            "type": "array",
            "items": {"type": "string"},
            "description": "회피 섹터 (14개 대분류에서 선택)",
        },
        "final_position_size_pct": {
            "type": "integer",
            "description": "최종 포지션 사이즈 (50-130)",
        },
        "final_stop_loss_adjust_pct": {
            "type": "integer",
            "description": "최종 손절폭 조정 (80-150)",
        },
        "trading_reasoning": {
            "type": "string",
            "description": "종합 트레이딩 근거 (2-3문장, 정치 리스크 포함)",
        },
        "council_consensus": {
            "type": "string",
            "enum": ["strong_agree", "agree", "partial_disagree", "disagree"],
            "description": "전략가-리스크분석가 간 의견 합치도",
        },
    },
    "required": [
        "final_sentiment", "final_sentiment_score", "final_regime_hint",
        "strategies_to_favor", "strategies_to_avoid",
        "sectors_to_favor", "sectors_to_avoid",
        "final_position_size_pct", "final_stop_loss_adjust_pct",
        "trading_reasoning", "council_consensus",
    ],
}
