
import unittest
from unittest.mock import MagicMock
import os
import sys
import importlib.util

# Project Root Setup
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

class TestBuyOpportunityWatcherRSI(unittest.TestCase):
    def setUp(self):
        # Load opportunity_watcher module dynamically because of hyphen in path
        module_path = os.path.join(PROJECT_ROOT, 'services', 'buy-scanner', 'opportunity_watcher.py')
        self.module = load_module("opportunity_watcher", module_path)
        
        self.mock_config = MagicMock()
        self.mock_publisher = MagicMock()
        self.watcher = self.module.BuyOpportunityWatcher(self.mock_config, self.mock_publisher, redis_url="redis://dummy")
        # Redis 연결 방지
        self.watcher.redis = MagicMock()

    def test_check_rsi_rebound_triggered(self):
        """RSI Rebound 감지: 28 -> 32"""
        # Mocking internal method directly on the instance
        self.watcher._calculate_simple_rsi = MagicMock(side_effect=[32.0, 28.0])
        
        # Dummy bars
        bars = [{'close': 100}] * 30 
        params = {'threshold': 30}
        
        triggered, reason = self.watcher._check_rsi_rebound(bars, params)
        
        self.assertTrue(triggered)
        self.assertIn("RSI Rebound", reason)
        self.assertEqual(self.watcher._calculate_simple_rsi.call_count, 2)

    def test_check_rsi_rebound_no_trigger_still_low(self):
        """RSI 여전히 과매도: 25 -> 28"""
        self.watcher._calculate_simple_rsi = MagicMock(side_effect=[28.0, 25.0]) # Curr, Prev
        
        bars = [{'close': 100}] * 30 
        params = {'threshold': 30}
        
        triggered, reason = self.watcher._check_rsi_rebound(bars, params)
        
        self.assertFalse(triggered)
        
    def test_check_rsi_rebound_no_trigger_normal(self):
        """이미 정상 구간: 35 -> 40"""
        self.watcher._calculate_simple_rsi = MagicMock(side_effect=[40.0, 35.0]) # Curr, Prev
        
        bars = [{'close': 100}] * 30 
        params = {'threshold': 30}
        
        triggered, reason = self.watcher._check_rsi_rebound(bars, params)
        
        self.assertFalse(triggered)

    def test_check_rsi_rebound_cross_down(self):
        """하향 돌파 (진입 아님): 32 -> 28"""
        self.watcher._calculate_simple_rsi = MagicMock(side_effect=[28.0, 32.0]) # Curr, Prev
        
        bars = [{'close': 100}] * 30 
        params = {'threshold': 30}
        
        triggered, reason = self.watcher._check_rsi_rebound(bars, params)
        
        self.assertFalse(triggered)

if __name__ == '__main__':
    unittest.main()
