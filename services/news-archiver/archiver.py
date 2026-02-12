#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
services/news-archiver/archiver.py
-----------------------------------
뉴스 아카이빙 전용 서비스 (Consumer A).
Redis Streams에서 뉴스를 소비하여 ChromaDB에 저장합니다.
LLM 분석 없이 빠르게 처리합니다.
"""

import os
import sys
import logging
from typing import Dict, Any

from dotenv import load_dotenv

# 프로젝트 루트 설정
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from shared.messaging.stream_client import (
    consume_messages, 
    get_stream_length, 
    get_pending_count,
    STREAM_NEWS_RAW, 
    GROUP_ARCHIVER
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

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "rag_stock_data") # Maintain env var for compat or rename? Let's keep it but comment.

# Embedding Model
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "jhgan/ko-sroberta-multitask")

# ==============================================================================
# ChromaDB & Embedding Initialization
# ==============================================================================

_vectorstore = None
_text_splitter = None
_qdrant_client = None


def get_vectorstore():
    """Qdrant Vectorstore 싱글톤 반환"""
    global _vectorstore, _text_splitter, _qdrant_client

    if _vectorstore is None:
        from langchain_qdrant import QdrantVectorStore
        from qdrant_client import QdrantClient
        from langchain_openai import OpenAIEmbeddings
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        # Qdrant Connection (Port 6333)
        QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
        QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

        logger.info(f"🔌 Qdrant 연결 중... ({QDRANT_HOST}:{QDRANT_PORT})")

        # Embeddings (vLLM 직접 호출 — OpenAI-compatible API)
        vllm_embed_url = os.getenv("VLLM_EMBED_URL", "http://localhost:8002/v1")
        embeddings = OpenAIEmbeddings(
            base_url=vllm_embed_url,
            api_key="EMPTY",  # vLLM은 인증 불필요
            model="nlpai-lab/KURE-v1",
        )

        from qdrant_client.http import models

        # Qdrant Client
        _qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

        # Ensure Collection Exists (+ source_url 인덱스)
        if not _qdrant_client.collection_exists(COLLECTION_NAME):
            logger.info(f"🆕 Qdrant Collection 생성: {COLLECTION_NAME} (size=1024)")
            _qdrant_client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(
                    size=1024,  # kure-v1 dimension
                    distance=models.Distance.COSINE
                )
            )

        # source_url 페이로드 인덱스 생성 (중복 체크 성능)
        try:
            _qdrant_client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name="metadata.source_url",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            logger.info("✅ source_url 페이로드 인덱스 생성 완료")
        except Exception:
            pass  # 이미 존재하면 무시

        # Vectorstore
        _vectorstore = QdrantVectorStore(
            client=_qdrant_client,
            collection_name=COLLECTION_NAME,
            embedding=embeddings,
        )

        # Text Splitter
        _text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50
        )

        logger.info(f"✅ Qdrant 연결 완료 (collection: {COLLECTION_NAME})")

    return _vectorstore, _text_splitter


# ==============================================================================
# Message Handler
# ==============================================================================

def _check_duplicate(source_url: str) -> bool:
    """source_url 기반 Qdrant 중복 체크"""
    if not source_url or not _qdrant_client:
        return False
    try:
        from qdrant_client.http import models
        result = _qdrant_client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(
                    key="metadata.source_url",
                    match=models.MatchValue(value=source_url),
                )]
            ),
            limit=1,
            with_payload=False,
            with_vectors=False,
        )
        return len(result[0]) > 0
    except Exception as e:
        logger.warning(f"⚠️ [Archive] 중복 체크 실패 (저장 진행): {e}")
        return False


def handle_archive_message(page_content: str, metadata: Dict[str, Any]) -> bool:
    """
    뉴스 메시지를 Qdrant에 저장합니다. (source_url 중복 체크 포함)

    Args:
        page_content: 뉴스 본문
        metadata: 메타데이터

    Returns:
        성공 여부
    """
    try:
        from langchain_core.documents import Document

        vectorstore, text_splitter = get_vectorstore()

        # source_url 중복 체크
        source_url = metadata.get("source_url", "")
        if source_url and _check_duplicate(source_url):
            logger.debug(f"ℹ️ [Archive] 중복 뉴스 스킵: {metadata.get('stock_name', '?')} - {source_url[:60]}")
            return True  # ACK (스트림에서 제거)

        # Create Document
        doc = Document(page_content=page_content, metadata=metadata)

        # Split and embed
        chunks = text_splitter.split_documents([doc])

        # Add to vectorstore
        vectorstore.add_documents(chunks)

        stock_info = f"{metadata.get('stock_name', 'General')} ({metadata.get('stock_code', 'N/A')})"
        logger.debug(f"✅ [Archive] 저장 완료: {stock_info}")

        return True

    except Exception as e:
        logger.error(f"❌ [Archive] 저장 실패: {e}")
        return False


# ==============================================================================
# Main Archiver
# ==============================================================================

def run_archiver_daemon(consumer_name: str = "archiver_1"):
    """
    Archiver 데몬 실행 (무한 루프)
    Redis Stream에서 메시지를 소비하여 ChromaDB에 저장합니다.
    """
    logger.info("=" * 60)
    logger.info("🚀 [Archiver Daemon] 시작")
    logger.info(f"   Stream: {STREAM_NEWS_RAW}")
    logger.info(f"   Group: {GROUP_ARCHIVER}")
    logger.info(f"   Consumer: {consumer_name}")
    logger.info(f"   Qdrant: {QDRANT_HOST}:{QDRANT_PORT}")
    logger.info("=" * 60)
    
    # Pre-initialize VectorDB connection
    try:
        get_vectorstore()
    except Exception as e:
        logger.error(f"❌ Qdrant 초기화 실패: {e}")
        return
    
    # Start consuming
    processed = consume_messages(
        group_name=GROUP_ARCHIVER,
        consumer_name=consumer_name,
        handler=handle_archive_message,
        stream_name=STREAM_NEWS_RAW,
        batch_size=20,  # Archiver is fast, process more at once
        block_ms=2000,
        max_iterations=None  # Infinite
    )
    
    logger.info(f"✅ [Archiver] 종료 - 총 {processed}개 처리")


def run_archiver_once(max_messages: int = 1000):
    """
    Archiver 1회 실행 (Airflow Task용)
    """
    logger.info(f"🚀 [Archiver] 1회 실행 (max: {max_messages})")
    
    stream_len = get_stream_length(STREAM_NEWS_RAW)
    pending = get_pending_count(STREAM_NEWS_RAW, GROUP_ARCHIVER)
    logger.info(f"📊 Stream 상태: 길이={stream_len}, 대기={pending}")
    
    try:
        get_vectorstore()
    except Exception as e:
        logger.error(f"❌ ChromaDB 초기화 실패: {e}")
        return
    
    # Calculate iterations (batch_size=20)
    iterations = (max_messages // 20) + 1
    
    processed = consume_messages(
        group_name=GROUP_ARCHIVER,
        consumer_name="archiver_batch",
        handler=handle_archive_message,
        stream_name=STREAM_NEWS_RAW,
        batch_size=20,
        block_ms=1000,
        max_iterations=iterations
    )
    
    logger.info(f"✅ [Archiver] 완료 - {processed}개 처리")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true", help="Run as daemon (infinite loop)")
    parser.add_argument("--name", type=str, default="archiver_1", help="Consumer name")
    parser.add_argument("--max", type=int, default=1000, help="Max messages for one-shot mode")
    args = parser.parse_args()
    
    if args.daemon:
        run_archiver_daemon(args.name)
    else:
        run_archiver_once(args.max)
