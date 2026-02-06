
import os
import sys
import logging
import time
from datetime import datetime, timedelta
import random

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import shared.database as database
from shared.db.connection import get_session
from shared.news_classifier import get_classifier
from shared.crawlers.naver import crawl_stock_news
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Constants
TARGET_START_DATE = datetime(2022, 1, 1)

def get_top_stocks(limit=100):
    """Get top KOSPI stocks by market cap from STOCK_MASTER"""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    try:
        query = """
            SELECT STOCK_CODE, STOCK_NAME 
            FROM STOCK_MASTER 
            WHERE IS_KOSPI = 1 
            AND MARKET_CAP IS NOT NULL
            ORDER BY MARKET_CAP DESC 
            LIMIT %s
        """
        cursor.execute(query, (limit,))
        return cursor.fetchall()
    except Exception as e:
        logger.error(f"Error fetching top stocks: {e}")
        return []
    finally:
        conn.close()

def backfill_stock_news(stock_code, stock_name, classifier, session):
    """Backfill news for a single stock using shared crawler"""
    logger.info(f"Starting backfill for {stock_name} ({stock_code})")
    
    total_added = 0
    # Use max_pages=500 to simulate the loop in original script, but in shared module usually limited. 
    # Since shared module processes page by page in a loop, we might need a custom loop here if we want deep backfill.
    # However, for consistency and cleaning, let's use the shared crawl function but maybe call it in chunks or modification.
    # The shared `crawl_stock_news` takes `max_pages`. We validly set it to a reasonable high number for backfill.
    
    documents = crawl_stock_news(stock_code, stock_name, max_pages=200, request_delay=0.2, deduplicate=True)
    
    if not documents:
        logger.info(f"No news found for {stock_name}")
        return

    logger.info(f"Fetched {len(documents)} news items. Processing...")

    for doc in documents:
        try:
            content = doc['page_content']
            # Parse content: new format "[종목명(코드)] 제목 | 출처: ... | 날짜: ..."
            # or legacy format "뉴스 제목: ...\n링크: ..."
            metadata = doc['metadata']
            if content.startswith("["):
                # New format: extract title between "] " and " | 출처:"
                bracket_end = content.find("] ")
                pipe_pos = content.find(" | 출처:")
                title = content[bracket_end + 2:pipe_pos].strip() if bracket_end != -1 and pipe_pos != -1 else content
                link = metadata.get('source_url', '')
            else:
                # Legacy format
                lines = content.split('\n')
                title = lines[0].replace("뉴스 제목: ", "").strip()
                link = lines[1].replace("링크: ", "").strip() if len(lines) > 1 else ''
            
            metadata = doc['metadata']
            pub_timestamp = metadata['created_at_utc']
            pub_date = datetime.fromtimestamp(pub_timestamp)
            
            # Check date limit
            if pub_date < TARGET_START_DATE:
                continue

            # Classify
            classification = classifier.classify(title)
            
            # Default values
            score = 50
            reason = "Neutral"
            category = "General"
            
            if classification:
                # Map NewsClassification to score (0-100)
                score = 50 + (classification.base_score * 2)
                score = max(0, min(100, score)) # Clamp 0-100
                category = classification.category
                reason = f"Category: {category} ({classification.sentiment})"
            
            # Save to DB
            from shared.db.models import NewsSentiment
            from sqlalchemy import text, select

            # Check DB existence
            stmt = select(NewsSentiment).where(NewsSentiment.source_url == link)
            existing = session.scalars(stmt).first()
            if existing:
                continue

            # 1. NEWS_SENTIMENT
            new_sentiment = NewsSentiment(
                stock_code=stock_code,
                news_title=title,
                sentiment_score=score,
                sentiment_reason=reason,
                source_url=link,
                published_at=pub_date
            )
            session.add(new_sentiment)
            
            # 2. STOCK_NEWS_SENTIMENT (Raw SQL)
            session.execute(text("""
                INSERT IGNORE INTO STOCK_NEWS_SENTIMENT 
                (STOCK_CODE, NEWS_DATE, ARTICLE_URL, HEADLINE, CATEGORY, SENTIMENT_SCORE, SCRAPED_AT, SOURCE)
                VALUES (:code, :date, :url, :title, :category, :score, NOW(), 'NAVER')
            """), {
                'code': stock_code,
                'date': pub_date,
                'url': link,
                'title': title,
                'category': category,
                'score': score
            })
            
            total_added += 1
            
        except Exception as e:
            logger.error(f"Error saving document: {e}")
            pass

    session.commit()
    logger.info(f"Finished {stock_name}: Added {total_added} news items.")

def main():
    load_dotenv()
    
    # Init DB Engine
    database.init_connection_pool()
    
    # Get Classifier
    classifier = get_classifier()
    
    # Get Top Stocks
    stocks = get_top_stocks(limit=100)
    logger.info(f"Found {len(stocks)} stocks to process.")
    
    session = get_session()
    start_total = time.time()
    
    try:
        for i, (code, name) in enumerate(stocks):
            logger.info(f"[{i+1}/{len(stocks)}] Processing {name} ({code})...")
            backfill_stock_news(code, name, classifier, session)
            
    except KeyboardInterrupt:
        logger.warning("Process interrupted by user.")
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
    finally:
        session.close()
        end_total = time.time()
        logger.info(f"Total execution time: {end_total - start_total:.2f} seconds")

if __name__ == "__main__":
    main()
