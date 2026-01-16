
import pytest
import unittest
from unittest.mock import MagicMock, patch, ANY
import os
import sys
from datetime import datetime

# Adjust path to import services
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

# Mock database and other dependencies before importing executor
sys.modules['shared.database'] = MagicMock()
sys.modules['shared.db.connection'] = MagicMock()
sys.modules['shared.db.connection'].session_scope = MagicMock()
sys.modules['shared.db.repository'] = MagicMock()
sys.modules['shared.redis_cache'] = MagicMock()
sys.modules['shared.strategy_presets'] = MagicMock()

# Handle import with dash in directory name
import importlib.util

spec = importlib.util.spec_from_file_location(
    "services.sell_executor.executor", 
    os.path.join(os.path.dirname(__file__), '../../../services/sell-executor/executor.py')
)
executor_module = importlib.util.module_from_spec(spec)
sys.modules["services.sell_executor.executor"] = executor_module
spec.loader.exec_module(executor_module)

SellExecutor = executor_module.SellExecutor
# Import these AFTER mocking sys.modules
from shared.db import repository as repo
from shared.redis_cache import get_redis_connection

class TestSellExecutorEnhancements(unittest.TestCase):
    def setUp(self):
        self.mock_kis = MagicMock()
        self.mock_config = MagicMock()
        self.mock_bot = MagicMock()
        self.executor = SellExecutor(self.mock_kis, self.mock_config, self.mock_bot)
        
        # Setup Redis mock
        self.mock_redis = MagicMock()
        # Fix: get_redis_connection is a mock object now, set its return value
        get_redis_connection.return_value = self.mock_redis
        
        # Setup DB mocks
        self.mock_session = MagicMock()
        # Fix: session_scope is a mock object
        sys.modules['shared.db.connection'].session_scope.return_value.__enter__.return_value = self.mock_session
        
        # Default portfolio holding
        repo.get_active_portfolio.return_value = [{
            'id': 1, 'code': '005930', 'name': '삼성전자', 
            'avg_price': 70000, 'quantity': 10, 'created_at': datetime.now()
        }]
        repo.check_duplicate_order.return_value = False
        
        # Reset mocks to clear history from previous tests
        repo.get_active_portfolio.reset_mock()
        repo.check_duplicate_order.reset_mock()

    def test_execute_sell_priority_price(self):
        """Test that provided current_price is used and API is not called"""
        # Execute with provided price
        self.executor.execute_sell_order(
            stock_code='005930', stock_name='삼성전자', quantity=10, 
            sell_reason='TEST', current_price=80000
        )
        
        # Check that get_stock_snapshot was NOT called
        self.mock_kis.get_stock_snapshot.assert_not_called()
        
        # Check that lock was acquired
        self.mock_redis.set.assert_called_with('lock:sell:005930', 'LOCKED', nx=True, ex=10)

    def test_execute_sell_lock_release_on_exception(self):
        """Test that Redis lock is released if an exception occurs during execution"""
        # Setup Redis lock acquisition success
        self.mock_redis.set.return_value = True
        
        # Make repo.get_active_portfolio raise an exception
        repo.get_active_portfolio.side_effect = RuntimeError("DB Error")
        
        # Execute
        result = self.executor.execute_sell_order(
            stock_code='005930', stock_name='삼성전자', quantity=10, 
            sell_reason='TEST', current_price=80000
        )
        
        # Verify result indicates error
        self.assertEqual(result['status'], 'error')
        self.assertIn("DB Error", result['reason'])
        
        # Verify lock was deleted
        self.mock_redis.delete.assert_called_with('lock:sell:005930')

    def test_execute_sell_lock_occupied(self):
        """Test that execution is skipped if lock is already occupied"""
        # Redis set returns False (lock occupied)
        self.mock_redis.set.return_value = False
        
        result = self.executor.execute_sell_order(
            stock_code='005930', stock_name='삼성전자', quantity=10, 
            sell_reason='TEST', current_price=80000
        )
        
        self.assertEqual(result['status'], 'skipped')
        self.assertIn("locked", result['reason'])
        
        # Process should stop, so no DB calls
        repo.get_active_portfolio.assert_not_called()

    def test_emergency_stop_blocks_auto_sell(self):
        """Test that emergency stop blocks automatic sell orders"""
        # Configure is_trading_stopped to return True
        executor_module.is_trading_stopped.return_value = True
        
        result = self.executor.execute_sell_order(
            stock_code='005930', stock_name='삼성전자', quantity=10, 
            sell_reason='RSI Overbought', current_price=80000
        )
        
        self.assertEqual(result['status'], 'skipped')
        self.assertIn("Emergency Stop", result['reason'])
        
        # Reset for other tests
        executor_module.is_trading_stopped.return_value = False

    def test_emergency_stop_allows_manual_sell(self):
        """Test that emergency stop does NOT block manual sell orders"""
        # Configure is_trading_stopped to return True
        executor_module.is_trading_stopped.return_value = True
        
        result = self.executor.execute_sell_order(
            stock_code='005930', stock_name='삼성전자', quantity=10, 
            sell_reason='MANUAL: User requested', current_price=80000, dry_run=True  # Dry run to avoid full execution path issues
        )
        
        # Should not be skipped due to Emergency Stop
        # Verify it went further (e.g. checked lock)
        self.mock_redis.set.assert_called_with('lock:sell:005930', 'LOCKED', nx=True, ex=10)
        # It might succeed or fail depending on other mocks, but NOT 'skipped' due to Stop
        self.assertNotEqual(result.get('reason'), "Emergency Stop Active")
        
        # Reset for other tests
        executor_module.is_trading_stopped.return_value = False

if __name__ == '__main__':
    unittest.main()
