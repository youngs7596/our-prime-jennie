# tests/e2e/test_sell_flow.py
"""
E2E Tests: Sell Flow

Tests the complete sell execution flow including:
- Stop loss trigger → Sell execution → DB update
- Take profit trigger
- RSI overheat exit
- Time-based liquidation
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from tests.e2e.conftest import create_portfolio_item


@pytest.mark.e2e
class TestSellFlow:
    """Tests for sell execution flow"""

    def test_stop_loss_sell_success(
        self, kis_server, mock_config, sell_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Stop loss trigger causes successful sell.

        Flow:
        1. Price drops below stop loss
        2. SellExecutor receives sell order
        3. Place sell order
        4. Record in DB
        """
        # Mock portfolio with position at loss
        portfolio_item = create_portfolio_item(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=10,
            avg_price=70000
        )

        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[portfolio_item])
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BEAR'})
        mocker.patch('shared.database.get_rag_context_with_validation', return_value=("", False, None))
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)
        mocker.patch('shared.redis_cache.delete_high_watermark')
        mocker.patch('shared.redis_cache.delete_scale_out_level')
        mocker.patch('shared.redis_cache.delete_profit_floor')
        mocker.patch('shared.db.repository.check_duplicate_order', return_value=False)

        mock_kis = MagicMock()
        mock_kis.get_stock_snapshot.return_value = {'price': 63000}  # -10% from buy
        mock_kis.place_sell_order.return_value = "SELL_12345"

        executor = sell_executor_class(kis=mock_kis, config=mock_config)

        result = executor.execute_sell_order(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=10,
            sell_reason="Stop Loss Triggered",
            current_price=63000,
            dry_run=False
        )

        assert result['status'] == 'success'
        assert result['order_no'] == 'SELL_12345'
        assert result['profit_pct'] < 0  # Should be negative
        mock_kis.place_sell_order.assert_called_once()

    def test_take_profit_sell_success(
        self, kis_server, mock_config, sell_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Take profit trigger causes successful sell.
        """
        portfolio_item = create_portfolio_item(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=10,
            avg_price=70000
        )

        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[portfolio_item])
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'STRONG_BULL'})
        mocker.patch('shared.database.get_rag_context_with_validation', return_value=("", False, None))
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)
        mocker.patch('shared.redis_cache.delete_high_watermark')
        mocker.patch('shared.redis_cache.delete_scale_out_level')
        mocker.patch('shared.redis_cache.delete_profit_floor')
        mocker.patch('shared.db.repository.check_duplicate_order', return_value=False)

        mock_kis = MagicMock()
        mock_kis.get_stock_snapshot.return_value = {'price': 84000}  # +20% from buy
        mock_kis.place_sell_order.return_value = "SELL_PROFIT"

        executor = sell_executor_class(kis=mock_kis, config=mock_config)

        result = executor.execute_sell_order(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=10,
            sell_reason="Take Profit Target Reached",
            current_price=84000,
            dry_run=False
        )

        assert result['status'] == 'success'
        assert result['profit_pct'] > 0  # Should be positive
        assert result['profit_pct'] == pytest.approx(20.0, rel=0.1)

    def test_rsi_overheat_sell(
        self, kis_server, mock_config, sell_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: RSI overheat condition triggers sell.
        """
        portfolio_item = create_portfolio_item(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=10,
            avg_price=70000
        )

        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[portfolio_item])
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.database.get_rag_context_with_validation', return_value=("", False, None))
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)
        mocker.patch('shared.redis_cache.delete_high_watermark')
        mocker.patch('shared.redis_cache.delete_scale_out_level')
        mocker.patch('shared.redis_cache.delete_profit_floor')
        mocker.patch('shared.db.repository.check_duplicate_order', return_value=False)

        mock_kis = MagicMock()
        mock_kis.get_stock_snapshot.return_value = {'price': 77000}
        mock_kis.place_sell_order.return_value = "SELL_RSI"

        executor = sell_executor_class(kis=mock_kis, config=mock_config)

        result = executor.execute_sell_order(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=10,
            sell_reason="RSI Overheat (>80)",
            current_price=77000,
            dry_run=False
        )

        assert result['status'] == 'success'
        assert 'RSI' in result['sell_reason']

    def test_time_based_liquidation(
        self, kis_server, mock_config, sell_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Time-based liquidation after holding period.
        """
        # Create position from 10 days ago
        old_date = datetime.now(timezone.utc) - timedelta(days=10)
        portfolio_item = create_portfolio_item(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=10,
            avg_price=70000,
            created_at=old_date
        )

        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[portfolio_item])
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'SIDEWAYS'})
        mocker.patch('shared.database.get_rag_context_with_validation', return_value=("", False, None))
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)
        mocker.patch('shared.redis_cache.delete_high_watermark')
        mocker.patch('shared.redis_cache.delete_scale_out_level')
        mocker.patch('shared.redis_cache.delete_profit_floor')
        mocker.patch('shared.db.repository.check_duplicate_order', return_value=False)

        mock_kis = MagicMock()
        mock_kis.get_stock_snapshot.return_value = {'price': 71000}
        mock_kis.place_sell_order.return_value = "SELL_TIME"

        executor = sell_executor_class(kis=mock_kis, config=mock_config)

        result = executor.execute_sell_order(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=10,
            sell_reason="Time Liquidation (10+ days)",
            current_price=71000,
            dry_run=False
        )

        assert result['status'] == 'success'

    def test_sell_not_in_portfolio_fails(
        self, kis_server, mock_config, sell_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Selling stock not in portfolio returns error.
        """
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])  # Empty portfolio
        mocker.patch('shared.redis_cache.is_trading_stopped', return_value=False)

        mock_kis = MagicMock()
        executor = sell_executor_class(kis=mock_kis, config=mock_config)

        result = executor.execute_sell_order(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=10,
            sell_reason="Test Sell",
            dry_run=False
        )

        assert result['status'] == 'error'
        assert 'Not in portfolio' in result['reason']

    def test_emergency_stop_blocks_auto_sell(
        self, kis_server, mock_config, sell_executor_module, e2e_db, mocker
    ):
        """
        Test: Emergency stop blocks automatic sells (but not manual).
        """
        # Patch at the dynamically loaded module level
        mocker.patch.object(sell_executor_module, 'is_trading_stopped', return_value=True)

        mock_kis = MagicMock()
        executor = sell_executor_module.SellExecutor(kis=mock_kis, config=mock_config)

        # Auto sell should be blocked
        result = executor.execute_sell_order(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=10,
            sell_reason="Stop Loss Auto",  # Not manual
            dry_run=False
        )

        assert result['status'] == 'skipped'
        assert 'Emergency Stop' in result['reason']

    def test_manual_sell_allowed_during_emergency(
        self, kis_server, mock_config, sell_executor_module, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Manual sells are allowed even during emergency stop.
        """
        portfolio_item = create_portfolio_item(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=10,
            avg_price=70000
        )

        # Patch at the dynamically loaded module level
        mocker.patch.object(sell_executor_module, 'is_trading_stopped', return_value=True)
        mocker.patch.object(sell_executor_module, 'get_redis_connection', return_value=mock_redis_connection)

        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[portfolio_item])
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BEAR'})
        mocker.patch('shared.database.get_rag_context_with_validation', return_value=("", False, None))
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)
        mocker.patch('shared.redis_cache.delete_high_watermark')
        mocker.patch('shared.redis_cache.delete_scale_out_level')
        mocker.patch('shared.redis_cache.delete_profit_floor')
        mocker.patch('shared.db.repository.check_duplicate_order', return_value=False)

        mock_kis = MagicMock()
        mock_kis.get_stock_snapshot.return_value = {'price': 65000}
        mock_kis.place_sell_order.return_value = "SELL_MANUAL"

        executor = sell_executor_module.SellExecutor(kis=mock_kis, config=mock_config)

        # Manual sell should work
        result = executor.execute_sell_order(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=10,
            sell_reason="MANUAL: User requested sell",
            current_price=65000,
            dry_run=False
        )

        assert result['status'] == 'success'

    def test_duplicate_sell_blocked(
        self, kis_server, mock_config, sell_executor_module, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Duplicate sell orders within time window are blocked.
        """
        portfolio_item = create_portfolio_item(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=10,
            avg_price=70000
        )

        # Patch at the dynamically loaded module level
        mocker.patch.object(sell_executor_module, 'is_trading_stopped', return_value=False)
        mocker.patch.object(sell_executor_module, 'get_redis_connection', return_value=mock_redis_connection)

        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[portfolio_item])
        mocker.patch('shared.db.repository.check_duplicate_order', return_value=True)  # Duplicate detected

        mock_kis = MagicMock()
        executor = sell_executor_module.SellExecutor(kis=mock_kis, config=mock_config)

        result = executor.execute_sell_order(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=10,
            sell_reason="Stop Loss",
            dry_run=False
        )

        assert result['status'] == 'skipped'
        assert 'Duplicate' in result['reason']

    def test_partial_sell_success(
        self, kis_server, mock_config, sell_executor_module, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Partial sell of position works correctly.
        """
        portfolio_item = create_portfolio_item(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=10,  # Have 10 shares
            avg_price=70000
        )

        # Patch at the dynamically loaded module level
        mocker.patch.object(sell_executor_module, 'is_trading_stopped', return_value=False)
        mocker.patch.object(sell_executor_module, 'get_redis_connection', return_value=mock_redis_connection)

        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[portfolio_item])
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.database.get_rag_context_with_validation', return_value=("", False, None))
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)
        mocker.patch('shared.redis_cache.delete_high_watermark')
        mocker.patch('shared.redis_cache.delete_scale_out_level')
        mocker.patch('shared.redis_cache.delete_profit_floor')
        mocker.patch('shared.db.repository.check_duplicate_order', return_value=False)

        mock_kis = MagicMock()
        mock_kis.get_stock_snapshot.return_value = {'price': 75000}
        mock_kis.place_sell_order.return_value = "SELL_PARTIAL"

        executor = sell_executor_module.SellExecutor(kis=mock_kis, config=mock_config)

        # Sell only 5 shares (partial)
        result = executor.execute_sell_order(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=5,  # Partial sell
            sell_reason="Scale Out",
            current_price=75000,
            dry_run=False
        )

        assert result['status'] == 'success'
        assert result['quantity'] == 5


@pytest.mark.e2e
class TestSellCalculations:
    """Tests for sell-related calculations"""

    def test_profit_calculation_accuracy(
        self, kis_server, mock_config, sell_executor_module, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Profit calculations are accurate.
        """
        buy_price = 70000
        sell_price = 77000
        quantity = 10
        expected_profit_pct = ((sell_price - buy_price) / buy_price) * 100
        expected_profit_amount = (sell_price - buy_price) * quantity

        portfolio_item = create_portfolio_item(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=quantity,
            avg_price=buy_price
        )

        # Patch at the dynamically loaded module level
        mocker.patch.object(sell_executor_module, 'is_trading_stopped', return_value=False)
        mocker.patch.object(sell_executor_module, 'get_redis_connection', return_value=mock_redis_connection)

        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[portfolio_item])
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.database.get_rag_context_with_validation', return_value=("", False, None))
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)
        mocker.patch('shared.redis_cache.delete_high_watermark')
        mocker.patch('shared.redis_cache.delete_scale_out_level')
        mocker.patch('shared.redis_cache.delete_profit_floor')
        mocker.patch('shared.db.repository.check_duplicate_order', return_value=False)

        mock_kis = MagicMock()
        mock_kis.place_sell_order.return_value = "SELL_CALC"

        executor = sell_executor_module.SellExecutor(kis=mock_kis, config=mock_config)

        result = executor.execute_sell_order(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=quantity,
            sell_reason="Test",
            current_price=sell_price,
            dry_run=False
        )

        assert result['profit_pct'] == pytest.approx(expected_profit_pct, rel=0.01)
        assert result['profit_amount'] == expected_profit_amount
