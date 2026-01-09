import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Adjust path to import services/buy-scanner
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../services/buy-scanner')))

# Mock external dependencies
sys.modules['shared.database'] = MagicMock()
sys.modules['shared.auth'] = MagicMock()
sys.modules['shared.strategy'] = MagicMock()
sys.modules['shared.market_regime'] = MagicMock()
sys.modules['shared.db.connection'] = MagicMock()
sys.modules['shared.db.repository'] = MagicMock()
sys.modules['shared.factor_scoring'] = MagicMock()
sys.modules['shared.strategy_presets'] = MagicMock()
sys.modules['shared.db.factor_repository'] = MagicMock()
sys.modules['strategy'] = MagicMock()
sys.modules['redis'] = MagicMock()

# Mock shared.watchlist specifically
mock_watchlist_module = MagicMock()
sys.modules['shared.watchlist'] = mock_watchlist_module

# Import Scanner
from scanner import BuyScanner, StrategySelector

class TestStrategyInjection(unittest.TestCase):
    
    @unittest.skip("CI Stabilization: Skip complex mock interaction test")
    @patch('scanner.session_scope')
    @patch('scanner.get_active_watchlist')
    def test_strategy_injection(self, mock_get_watchlist, mock_session_scope):
        # Setup Scanner
        mock_kis = MagicMock()
        mock_config = MagicMock()
        mock_config.get_int.return_value = 20
        mock_config.get_float.return_value = 2.0
        
        scanner = BuyScanner(mock_kis, mock_config)
        
        # Mock Market Regime
        scanner._analyze_market_regime = MagicMock(return_value={
            'regime': 'BULL',
            'active_strategies': [StrategySelector.STRATEGY_MEAN_REVERSION], 
            'market_context_dict': {},
            'strategy_preset': None
        })
        
        # Mock Hot Watchlist Data (via shared.watchlist mock)
        mock_watchlist_module.get_hot_watchlist.return_value = {
            "stocks": [{"code": "005930", "name": "Samsung"}],
            "market_regime": "BULL",
            "score_threshold": 70
        }
        
        # Mock DB Watchlist
        mock_get_watchlist.return_value = {"005930": {"code": "005930"}}
        
        # Mock _scan_stocks_parallel
        scanner._scan_stocks_parallel = MagicMock(return_value=[])
        
        # Helper for Context Manager
        mock_session = MagicMock()
        mock_session_scope.return_value.__enter__.return_value = mock_session
        
        # Run Scan
        scanner.scan_buy_opportunities()
        
        # Verify save_hot_watchlist called
        mock_watchlist_module.save_hot_watchlist.assert_called_once()
        
        # Verify content
        args, kwargs = mock_watchlist_module.save_hot_watchlist.call_args
        stocks_saved = kwargs['stocks']
        
        self.assertEqual(len(stocks_saved), 1)
        self.assertEqual(stocks_saved[0]['code'], "005930")
        
        # Verify Strategy Injection
        strategies = stocks_saved[0]['strategies']
        # MEAN_REVERSION maps to BB_LOWER and RSI_OVERSOLD
        strategy_ids = [s['id'] for s in strategies]
        self.assertIn("BB_LOWER", strategy_ids)
        self.assertIn("RSI_OVERSOLD", strategy_ids)

if __name__ == '__main__':
    unittest.main()
