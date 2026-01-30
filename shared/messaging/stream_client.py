#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/messaging/stream_client.py
---------------------------------
Redis Streams 기반 메시지 브로커 클라이언트.
뉴스 파이프라인(Collector -> Archiver/Analyzer)의 Pub/Sub 통신을 담당합니다.
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable

import redis

logger = logging.getLogger(__name__)

# ==============================================================================
# Configuration
# ==============================================================================

REDIS_URL = os.getenv("REDIS_URL", "redis://10.178.0.2:6379/0")

# Stream Names
STREAM_NEWS_RAW = "stream:news:raw"  # Collector -> Archiver/Analyzer
STREAM_MACRO_RAW = "stream:macro:raw"  # TelegramCollector -> MacroAnalyzer

# Consumer Groups
GROUP_ARCHIVER = "group_archiver"
GROUP_ANALYZER = "group_analyzer"
GROUP_MACRO_ANALYZER = "group_macro_analyzer"

# Default Settings
DEFAULT_BLOCK_MS = 2000  # 2 seconds
DEFAULT_BATCH_SIZE = 10


# ==============================================================================
# Redis Client Singleton
# ==============================================================================

_redis_client: Optional[redis.Redis] = None


def get_redis_client() -> redis.Redis:
    """Redis 클라이언트 싱글톤 반환"""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=False)
        logger.info(f"✅ Redis 연결 완료: {REDIS_URL}")
    return _redis_client


# ==============================================================================
# Producer Functions (Collector)
# ==============================================================================

def publish_news(
    page_content: str,
    metadata: Dict[str, Any],
    stream_name: str = STREAM_NEWS_RAW
) -> str:
    """
    뉴스 메시지를 Redis Stream에 발행합니다.
    
    Args:
        page_content: 뉴스 본문
        metadata: 메타데이터 (stock_code, source_url, created_at_utc 등)
        stream_name: 대상 스트림 이름
    
    Returns:
        발행된 메시지 ID
    """
    client = get_redis_client()
    
    # Serialize metadata to JSON (handles datetime, etc.)
    message = {
        b"page_content": page_content.encode("utf-8"),
        b"metadata": json.dumps(metadata, default=str).encode("utf-8"),
        b"published_at": datetime.now(timezone.utc).isoformat().encode("utf-8"),
    }
    
    msg_id = client.xadd(stream_name, message)
    logger.debug(f"✅ [Stream] 발행 완료: {msg_id.decode()} -> {stream_name}")
    return msg_id.decode() if isinstance(msg_id, bytes) else msg_id


def publish_news_batch(
    documents: List[Dict[str, Any]],
    stream_name: str = STREAM_NEWS_RAW
) -> int:
    """
    여러 뉴스를 한 번에 발행합니다.
    
    Args:
        documents: [{"page_content": str, "metadata": dict}, ...]
        stream_name: 대상 스트림 이름
    
    Returns:
        발행된 메시지 수
    """
    client = get_redis_client()
    pipeline = client.pipeline()
    
    for doc in documents:
        message = {
            b"page_content": doc["page_content"].encode("utf-8"),
            b"metadata": json.dumps(doc["metadata"], default=str).encode("utf-8"),
            b"published_at": datetime.now(timezone.utc).isoformat().encode("utf-8"),
        }
        pipeline.xadd(stream_name, message)
    
    results = pipeline.execute()
    published = sum(1 for r in results if r)
    logger.info(f"✅ [Stream] 배치 발행 완료: {published}/{len(documents)}개 -> {stream_name}")
    return published


# ==============================================================================
# Consumer Functions (Archiver, Analyzer)
# ==============================================================================

def ensure_consumer_group(
    stream_name: str = STREAM_NEWS_RAW,
    group_name: str = GROUP_ARCHIVER,
    reset_cursor: bool = False
) -> bool:
    """
    Consumer Group이 없으면 생성합니다.
    
    Args:
        reset_cursor: True이면 그룹이 이미 존재해도 커서를 처음("0")으로 리셋
    
    Returns:
        생성 성공 여부 (이미 존재하면 True)
    """
    client = get_redis_client()
    try:
        # Create group starting from the beginning ('0')
        client.xgroup_create(stream_name, group_name, id="0", mkstream=True)
        logger.info(f"✅ [Stream] Consumer Group 생성: {group_name} @ {stream_name}")
        return True
    except redis.ResponseError as e:
        if "BUSYGROUP" in str(e):
            logger.info(f"ℹ️ [Stream] Consumer Group 이미 존재: {group_name}")
            if reset_cursor:
                # 기존 그룹의 커서를 처음으로 리셋 (모든 메시지 재처리)
                client.xgroup_setid(stream_name, group_name, id="0")
                logger.info(f"🔄 [Stream] Consumer Group 커서 리셋: {group_name} -> 0")
            return True
        raise


def consume_messages(
    group_name: str,
    consumer_name: str,
    handler: Callable[[str, Dict[str, Any]], bool],
    stream_name: str = STREAM_NEWS_RAW,
    batch_size: int = DEFAULT_BATCH_SIZE,
    block_ms: int = DEFAULT_BLOCK_MS,
    max_iterations: Optional[int] = None
) -> int:
    """
    Consumer Group 방식으로 메시지를 소비합니다.
    
    Args:
        group_name: Consumer Group 이름
        consumer_name: 이 Consumer의 고유 이름
        handler: 메시지 처리 함수 (page_content, metadata) -> success
        stream_name: 스트림 이름
        batch_size: 한 번에 읽을 메시지 수
        block_ms: 메시지가 없을 때 대기 시간 (ms)
        max_iterations: 최대 반복 횟수 (None=무한)
    
    Returns:
        처리한 메시지 총 수
    """
    client = get_redis_client()
    ensure_consumer_group(stream_name, group_name)
    
    total_processed = 0
    iteration = 0
    
    logger.info(f"🚀 [Stream] Consumer 시작: {consumer_name} @ {group_name}/{stream_name}")
    
    while True:
        if max_iterations and iteration >= max_iterations:
            break
        iteration += 1
        
        try:
            # Read new messages
            messages = client.xreadgroup(
                group_name,
                consumer_name,
                {stream_name: ">"},
                count=batch_size,
                block=block_ms
            )
            
            if not messages:
                logger.debug(f"[Stream] 새 메시지 없음, 대기 중... (iteration={iteration})")
                continue
            
            for stream, msg_list in messages:
                for msg_id, msg_data in msg_list:
                    try:
                        # Deserialize
                        page_content = msg_data[b"page_content"].decode("utf-8")
                        metadata = json.loads(msg_data[b"metadata"].decode("utf-8"))
                        
                        # Call handler
                        success = handler(page_content, metadata)
                        
                        if success:
                            # ACK
                            client.xack(stream_name, group_name, msg_id)
                            total_processed += 1
                            logger.debug(f"✅ [Stream] 처리 완료: {msg_id.decode()}")
                        else:
                            logger.warning(f"⚠️ [Stream] 핸들러 실패: {msg_id.decode()}")
                            # Message will be retried (not ACKed)
                    
                    except Exception as e:
                        logger.error(f"❌ [Stream] 메시지 처리 오류: {e}")
        
        except KeyboardInterrupt:
            logger.info("🛑 [Stream] Consumer 중단됨 (KeyboardInterrupt)")
            break
        except Exception as e:
            logger.error(f"❌ [Stream] Consumer 오류: {e}")
            import time
            time.sleep(1)  # Backoff on error
    
    logger.info(f"✅ [Stream] Consumer 종료: 총 {total_processed}개 처리")
    return total_processed


# ==============================================================================
# Utility Functions
# ==============================================================================

def get_stream_length(stream_name: str = STREAM_NEWS_RAW) -> int:
    """스트림의 현재 길이 (백로그) 조회"""
    client = get_redis_client()
    return client.xlen(stream_name)


def get_pending_count(
    stream_name: str,
    group_name: str
) -> int:
    """처리 대기 중인 메시지 수 조회"""
    client = get_redis_client()
    try:
        pending = client.xpending(stream_name, group_name)
        return pending.get("pending", 0) if pending else 0
    except Exception:
        return 0


def trim_stream(
    stream_name: str = STREAM_NEWS_RAW,
    maxlen: int = 100000
) -> int:
    """
    스트림을 지정된 길이로 트리밍합니다.
    
    Returns:
        삭제된 메시지 수
    """
    client = get_redis_client()
    before = client.xlen(stream_name)
    client.xtrim(stream_name, maxlen=maxlen, approximate=True)
    after = client.xlen(stream_name)
    trimmed = before - after
    if trimmed > 0:
        logger.info(f"🧹 [Stream] 트리밍 완료: {trimmed}개 삭제 ({stream_name})")
    return trimmed


# ==============================================================================
# Module Init
# ==============================================================================

def init_streams():
    """모든 스트림과 Consumer Group을 초기화합니다."""
    ensure_consumer_group(STREAM_NEWS_RAW, GROUP_ARCHIVER)
    ensure_consumer_group(STREAM_NEWS_RAW, GROUP_ANALYZER)
    logger.info("✅ [Stream] 모든 스트림 초기화 완료")


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.DEBUG)
    init_streams()
    print(f"Stream Length: {get_stream_length()}")
