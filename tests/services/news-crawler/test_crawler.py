import unittest
try:
    import pytest
except ImportError:
    pytest = None

# unittest discover 시 pytest 없으면 전체 모듈 스킵
if pytest is None:
    raise unittest.SkipTest("pytest not installed, skipping pytest-based tests")

from unittest.mock import MagicMock, patch, ANY
import sys
import os
from datetime import datetime, timedelta, timezone
import importlib.util

# Project Root Setup
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if PROJECT_ROOT not in sys.path:
    # sys.path.insert(0, PROJECT_ROOT)
    pass

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
        """Test fetching news from Google RSS (with trusted source)"""
        # Mock RSS Feed with trusted source
        mock_entry = MagicMock()
        mock_entry.title = "Samsung Electronics Hits Record High"
        mock_entry.link = "https://www.hankyung.com/economy/article/20260103news1"  # Trusted domain
        # 1 day ago (Safe)
        mock_entry.published_parsed = (datetime.now(timezone.utc) - timedelta(days=1)).timetuple()
        mock_entry.get.return_value = {"title": "한경"}  # Trusted source name

        mock_feedparser.parse.return_value = MagicMock(entries=[mock_entry])

        docs = crawler.crawl_news_for_stock("005930", "Samsung Electronics")

        assert len(docs) == 1
        assert docs[0].metadata["stock_code"] == "005930"
        assert docs[0].metadata["stock_name"] == "Samsung Electronics"
        assert "hankyung.com" in docs[0].metadata["source_url"]
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

    def test_process_unified_analysis(self, mock_jennie_brain, mock_database, mock_session_scope):
        """Test unified analysis flow (sentiment + competitor risk)"""
        doc = Document(
            page_content="뉴스 제목: Good News\n링크: http://url", 
            metadata={
                "stock_code": "005930", 
                "stock_name": "Samsung", 
                "source_url": "http://url",
                "source": "Title",
                "created_at_utc": 1735800000
            }
        )

        # New unified response format
        mock_jennie_brain.analyze_news_unified.return_value = [{
            'id': 0,
            'sentiment': {'score': 80, 'reason': 'Good'},
            'competitor_risk': {'is_detected': False, 'type': 'NONE', 'benefit_score': 0, 'reason': 'N/A'}
        }]

        # Mock session_scope for DB operations
        mock_session = MagicMock()
        mock_session_scope.return_value.__enter__.return_value = mock_session

        # Run unified analysis
        crawler.process_unified_analysis([doc])

        # Verify unified LLM call
        mock_jennie_brain.analyze_news_unified.assert_called_once()
        
        # Verify Redis set was called for sentiment
        mock_database.set_sentiment_score.assert_called()

    @patch("crawler.crawl_stock_news_with_fallback")  # Updated: using fallback function
    @patch("crawler.get_kospi_200_universe")
    @patch("crawler.filter_new_documents")
    @patch("crawler.add_documents_to_chroma")
    @patch("crawler.process_unified_analysis")
    @patch("crawler.cleanup_old_data_job")
    @patch("shared.utils.is_operating_hours")
    def test_run_collection_job_flow(self, mock_is_op, mock_cleanup, mock_unified, 
                                     mock_add, mock_filter, mock_universe, mock_fallback_crawl):
        """Test the main job flow with fallback crawler"""
        # Setup mocks
        mock_is_op.return_value = True
        mock_universe.return_value = [{"code": "005930", "name": "Samsung"}]
        mock_fallback_crawl.return_value = [Document(page_content="News", metadata={"url": "abc"})]
        mock_filter.return_value = [Document(page_content="News", metadata={"url": "abc"})]

        # Use patch for initialize_services since it modifies globals
        with patch("crawler.initialize_services"):
            crawler.run_collection_job()

        # Assertions
        mock_universe.assert_called_once()
        mock_fallback_crawl.assert_called()  # Now checks fallback function
        mock_filter.assert_called()
        mock_add.assert_called()
        mock_cleanup.assert_called()
