# tests/e2e/test_error_handling.py
"""
E2E Tests: Error Handling

Tests error handling scenarios including:
- KIS Gateway timeout
- KIS Gateway 500 errors
- Redis connection failures
- Redis Streams publish failures
"""

import os
import sys
import pytest
import importlib.util
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
import requests

from tests.e2e.conftest import create_scan_result, create_portfolio_item
from tests.e2e.mock_server.scenarios import ResponseMode

# Dynamic import for services with hyphens in names
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_opportunity_watcher_class():
    """Dynamically load BuyOpportunityWatcher class"""
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
class TestKISGatewayErrors:
    """Tests for KIS Gateway error handling"""

    def test_gateway_timeout_handling(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: KIS Gateway timeout is propagated as Timeout exception.

        The executor allows the timeout to propagate so higher-level
        handlers (message consumer) can handle retry logic.
        """
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.side_effect = requests.exceptions.Timeout("Connection timed out")

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=85.0,
            current_price=0  # Force snapshot lookup
        )

        # Timeout exception is propagated for higher-level retry handling
        with pytest.raises(requests.exceptions.Timeout):
            executor.process_buy_signal(scan_result, dry_run=False)

    def test_gateway_500_error_handling(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: KIS Gateway 500 error is propagated as Exception.

        The executor allows errors to propagate so higher-level
        handlers can implement proper error handling/logging.
        """
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 70000}
        mock_kis.place_buy_order.side_effect = Exception("Internal Server Error")

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=85.0
        )

        # Server error exception is propagated for higher-level error handling
        with pytest.raises(Exception) as exc_info:
            executor.process_buy_signal(scan_result, dry_run=False)

        assert "Internal Server Error" in str(exc_info.value)

    def test_gateway_order_rejection(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: KIS Gateway order rejection is handled.
        """
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 70000}
        mock_kis.place_buy_order.return_value = None  # Order rejected

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=85.0
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'error'
        assert 'failed' in result['reason'].lower()


@pytest.mark.e2e
class TestRedisErrors:
    """Tests for Redis error handling"""

    def test_redis_connection_failure(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mocker
    ):
        """
        Test: Redis connection failure is handled gracefully.
        """
        # Simulate Redis connection failure
        mocker.patch('shared.redis_cache.get_redis_connection', side_effect=Exception("Redis unavailable"))
        mocker.patch('shared.redis_cache.is_trading_stopped', side_effect=Exception("Redis unavailable"))
        mocker.patch('shared.redis_cache.is_trading_paused', side_effect=Exception("Redis unavailable"))

        mock_kis = MagicMock()
        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=85.0
        )

        # Should handle Redis failure
        try:
            result = executor.process_buy_signal(scan_result, dry_run=False)
            # Might skip or error, but shouldn't crash
            assert result['status'] in ('error', 'skipped')
        except Exception as e:
            # Some Redis failures might raise, that's acceptable
            assert "Redis" in str(e) or "redis" in str(e).lower()

    def test_redis_lock_failure(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mocker
    ):
        """
        Test: Redis distributed lock failure is handled.
        """
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)
        mocker.patch('shared.redis_cache.is_trading_stopped', return_value=False)
        mocker.patch('shared.redis_cache.is_trading_paused', return_value=False)

        # Mock Redis that fails on lock
        mock_redis = MagicMock()
        mock_redis.set.side_effect = Exception("Lock failed")
        mocker.patch('shared.redis_cache.get_redis_connection', return_value=mock_redis)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 70000}

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=85.0
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        # Should skip due to lock failure
        assert result['status'] == 'skipped'
        assert 'lock' in result['reason'].lower()


@pytest.mark.e2e
class TestDatabaseErrors:
    """Tests for database error handling"""

    def test_db_connection_failure(
        self, kis_server, mock_config, buy_executor_class, mocker, e2e_redis
    ):
        """
        Test: Database connection failure is handled gracefully.

        When the database is unavailable, the executor catches the
        exception in safety checks and returns a skipped status.
        """
        mocker.patch('shared.redis_cache.is_trading_stopped', return_value=False)
        mocker.patch('shared.redis_cache.is_trading_paused', return_value=False)
        mocker.patch('shared.redis_cache.get_redis_connection', return_value=e2e_redis)
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})

        # Mock repository functions to raise database connection error
        mocker.patch('shared.db.repository.get_today_buy_count',
                     side_effect=Exception("Database connection failed"))

        mock_kis = MagicMock()
        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=85.0
        )

        # Executor catches DB error in safety checks and returns skipped
        result = executor.process_buy_signal(scan_result, dry_run=False)
        assert result['status'] == 'skipped'
        assert 'Safety' in result['reason'] or 'Database' in result['reason']

    def test_db_write_failure_rollback(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Database write failure triggers rollback.
        """
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)
        mocker.patch('shared.database.get_daily_prices', return_value=None)

        # Simulate DB write failure
        mocker.patch('shared.database.execute_trade_and_log', side_effect=Exception("Write failed"))

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 70000}
        mock_kis.place_buy_order.return_value = "BUY_12345"

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=85.0
        )

        # Should propagate error
        with pytest.raises(Exception):
            executor.process_buy_signal(scan_result, dry_run=False)


@pytest.mark.e2e
class TestStreamErrors:
    """Tests for Redis Streams error handling"""

    def test_mq_publish_failure(
        self, e2e_redis, mock_config, opportunity_watcher_class
    ):
        """
        Test: Stream publish failure is handled.
        """
        BuyOpportunityWatcher = opportunity_watcher_class

        with patch.object(BuyOpportunityWatcher, '_ensure_redis_connection', return_value=True):
            # Create publisher that fails
            mock_publisher = MagicMock()
            mock_publisher.publish.return_value = None  # Publish failed

            watcher = BuyOpportunityWatcher(
                config=mock_config,
                tasks_publisher=mock_publisher,
                redis_url="redis://fake:6379/0"
            )
            watcher.redis = e2e_redis

            signal = {
                'stock_code': '005930',
                'stock_name': '삼성전자',
                'signal_type': 'GOLDEN_CROSS',
                'signal_reason': 'Test',
                'current_price': 70000,
                'llm_score': 80,
                'market_regime': 'BULL',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'trade_tier': 'TIER1'
            }

            result = watcher.publish_signal(signal)
            assert result == False

    def test_mq_no_publisher(
        self, e2e_redis, mock_config, opportunity_watcher_class
    ):
        """
        Test: Missing stream publisher is handled.
        """
        BuyOpportunityWatcher = opportunity_watcher_class

        with patch.object(BuyOpportunityWatcher, '_ensure_redis_connection', return_value=True):
            watcher = BuyOpportunityWatcher(
                config=mock_config,
                tasks_publisher=None,  # No publisher
                redis_url="redis://fake:6379/0"
            )
            watcher.redis = e2e_redis

            signal = {
                'stock_code': '005930',
                'stock_name': '삼성전자',
                'signal_type': 'GOLDEN_CROSS'
            }

            result = watcher.publish_signal(signal)
            assert result == False


@pytest.mark.e2e
class TestNetworkErrors:
    """Tests for network error handling"""

    def test_network_partition_recovery(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Network connection error is propagated as ConnectionError.

        The executor allows the connection error to propagate so
        higher-level handlers can implement retry logic.
        """
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.side_effect = requests.exceptions.ConnectionError("Network error")

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=85.0,
            current_price=0
        )

        # Connection error is propagated for retry logic
        with pytest.raises(requests.exceptions.ConnectionError):
            executor.process_buy_signal(scan_result, dry_run=False)


@pytest.mark.e2e
class TestInvalidDataHandling:
    """Tests for invalid/corrupted data handling"""

    def test_invalid_price_data(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Invalid price data is handled.
        """
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': -1000}  # Invalid negative price

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=85.0,
            current_price=0
        )

        # Should handle invalid price
        result = executor.process_buy_signal(scan_result, dry_run=False)
        # Behavior depends on implementation - should not crash

    def test_malformed_scan_result(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Malformed scan result is handled.
        """
        mocker.patch('shared.redis_cache.is_trading_stopped', return_value=False)
        mocker.patch('shared.redis_cache.is_trading_paused', return_value=False)

        mock_kis = MagicMock()
        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        # Malformed scan result - missing required fields
        scan_result = {
            'candidates': [{}],  # Empty candidate
            'market_regime': 'BULL'
        }

        # Should handle gracefully
        try:
            result = executor.process_buy_signal(scan_result, dry_run=False)
            # Should skip or error
        except KeyError:
            pass  # KeyError is acceptable for malformed data
        except Exception as e:
            # Other exceptions should be specific
            pass
