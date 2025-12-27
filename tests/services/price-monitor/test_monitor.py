import pytest
from unittest.mock import MagicMock, patch, ANY
import sys
import os
import pandas as pd
from datetime import datetime, timedelta
import importlib.util

# Project Root Setup
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Removed global import logic
# from monitor import PriceMonitor # Removed

@pytest.fixture
def monitor_module_setup():
    """Setup monitor module and clean up after test"""
    spec = importlib.util.spec_from_file_location(
        "monitor", 
        os.path.join(PROJECT_ROOT, "services/price-monitor/monitor.py")
    )
    monitor_module = importlib.util.module_from_spec(spec)
    
    with patch.dict(sys.modules, {"monitor": monitor_module}):
        spec.loader.exec_module(monitor_module)
        yield monitor_module

@pytest.fixture
def PriceMonitor(monitor_module_setup):
    return monitor_module_setup.PriceMonitor

@pytest.fixture
def mock_kis():
    return MagicMock()

@pytest.fixture
def mock_config():
    config = MagicMock()
    config.get_float.return_value = -5.0 # Stop Loss default
    config.get_int.return_value = 30 # Max holding days
    return config

@pytest.fixture
def mock_publisher():
    return MagicMock()

@pytest.fixture
def monitor_instance(PriceMonitor, mock_kis, mock_config, mock_publisher):
    return PriceMonitor(mock_kis, mock_config, mock_publisher)

@pytest.fixture
def mock_db_session():
    return MagicMock()

class TestPriceMonitor:
    def test_check_sell_signal_stop_loss(self, monitor_instance, mock_config, mock_db_session):
        """Test Fixed Stop Loss Trigger"""
        with patch("monitor.database.get_daily_prices", return_value=pd.DataFrame()):
            monitor_instance.config.get_float.side_effect = lambda k, default: -5.0 if 'STOP_LOSS' in k else default
            
            # Buy 100, Current 90 (-10%) -> Should Trigger
            result = monitor_instance._check_sell_signal(
                mock_db_session, "005930", "Samsung", 100, 90, {}
            )
            
            assert result is not None
            assert result['signal'] is True
            assert "Fixed Stop Loss" in result['reason']

    def test_check_sell_signal_target_profit(self, monitor_instance, mock_config, mock_db_session):
        """Test Target Profit Trigger"""
        with patch("monitor.database.get_daily_prices", return_value=pd.DataFrame()):
            monitor_instance.config.get_float.side_effect = lambda k, default: 10.0 if 'TARGET_PROFIT' in k else default
            
            # Buy 100, Current 120 (+20%) -> Should Trigger
            result = monitor_instance._check_sell_signal(
                mock_db_session, "005930", "Samsung", 100, 120, {}
            )
            
            assert result is not None
            assert result['signal'] is True
            assert "Target Profit" in result['reason']

    def test_check_sell_signal_atr_stop(self, monitor_instance, mock_config, mock_db_session):
        """Test ATR Trailing Stop"""
        # Mock daily prices for ATR calculation
        prices = pd.DataFrame({
            'high': [105]*20, 'low': [95]*20, 'close': [100]*20,
            'HIGH_PRICE': [105]*20, 'LOW_PRICE': [95]*20, 'CLOSE_PRICE': [100]*20
        })
        
        with patch("monitor.database.get_daily_prices", return_value=prices), \
             patch("monitor.strategy.calculate_atr", return_value=5.0): # ATR = 5
            
            monitor_instance.config.get_float.return_value = 2.0 # Multiplier
            
            # Stop Price = Buy(100) - (2.0 * 5) = 90
            # Current Price = 89 -> Trigger
            result = monitor_instance._check_sell_signal(
                mock_db_session, "005930", "Samsung", 100, 89, {}
            )
            
            assert result is not None
            assert "ATR Stop" in result['reason']

    def test_publish_sell_order(self, monitor_instance, mock_publisher):
        """Test publishing sell order to RabbitMQ"""
        signal = {"reason": "Test Reason", "quantity_pct": 50.0}
        holding = {"code": "005930", "name": "Samsung", "quantity": 10, "id": 1}
        
        monitor_instance._publish_sell_order(signal, holding, 100)
        
        mock_publisher.publish.assert_called_once()
        args = mock_publisher.publish.call_args[0][0]
        assert args['stock_code'] == "005930"
        assert args['quantity'] == 5 # 50% of 10
        assert args['sell_reason'] == "Test Reason"

    @patch("monitor.redis_cache")
    def test_process_price_alerts(self, mock_redis, monitor_instance, mock_kis):
        """Test price alert processing"""
        # Mock Redis alerts
        mock_redis.get_price_alerts.return_value = {
            "005930": {"target_price": 100000, "alert_type": "above", "stock_name": "Samsung"}
        }
        
        # Mock KIS current price
        mock_kis.get_stock_snapshot.return_value = {"price": 105000}
        
        # Mock Telegram Bot
        monitor_instance.telegram_bot = MagicMock()
        
        # Set Trading Mode REAL (via environment variable patch if needed, or mocking logic)
        with patch.dict(os.environ, {"TRADING_MODE": "REAL"}):
            monitor_instance._process_price_alerts()
        
        # Verify alert triggered
        monitor_instance.telegram_bot.send_message.assert_called_once()
        mock_redis.delete_price_alert.assert_called_with("005930")

    def test_monitor_with_polling_loop(self, monitor_instance, mock_kis, mock_publisher):
        """Test the polling loop execution flow"""
        # Mock dependencies for the loop
        monitor_instance.config.get_int.return_value = 0 # specific interval
        
        # Mock Session and Portfolio
        with patch("monitor.session_scope"), \
             patch("monitor.repo.get_active_portfolio") as mock_get_portfolio, \
             patch("monitor.database.get_daily_prices") as mock_get_prices, \
             patch.object(monitor_instance, '_check_sell_signal') as mock_check_signal:
             
            # Setup portfolio
            mock_get_portfolio.return_value = [
                {'code': '005930', 'name': 'Samsung', 'avg_price': 100000, 'quantity': 10}
            ]
            
            # Setup Price (Mock Mode default)
            mock_get_prices.return_value = pd.DataFrame({'CLOSE_PRICE': [105000]})
            
            # Setup Signal
            mock_check_signal.return_value = {"signal": True, "reason": "Test", "quantity_pct": 50}
            
            # Control Loop: Run once then stop
            # is_set() is called:
            # 1. while not is_set(): (False -> enter)
            # 2. inside loop "if is_set(): break" (False -> continue)
            # 3. next iteration while check (True -> exit)
            # Provide enough values
            monitor_instance.stop_event.is_set = MagicMock(side_effect=[False, False, True, True, True])
            
            monitor_instance._monitor_with_polling(dry_run=True)
            
            # Verify Flow
            mock_get_portfolio.assert_called()
            mock_check_signal.assert_called()
            mock_publisher.publish.assert_called() 

    def test_on_websocket_price_update(self, monitor_instance, mock_publisher):
        """Test WebSocket price update callback"""
        # Setup Cache
        monitor_instance.portfolio_cache = {
             1: {'code': '005930', 'name': 'Samsung', 'avg_price': 100000, 'quantity': 10, 'id': 1}
        }
        
        with patch("monitor.session_scope"), \
             patch.object(monitor_instance, '_check_sell_signal', return_value={"signal": True, "reason": "WS Test", "quantity_pct": 100}):
            
            monitor_instance._on_websocket_price_update('005930', 90000, 95000)
            
            # Should publish and remove from cache
            mock_publisher.publish.assert_called()
            assert 1 not in monitor_instance.portfolio_cache

    def test_check_sell_signal_rsi_overbought(self, monitor_instance, mock_db_session):
        """Test RSI Overbought Scale-out"""
        with patch("monitor.database.get_daily_prices", return_value=pd.DataFrame({'CLOSE_PRICE': [100]*20})), \
             patch("monitor.strategy.calculate_atr", return_value=None), \
             patch("monitor.strategy.calculate_rsi", return_value=80.0): # RSI > 75
            
            # Ensure Target Profit (10%) doesn't trigger at +10%
            # Set Target Profit to 20%
            monitor_instance.config.get_float.side_effect = lambda k, default: 75.0 if 'RSI' in k else (20.0 if 'TARGET' in k else -5.0)
            
            result = monitor_instance._check_sell_signal(
                mock_db_session, "005930", "Samsung", 100, 110, {}
            )
            
            assert result is not None
            assert "RSI Overbought" in result['reason']
            assert result['quantity_pct'] == 50.0

    def test_check_sell_signal_death_cross(self, monitor_instance, mock_db_session):
        """Test Death Cross Signal"""
        # Mock daily prices
        # Provide full columns to avoid ATR error or mock ATR
        daily_prices = pd.DataFrame({'CLOSE_PRICE': [100]*30})
        
        with patch("monitor.database.get_daily_prices", return_value=daily_prices), \
             patch("monitor.strategy.calculate_atr", return_value=None), \
             patch("monitor.strategy.calculate_rsi", return_value=None), \
             patch("monitor.strategy.check_death_cross", return_value=True):
            
            # Disable Stop Loss triggering (-5%) by setting very low limit or changing price change
            # Default mock_config returns -5.0. 
            # If price 100->100 (0%), Stop Loss triggers.
            # Change price 100->100 (0% change), Death Cross should still trigger if check_death_cross=True
            
            # Also Disable Target Profit (0% profit checks). Default mock returns MagicMock -> >= checks True.
            # We must force get_float to return high value for TARGET_PROFIT
            monitor_instance.config.get_float.side_effect = lambda k, default: 999.0 if 'TARGET' in k else -5.0

            result = monitor_instance._check_sell_signal(
                mock_db_session, "005930", "Samsung", 100, 100, {}
            )
            
            assert result is not None
            assert "Death Cross" in result['reason']

    def test_check_sell_signal_max_holding_days(self, monitor_instance, mock_db_session):
        """Test Max Holding Days Exceeded"""
        monitor_instance.config.get_int.return_value = 10
        # Prevent Target Profit triggering (Default mock returns MagicMock -> comparison might be weird)
        # Explicitly set Target Profit high
        monitor_instance.config.get_float.return_value = 99.0
        
        buy_date = (datetime.now() - timedelta(days=11)).strftime('%Y%m%d')
        holding = {'buy_date': buy_date}
        
        with patch("monitor.database.get_daily_prices", return_value=pd.DataFrame()), \
             patch("monitor.strategy.calculate_atr", return_value=None):
            
            result = monitor_instance._check_sell_signal(
                mock_db_session, "005930", "Samsung", 100, 100, holding
            )
            
            assert result is not None
            assert "Max Holding Days" in result['reason']

    def test_start_monitoring_market_check(self, monitor_instance):
        """Test market open check prevents monitoring"""
        monitor_instance.kis.check_market_open = MagicMock(return_value=False)
        monitor_instance._monitor_with_polling = MagicMock()
        
        monitor_instance.start_monitoring()
        
        monitor_instance._monitor_with_polling.assert_not_called()

    def test_stop_monitoring(self, monitor_instance):
        """Test stop monitoring signal"""
        monitor_instance.stop_monitoring()
        assert monitor_instance.stop_event.is_set()

    @pytest.mark.skip(reason="Patches global datetime.datetime which causes test pollution")
    def test_start_monitoring_fallback_time_check(self, monitor_instance):
        """Test fallback time check when check_market_open is missing"""
        # Remove check_market_open from mock
        del monitor_instance.kis.check_market_open
        
        # Mock datetime to be Sunday (weekday 6)
        with patch("monitor.datetime") as mock_datetime:
            # Create a mock datetime object that returns 6 for weekday()
            # Note: monitor.py imports datetime using `from datetime import datetime` twice.
            # One generic, one inside the method.
            # The method uses `from datetime import datetime` locally, so patching `monitor.datetime` works if it targets the module.
            # However `monitor.py` has `from datetime import datetime` at top level too.
            # Inside `start_monitoring`:
            # `from datetime import datetime` -> This shadows the global one.
            # So `patch("monitor.datetime")` might NOT work for the local import inside function?
            # Actually weak point. If function imports it, we should patch where it's looked up.
            # But since it's "monitor.datetime", wait.
            # 'monitor.py' line 60: `from datetime import datetime`
            # This is a local import. Mocking `monitor.datetime` usually affects global scope in monitor module.
            # Local import `from datetime import datetime` creates a NEW local variable `datetime`.
            # We cannot patch a local variable inside a function.
            # We must patch `datetime.datetime` globally so the import fetches the mock.
            pass

        # Since I cannot easily patch local import inside function without patching sys.modules or datetime.datetime globally:
        # I'll rely on patching `monitor.datetime` and hope the user code used global one or I can change the code?
        # No, I should not change code just for test if possible.
        # But wait, line 8 says `from datetime import datetime`.
        # Line 60 says `from datetime import datetime`.
        # Redundant import.
        
        # Let's try patching `datetime.datetime` completely.
        with patch("datetime.datetime") as mock_dt:
            mock_dt.now.return_value.weekday.return_value = 6 # Sunday
            monitor_instance._monitor_with_polling = MagicMock()
            
            # We need to make sure the class is initialized correctly before this patch if it uses datetime?
            # It uses `Event` and others.
            
            monitor_instance.start_monitoring()
            monitor_instance._monitor_with_polling.assert_not_called()
