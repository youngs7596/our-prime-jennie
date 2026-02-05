# tests/services/price-monitor/test_monitor.py
# PriceMonitor 유닛 테스트 (unittest 변환)

import unittest
from unittest.mock import MagicMock, patch, ANY
import sys
import os
import pandas as pd
from datetime import datetime, timedelta
import importlib.util

# Project Root Setup
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if PROJECT_ROOT not in sys.path:
    # sys.path.insert(0, PROJECT_ROOT)
    pass

# Standard import via importlib to avoid sys.path and legacy loader issues
def load_monitor_module():
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
    module_path = os.path.join(PROJECT_ROOT, 'services', 'price-monitor', 'monitor.py')
    spec = importlib.util.spec_from_file_location("monitor", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["monitor"] = module
    spec.loader.exec_module(module)
    return module

monitor_mod = load_monitor_module()
PriceMonitor = monitor_mod.PriceMonitor


class TestPriceMonitor(unittest.TestCase):
    
    def setUp(self):
        self.mock_kis = MagicMock()
        
        self.mock_config = MagicMock()
        self.mock_config.get_float.return_value = -5.0 # Stop Loss default
        self.mock_config.get_int.return_value = 30 # Max holding days
        # per-symbol getter defaults
        self.mock_config.get_float_for_symbol.side_effect = lambda code, k, default=None: self.mock_config.get_float(k, default)
        self.mock_config.get_int_for_symbol.side_effect = lambda code, k, default=None: self.mock_config.get_int(k, default)
        self.mock_config.get_bool.return_value = False
        
        self.mock_publisher = MagicMock()
        self.mock_db_session = MagicMock()
        
        self.monitor = PriceMonitor(self.mock_kis, self.mock_config, self.mock_publisher)

    def tearDown(self):
        pass

    def test_check_sell_signal_stop_loss(self):
        """Test Fixed Stop Loss Trigger"""
        with patch("monitor.database.get_daily_prices", return_value=pd.DataFrame()), \
             patch("monitor.repo.get_active_portfolio") as mock_get_p:
            mock_get_p.return_value = [{'code': '005930', 'avg_price': 100}]
            self.mock_config.get_float.side_effect = lambda k, default: -5.0 if 'STOP_LOSS' in k else default
            
            # Buy 100, Current 90 (-10%) -> Should Trigger
            holding = {'code': '005930', 'name': 'Samsung', 'avg_price': 100, 'quantity': 10, 'id': 1}
            result = self.monitor._check_sell_signal(
                self.mock_db_session, "005930", "Samsung", 100, 90, holding
            )
            
            self.assertIsNotNone(result)
            self.assertTrue(result['signal'])
            self.assertIn("Fixed Stop Loss", result['reason'])

    def test_check_sell_signal_target_profit(self):
        """Test Target Profit Trigger (트레일링/분할 익절 비활성화 시)"""
        def config_side_effect(key, default=None):
            config_map = {
                'SELL_TARGET_PROFIT_PCT': 10.0,
                'TRAILING_TAKE_PROFIT_ENABLED': False,
                'SCALE_OUT_ENABLED': False,
                'SELL_STOP_LOSS_PCT': -5.0,
            }
            return config_map.get(key, default)
        
        self.mock_config.get_float.side_effect = config_side_effect
        self.mock_config.get_bool.side_effect = lambda k, default=False: config_side_effect(k, default)
        
        with patch("monitor.database.get_daily_prices", return_value=pd.DataFrame()), \
             patch("monitor.update_high_watermark", return_value={"high_price": 120, "buy_price": 100, "profit_from_high_pct": 0, "updated": False}), \
             patch("monitor.get_scale_out_level", return_value=0), \
             patch("monitor.repo.get_active_portfolio") as mock_get_p:
            mock_get_p.return_value = [{'code': '005930', 'avg_price': 100}]
            
            # Buy 100, Current 120 (+20%) -> Should Trigger
            holding = {'code': '005930', 'name': 'Samsung', 'avg_price': 100, 'quantity': 10, 'id': 1}
            result = self.monitor._check_sell_signal(
                self.mock_db_session, "005930", "Samsung", 100, 120, holding
            )
            
            self.assertIsNotNone(result)
            self.assertTrue(result['signal'])
            self.assertIn("Target Profit", result['reason'])

    def test_check_sell_signal_atr_stop(self):
        """Test ATR Trailing Stop"""
        prices = pd.DataFrame({
            'high': [105]*20, 'low': [95]*20, 'close': [100]*20,
            'HIGH_PRICE': [105]*20, 'LOW_PRICE': [95]*20, 'CLOSE_PRICE': [100]*20
        })

        def config_side_effect(key, default=None):
            config_map = {
                'ATR_MULTIPLIER': 1.0,  # 1.0x ATR
                'SELL_STOP_LOSS_PCT': -10.0,  # Fixed stop at -10% (wider than ATR stop)
            }
            return config_map.get(key, default)

        self.mock_config.get_float.side_effect = config_side_effect

        with patch("monitor.database.get_daily_prices", return_value=prices), \
             patch("monitor.strategy.calculate_atr", return_value=5.0), \
             patch("monitor.strategy.check_death_cross", return_value=False), \
             patch("monitor.repo.get_active_portfolio") as mock_get_p: # ATR = 5
            mock_get_p.return_value = [{'code': '005930', 'avg_price': 100}]

            # ATR Stop = Buy(100) - (1.0 * macro_mult * 5) = 100 - (1.0 * 1.3 * 5) = 93.5
            # Fixed Stop = -10% * 1.3 = -13% (wider, won't trigger first)
            # Current Price = 93 -> ATR Stop Trigger (-7%)
            holding = {'code': '005930', 'name': 'Samsung', 'avg_price': 100, 'quantity': 10, 'id': 1}
            result = self.monitor._check_sell_signal(
                self.mock_db_session, "005930", "Samsung", 100, 93, holding
            )

            self.assertIsNotNone(result)
            self.assertIn("ATR Stop", result['reason'])

    def test_publish_sell_order(self):
        """Test publishing sell order to RabbitMQ"""
        signal = {"reason": "Test Reason", "quantity_pct": 50.0}
        holding = {"code": "005930", "name": "Samsung", "quantity": 10, "id": 1}
        
        self.monitor._publish_sell_order(signal, holding, 100)
        
        self.mock_publisher.publish.assert_called_once()
        args = self.mock_publisher.publish.call_args[0][0]
        self.assertEqual(args['stock_code'], "005930")
        self.assertEqual(args['quantity'], 5) # 50% of 10
        self.assertEqual(args['sell_reason'], "Test Reason")

    @patch("monitor.redis_cache")
    def test_process_price_alerts(self, mock_redis):
        """Test price alert processing"""
        mock_redis.get_price_alerts.return_value = {
            "005930": {"target_price": 100000, "alert_type": "above", "stock_name": "Samsung"}
        }
        
        self.mock_kis.get_stock_snapshot.return_value = {"price": 105000}
        self.monitor.telegram_bot = MagicMock()
        
        with patch.dict(os.environ, {"TRADING_MODE": "REAL"}):
            self.monitor._process_price_alerts()
        
        self.monitor.telegram_bot.send_message.assert_called_once()
        mock_redis.delete_price_alert.assert_called_with("005930")

    def test_on_websocket_price_update(self):
        """Test WebSocket price update callback (used by StreamConsumer too)"""
        self.monitor.portfolio_cache = {
             1: {'code': '005930', 'name': 'Samsung', 'avg_price': 100000, 'quantity': 10, 'id': 1}
        }
        
        with patch("monitor.session_scope"), \
             patch.object(self.monitor, '_check_sell_signal', return_value={"signal": True, "reason": "Stream Test", "quantity_pct": 100}):
            
            self.monitor._on_websocket_price_update('005930', 90000, 95000)
            
            self.mock_publisher.publish.assert_called()
            self.assertNotIn(1, self.monitor.portfolio_cache)

    def test_check_sell_signal_rsi_overbought(self):
        """Test RSI Overbought Scale-out (requires 3%+ profit)"""
        def config_side_effect(key, default=None):
            config_map = {
                'SELL_RSI_OVERBOUGHT_THRESHOLD': 75.0,
                'SELL_RSI_MIN_PROFIT_PCT': 3.0,
                'SELL_TARGET_PROFIT_PCT': 20.0,
                'SELL_STOP_LOSS_PCT': -5.0,
                'TRAILING_TAKE_PROFIT_ENABLED': False,
                'SCALE_OUT_ENABLED': False,
            }
            return config_map.get(key, default)
        
        self.mock_config.get_float.side_effect = config_side_effect
        self.mock_config.get_bool.side_effect = lambda k, default=False: config_side_effect(k, default)
        self.mock_config.get_float_for_symbol.side_effect = lambda code, k, default=None: config_side_effect(k, default)
        
        # Buy price=100, Current price=105 (5% profit, satisfies 3% minimum)
        with patch("monitor.database.get_daily_prices", return_value=pd.DataFrame({'CLOSE_PRICE': [100]*20})), \
             patch("monitor.strategy.calculate_atr", return_value=None), \
             patch("monitor.strategy.calculate_rsi", return_value=80.0), \
             patch("monitor.update_high_watermark", return_value={"high_price": 105, "buy_price": 100, "profit_from_high_pct": 0, "updated": False}), \
             patch("monitor.get_scale_out_level", return_value=0), \
             patch("monitor.get_rsi_overbought_sold", return_value=False), \
             patch("monitor.set_rsi_overbought_sold", return_value=None), \
             patch("monitor.repo.get_active_portfolio") as mock_get_p:
            mock_get_p.return_value = [{'code': '005930', 'avg_price': 100}]
            
            holding = {'code': '005930', 'name': 'Samsung', 'avg_price': 100, 'quantity': 10, 'id': 1}
            result = self.monitor._check_sell_signal(
                self.mock_db_session, "005930", "Samsung", 100, 105, holding  # 5% profit
            )
            
            self.assertIsNotNone(result)
            self.assertIn("RSI Overbought", result['reason'])
            self.assertEqual(result['quantity_pct'], 50.0)

    def test_check_sell_signal_death_cross(self):
        """Test Death Cross Signal"""
        daily_prices = pd.DataFrame({'CLOSE_PRICE': [100]*30})
        
        with patch("monitor.database.get_daily_prices", return_value=daily_prices), \
             patch("monitor.strategy.calculate_atr", return_value=None), \
             patch("monitor.strategy.calculate_rsi", return_value=None), \
             patch("monitor.strategy.check_death_cross", return_value=True), \
             patch("monitor.repo.get_active_portfolio") as mock_get_p:
            mock_get_p.return_value = [{'code': '005930', 'avg_price': 100}]
            
            self.mock_config.get_float.side_effect = lambda k, default: 999.0 if 'TARGET' in k else -5.0

            holding = {'code': '005930', 'name': 'Samsung', 'avg_price': 100, 'quantity': 10, 'id': 1}
            result = self.monitor._check_sell_signal(
                self.mock_db_session, "005930", "Samsung", 100, 100, holding
            )
            
            self.assertIsNotNone(result)
            self.assertIn("Death Cross", result['reason'])

    def test_check_sell_signal_max_holding_days(self):
        """Test Max Holding Days Exceeded"""
        self.mock_config.get_int.return_value = 10
        self.mock_config.get_float.return_value = 99.0
        
        buy_date = (datetime.now() - timedelta(days=11)).strftime('%Y%m%d')
        holding = {'code': '005930', 'buy_date': buy_date, 'avg_price': 100, 'quantity': 10, 'id': 1}
        
        with patch("monitor.database.get_daily_prices", return_value=pd.DataFrame()), \
             patch("monitor.strategy.calculate_atr", return_value=None), \
             patch("monitor.repo.get_active_portfolio") as mock_get_p:
            mock_get_p.return_value = [{'code': '005930', 'avg_price': 100}]
            
            result = self.monitor._check_sell_signal(
                self.mock_db_session, "005930", "Samsung", 100, 100, holding
            )
            
            self.assertIsNotNone(result)
            self.assertIn("Max Holding Days", result['reason'])

    @patch("monitor.StreamPriceConsumer")
    def test_monitor_with_redis_streams(self, MockConsumer):
        """Test Redis Streams monitoring flow"""
        mock_consumer_instance = MockConsumer.return_value
        # inner loop breaks on second call
        mock_consumer_instance.is_connected.side_effect = [True, False] 
        
        with patch("monitor.session_scope"), \
             patch("monitor.repo.get_active_portfolio") as mock_get_portfolio, \
             patch("time.sleep"):
             
            mock_get_portfolio.return_value = [
                {'code': '005930', 'name': 'Samsung', 'id': 1}
            ]
            
            # Make the outer loop break after one iteration
            # logic: [outer_check=False, inner_check=False(ignored due to is_connected=True), outer_check_after_break=True]
            # Wait, outer loop is `while not self.stop_event.is_set()`
            # Inside: `while self.stream_consumer.is_connected() and not self.stop_event.is_set()`
            
            # We can just set stop_event.is_set side effect
            self.monitor.stop_event = MagicMock()
            self.monitor.stop_event.is_set.side_effect = [False, False, True] 
            # 1. Outer loop check (False -> enter)
            # 2. Inner loop check (False -> continue, AND is_connected=True)
            # 3. Inner loop check 2 (is_connected=False -> break inner)
            # 4. End of outer loop check (if self.stop_event.is_set(): break) -> Wait, logic is:
            #    if self.stop_event.is_set(): break
            #    logger.warning...
            #    next outer loop iteration check
            
            # Implementation:
            # while not stop_event.is_set(): # Call 1
            #    ...
            #    start_consuming
            #    while is_connected and not stop_event.is_set(): # Call 2 (is_connected=True)
            #        sleep 1
            #        ...
            #    # Next is_connected=False -> breaks inner loop
            #    if stop_event.is_set(): # Call 3
            #        break
            
            # So [False, False, True] should work.

            with patch.dict(monitor_mod.__dict__, {"REDIS_STREAMS_AVAILABLE": True}):
                 self.monitor._monitor_with_redis_streams(dry_run=True)
                 
            mock_consumer_instance.start_consuming.assert_called()
            mock_consumer_instance.stop.assert_called()

if __name__ == '__main__':
    unittest.main()
