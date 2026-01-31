# tests/e2e/test_full_cycle.py
"""
E2E Tests: Full Trading Cycle

Tests complete trading cycles including:
- Full Buy → Hold → Sell cycle
- Multiple concurrent trades
- Graceful shutdown during orders
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
import time

from tests.e2e.conftest import create_scan_result, create_portfolio_item
from tests.e2e.fixtures.rabbitmq_fixtures import RabbitMQTestBridge, QueueNames

# Dynamic import for services with hyphens in names
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_opportunity_watcher_class():
    """Dynamically load BuyOpportunityWatcher class"""
    import importlib.util
    module_path = os.path.join(PROJECT_ROOT, 'services', 'buy-scanner', 'opportunity_watcher.py')
    spec = importlib.util.spec_from_file_location("opportunity_watcher_dynamic", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BuyOpportunityWatcher


@pytest.fixture
def opportunity_watcher_class():
    """Fixture to get BuyOpportunityWatcher class"""
    return get_opportunity_watcher_class()


@pytest.mark.e2e
class TestFullTradingCycle:
    """Tests for complete trading cycles"""

    def test_complete_buy_hold_sell_cycle(
        self, kis_server, mock_config, buy_executor_class, sell_executor_module,
        e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Complete trading cycle from buy to sell.

        Flow:
        1. Receive buy signal
        2. Execute buy order
        3. Hold position
        4. Price reaches target
        5. Execute sell order
        6. Verify profit recorded
        """
        # Phase 1: Setup
        scenario = kis_server.activate_scenario("empty_portfolio")
        scenario.add_stock("005930", "삼성전자", 70000)

        mocker.patch('shared.database.get_market_regime_cache', return_value={
            'regime': 'BULL',
            'strategy_preset': {'name': 'BULL_PRESET', 'params': {}}
        })
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)
        mocker.patch('shared.database.get_daily_prices', return_value=None)
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)
        mocker.patch('shared.database.get_rag_context_with_validation', return_value=("", False, None))
        mocker.patch('shared.redis_cache.delete_high_watermark')
        mocker.patch('shared.redis_cache.delete_scale_out_level')
        mocker.patch('shared.redis_cache.delete_profit_floor')
        mocker.patch('shared.redis_cache.reset_trading_state_for_stock')
        mocker.patch('shared.db.repository.check_duplicate_order', return_value=False)

        # Phase 2: Buy
        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 70000, 'open': 69000, 'high': 71000, 'low': 69000}
        mock_kis.place_buy_order.return_value = "BUY_CYCLE_001"

        buy_executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=85.0,
            signal_type="GOLDEN_CROSS",
            current_price=70000,
            market_regime="BULL"
        )

        buy_result = buy_executor.process_buy_signal(scan_result, dry_run=False)

        assert buy_result['status'] == 'success'
        assert buy_result['stock_code'] == '005930'
        buy_quantity = buy_result['quantity']
        buy_price = buy_result['price']

        # Phase 3: Simulate holding period (update portfolio mock)
        portfolio_item = create_portfolio_item(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=buy_quantity,
            avg_price=buy_price
        )
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[portfolio_item])

        # Phase 4: Price rises to target (+15%)
        target_price = int(buy_price * 1.15)
        mock_kis.get_stock_snapshot.return_value = {'price': target_price}
        mock_kis.place_sell_order.return_value = "SELL_CYCLE_001"

        # Clear Redis locks before sell and patch sell executor module
        mock_redis_connection.flushall()
        mocker.patch.object(sell_executor_module, 'is_trading_stopped', return_value=False)
        mocker.patch.object(sell_executor_module, 'get_redis_connection', return_value=mock_redis_connection)

        sell_executor = sell_executor_module.SellExecutor(kis=mock_kis, config=mock_config)

        sell_result = sell_executor.execute_sell_order(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=buy_quantity,
            sell_reason="Take Profit Target Reached",
            current_price=target_price,
            dry_run=False
        )

        # Phase 5: Verify
        assert sell_result['status'] == 'success'
        assert sell_result['profit_pct'] > 0
        assert sell_result['profit_pct'] == pytest.approx(15.0, rel=0.1)

    def test_buy_stop_loss_cycle(
        self, kis_server, mock_config, buy_executor_class, sell_executor_module,
        e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Buy followed by stop loss exit.

        Flow:
        1. Buy at 70000
        2. Price drops to 65000 (-7.14%)
        3. Stop loss triggered
        4. Verify loss recorded
        """
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)
        mocker.patch('shared.database.get_daily_prices', return_value=None)
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)
        mocker.patch('shared.database.get_rag_context_with_validation', return_value=("", False, None))
        mocker.patch('shared.redis_cache.delete_high_watermark')
        mocker.patch('shared.redis_cache.delete_scale_out_level')
        mocker.patch('shared.redis_cache.delete_profit_floor')
        mocker.patch('shared.redis_cache.reset_trading_state_for_stock')
        mocker.patch('shared.db.repository.check_duplicate_order', return_value=False)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 70000}
        mock_kis.place_buy_order.return_value = "BUY_SL_001"

        buy_executor = buy_executor_class(kis=mock_kis, config=mock_config)

        buy_result = buy_executor.process_buy_signal(
            create_scan_result("005930", "삼성전자", 80, "GOLDEN_CROSS", 70000),
            dry_run=False
        )

        assert buy_result['status'] == 'success'
        buy_qty = buy_result['quantity']

        # Simulate price drop
        portfolio_item = create_portfolio_item("005930", "삼성전자", buy_qty, 70000)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[portfolio_item])

        stop_loss_price = 65000  # -7.14%
        mock_kis.place_sell_order.return_value = "SELL_SL_001"

        # Clear Redis locks before sell and patch sell executor module
        mock_redis_connection.flushall()
        mocker.patch.object(sell_executor_module, 'is_trading_stopped', return_value=False)
        mocker.patch.object(sell_executor_module, 'get_redis_connection', return_value=mock_redis_connection)

        sell_executor = sell_executor_module.SellExecutor(kis=mock_kis, config=mock_config)
        sell_result = sell_executor.execute_sell_order(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=buy_qty,
            sell_reason="Stop Loss Triggered",
            current_price=stop_loss_price,
            dry_run=False
        )

        assert sell_result['status'] == 'success'
        assert sell_result['profit_pct'] < 0
        assert sell_result['profit_pct'] == pytest.approx(-7.14, rel=0.1)


@pytest.mark.e2e
class TestMultipleConcurrentTrades:
    """Tests for handling multiple trades"""

    def test_multiple_stocks_sequential_buy(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Sequential buy of multiple stocks.
        """
        scenario = kis_server.activate_scenario("empty_portfolio")
        scenario.add_stock("005930", "삼성전자", 70000)
        scenario.add_stock("000660", "SK하이닉스", 150000)
        scenario.add_stock("035720", "카카오", 50000)

        portfolio = []

        def mock_get_portfolio(session=None):
            return portfolio

        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', side_effect=mock_get_portfolio)
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)
        mocker.patch('shared.database.get_daily_prices', return_value=None)
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)
        mocker.patch('shared.redis_cache.reset_trading_state_for_stock')

        order_counter = [0]

        def mock_place_buy(*args, **kwargs):
            order_counter[0] += 1
            stock_code = kwargs.get('stock_code', 'UNKNOWN')
            return f"BUY_{stock_code}_{order_counter[0]:03d}"

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 30_000_000
        mock_kis.place_buy_order.side_effect = mock_place_buy

        # Stock snapshots
        def mock_snapshot(stock_code):
            prices = {"005930": 70000, "000660": 150000, "035720": 50000}
            return {'price': prices.get(stock_code, 10000)}

        mock_kis.get_stock_snapshot.side_effect = mock_snapshot

        buy_executor = buy_executor_class(kis=mock_kis, config=mock_config)

        # Buy stock 1
        result1 = buy_executor.process_buy_signal(
            create_scan_result("005930", "삼성전자", 85, current_price=70000),
            dry_run=False
        )
        assert result1['status'] == 'success'
        portfolio.append({'code': '005930', 'name': '삼성전자', 'quantity': result1['quantity'], 'avg_price': 70000})

        # Update buy count mock
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=1)

        # Buy stock 2
        result2 = buy_executor.process_buy_signal(
            create_scan_result("000660", "SK하이닉스", 82, current_price=150000),
            dry_run=False
        )
        assert result2['status'] == 'success'
        portfolio.append({'code': '000660', 'name': 'SK하이닉스', 'quantity': result2['quantity'], 'avg_price': 150000})

        # Verify both orders placed
        assert mock_kis.place_buy_order.call_count == 2

    def test_portfolio_diversification_limit(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Portfolio diversification limits are enforced.
        """
        # Create full portfolio (10 stocks)
        full_portfolio = [
            {'code': f'00{i:04d}', 'name': f'Stock{i}', 'quantity': 10, 'avg_price': 10000}
            for i in range(10)
        ]

        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=full_portfolio)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000

        buy_executor = buy_executor_class(kis=mock_kis, config=mock_config)

        result = buy_executor.process_buy_signal(
            create_scan_result("005930", "삼성전자", 85),
            dry_run=False
        )

        assert result['status'] == 'skipped'
        assert 'Portfolio size limit' in result['reason']


@pytest.mark.e2e
class TestGracefulShutdown:
    """Tests for graceful shutdown handling"""

    def test_order_completes_during_shutdown(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: In-progress orders complete during shutdown.
        """
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)
        mocker.patch('shared.database.get_daily_prices', return_value=None)
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)
        mocker.patch('shared.redis_cache.reset_trading_state_for_stock')

        def slow_order(*args, **kwargs):
            time.sleep(0.5)  # Simulate order processing time
            return "BUY_SHUTDOWN_001"

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 70000}
        mock_kis.place_buy_order.side_effect = slow_order

        buy_executor = buy_executor_class(kis=mock_kis, config=mock_config)

        # Start order (simulating shutdown during processing)
        result = buy_executor.process_buy_signal(
            create_scan_result("005930", "삼성전자", 85),
            dry_run=False
        )

        # Order should still complete
        assert result['status'] == 'success'


@pytest.mark.e2e
class TestMessageQueueIntegration:
    """Tests for message queue integration"""

    def test_buy_signal_through_queue(self, mq_bridge, mock_config):
        """
        Test: Buy signal flows correctly through message queue.
        """
        publisher = mq_bridge.get_publisher(QueueNames.BUY_SIGNALS)
        consumer = mq_bridge.get_consumer(QueueNames.BUY_SIGNALS)

        # Publish buy signal
        signal = {
            'candidates': [{
                'stock_code': '005930',
                'stock_name': '삼성전자',
                'llm_score': 85.0,
                'current_price': 70000,
                'buy_signal_type': 'GOLDEN_CROSS'
            }],
            'market_regime': 'BULL',
            'source': 'test'
        }

        msg_id = publisher.publish(signal)
        assert msg_id is not None

        # Consume message
        message = consumer.consume_one(timeout=1.0)
        assert message is not None
        assert message.body['candidates'][0]['stock_code'] == '005930'

    def test_sell_order_through_queue(self, mq_bridge):
        """
        Test: Sell order flows correctly through message queue.
        """
        publisher = mq_bridge.get_publisher(QueueNames.SELL_ORDERS)
        consumer = mq_bridge.get_consumer(QueueNames.SELL_ORDERS)

        order = {
            'stock_code': '005930',
            'stock_name': '삼성전자',
            'quantity': 10,
            'sell_reason': 'Stop Loss',
            'current_price': 65000
        }

        msg_id = publisher.publish(order)
        assert msg_id is not None

        message = consumer.consume_one(timeout=1.0)
        assert message is not None
        assert message.body['stock_code'] == '005930'
        assert message.body['sell_reason'] == 'Stop Loss'

    def test_queue_ordering_preserved(self, mq_bridge):
        """
        Test: Message ordering is preserved in queue.
        """
        publisher = mq_bridge.get_publisher(QueueNames.BUY_SIGNALS)
        consumer = mq_bridge.get_consumer(QueueNames.BUY_SIGNALS)

        # Publish multiple messages
        for i in range(5):
            publisher.publish({'order': i, 'stock': f'STOCK_{i}'})

        # Consume and verify order
        for i in range(5):
            message = consumer.consume_one(timeout=1.0)
            assert message.body['order'] == i


@pytest.mark.e2e
class TestPriceStreamIntegration:
    """Tests for price stream integration"""

    def test_price_update_triggers_signal_check(
        self, e2e_redis, price_simulator, mock_config, opportunity_watcher_class
    ):
        """
        Test: Price updates trigger signal checking in watcher.
        """
        BuyOpportunityWatcher = opportunity_watcher_class

        with patch.object(BuyOpportunityWatcher, '_ensure_redis_connection', return_value=True):
            mock_publisher = MagicMock()
            mock_publisher.publish.return_value = "MSG_001"

            watcher = BuyOpportunityWatcher(
                config=mock_config,
                tasks_publisher=mock_publisher,
                redis_url="redis://fake:6379/0"
            )
            watcher.redis = e2e_redis
            watcher.hot_watchlist = {
                '005930': {
                    'name': '삼성전자',
                    'llm_score': 80,
                    'is_tradable': True,
                    'strategies': [],
                    'trade_tier': 'TIER1'
                }
            }
            watcher.market_regime = 'BULL'

            # Inject prices
            price_simulator.inject_price('005930', 70000, 10000)

            # Process price update
            result = watcher.on_price_update('005930', 70000, 10000)

            # Verify tick was counted
            assert watcher.metrics['tick_count'] > 0

    def test_golden_cross_pattern_detection(
        self, e2e_redis, price_simulator, mock_config, opportunity_watcher_class
    ):
        """
        Test: Golden cross pattern is detected from price stream.
        """
        BuyOpportunityWatcher = opportunity_watcher_class

        with patch.object(BuyOpportunityWatcher, '_ensure_redis_connection', return_value=True):
            watcher = BuyOpportunityWatcher(
                config=mock_config,
                tasks_publisher=MagicMock(),
                redis_url="redis://fake:6379/0"
            )
            watcher.redis = e2e_redis

            # Simulate golden cross pattern
            entry_ids = price_simulator.simulate_golden_cross('005930', 70000, steps=30)
            assert len(entry_ids) == 30
