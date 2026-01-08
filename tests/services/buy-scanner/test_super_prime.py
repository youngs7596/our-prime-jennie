
import unittest
from unittest.mock import MagicMock
import pandas as pd
from datetime import datetime, timedelta
import sys
import os

# Add services/buy-scanner to path to handle hyphen in directory name
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../services/buy-scanner')))

try:
    from scanner import BuyScanner
except ImportError:
    # Fallback if running from proper root context
    from services.buy_scanner.scanner import BuyScanner

class TestSuperPrimeStrategy(unittest.TestCase):
    def setUp(self):
        # Initialize BuyScanner with minimal mock objects
        mock_config = MagicMock()
        mock_kis = MagicMock()
        self.scanner = BuyScanner(kis=mock_kis, config=mock_config)
        self.scanner.logger = MagicMock() # Mock logger to avoid clutter

    def test_check_legendary_pattern_success(self):
        """Test Super Prime Strategy (Legendary Pattern) - Success Case"""
        
        # 1. Prepare Mock Data
        # Daily Prices (needs PRICE_DATE, CLOSE_PRICE, VOLUME) for last 30 days
        dates = [datetime.now() - timedelta(days=i) for i in range(29, -1, -1)]
        prices_data = {
            'PRICE_DATE': dates,
            'CLOSE_PRICE': [10000 + i*10 for i in range(30)], 
            'VOLUME': [100000] * 30 
        }
        daily_prices_df = pd.DataFrame(prices_data)
        
        # Force a sharp drop to get RSI <= 30 at index around 20 (14 days rolling window need)
        # Construct a sequence that guarantees RSI <= 30
        for i in range(10, 24):
            daily_prices_df.loc[i, 'CLOSE_PRICE'] = daily_prices_df.loc[i-1, 'CLOSE_PRICE'] - 200
            
        # Supply Demand Data
        supply_data = {
            'TRADE_DATE': dates,
            'FOREIGN_NET_BUY': [1000] * 30 
        }
        supply_demand_df = pd.DataFrame(supply_data)
        
        # Condition: RSI <= 30 AND Foreign Buy >= (Vol MA20 * 0.05)
        # We need this to happen within the last 20 days. Use index 23 where price drop is significant.
        supply_demand_df.loc[23, 'FOREIGN_NET_BUY'] = 10000 # Satisfies >= 5000 (5% of 100k)
        
        is_legendary = self.scanner._check_legendary_pattern('TEST', daily_prices_df, supply_demand_df)
        self.assertTrue(is_legendary, "Should detect legendary pattern with low RSI drops and high visible foreign buy")

    def test_check_legendary_pattern_failure_volume(self):
        """Test Super Prime Strategy - Failure due to low Foreign Buy"""
        dates = [datetime.now() - timedelta(days=i) for i in range(29, -1, -1)]
        prices_data = {
            'PRICE_DATE': dates,
            'CLOSE_PRICE': [10000 - i*100 for i in range(30)], # Constant drop guarantees low RSI
            'VOLUME': [100000] * 30
        }
        daily_prices_df = pd.DataFrame(prices_data)
        
        supply_data = {
            'TRADE_DATE': dates,
            'FOREIGN_NET_BUY': [100] * 30 # Very low foreign buy (fails 5% threshold)
        }
        supply_demand_df = pd.DataFrame(supply_data)
        
        is_legendary = self.scanner._check_legendary_pattern('TEST', daily_prices_df, supply_demand_df)
        self.assertFalse(is_legendary, "Should NOT detect pattern if foreign buy is weak")

if __name__ == '__main__':
    unittest.main()
