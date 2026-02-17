
import sys
import os
import logging
from sqlalchemy import text
from datetime import datetime, timedelta

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.db.connection import session_scope, ensure_engine_initialized
from shared.db.models import WatchList, StockNewsSentiment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def audit_pipeline():
    ensure_engine_initialized()
    print("Starting News Pipeline Audit...")

    with session_scope() as session:
        # 1. News Coverage (Last 24h)
        try:
            query = text("""
                SELECT COUNT(DISTINCT STOCK_CODE)
                FROM STOCK_NEWS_SENTIMENT
                WHERE PUBLISHED_AT >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
            """)
            stocks_with_news = session.execute(query).scalar() or 0

            wl_query = text("SELECT COUNT(*) FROM WATCHLIST WHERE IS_TRADABLE=1")
            watchlist_count = session.execute(wl_query).scalar() or 0

            coverage = (stocks_with_news / watchlist_count * 100) if watchlist_count > 0 else 0

            print(f"\n[News Coverage 24h]")
            print(f"- Watchlist Stocks: {watchlist_count}")
            print(f"- Stocks with News: {stocks_with_news}")
            print(f"- Coverage: {coverage:.1f}%")

            if coverage < 10:
                print("WARNING: Very low news coverage. Crawler might be failing or idle.")

        except Exception as e:
            print(f"Error checking coverage: {e}")

        # 2. Average News Score (Last 7 Days) for Smart Fallback
        try:
            avg_query = text("""
                SELECT AVG(SENTIMENT_SCORE)
                FROM STOCK_NEWS_SENTIMENT
                WHERE PUBLISHED_AT >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                AND SENTIMENT_SCORE > 0
            """)
            avg_score = session.execute(avg_query).scalar()

            print(f"\n[Smart Fallback Verification]")
            if avg_score:
                print(f"- Avg Sentiment (7d): {avg_score:.2f}")
                print(f"- 80% Target: {avg_score * 0.8:.2f} (This will be used as Fallback)")
            else:
                print("- Avg Sentiment: None (No data in last 7 days)")
                print("- Fallback will use Conservative Default (2.0 + 4.0 = 6.0)")

        except Exception as e:
            print(f"Error checking average score: {e}")

    print("\nAudit Complete.")

if __name__ == "__main__":
    audit_pipeline()
