import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Adjust path to import services/buy-scanner
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../services/buy-scanner')))

# Mock external dependencies
import importlib.util

class TestStrategyInjection(unittest.TestCase):
    
    def setUp(self):
        # Create a patcher for sys.modules
        self.modules_patcher = patch.dict(sys.modules, {
            'shared.database': MagicMock(),
            'shared.auth': MagicMock(),
            'shared.strategy': MagicMock(),
            'shared.market_regime': MagicMock(),
            'shared.db.connection': MagicMock(),
            'shared.db.repository': MagicMock(),
            'shared.factor_scoring': MagicMock(),
            'shared.strategy_presets': MagicMock(),
            'shared.db.factor_repository': MagicMock(),
            'strategy': MagicMock(),
            'redis': MagicMock(),
            'shared.watchlist': MagicMock()
        })
        self.modules_patcher.start()
        
        # Load Scanner Module Safely
        PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
        module_path = os.path.join(PROJECT_ROOT, 'services', 'buy-scanner', 'scanner.py')
        spec = importlib.util.spec_from_file_location("scanner_injected", module_path)
        self.scanner_module = importlib.util.module_from_spec(spec)
        
        # Inject the mock modules into the loaded module's namespace is handled by sys.modules patch
        # but we also need to ensure the module sees them during exec
        spec.loader.exec_module(self.scanner_module)
        
        self.BuyScanner = self.scanner_module.BuyScanner
        self.StrategySelector = self.scanner_module.StrategySelector
        
        # Capture the mock watchlist module we just created
        self.mock_watchlist_module = sys.modules['shared.watchlist']

    def tearDown(self):
        self.modules_patcher.stop()
    
    def test_strategy_injection(self):
        # Setup Scanner
        mock_kis = MagicMock()
        mock_config = MagicMock()
        mock_config.get_int.return_value = 20
        mock_config.get_float.return_value = 2.0
        
        scanner = self.BuyScanner(mock_kis, mock_config)
        
        # Mock Market Regime
        scanner._analyze_market_regime = MagicMock(return_value={
            'regime': 'BULL',
            'active_strategies': [self.StrategySelector.STRATEGY_MEAN_REVERSION], 
            'market_context_dict': {},
            'strategy_preset': None
        })
        
        # Mock Hot Watchlist Data
        self.mock_watchlist_module.get_hot_watchlist.return_value = {
            "stocks": [{"code": "005930", "name": "Samsung"}],
            "market_regime": "BULL",
            "score_threshold": 70
        }
        
        # Mock DB Watchlist and session using patch.object on the loaded module instance
        with patch.object(self.scanner_module, 'session_scope') as mock_session_scope, \
             patch.object(self.scanner_module, 'get_active_watchlist') as mock_get_watchlist:
            
            mock_get_watchlist.return_value = {"005930": {"code": "005930"}}
            
            # Mock _scan_stocks_parallel
            scanner._scan_stocks_parallel = MagicMock(return_value=[])
            
            # Helper for Context Manager
            mock_session = MagicMock()
            mock_session_scope.return_value.__enter__.return_value = mock_session
            
            # Run Scan
            scanner.scan_buy_opportunities()
            
            # Verify save_hot_watchlist called
            self.mock_watchlist_module.save_hot_watchlist.assert_called()
            
            # Verify content
            args, kwargs = self.mock_watchlist_module.save_hot_watchlist.call_args
            stocks_saved = kwargs['stocks']
            
            self.assertEqual(len(stocks_saved), 1)
            self.assertEqual(stocks_saved[0]['code'], "005930")
            
            # Verify Strategy Injection
            strategies = stocks_saved[0]['strategies']
            strategy_ids = [s['id'] for s in strategies]
            self.assertIn("BB_LOWER", strategy_ids)
            self.assertIn("RSI_OVERSOLD", strategy_ids)

if __name__ == '__main__':
    unittest.main()
