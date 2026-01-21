#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
services/news-analyzer/analyzer.py
-----------------------------------
뉴스 분석 전용 서비스 (Consumer B).
Redis Streams에서 뉴스를 소비하여 LLM 감성분석 후 MariaDB에 저장합니다.
Archiver와 독립적으로 동작하며, 느려도 됩니다.
"""

import os
import sys
import logging
import time
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from dotenv import load_dotenv

# 프로젝트 루트 설정
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from shared.messaging.stream_client import (
    consume_messages,
    get_stream_length,
    get_pending_count,
    STREAM_NEWS_RAW,
    GROUP_ANALYZER
)

# ==============================================================================
# Logging
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s',
)
logger = logging.getLogger(__name__)

# ==============================================================================
# Configuration
# ==============================================================================
load_dotenv()

# LLM Model
LOCAL_MODEL_FAST = os.getenv("LOCAL_MODEL_FAST", "gemma3:27b")

# Batch Settings (for LLM)
ANALYSIS_BATCH_SIZE = int(os.getenv("ANALYZER_BATCH_SIZE", "5"))

# ==============================================================================
# JennieBrain Initialization
# ==============================================================================

_jennie_brain = None


def get_jennie_brain():
    """JennieBrain 싱글톤 반환"""
    global _jennie_brain
    
    if _jennie_brain is None:
        from shared.llm import JennieBrain
        
        logger.info("🧠 JennieBrain 초기화 중...")
        _jennie_brain = JennieBrain(
            project_id=os.getenv("GCP_PROJECT_ID", "local"),
            gemini_api_key_secret=os.getenv("SECRET_ID_GEMINI_API_KEY")
        )
        logger.info("✅ JennieBrain 초기화 완료")
    
    return _jennie_brain


# ==============================================================================
# DB Connection
# ==============================================================================

def get_db_session():
    """SQLAlchemy 세션 반환"""
    from shared.db.connection import session_scope
    return session_scope


# ==============================================================================
# Analysis Handler
# ==============================================================================

# Buffer for batch processing
_message_buffer = []


def _save_sentiment_to_db(
    stock_code: str,
    stock_name: str,
    news_title: str,
    score: float,
    reason: str,
    source_url: str,
    published_at: Optional[int]
) -> bool:
    """감성 점수를 DB에 저장"""
    try:
        from shared.database.market import save_news_sentiment
        from shared.db.connection import session_scope
        
        # Convert timestamp to datetime
        pub_datetime = None
        if published_at:
            pub_datetime = datetime.fromtimestamp(published_at, tz=timezone.utc)
        
        with session_scope() as session:
            save_news_sentiment(
                session=session,
                stock_code=stock_code,
                title=news_title,
                score=score,
                reason=reason,
                url=source_url,
                published_at=pub_datetime
            )
        
        return True
    except Exception as e:
        logger.error(f"❌ DB 저장 실패: {e}")
        return False


def _process_batch_analysis(batch: list) -> int:
    """배치 분석 수행 및 저장"""
    if not batch:
        return 0
    
    brain = get_jennie_brain()
    
    # Prepare items for LLM
    batch_items = []
    for idx, item in enumerate(batch):
        content_lines = item["page_content"].split('\n')
        news_title = content_lines[0].replace("뉴스 제목: ", "") if content_lines else "제목 없음"
        
        batch_items.append({
            "id": idx,
            "title": news_title,
            "summary": news_title
        })
    
    # Call LLM
    try:
        results = brain.analyze_news_unified(batch_items)
    except Exception as e:
        logger.error(f"❌ LLM 분석 실패: {e}")
        return 0
    
    # Save results
    saved = 0
    for result in results:
        idx = result.get("id")
        if idx is None or idx >= len(batch):
            continue
        
        item = batch[idx]
        metadata = item["metadata"]
        
        stock_code = metadata.get("stock_code")
        if not stock_code:
            continue  # Skip non-stock news
        
        sentiment = result.get("sentiment", {})
        score = sentiment.get("score", 50)
        reason = sentiment.get("reason", "N/A")
        
        content_lines = item["page_content"].split('\n')
        news_title = content_lines[0].replace("뉴스 제목: ", "") if content_lines else "제목 없음"
        
        success = _save_sentiment_to_db(
            stock_code=stock_code,
            stock_name=metadata.get("stock_name", ""),
            news_title=news_title,
            score=score,
            reason=reason,
            source_url=metadata.get("source_url", ""),
            published_at=metadata.get("created_at_utc")
        )
        
        if success:
            saved += 1
    
    logger.info(f"✅ [Analyzer] 배치 분석 완료: {saved}/{len(batch)}건 저장")
    return saved


def handle_analyze_message(page_content: str, metadata: Dict[str, Any]) -> bool:
    """
    뉴스 메시지를 분석용 버퍼에 추가합니다.
    버퍼가 가득 차면 배치 분석을 수행합니다.
    
    Note: 이 함수는 consume_messages의 핸들러로 사용됩니다.
          단, 버퍼링 방식이므로 즉시 ACK하지 않습니다.
          간단하게 매 메시지마다 분석합니다 (배치는 추후 최적화).
    """
    # Skip non-stock news (general news)
    stock_code = metadata.get("stock_code")
    if not stock_code:
        logger.info("[Analyzer] 종목 코드 없음 (일반 뉴스) → Skip")
        return True  # ACK but don't analyze
    
    brain = get_jennie_brain()
    
    # Prepare single item
    content_lines = page_content.split('\n')
    news_title = content_lines[0].replace("뉴스 제목: ", "") if content_lines else "제목 없음"
    
    batch_item = {
        "id": 0,
        "title": news_title,
        "summary": news_title
    }
    
    # Call LLM
    try:
        results = brain.analyze_news_unified([batch_item])
        if not results:
            logger.warning(f"⚠️ [Analyzer] LLM 결과 없음: {news_title[:30]}...")
            return True  # ACK anyway
        
        sentiment = results[0].get("sentiment", {})
        score = sentiment.get("score", 50)
        reason = sentiment.get("reason", "N/A")
        
        success = _save_sentiment_to_db(
            stock_code=stock_code,
            stock_name=metadata.get("stock_name", ""),
            news_title=news_title,
            score=score,
            reason=reason,
            source_url=metadata.get("source_url", ""),
            published_at=metadata.get("created_at_utc")
        )
        
        if success:
            logger.info(f"✅ [Analyzer] {metadata.get('stock_name', stock_code)}: {score}점")
        
        return True  # ACK
    
    except Exception as e:
        logger.error(f"❌ [Analyzer] 분석 오류: {e}")
        return False  # Don't ACK, will retry


# ==============================================================================
# Main Analyzer
# ==============================================================================

def run_analyzer_daemon(consumer_name: str = "analyzer_1"):
    """
    Analyzer 데몬 실행 (무한 루프)
    Redis Stream에서 메시지를 소비하여 LLM 분석 후 MariaDB에 저장합니다.
    """
    logger.info("=" * 60)
    logger.info("🚀 [Analyzer Daemon] 시작")
    logger.info(f"   Stream: {STREAM_NEWS_RAW}")
    logger.info(f"   Group: {GROUP_ANALYZER}")
    logger.info(f"   Consumer: {consumer_name}")
    logger.info(f"   LLM Model: {LOCAL_MODEL_FAST}")
    logger.info("=" * 60)
    
    # Pre-initialize DB connection
    try:
        from shared.db.connection import ensure_engine_initialized
        ensure_engine_initialized()
        logger.info("✅ DB 연결 초기화 완료")
    except Exception as e:
        logger.error(f"❌ DB 초기화 실패: {e}")
        return
    
    # Pre-initialize JennieBrain
    try:
        get_jennie_brain()
    except Exception as e:
        logger.error(f"❌ JennieBrain 초기화 실패: {e}")
        return
    
    # Start consuming (slower than Archiver)
    processed = consume_messages(
        group_name=GROUP_ANALYZER,
        consumer_name=consumer_name,
        handler=handle_analyze_message,
        stream_name=STREAM_NEWS_RAW,
        batch_size=1,  # One at a time for LLM (sequential)
        block_ms=5000,  # Wait longer between messages
        max_iterations=None  # Infinite
    )
    
    logger.info(f"✅ [Analyzer] 종료 - 총 {processed}개 처리")


def run_analyzer_once(max_messages: int = 100):
    """
    Analyzer 1회 실행 (Airflow Task용)
    """
    logger.info(f"🚀 [Analyzer] 1회 실행 (max: {max_messages})")
    
    stream_len = get_stream_length(STREAM_NEWS_RAW)
    pending = get_pending_count(STREAM_NEWS_RAW, GROUP_ANALYZER)
    logger.info(f"📊 Stream 상태: 길이={stream_len}, 대기={pending}")
    
    # Pre-initialize DB connection
    try:
        from shared.db.connection import ensure_engine_initialized
        ensure_engine_initialized()
        logger.info("✅ DB 연결 초기화 완료")
    except Exception as e:
        logger.error(f"❌ DB 초기화 실패: {e}")
        return
    
    try:
        get_jennie_brain()
    except Exception as e:
        logger.error(f"❌ JennieBrain 초기화 실패: {e}")
        return
    
    processed = consume_messages(
        group_name=GROUP_ANALYZER,
        consumer_name="analyzer_batch",
        handler=handle_analyze_message,
        stream_name=STREAM_NEWS_RAW,
        batch_size=1,
        block_ms=2000,
        max_iterations=max_messages
    )
    
    logger.info(f"✅ [Analyzer] 완료 - {processed}개 처리")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true", help="Run as daemon (infinite loop)")
    parser.add_argument("--name", type=str, default="analyzer_1", help="Consumer name")
    parser.add_argument("--max", type=int, default=100, help="Max messages for one-shot mode")
    args = parser.parse_args()
    
    if args.daemon:
        run_analyzer_daemon(args.name)
    else:
        run_analyzer_once(args.max)
