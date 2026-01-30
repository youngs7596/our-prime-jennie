#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
services/telegram-collector/collector.py
----------------------------------------
텔레그램 증권사 리서치 채널에서 메시지를 수집하는 서비스.

3현자 Council 권고사항:
- 외부 정보는 보조 역할에 머물러야 함 (가중치 ≤10%)
- RISK_OFF 단독 발동 금지
- 편향 필터링 및 다중 검증 필수

v1.0: Telethon 기반 채널 메시지 수집
"""

import os
import sys
import json
import asyncio
import logging
import hashlib
import re
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from dotenv import load_dotenv

# 프로젝트 루트 설정
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from channels import (
    TELEGRAM_CHANNELS,
    TelegramChannel,
    ChannelRole,
    get_channel_by_username,
)

# ==============================================================================
# Logging
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# ==============================================================================
# Configuration
# ==============================================================================
load_dotenv()


def load_secrets() -> dict:
    """secrets.json에서 설정 로드"""
    secrets_paths = [
        "/app/secrets.json",  # Docker 환경 (볼륨 마운트)
        os.path.join(PROJECT_ROOT, "secrets.json"),
        "/app/config/secrets.json",
    ]
    for path in secrets_paths:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    import json
                    logger.info(f"secrets.json 로드: {path}")
                    return json.load(f)
            except Exception as e:
                logger.warning(f"secrets.json 로드 실패 ({path}): {e}")
    logger.warning("secrets.json을 찾을 수 없음")
    return {}


_secrets = load_secrets()

# Telegram API 설정 (secrets.json 우선, 환경변수 fallback)
TELEGRAM_API_ID = _secrets.get("telegram_api_id") or os.getenv("TELEGRAM_API_ID")
TELEGRAM_API_HASH = _secrets.get("telegram_api_hash") or os.getenv("TELEGRAM_API_HASH")
TELEGRAM_SESSION_NAME = os.getenv("TELEGRAM_SESSION_NAME", "telegram_collector")

# 수집 설정
MAX_MESSAGES_PER_CHANNEL = int(os.getenv("TELEGRAM_MAX_MESSAGES", "50"))
MESSAGE_AGE_HOURS = int(os.getenv("TELEGRAM_MESSAGE_AGE_HOURS", "24"))

# 중복 체크 캐시
_seen_message_hashes: set = set()


# ==============================================================================
# Data Classes
# ==============================================================================

@dataclass
class CollectedMessage:
    """수집된 메시지 데이터 구조"""
    message_id: int
    channel_username: str
    channel_name: str
    channel_role: str
    content: str
    published_at: datetime
    collected_at: datetime
    content_hash: str
    weight: float
    metadata: Dict[str, Any]

    def to_stream_format(self) -> Dict[str, Any]:
        """Redis Stream 발행 형식으로 변환"""
        return {
            "page_content": self.content,
            "metadata": {
                "message_id": self.message_id,
                "channel_username": self.channel_username,
                "channel_name": self.channel_name,
                "channel_role": self.channel_role,
                "published_at_utc": int(self.published_at.timestamp()),
                "collected_at_utc": int(self.collected_at.timestamp()),
                "content_hash": self.content_hash,
                "weight": self.weight,
                "source": "telegram",
                **self.metadata,
            }
        }


# ==============================================================================
# Helper Functions
# ==============================================================================

def compute_content_hash(content: str) -> str:
    """콘텐츠 해시 계산 (중복 체크용)"""
    normalized = re.sub(r'\s+', ' ', content.lower().strip())
    return hashlib.md5(normalized.encode()).hexdigest()[:16]


def is_duplicate(content_hash: str) -> bool:
    """중복 메시지 체크"""
    if content_hash in _seen_message_hashes:
        return True
    _seen_message_hashes.add(content_hash)
    return False


def clear_hash_cache():
    """해시 캐시 초기화"""
    global _seen_message_hashes
    _seen_message_hashes = set()


def extract_metadata_from_content(
    content: str,
    channel: TelegramChannel
) -> Dict[str, Any]:
    """콘텐츠에서 메타데이터 추출"""
    metadata = {
        "has_link": bool(re.search(r'https?://', content)),
        "has_stock_code": bool(re.search(r'\d{6}\.KS', content)),
        "content_length": len(content),
        "line_count": content.count('\n') + 1,
    }

    # 채널별 제목 패턴 추출
    if channel.title_pattern:
        match = re.search(channel.title_pattern, content)
        if match:
            metadata["parsed_title"] = match.groups()

    # 섹터/종목 키워드 감지
    sector_keywords = ['반도체', '자동차', '바이오', '2차전지', '조선', '은행', '증권']
    detected_sectors = [kw for kw in sector_keywords if kw in content]
    if detected_sectors:
        metadata["detected_sectors"] = detected_sectors

    # 매크로 키워드 감지
    macro_keywords = ['금리', '환율', 'FOMC', '물가', 'CPI', 'GDP', '경기', '침체', '인플레이션', '관세', '트럼프', '달러']
    detected_macro = [kw for kw in macro_keywords if kw in content]
    if detected_macro:
        metadata["detected_macro_keywords"] = detected_macro
        metadata["is_macro_related"] = True
    else:
        metadata["is_macro_related"] = False

    return metadata


# ==============================================================================
# Telegram Client (Telethon)
# ==============================================================================

async def collect_channel_messages(
    channel_username: str,
    max_messages: int = MAX_MESSAGES_PER_CHANNEL,
    hours_ago: int = MESSAGE_AGE_HOURS,
) -> List[CollectedMessage]:
    """
    텔레그램 채널에서 메시지를 수집합니다.

    Args:
        channel_username: 채널 username (@ 제외)
        max_messages: 최대 수집 메시지 수
        hours_ago: 몇 시간 이내 메시지만 수집

    Returns:
        수집된 메시지 리스트
    """
    try:
        from telethon import TelegramClient
        from telethon.tl.functions.messages import GetHistoryRequest
    except ImportError:
        logger.error("Telethon not installed. Run: pip install telethon")
        return []

    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        logger.error("TELEGRAM_API_ID and TELEGRAM_API_HASH must be set")
        return []

    channel = get_channel_by_username(channel_username)
    if not channel:
        logger.warning(f"Unknown channel: {channel_username}")
        return []

    collected = []
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_ago)

    # Docker 환경에서 세션 디렉토리 탐색 (우선순위 순)
    session_dir = None
    for candidate in [
        "/opt/airflow/.telegram_sessions",  # Airflow container
        "/app/.telegram_sessions",           # telegram-collector container
        os.path.join(PROJECT_ROOT, ".telegram_sessions"),  # Local development
    ]:
        if os.path.exists(candidate):
            session_dir = candidate
            break
    if session_dir is None:
        session_dir = os.path.join(PROJECT_ROOT, ".telegram_sessions")
    os.makedirs(session_dir, exist_ok=True)
    session_path = os.path.join(session_dir, TELEGRAM_SESSION_NAME)

    async with TelegramClient(session_path, int(TELEGRAM_API_ID), TELEGRAM_API_HASH) as client:
        try:
            entity = await client.get_entity(channel_username)

            messages = await client(GetHistoryRequest(
                peer=entity,
                limit=max_messages,
                offset_id=0,
                offset_date=None,
                add_offset=0,
                max_id=0,
                min_id=0,
                hash=0
            ))

            for msg in messages.messages:
                if not msg.message:
                    continue

                # 시간 필터
                msg_time = msg.date.replace(tzinfo=timezone.utc)
                if msg_time < cutoff_time:
                    continue

                content = msg.message.strip()
                content_hash = compute_content_hash(content)

                # 중복 체크
                if is_duplicate(content_hash):
                    logger.debug(f"Duplicate message skipped: {content_hash}")
                    continue

                # 메타데이터 추출
                metadata = extract_metadata_from_content(content, channel)

                collected.append(CollectedMessage(
                    message_id=msg.id,
                    channel_username=channel_username,
                    channel_name=channel.name,
                    channel_role=channel.role.value,
                    content=content,
                    published_at=msg_time,
                    collected_at=datetime.now(timezone.utc),
                    content_hash=content_hash,
                    weight=channel.weight,
                    metadata=metadata,
                ))

            logger.info(f"Collected {len(collected)} messages from @{channel_username}")

        except Exception as e:
            logger.error(f"Error collecting from @{channel_username}: {e}")

    return collected


async def collect_all_channels(
    max_messages: int = MAX_MESSAGES_PER_CHANNEL,
    hours_ago: int = MESSAGE_AGE_HOURS,
) -> List[CollectedMessage]:
    """모든 설정된 채널에서 메시지 수집"""
    all_messages = []

    for channel in TELEGRAM_CHANNELS:
        messages = await collect_channel_messages(
            channel.username,
            max_messages=max_messages,
            hours_ago=hours_ago,
        )
        all_messages.extend(messages)

    logger.info(f"Total collected: {len(all_messages)} messages from {len(TELEGRAM_CHANNELS)} channels")
    return all_messages


# ==============================================================================
# Redis Stream Publisher
# ==============================================================================

def publish_to_stream(messages: List[CollectedMessage]) -> int:
    """
    수집된 메시지를 Redis Stream에 발행합니다.

    Returns:
        발행된 메시지 수
    """
    try:
        from shared.messaging.stream_client import publish_news_batch, STREAM_MACRO_RAW
    except ImportError:
        logger.error("Failed to import stream_client")
        return 0

    if not messages:
        return 0

    documents = [msg.to_stream_format() for msg in messages]
    published = publish_news_batch(documents, STREAM_MACRO_RAW)

    logger.info(f"Published {published} messages to {STREAM_MACRO_RAW}")
    return published


# ==============================================================================
# Main Entry Points
# ==============================================================================

def run_collector_job():
    """
    수집 작업 실행 (1회)
    - 모든 채널에서 메시지 수집
    - Redis Stream에 발행
    """
    logger.info("=" * 60)
    logger.info("[TelegramCollector] Starting collection job")
    logger.info("=" * 60)

    # Async 실행
    messages = asyncio.run(collect_all_channels())

    if messages:
        published = publish_to_stream(messages)
        logger.info(f"[TelegramCollector] Job complete: {published} messages published")
    else:
        logger.info("[TelegramCollector] No new messages to publish")

    return len(messages)


def run_collector_daemon(interval_seconds: int = 600):
    """
    수집 데몬 (무한 루프)
    - 지정된 간격으로 메시지 수집
    """
    import time

    logger.info(f"[TelegramCollector Daemon] Starting (interval={interval_seconds}s)")

    while True:
        try:
            run_collector_job()
        except Exception as e:
            logger.error(f"[TelegramCollector] Job failed: {e}", exc_info=True)

        logger.info(f"Sleeping for {interval_seconds} seconds...")
        time.sleep(interval_seconds)


# ==============================================================================
# Mock Mode (테스트용)
# ==============================================================================

def generate_mock_messages() -> List[CollectedMessage]:
    """테스트용 모의 메시지 생성"""
    now = datetime.now(timezone.utc)

    mock_data = [
        {
            "channel_username": "hedgecat0301",
            "content": """[1/30, 장 시작 전 생각: 미중 관세 우려 vs 실적 기대, 키움 한지영]

1. 다우 +0.3%, S&P500 +0.5%, 나스닥 +0.8%
2. 미중 관세 이슈 지속. 트럼프 대통령 관세 부과 시사
3. 반도체 업종 강세. AI 투자 기대감 유지
4. 원/달러 1,450원대. 외국인 순매수 전환 기대

오늘도 좋은 하루 되세요!""",
        },
        {
            "channel_username": "HanaResearch",
            "content": """삼성전자 (005930.KS/매수): 4Q24 실적 리뷰

■ 실적 하이라이트
- 매출 75조원 (YoY +10%)
- 영업이익 8조원 (YoY +15%)

■ 애널리스트 Comment
메모리 가격 상승으로 실적 개선. 목표주가 90,000원 유지.

하나증권 반도체 담당
https://vo.la/xxx""",
        },
        {
            "channel_username": "meritz_research",
            "content": """📮 [반도체/디스플레이 김선우]

현대차 (005380) 4Q24 Review

▶ 실적 요약
- 매출 42조원 (컨센서스 상회)
- 영업이익률 9.5%

▶ 투자의견
적정주가 320,000원으로 상향

*동 자료는 Compliance 규정을 준수하여 사전 공표된 자료입니다.""",
        },
    ]

    messages = []
    for i, data in enumerate(mock_data):
        channel = get_channel_by_username(data["channel_username"])
        content = data["content"]
        content_hash = compute_content_hash(content)

        messages.append(CollectedMessage(
            message_id=1000 + i,
            channel_username=data["channel_username"],
            channel_name=channel.name if channel else "Unknown",
            channel_role=channel.role.value if channel else "unknown",
            content=content,
            published_at=now - timedelta(hours=i),
            collected_at=now,
            content_hash=content_hash,
            weight=channel.weight if channel else 0.0,
            metadata=extract_metadata_from_content(content, channel) if channel else {},
        ))

    return messages


# ==============================================================================
# CLI Entry Point
# ==============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Telegram Collector Service")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    parser.add_argument("--interval", type=int, default=600, help="Daemon interval (seconds)")
    parser.add_argument("--mock", action="store_true", help="Use mock data (no Telegram API)")
    parser.add_argument("--max-messages", type=int, default=50, help="Max messages per channel")
    args = parser.parse_args()

    if args.mock:
        logger.info("[Mock Mode] Generating mock messages...")
        messages = generate_mock_messages()
        for msg in messages:
            print(f"\n--- {msg.channel_name} ({msg.channel_role}) ---")
            print(f"Weight: {msg.weight}")
            print(f"Macro related: {msg.metadata.get('is_macro_related', False)}")
            print(f"Content preview: {msg.content[:200]}...")

        # Redis에 발행
        published = publish_to_stream(messages)
        print(f"\nPublished {published} mock messages")
    elif args.daemon:
        run_collector_daemon(args.interval)
    else:
        run_collector_job()
