import pytest
from unittest.mock import MagicMock, patch, ANY
import sys
import os
from datetime import datetime, timedelta, timezone
import importlib.util

# Project Root Setup
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Dynamic import for module with hyphen in name
spec = importlib.util.spec_from_file_location(
    "crawler", 
    os.path.join(PROJECT_ROOT, "services/news-crawler/crawler.py")
)
crawler = importlib.util.module_from_spec(spec)
sys.modules["crawler"] = crawler # Register to sys.modules to handle relative imports if any
spec.loader.exec_module(crawler)

from langchain_core.documents import Document

@pytest.fixture
def mock_feedparser():
    with patch("crawler.feedparser") as mock:
        yield mock

@pytest.fixture
def mock_vectorstore():
    with patch("crawler.vectorstore") as mock:
        yield mock

@pytest.fixture
def mock_jennie_brain():
    with patch("crawler.jennie_brain") as mock:
        yield mock

@pytest.fixture
def mock_database():
    with patch("crawler.database") as mock:
        yield mock

@pytest.fixture
def mock_session_scope():
    with patch("crawler.session_scope") as mock:
        yield mock

class TestCrawler:
    def test_crawl_news_for_stock_success(self, mock_feedparser):
        """Test fetching news from Google RSS"""
        # Mock RSS Feed
        mock_entry = MagicMock()
        mock_entry.title = "Samsung Electronics Hits Record High"
        mock_entry.link = "http://example.com/news1"
        # 1 day ago (Safe)
        mock_entry.published_parsed = (datetime.now(timezone.utc) - timedelta(days=1)).timetuple()
        mock_entry.get.return_value = {"title": "Google News"}

        mock_feedparser.parse.return_value = MagicMock(entries=[mock_entry])

        docs = crawler.crawl_news_for_stock("005930", "Samsung Electronics")

        assert len(docs) == 1
        assert docs[0].metadata["stock_code"] == "005930"
        assert docs[0].metadata["stock_name"] == "Samsung Electronics"
        assert docs[0].metadata["source_url"] == "http://example.com/news1"
        assert "Samsung Electronics Hits Record High" in docs[0].page_content

    def test_crawl_news_skips_old_news(self, mock_feedparser):
        """Test that news older than 7 days is skipped"""
        mock_entry = MagicMock()
        mock_entry.title = "Old News"
        mock_entry.link = "http://example.com/old"
        # 8 days ago (Should skip)
        mock_entry.published_parsed = (datetime.now(timezone.utc) - timedelta(days=8)).timetuple()

        mock_feedparser.parse.return_value = MagicMock(entries=[mock_entry])

        docs = crawler.crawl_news_for_stock("005930", "Samsung Electronics")

        assert len(docs) == 0

    def test_filter_new_documents(self, mock_vectorstore):
        """Test deduplication against ChromaDB"""
        # Docs to check
        doc1 = Document(page_content="News 1", metadata={"source_url": "http://example.com/1"})
        doc2 = Document(page_content="News 2", metadata={"source_url": "http://example.com/2"})
        
        # Mock ChromaDB response: http://example.com/1 already exists
        mock_vectorstore.get.return_value = {
            'metadatas': [{'source_url': "http://example.com/1"}]
        }

        new_docs = crawler.filter_new_documents([doc1, doc2])

        # Should only return doc2
        assert len(new_docs) == 1
        assert new_docs[0].metadata["source_url"] == "http://example.com/2"

    def test_process_sentiment_analysis(self, mock_jennie_brain, mock_database, mock_session_scope):
        """Test sentiment analysis flow"""
        doc = Document(
            page_content="Good News", 
            metadata={
                "stock_code": "005930", 
                "stock_name": "Samsung", 
                "source_url": "http://url",
                "source": "Title"
            }
        )

        mock_jennie_brain.analyze_news_sentiment.return_value = {
            'score': 80, 'reason': 'Good'
        }

        # Run process
        crawler.process_sentiment_analysis([doc])

        # Verify LLM call
        mock_jennie_brain.analyze_news_sentiment.assert_called_once()
        
        # Verify Redis set
        mock_database.set_sentiment_score.assert_called_with(
            "005930", 80, 'Good', 
            source_url="http://url", 
            stock_name="Samsung", 
            news_title=ANY, 
            news_date=ANY
        )

        # Verify DB save
        mock_database.save_news_sentiment.assert_called()

    @patch("crawler.crawl_news_for_stock")
    @patch("crawler.get_kospi_200_universe")
    @patch("crawler.filter_new_documents")
    @patch("crawler.add_documents_to_chroma")
    @patch("crawler.process_sentiment_analysis")
    @patch("crawler.cleanup_old_data_job")
    @patch("shared.utils.is_operating_hours")
    def test_run_collection_job_flow(self, mock_is_op, mock_cleanup, mock_sentiment, 
                                     mock_add, mock_filter, mock_universe, mock_crawl):
        """Test the main job flow"""
        # Setup mocks
        mock_is_op.return_value = True
        mock_universe.return_value = [{"code": "005930", "name": "Samsung"}]
        mock_crawl.return_value = [Document(page_content="News", metadata={"url": "abc"})]
        mock_filter.return_value = [Document(page_content="News", metadata={"url": "abc"})]

        # Use patch for initialize_services since it modifies globals
        with patch("crawler.initialize_services"):
            crawler.run_collection_job()

        # Assertions
        mock_universe.assert_called_once()
        mock_crawl.assert_called()
        mock_filter.assert_called()
        mock_add.assert_called()
        mock_cleanup.assert_called()
