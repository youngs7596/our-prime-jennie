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

CHROMA_SERVER_HOST = os.getenv("CHROMA_SERVER_HOST", "10.178.0.2")
CHROMA_SERVER_PORT = int(os.getenv("CHROMA_SERVER_PORT", "8000"))
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "rag_stock_data")

# Embedding Model
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "jhgan/ko-sroberta-multitask")

# ==============================================================================
# ChromaDB & Embedding Initialization
# ==============================================================================

_vectorstore = None
_text_splitter = None


def get_vectorstore():
    """ChromaDB Vectorstore 싱글톤 반환"""
    global _vectorstore, _text_splitter
    
    if _vectorstore is None:
        from langchain_qdrant import QdrantVectorStore
        from qdrant_client import QdrantClient
        from langchain_ollama import OllamaEmbeddings
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        
        # Qdrant Connection (Port 6333)
        QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
        QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
        
        logger.info(f"🔌 Qdrant 연결 중... ({QDRANT_HOST}:{QDRANT_PORT})")
        
        # Embeddings (Ollama via Host/Gateway)
        ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        embeddings = OllamaEmbeddings(
            model="daynice/kure-v1",
            base_url=ollama_base_url
        )
        
        from qdrant_client.http import models
        
        # Qdrant Client
        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        
        # Ensure Collection Exists
        if not client.collection_exists(COLLECTION_NAME):
            logger.info(f"🆕 Qdrant Collection 생성: {COLLECTION_NAME} (size=1024)")
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(
                    size=1024,  # kure-v1 dimension
                    distance=models.Distance.COSINE
                )
            )
        
        # Vectorstore
        _vectorstore = QdrantVectorStore(
            client=client,
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

def handle_archive_message(page_content: str, metadata: Dict[str, Any]) -> bool:
    """
    뉴스 메시지를 ChromaDB에 저장합니다.
    
    Args:
        page_content: 뉴스 본문
        metadata: 메타데이터
    
    Returns:
        성공 여부
    """
    try:
        from langchain_core.documents import Document
        
        vectorstore, text_splitter = get_vectorstore()
        
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
    logger.info(f"   ChromaDB: {CHROMA_SERVER_HOST}:{CHROMA_SERVER_PORT}")
    logger.info("=" * 60)
    
    # Pre-initialize ChromaDB connection
    try:
        get_vectorstore()
    except Exception as e:
        logger.error(f"❌ ChromaDB 초기화 실패: {e}")
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
