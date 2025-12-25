"""
Centralized configuration registry (Project Recon - Phase 1)

목적:
- 설정 키/타입/기본값/설명을 한 곳에 모아 관리
- 우선순위: env > DB(CONFIG) > preset/json(향후) > registry 기본값

구성:
- REGISTRY: {key: {"value": default, "type": "int|float|bool|str", "desc": "...", "category": "..."}}
"""

REGISTRY = {
    # ===== LLM / 점수 임계값 =====
    "MIN_LLM_SCORE": {"value": 60, "type": "int", "desc": "LLM 최소 점수(Tier1)", "category": "LLM"},
    "MIN_LLM_SCORE_TIER2": {"value": 65, "type": "int", "desc": "LLM 최소 점수(Tier2)", "category": "LLM"},
    "MIN_LLM_SCORE_RECON": {"value": 65, "type": "int", "desc": "LLM 최소 점수(정찰병)", "category": "LLM"},

    # ===== Recon / Trend =====
    "RECON_POSITION_MULT": {"value": 0.3, "type": "float", "desc": "정찰병 포지션 비중 배수", "category": "Recon"},
    "RECON_STOP_LOSS_PCT": {"value": -0.025, "type": "float", "desc": "정찰병 손절 기준 (%)", "category": "Recon"},
    "RECON_MOMENTUM_MIN": {"value": 20.0, "type": "float", "desc": "정찰 모멘텀 최소 점수(25점 만점 환산)", "category": "Recon"},
    "RECON_VOLUME_RATIO_MIN": {"value": 1.5, "type": "float", "desc": "정찰 거래량 추세 최소 배수", "category": "Recon"},
    "ENABLE_RECON_IN_BEAR": {"value": True, "type": "bool", "desc": "하락장에서도 정찰(추세) 허용", "category": "Recon"},

    # ===== 시그널 파라미터 =====
    "BUY_GOLDEN_CROSS_SHORT": {"value": 5, "type": "int", "desc": "골든크로스 단기 이평", "category": "Signal"},
    "BUY_GOLDEN_CROSS_LONG": {"value": 20, "type": "int", "desc": "골든크로스 장기 이평", "category": "Signal"},
    "BUY_RSI_OVERSOLD_THRESHOLD": {"value": 30, "type": "int", "desc": "RSI 과매도 기준", "category": "Signal"},

    # ===== 리스크/비중 =====
    "MAX_BUY_COUNT_PER_DAY": {"value": 5, "type": "int", "desc": "일일 최대 매수 건수", "category": "Risk"},
    "MAX_PORTFOLIO_SIZE": {"value": 10, "type": "int", "desc": "보유 종목 한도", "category": "Risk"},
    "MAX_POSITION_VALUE_PCT": {"value": 10.0, "type": "float", "desc": "단일 종목 최대 비중(%)", "category": "Risk"},
    "MAX_SECTOR_PCT": {"value": 30.0, "type": "float", "desc": "섹터 최대 비중(%)", "category": "Risk"},
    "CASH_KEEP_PCT": {"value": 10.0, "type": "float", "desc": "최소 현금 보유 비중(%)", "category": "Risk"},

    # ===== Secrets (표시는 하되 값은 노출 금지) =====
    "OPENAI_API_KEY": {"value": "", "type": "str", "desc": "OpenAI API Key", "category": "Secrets", "sensitive": True},
    "GEMINI_API_KEY": {"value": "", "type": "str", "desc": "Google Gemini API Key", "category": "Secrets", "sensitive": True},
    "ANTHROPIC_API_KEY": {"value": "", "type": "str", "desc": "Anthropic Claude API Key", "category": "Secrets", "sensitive": True},
    "KIS_APP_KEY": {"value": "", "type": "str", "desc": "KIS App Key", "category": "Secrets", "sensitive": True},
    "KIS_APP_SECRET": {"value": "", "type": "str", "desc": "KIS App Secret", "category": "Secrets", "sensitive": True},
    "KIS_ACCOUNT_NO": {"value": "", "type": "str", "desc": "KIS 계좌번호(앞 8자리)", "category": "Secrets", "sensitive": True},
    "KIS_ACCOUNT_SUFFIX": {"value": "", "type": "str", "desc": "KIS 계좌번호 뒤 2자리", "category": "Secrets", "sensitive": True},
    "KIS_VIRTUAL_ACCOUNT_NO": {"value": "", "type": "str", "desc": "KIS 모의 계좌번호(앞 8자리)", "category": "Secrets", "sensitive": True},
    "KIS_VIRTUAL_ACCOUNT_SUFFIX": {"value": "", "type": "str", "desc": "KIS 모의 계좌번호 뒤 2자리", "category": "Secrets", "sensitive": True},
    "TELEGRAM_BOT_TOKEN": {"value": "", "type": "str", "desc": "텔레그램 봇 토큰", "category": "Secrets", "sensitive": True},
    "TELEGRAM_CHAT_ID": {"value": "", "type": "str", "desc": "텔레그램 채팅 ID", "category": "Secrets", "sensitive": True},
    "JWT_SECRET": {"value": "", "type": "str", "desc": "대시보드 JWT 시크릿", "category": "Secrets", "sensitive": True},
    "DASHBOARD_PASSWORD": {"value": "", "type": "str", "desc": "대시보드 관리자 비밀번호", "category": "Secrets", "sensitive": True},
    "MARIADB_PASSWORD": {"value": "", "type": "str", "desc": "MariaDB 비밀번호", "category": "Secrets", "sensitive": True},
    "REDIS_PASSWORD": {"value": "", "type": "str", "desc": "Redis 비밀번호", "category": "Secrets", "sensitive": True},
    "RABBITMQ_PASS": {"value": "", "type": "str", "desc": "RabbitMQ 패스워드", "category": "Secrets", "sensitive": True},
    "RABBITMQ_USER": {"value": "", "type": "str", "desc": "RabbitMQ 사용자", "category": "Secrets", "sensitive": True},
}


def get_registry_defaults() -> dict:
    """레지스트리 기본값(dict) 반환 (ConfigManager 병합용)."""
    return REGISTRY

