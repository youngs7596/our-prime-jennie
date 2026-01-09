import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Adjust path to import services/buy-scanner (OpportunityWatcher 이관됨)
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../services/buy-scanner')))

# Mock external dependencies before importing
sys.modules['redis'] = MagicMock()
sys.modules['shared.database'] = MagicMock()

import importlib.util

def load_opportunity_watcher_module():
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
    module_path = os.path.join(PROJECT_ROOT, 'services', 'buy-scanner', 'opportunity_watcher.py')
    spec = importlib.util.spec_from_file_location("opportunity_watcher", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["opportunity_watcher"] = module
    spec.loader.exec_module(module)
    return module

opportunity_watcher_mod = load_opportunity_watcher_module()
BuyOpportunityWatcher = opportunity_watcher_mod.BuyOpportunityWatcher

class TestDynamicStrategies(unittest.TestCase):
    
    def setUp(self):
        self.mock_config = MagicMock()
        self.mock_publisher = MagicMock()
        self.watcher = BuyOpportunityWatcher(self.mock_config, self.mock_publisher)
        
        # Mock BarAggregator
        self.watcher.bar_aggregator = MagicMock()
        
        # Set default regime
        self.watcher.market_regime = "BULL"
    
    def test_check_buy_signal_executes_only_assigned_strategies(self):
        # Setup specific strategies for stock "005930"
        stock_code = "005930"
        self.watcher.hot_watchlist = {
            stock_code: {
                "name": "Samsung",
                "strategies": [
                    {"id": "GOLDEN_CROSS", "params": {"short_window": 5, "long_window": 20}}
                ]
            }
        }
        
        # Mock bars that would trigger RSI but NOT Golden Cross
        # To prove RSI is NOT checked if not in strategies
        # (Assuming we can control check methods directly or mock them)
        
        # However, it's black-box testing _check_buy_signal.
        # Let's mock the internal check methods to verify dispatching
        
        self.watcher._check_golden_cross = MagicMock(return_value=(False, ""))
        self.watcher._check_rsi_oversold = MagicMock(return_value=(True, "RSI Triggered")) # Should NOT be called
        self.watcher._check_bb_lower = MagicMock(return_value=(True, "BB Triggered")) # Should NOT be called

        # Need enough bars to pass length check
        self.watcher.bar_aggregator.get_recent_bars.return_value = [{"close": 100}] * 30
        self.watcher._check_cooldown = MagicMock(return_value=True)

        # Execute
        result = self.watcher._check_buy_signal(stock_code, 100.0, {})
        
        # Verify
        self.watcher._check_golden_cross.assert_called_once()
        self.watcher._check_rsi_oversold.assert_not_called()
        self.watcher._check_bb_lower.assert_not_called()
        self.assertIsNone(result) # Golden Cross returned False

    def test_golden_cross_trigger(self):
        stock_code = "005930"
        self.watcher.hot_watchlist = {
            stock_code: {
                "name": "Samsung",
                "strategies": [{"id": "GOLDEN_CROSS", "params": {"short_window": 5, "long_window": 20}}]
            }
        }
        
        # Mock check method to return True
        self.watcher._check_golden_cross = MagicMock(return_value=(True, "Golden Cross!"))
        self.watcher.bar_aggregator.get_recent_bars.return_value = [{"close": 100}] * 30
        self.watcher._check_cooldown = MagicMock(return_value=True)

        result = self.watcher._check_buy_signal(stock_code, 100.0, {})
        
        self.assertIsNotNone(result)
        self.assertEqual(result['signal_type'], "GOLDEN_CROSS")
        self.assertEqual(result['signal_reason'], "Golden Cross!")

if __name__ == '__main__':
    unittest.main()
