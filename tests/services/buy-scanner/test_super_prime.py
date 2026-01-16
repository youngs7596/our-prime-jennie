
import unittest
from unittest.mock import MagicMock
import pandas as pd
from datetime import datetime, timedelta
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

class TestSuperPrimeStrategy(unittest.TestCase):
    def setUp(self):
        # Load opportunity_watcher module dynamically
        module_path = os.path.join(PROJECT_ROOT, 'services', 'buy-scanner', 'opportunity_watcher.py')
        self.module = load_module("opportunity_watcher_super_prime", module_path)
        
        mock_config = MagicMock()
        mock_publisher = MagicMock()
        self.watcher = self.module.BuyOpportunityWatcher(mock_config, mock_publisher, redis_url="redis://dummy")
        self.watcher.redis = MagicMock()

    def test_check_legendary_pattern_success(self):
        """Test Super Prime Strategy (Legendary Pattern) - Success Case"""
        stock_code = "TEST"
        
        # 1. Prepare Supply Data (Mock cache)
        # Recent 5 days foreign net buy sum > 0
        dates = [datetime.now() - timedelta(days=i) for i in range(5)]
        supply_data = {
            'TRADE_DATE': dates,
            'FOREIGN_NET_BUY': [1000, 2000, -500, 1000, 1000] # Sum > 0
        }
        self.watcher.supply_demand_cache[stock_code] = pd.DataFrame(supply_data)
        
        # 2. Prepare Bars (Low RSI)
        # Create a price drop sequence
        # Start high, drop to low
        prices = [100 - i*2 for i in range(20)] # 100, 98, ..., 62
        bars = [{'close': p} for p in prices]
        
        # Mock RSI calculation to return <= 40
        self.watcher._calculate_simple_rsi = MagicMock(return_value=30.0)
        
        # 3. Test
        is_legendary = self.watcher._check_legendary_pattern(stock_code, bars)
        
        self.assertTrue(is_legendary, "Should detect legendary pattern (Foreign Buy > 0 & RSI <= 40)")

    def test_check_legendary_pattern_failure_foreign_sell(self):
        """Test Super Prime - Fail due to Foreign Net Sell"""
        stock_code = "TEST2"
        
        supply_data = {
            'TRADE_DATE': [datetime.now()],
            'FOREIGN_NET_BUY': [-10000] # Net Sell
        }
        self.watcher.supply_demand_cache[stock_code] = pd.DataFrame(supply_data)
        
        bars = [{'close': 100}] * 20
        self.watcher._calculate_simple_rsi = MagicMock(return_value=30.0) # RSI OK
        
        is_legendary = self.watcher._check_legendary_pattern(stock_code, bars)
        self.assertFalse(is_legendary, "Should fail if foreign matches are selling")

    def test_check_legendary_pattern_failure_high_rsi(self):
        """Test Super Prime - Fail due to High RSI"""
        stock_code = "TEST3"
        
        supply_data = {
            'TRADE_DATE': [datetime.now()],
            'FOREIGN_NET_BUY': [10000] # Net Buy OK
        }
        self.watcher.supply_demand_cache[stock_code] = pd.DataFrame(supply_data)
        
        bars = [{'close': 100}] * 20
        self.watcher._calculate_simple_rsi = MagicMock(return_value=60.0) # RSI Too High (>40)
        
        is_legendary = self.watcher._check_legendary_pattern(stock_code, bars)
        self.assertFalse(is_legendary, "Should fail if RSI is not low enough")

if __name__ == '__main__':
    unittest.main()
