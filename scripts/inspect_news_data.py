
import sys
import os
import logging
from sqlalchemy import text

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.db.connection import session_scope, ensure_engine_initialized
from shared.db.models import StockNewsSentiment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def inspect_news_data():
    ensure_engine_initialized()
    
    with session_scope(readonly=True) as session:
        # 1. Describe Table
        logger.info("--- DESCRIBE STOCK_NEWS_SENTIMENT ---")
        try:
            result = session.execute(text("DESCRIBE STOCK_NEWS_SENTIMENT"))
            for row in result:
                logger.info(row)
        except Exception as e:
            logger.error(f"Failed to describe: {e}")

        # 2. Select last 5 rows (raw) to see data
        logger.info("\n--- SELECT * ORDER BY ID DESC LIMIT 5 ---")
        try:
            # Use raw select * to avoid ORM column mapping issues
            result = session.execute(text("SELECT * FROM STOCK_NEWS_SENTIMENT ORDER BY ID DESC LIMIT 5"))
            keys = result.keys()
            logger.info(f"Columns: {keys}")
            for row in result:
                logger.info(row)
        except Exception as e:
            logger.error(f"Failed to select: {e}")

if __name__ == "__main__":
    inspect_news_data()
