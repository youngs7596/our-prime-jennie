
import unittest
from unittest.mock import MagicMock, patch, ANY
import sys
import os
from concurrent.futures import Future

# Adjust path to find modules (Project Root for 'shared')
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Handle hyphenated directory name import (for 'crawler')
services_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'services', 'news-crawler'))
sys.path.append(services_path)

# Mock modules before importing crawler to avoid import errors
sys.modules['shared.auth'] = MagicMock()
sys.modules['shared.database'] = MagicMock()
sys.modules['shared.llm'] = MagicMock()
sys.modules['shared.db.connection'] = MagicMock()
sys.modules['shared.db.models'] = MagicMock()
sys.modules['shared.gemini'] = MagicMock()
sys.modules['shared.news_classifier'] = MagicMock()
sys.modules['shared.hybrid_scoring.competitor_analyzer'] = MagicMock()
# sys.modules['langchain_core.documents'] = MagicMock() # Removed to avoid metaclass conflict
sys.modules['langchain_chroma'] = MagicMock() # crawler imports this too
sys.modules['langchain_huggingface'] = MagicMock()

# Import crawler after mocking
import crawler

class TestCrawlerIntegration(unittest.TestCase):
    def setUp(self):
        # Reset mocks
        crawler.jennie_brain = MagicMock()
        crawler.database = MagicMock()
        crawler.session_scope = MagicMock()
        crawler.logger = MagicMock()
        
    def test_process_unified_analysis_flow(self):
        # 1. Setup Mock Documents
        mock_doc1 = MagicMock()
        mock_doc1.metadata = {"stock_code": "005930", "stock_name": "Samsung", "source_url": "http://test.com/1", "created_at_utc": 1234567890}
        mock_doc1.page_content = "뉴스 제목: 삼성전자 호항\n본문내용..."
        
        mock_doc2 = MagicMock() # Non-stock doc (should be skipped)
        mock_doc2.metadata = {} 

        documents = [mock_doc1, mock_doc2]
        
        # 2. Setup JennieBrain Mock Response
        mock_analysis_result = [
            {
                "id": 0,
                "sentiment": {"score": 80, "reason": "호실적 기대"},
                "competitor_risk": {"is_detected": True, "type": "FIRE", "benefit_score": 10, "reason": "화재 발생"}
            }
        ]
        crawler.jennie_brain.analyze_news_unified.return_value = mock_analysis_result
        
        # 3. Setup DB/Session Mock
        mock_session = MagicMock()
        crawler.session_scope.return_value.__enter__.return_value = mock_session
        
        # Mock IndustryCompetitors query
        mock_affected_stock = MagicMock()
        mock_affected_stock.sector_code = "SEC001"
        mock_affected_stock.stock_name = "Samsung"
        
        mock_competitor = MagicMock()
        mock_competitor.stock_code = "000660"
        mock_competitor.stock_name = "SK Hynix"
        
        # Configure query return values
        # Ensure name check works for MagicMocks
        sys.modules['shared.db.models'].IndustryCompetitors.__name__ = 'IndustryCompetitors'
        sys.modules['shared.db.models'].CompetitorBenefitEvents.__name__ = 'CompetitorBenefitEvents'
        
        # Fix MagicMock comparison error for detected_at (>= operator)
        sys.modules['shared.db.models'].CompetitorBenefitEvents.detected_at.__ge__.return_value = MagicMock()

        # First query: affected_stock
        # Second query: competitors
        # We need side_effect to handle different filters
        def query_side_effect(model):
            query_mock = MagicMock()
            if model.__name__ == 'IndustryCompetitors':
                filter_mock = MagicMock()
                # Simulate finding affected stock then competitors
                # unique per logic flow
                filter_mock.first.return_value = mock_affected_stock
                filter_mock.all.return_value = [mock_competitor]
                query_mock.filter.return_value = filter_mock
            elif model.__name__ == 'CompetitorBenefitEvents':
                 filter_mock = MagicMock()
                 filter_mock.first.return_value = None # No duplicate
                 query_mock.filter.return_value = filter_mock
            return query_mock
            
        mock_session.query.side_effect = query_side_effect

        # 4. Run Function
        crawler.process_unified_analysis(documents)
        
        # 5. Verify Calls
        
        # Verify LLM call
        crawler.jennie_brain.analyze_news_unified.assert_called_once()
        call_args = crawler.jennie_brain.analyze_news_unified.call_args[0][0]
        self.assertEqual(len(call_args), 1)
        self.assertEqual(call_args[0]['title'], "삼성전자 호항")
        
        # Verify Sentiment Save (Redis)
        crawler.database.set_sentiment_score.assert_called()
        crawler.database.set_sentiment_score.assert_any_call(
            "005930", 80, "호실적 기대", 
            source_url="http://test.com/1", 
            stock_name="Samsung", 
            news_title="삼성전자 호항", 
            news_date="2009-02-13" # from timestamp
        )
        
        # Verify Sentiment Save (DB)
        crawler.database.save_news_sentiment.assert_called()

        if crawler.logger.error.called:
            print("🚨 Captured Logger Error:", crawler.logger.error.call_args)
        if crawler.logger.exception.called:
            print("🚨 Captured Logger Exception:", crawler.logger.exception.call_args)

        # Verify Competitor Event Creation
        # Check constructor call arguments
        comp_event_class = sys.modules['shared.db.models'].CompetitorBenefitEvents
        self.assertTrue(comp_event_class.called)
        
        # Get kwargs of the last call
        call_kwargs = comp_event_class.call_args[1]
        self.assertEqual(call_kwargs['event_type'], "FIRE")
        self.assertEqual(call_kwargs['beneficiary_stock_code'], "000660")
        
        # Verify session.add called with the return value
        mock_instance = comp_event_class.return_value
        mock_session.add.assert_called_with(mock_instance)
        
        print("\n✅ Integration Test Passed: process_unified_analysis flow verified.")

if __name__ == '__main__':
    unittest.main()
