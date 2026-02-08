#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
services/news-collector/collector.py
--------------------------------------
뉴스 수집 전용 서비스 (Producer).
Redis Streams에 뉴스를 발행하며, 분석은 수행하지 않습니다.

v2.0: shared/crawlers/naver.py 공통 모듈 사용
"""

import os
import sys
import time
import logging
import calendar
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import feedparser
from dotenv import load_dotenv

# 프로젝트 루트 설정
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from shared.messaging.stream_client import (
    publish_news_batch, get_stream_length, trim_stream,
    STREAM_NEWS_RAW, NewsDeduplicator, compute_news_hash,
)
from shared.crawlers.naver import (
    crawl_stock_news,
    get_kospi_top_stocks,
    clear_news_hash_cache,
    NOISE_KEYWORDS,
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

# Universe
UNIVERSE_SIZE = int(os.getenv("COLLECTOR_UNIVERSE_SIZE", "200"))

# Naver Finance
NAVER_NEWS_MAX_PAGES = int(os.getenv("NAVER_NEWS_MAX_PAGES", "2"))
NAVER_NEWS_REQUEST_DELAY = float(os.getenv("NAVER_NEWS_REQUEST_DELAY", "0.3"))

# General RSS
GENERAL_RSS_FEEDS = [
    {"source_name": "Hankyung (Finance)", "url": "https://www.hankyung.com/feed/finance"},
    {"source_name": "Hankyung (Economy)", "url": "https://www.hankyung.com/feed/economy"},
    {"source_name": "Maeil Business (Economy)", "url": "https://www.mk.co.kr/rss/50000001/"},
    {"source_name": "Maeil Business (Stock)", "url": "https://www.mk.co.kr/rss/50100001/"},
]

# Redis 기반 영속 중복 체크 (컨테이너 재시작에도 유지)
_deduplicator = NewsDeduplicator()

# ==============================================================================
# Helper Functions
# ==============================================================================

def _compute_hash(title: str) -> str:
    import hashlib
    import re
    normalized = re.sub(r'[^\w]', '', title.lower())
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


def _is_noise_title(title: str) -> bool:
    for noise in NOISE_KEYWORDS:
        if noise in title:
            return True
    return False


# ==============================================================================
# RSS News Crawling
# ==============================================================================

def crawl_general_rss_news() -> list:
    """일반 경제/금융 RSS 뉴스 수집"""
    logger.info("📰 일반 경제 뉴스 RSS 수집 중...")
    documents = []

    for feed_info in GENERAL_RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_info["url"])
            for entry in feed.entries[:20]:
                title = entry.get('title', '').strip()
                link = entry.get('link', '')

                if not title or not link:
                    continue

                # Filter
                if _is_noise_title(title):
                    continue

                news_hash = _compute_hash(title)
                if not _deduplicator.check_and_mark(news_hash):
                    continue
                
                # Timestamp
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_timestamp = int(calendar.timegm(entry.published_parsed))
                else:
                    pub_timestamp = int(datetime.now(timezone.utc).timestamp())
                
                # Phase 1C: 메타데이터 강화 - 출처/날짜를 page_content에 포함
                pub_date_str = datetime.fromtimestamp(pub_timestamp, tz=timezone.utc).strftime('%Y-%m-%d')
                documents.append({
                    "page_content": f"[시장뉴스] {title} | 출처: {feed_info['source_name']} | 날짜: {pub_date_str}",
                    "metadata": {
                        "stock_code": None,
                        "stock_name": None,
                        "source": feed_info["source_name"],
                        "source_url": link,
                        "created_at_utc": pub_timestamp,
                    }
                })
        except Exception as e:
            logger.warning(f"RSS 수집 오류 ({feed_info['source_name']}): {e}")
    
    logger.info(f"✅ 일반 뉴스 {len(documents)}개 수집 완료")
    return documents


# ==============================================================================
# Main Collector Job
# ==============================================================================

def run_collector_job():
    """
    수집 작업 실행 (1회)
    - KOSPI 200 종목 뉴스 수집
    - 일반 경제 뉴스 수집
    - Redis Stream에 발행
    """
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("🚀 [Collector] 뉴스 수집 시작")
    logger.info("=" * 60)
    
    all_documents = []
    
    # 1. General News
    general_docs = crawl_general_rss_news()
    all_documents.extend(general_docs)
    
    # 2. Stock-specific News (Parallel) - shared 모듈 사용
    logger.info(f"📊 KOSPI 상위 {UNIVERSE_SIZE}개 종목 로드 중...")
    universe = get_kospi_top_stocks(UNIVERSE_SIZE)
    
    if universe:
        logger.info(f"✅ {len(universe)}개 종목 로드 완료")
        logger.info(f"📊 {len(universe)}개 종목 뉴스 수집 시작...")
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(
                    crawl_stock_news, 
                    s["code"], 
                    s["name"], 
                    max_pages=NAVER_NEWS_MAX_PAGES,
                    request_delay=NAVER_NEWS_REQUEST_DELAY
                ): s
                for s in universe
            }
            for future in as_completed(futures):
                stock = futures[future]
                try:
                    docs = future.result()
                    if docs:
                        all_documents.extend(docs)
                except Exception as e:
                    logger.warning(f"종목 수집 실패 ({stock['name']}): {e}")
    
    # 3. Redis 영속 중복 체크 (naver.py 인메모리 dedup 보완 — 컨테이너 재시작 대응)
    if all_documents:
        doc_hashes = [compute_news_hash(doc["page_content"]) for doc in all_documents]
        new_hashes = _deduplicator.filter_new_batch(doc_hashes)

        before_count = len(all_documents)
        all_documents = [
            doc for doc, h in zip(all_documents, doc_hashes)
            if h in new_hashes
        ]
        dedup_removed = before_count - len(all_documents)
        if dedup_removed > 0:
            logger.info(f"🔄 [Dedup] 영속 중복 제거: {dedup_removed}개 ({before_count} → {len(all_documents)})")

    # 4. Publish to Redis Stream
    if all_documents:
        logger.info(f"📤 Redis Stream에 {len(all_documents)}개 뉴스 발행 중...")
        published = publish_news_batch(all_documents, STREAM_NEWS_RAW)
        logger.info(f"✅ {published}개 발행 완료")
        
        # Trim old messages (keep last 100k)
        trim_stream(STREAM_NEWS_RAW, maxlen=100000)
    else:
        logger.info("ℹ️ 수집된 뉴스 없음")
    
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info(f"✅ [Collector] 완료 - 총 {len(all_documents)}개 수집, {elapsed:.1f}초 소요")
    logger.info(f"📊 Stream 길이: {get_stream_length(STREAM_NEWS_RAW)}")
    logger.info("=" * 60)


def run_collector_daemon(interval_seconds: int = 600):
    """
    수집 데몬 (무한 루프)
    - 지정된 간격으로 뉴스 수집
    """
    logger.info(f"🔄 [Collector Daemon] 시작 (interval={interval_seconds}s)")
    
    while True:
        try:
            run_collector_job()
        except Exception as e:
            logger.error(f"❌ [Collector] 작업 실패: {e}", exc_info=True)
        
        logger.info(f"💤 {interval_seconds}초 대기...")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true", help="Run as daemon (infinite loop)")
    parser.add_argument("--interval", type=int, default=600, help="Interval seconds for daemon mode")
    args = parser.parse_args()
    
    if args.daemon:
        run_collector_daemon(args.interval)
    else:
        run_collector_job()
