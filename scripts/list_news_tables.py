
import sys
import os
import logging
from sqlalchemy import text

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.db.connection import session_scope, ensure_engine_initialized

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def list_news_tables():
    ensure_engine_initialized()
    
    with session_scope(readonly=True) as session:
        # Use raw SQL to list tables
        try:
            result = session.execute(text("SHOW TABLES LIKE '%NEWS%';"))
            tables = result.fetchall()
            logger.info("Found Tables matching '%NEWS%':")
            for t in tables:
                logger.info(t)
        except Exception as e:
            logger.error(f"Failed to list tables: {e}")

if __name__ == "__main__":
    list_news_tables()
