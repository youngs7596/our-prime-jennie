#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
services/telegram-collector/channels.py
---------------------------------------
텔레그램 채널 설정 및 메타데이터 정의.
3현자 Council 권고에 따라 각 채널의 역할을 명확히 구분합니다.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class ChannelRole(Enum):
    """채널 역할 구분 (3현자 권고)"""
    MACRO_SIGNAL = "macro_signal"  # 시황/매크로 분석 (키움 한지영)
    STOCK_REFERENCE = "stock_reference"  # 종목 참고용 (하나/메리츠)


class ContentType(Enum):
    """콘텐츠 유형"""
    MARKET_OUTLOOK = "market_outlook"  # 시황 전망
    SECTOR_ANALYSIS = "sector_analysis"  # 섹터 분석
    STOCK_ANALYSIS = "stock_analysis"  # 종목 분석
    MACRO_EVENT = "macro_event"  # 매크로 이벤트 (금리, 환율 등)
    WEEKLY_REPORT = "weekly_report"  # 주간 리포트


@dataclass
class TelegramChannel:
    """텔레그램 채널 설정"""
    username: str  # @username (@ 제외)
    name: str  # 표시 이름
    role: ChannelRole
    primary_content: List[ContentType]
    weight: float  # 신호 가중치 (0.0 ~ 1.0)
    description: str

    # 파싱 힌트
    has_structured_format: bool = False  # 구조화된 형식 여부
    title_pattern: Optional[str] = None  # 제목 패턴 (정규식)
    section_delimiter: Optional[str] = None  # 섹션 구분자


# ==============================================================================
# 채널 정의 (3현자 Council 권고 반영)
# ==============================================================================

TELEGRAM_CHANNELS = [
    TelegramChannel(
        username="hedgecat0301",
        name="키움증권 전략/시황 한지영",
        role=ChannelRole.MACRO_SIGNAL,
        primary_content=[
            ContentType.MARKET_OUTLOOK,
            ContentType.MACRO_EVENT,
            ContentType.WEEKLY_REPORT,
        ],
        weight=0.6,  # Macro Signal 주 소스
        description="장 시작 전 시황, 주간 전략, 매크로 분석. MarketRegimeDetector 보조 입력의 핵심 소스.",
        has_structured_format=True,
        title_pattern=r"\[(\d+/\d+),\s*(.+?),\s*키움\s*한지영\]",
        section_delimiter=None,  # 번호 기반 (1. 2. 3.)
    ),
    TelegramChannel(
        username="HanaResearch",
        name="하나증권 리서치",
        role=ChannelRole.STOCK_REFERENCE,
        primary_content=[
            ContentType.STOCK_ANALYSIS,
            ContentType.SECTOR_ANALYSIS,
            ContentType.MARKET_OUTLOOK,
        ],
        weight=0.2,  # 종목 참고용 (낮은 가중치)
        description="기업 실적, 글로벌 Macro, 섹터 리포트. 종목별 투자의견 및 목표주가.",
        has_structured_format=True,
        title_pattern=r"(.+?)\s*\((\d{6})\.KS/(.+?)\)",
        section_delimiter="■",
    ),
    TelegramChannel(
        username="meritz_research",
        name="메리츠증권 리서치",
        role=ChannelRole.STOCK_REFERENCE,
        primary_content=[
            ContentType.STOCK_ANALYSIS,
            ContentType.SECTOR_ANALYSIS,
        ],
        weight=0.2,  # 종목 참고용 (낮은 가중치)
        description="기업 분석, 목표주가, 시장 전망. 실적 리뷰 중심.",
        has_structured_format=True,
        title_pattern=r"📮\s*\[(.+?)\s+(.+?)\]",
        section_delimiter="▶",
    ),
]


def get_channel_by_username(username: str) -> Optional[TelegramChannel]:
    """username으로 채널 설정 조회"""
    for channel in TELEGRAM_CHANNELS:
        if channel.username == username:
            return channel
    return None


def get_macro_channels() -> List[TelegramChannel]:
    """Macro Signal 역할의 채널만 반환"""
    return [ch for ch in TELEGRAM_CHANNELS if ch.role == ChannelRole.MACRO_SIGNAL]


def get_all_channel_usernames() -> List[str]:
    """모든 채널의 username 목록 반환"""
    return [ch.username for ch in TELEGRAM_CHANNELS]
