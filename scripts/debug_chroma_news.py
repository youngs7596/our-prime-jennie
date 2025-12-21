
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import chromadb
from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.gemini import ensure_gemini_api_key

# Setup Logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Target Stocks
TARGET_STOCKS = [
    {"code": "005930", "name": "삼성전자"},
    {"code": "000660", "name": "SK하이닉스"},
    {"code": "111770", "name": "영원무역"},
    {"code": "307950", "name": "현대오토에버"},
    {"code": "016360", "name": "삼성증권"},
    {"code": "029780", "name": "삼성카드"},
    {"code": "001720", "name": "신영증권"},
]

def main():
    load_dotenv(override=True)
    
    # 1. Connect to Chroma
    logger.info("Connecting to ChromaDB...")
    try:
        api_key = ensure_gemini_api_key()
        embeddings = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-001", 
            google_api_key=api_key
        )
        
        CHROMA_SERVER_HOST = os.getenv("CHROMA_SERVER_HOST", "10.178.0.2")
        CHROMA_SERVER_PORT = 8000
        
        chroma_client = chromadb.HttpClient(
            host=CHROMA_SERVER_HOST, 
            port=CHROMA_SERVER_PORT
        )
        vectorstore = Chroma(
            client=chroma_client, 
            collection_name="rag_stock_data", 
            embedding_function=embeddings
        )
        logger.info("✅ Connected to ChromaDB")
    except Exception as e:
        logger.error(f"❌ Failed to connect: {e}")
        return

    # 2. Check Stocks
    try:
        count = vectorstore._collection.count()
        logger.info(f"Total documents in collection: {count}")
        
        # [Debug] Peek at what these documents actually are
        if count > 0:
            peek_results = vectorstore._collection.peek(limit=10)
            logger.info("\n--- [PEEK] First 10 Documents in Collection ---")
            for i in range(len(peek_results['ids'])):
                meta = peek_results['metadatas'][i]
                content = peek_results['documents'][i]
                created_ts = meta.get('created_at_utc', 0)
                created_str = datetime.fromtimestamp(created_ts).strftime('%Y-%m-%d %H:%M:%S') if created_ts else "N/A"
                logger.info(f"[{i}] {created_str} | Source: {meta.get('source', 'N/A')} | Stock: {meta.get('stock_name', 'N/A')} | Content: {content[:50]}...")
            logger.info("-----------------------------------------------\n")
            
    except Exception as e:
        logger.error(f"Failed to get count/peek: {e}")

    recency_timestamp = int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp())
    logger.info(f"Target Recency Timestamp: {recency_timestamp} ({datetime.fromtimestamp(recency_timestamp)})")

    for stock in TARGET_STOCKS:
        code = stock['code']
        name = stock['name']
        logger.info(f"\n======================================")
        logger.info(f"Checking {name} ({code})...")
        
        # Test 1: Exact Query used in scout.py
        try:
            docs = vectorstore.similarity_search(
                query=f"{name} 실적 수주 호재",
                k=5,
                filter={
                    "$and": [
                        {"stock_code": code},
                        {"created_at_utc": {"$gte": recency_timestamp}}
                    ]
                }
            )
            logger.info(f"▶ Scout Query Results: {len(docs)}")
            for i, d in enumerate(docs):
                clean_content = d.page_content.replace('\n', ' ')[:100]
                created_ts = d.metadata.get('created_at_utc')
                created_str = datetime.fromtimestamp(created_ts).strftime('%Y-%m-%d %H:%M:%S') if created_ts else "N/A"
                logger.info(f"   [{i+1}] {created_str} | {clean_content}...")
        except Exception as e:
            logger.error(f"   Scout Query Failed: {e}")

        # Test 2: Check for ANY news for this stock (ignore date)
        try:
            all_docs = vectorstore.similarity_search(
                query=f"{name}",
                k=3,
                filter={"stock_code": code}
            )
            logger.info(f"▶ Broad Query (No Date Filter): {len(all_docs)}")
            if all_docs:
                first_doc = all_docs[0]
                created_ts = first_doc.metadata.get('created_at_utc')
                created_str = datetime.fromtimestamp(created_ts).strftime('%Y-%m-%d %H:%M:%S') if created_ts else "N/A"
                logger.info(f"   Latest doc: {created_str}")
            else:
                logger.warning(f"   ⚠️ No documents found even without date filter!")

        except Exception as e:
            logger.error(f"   Broad Query Failed: {e}")

if __name__ == "__main__":
    main()
