import unittest
from unittest.mock import MagicMock, patch
import json
import sys
import os

# Adjust path to import shared
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from shared.watchlist import save_hot_watchlist, get_hot_watchlist

class TestSharedWatchlist(unittest.TestCase):
    
    @patch('shared.watchlist.get_redis_connection')
    def test_save_and_get_watchlist(self, mock_get_redis):
        # Setup mock Redis
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        
        # Test Data
        stocks = [
            {
                "code": "005930",
                "name": "Samsung",
                "llm_score": 88,
                "strategies": [{"id": "GOLDEN_CROSS", "params": {}}]
            }
        ]
        
        # 1. Test Save
        success = save_hot_watchlist(stocks, "BULL", 70)
        self.assertTrue(success)
        
        # Verify Redis calls
        # Should set actual data key
        self.assertTrue(mock_redis.set.called)
        # Should set active pointer
        mock_redis.set.assert_any_call("hot_watchlist:active", unittest.mock.ANY)
        
        # 2. Test Get
        # Setup mock behavior for GET
        # First get returns "hot_watchlist:v12345"
        # Second get returns the JSON payload
        mock_redis.get.side_effect = [
            "hot_watchlist:v12345", 
            json.dumps({
                "generated_at": "2024-01-01T00:00:00",
                "market_regime": "BULL",
                "score_threshold": 70,
                "stocks": stocks
            })
        ]
        
        result = get_hot_watchlist()
        
        self.assertIsNotNone(result)
        self.assertEqual(result['market_regime'], "BULL")
        self.assertEqual(len(result['stocks']), 1)
        self.assertEqual(result['stocks'][0]['code'], "005930")
        self.assertEqual(result['stocks'][0]['strategies'][0]['id'], "GOLDEN_CROSS")

if __name__ == '__main__':
    unittest.main()
