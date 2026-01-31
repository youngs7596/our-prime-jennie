import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import importlib.util

# Adjust path to import services/buy-scanner (OpportunityWatcher 이관됨)
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../services/buy-scanner')))

# Mock external dependencies before importing
class TestDynamicStrategies(unittest.TestCase):
    
    def setUp(self):
        # Create a patcher for sys.modules
        self.modules_patcher = patch.dict(sys.modules, {
            'redis': MagicMock(),
            'shared.database': MagicMock()
        })
        self.modules_patcher.start()

        # Load Opportunity Watcher Module Safely
        PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
        module_path = os.path.join(PROJECT_ROOT, 'services', 'buy-scanner', 'opportunity_watcher.py')
        spec = importlib.util.spec_from_file_location("opportunity_watcher_dynamic", module_path)
        self.watcher_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.watcher_module)
        
        self.BuyOpportunityWatcher = self.watcher_module.BuyOpportunityWatcher

        # Create a proper mock config with return values for get_* methods
        self.mock_config = MagicMock()
        self.mock_config.get_int.return_value = 75  # For RISK_GATE_RSI_MAX, SIGNAL_COOLDOWN_SECONDS, etc.
        self.mock_config.get_float.return_value = 2.0  # For RISK_GATE_VOLUME_RATIO, etc.
        self.mock_config.get_bool.return_value = True
        self.mock_config.get.return_value = None

        self.mock_publisher = MagicMock()
        self.watcher = self.BuyOpportunityWatcher(self.mock_config, self.mock_publisher)
        
        # Mock BarAggregator
        self.watcher.bar_aggregator = MagicMock()
        self.watcher.bar_aggregator.get_volume_info.return_value = {'current': 1000, 'avg': 1000, 'ratio': 1.0}
        self.watcher.bar_aggregator.get_vwap.return_value = 100.0

        # Set default regime (use NEUTRAL to skip bull-market specific strategies)
        self.watcher.market_regime = "NEUTRAL"

        # Mock DB/Redis dependent functions
        self.watcher._save_buy_logic_snapshot = MagicMock()
        self.watcher._check_legendary_pattern = MagicMock(return_value=False)

    def tearDown(self):
        self.modules_patcher.stop()
    
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
        self.watcher.bar_aggregator.get_recent_bars.return_value = [{"open": 100, "high": 110, "low": 90, "close": 100, "volume": 1000}] * 30
        self.watcher._check_cooldown = MagicMock(return_value=True)

        # Mock time-based gates to pass (these depend on current time)
        self.watcher._check_no_trade_window = MagicMock(return_value=True)
        self.watcher._check_danger_zone = MagicMock(return_value=True)
        self.watcher._check_rsi_guard = MagicMock(return_value=True)

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
        self.watcher.bar_aggregator.get_recent_bars.return_value = [{"open": 100, "high": 110, "low": 90, "close": 100, "volume": 1000}] * 30
        self.watcher._check_cooldown = MagicMock(return_value=True)

        # Mock time-based gates to pass (these depend on current time)
        self.watcher._check_no_trade_window = MagicMock(return_value=True)
        self.watcher._check_danger_zone = MagicMock(return_value=True)
        self.watcher._check_rsi_guard = MagicMock(return_value=True)

        result = self.watcher._check_buy_signal(stock_code, 100.0, {})
        
        self.assertIsNotNone(result)
        self.assertEqual(result['signal_type'], "GOLDEN_CROSS")
        self.assertEqual(result['signal_reason'], "Golden Cross!")

if __name__ == '__main__':
    unittest.main()
