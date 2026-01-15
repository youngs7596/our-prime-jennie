
import sys
import os
import logging
from datetime import datetime, timezone

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock environment for shared/db/connection used in imports if needed, but here we use chromadb directly
import chromadb

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def inspect_chroma():
    try:
        # ChromaDB settings from docker-compose/crawler.py
        # Port 8000 mapped to host
        client = chromadb.HttpClient(host='localhost', port=8000)
        collection = client.get_collection("rag_stock_data")
        
        count = collection.count()
        logger.info(f"📚 Total Documents in Chroma: {count}")
        
        # Peek last added
        # Chroma doesn't strictly support time-based sort in peek, but we can query by metadata
        # Query for created_at_utc > 7 days ago
        
        now_ts = int(datetime.now(timezone.utc).timestamp())
        week_ago_ts = now_ts - (7 * 86400)
        
        results = collection.get(
            where={"created_at_utc": {"$gt": week_ago_ts}},
            limit=5,
            include=["metadatas"]
        )
        
        found_recent = len(results['ids'])
        logger.info(f"🔎 Recent Documents (> 7 days ago): {found_recent} found in sample query")
        
        if found_recent > 0:
            for meta in results['metadatas']:
                logger.info(f"SAMPLE META: {meta}")
        else:
            logger.warning("⚠️ No recent documents found in ChromaDB either.")

    except Exception as e:
        logger.error(f"Failed to inspect Chroma: {e}")

if __name__ == "__main__":
    inspect_chroma()
