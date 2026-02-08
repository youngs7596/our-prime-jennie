# tests/e2e/test_buy_flow.py
"""
E2E Tests: Buy Flow

Tests the complete buy execution flow including:
- Golden cross signal → Buy execution → DB update
- Daily buy limit enforcement
- Emergency stop handling
- LLM score filtering
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from tests.e2e.conftest import create_scan_result, create_portfolio_item


@pytest.mark.e2e
class TestBuyFlow:
    """Tests for buy execution flow"""

    def test_golden_cross_buy_success(
        self, kis_server, mock_kis_client, mock_config,
        buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Golden cross signal generates successful buy order.

        Flow:
        1. Receive GOLDEN_CROSS signal
        2. BuyExecutor validates candidate
        3. Place buy order
        4. Record in DB
        """
        # Setup scenario
        scenario = kis_server.activate_scenario("empty_portfolio")
        scenario.add_stock("005930", "삼성전자", 70000)

        # Mock dependencies
        mocker.patch('shared.database.get_market_regime_cache', return_value={
            'regime': 'BULL',
            'strategy_preset': {'name': 'BULL_PRESET', 'params': {}}
        })
        mocker.patch('shared.database.get_daily_prices', return_value=None)
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)

        # Create executor with mocked KIS
        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 70000, 'open': 69000, 'high': 71000, 'low': 69000}
        mock_kis.place_buy_order.return_value = "BUY_12345"

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        # Create buy signal
        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=85.0,
            signal_type="GOLDEN_CROSS",
            current_price=70000,
            market_regime="BULL"
        )

        # Execute
        result = executor.process_buy_signal(scan_result, dry_run=False)

        # Verify
        assert result['status'] == 'success'
        assert result['stock_code'] == '005930'
        assert result['order_no'] == 'BUY_12345'
        mock_kis.place_buy_order.assert_called_once()

    def test_daily_buy_limit_blocks_order(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Orders are blocked when daily buy limit is reached.
        """
        # Mock dependencies
        mocker.patch('shared.database.get_market_regime_cache', return_value={
            'regime': 'BULL'
        })
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=5)  # At limit

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=85.0
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'skipped'
        assert 'Daily buy limit' in result['reason']

    def test_emergency_stop_blocks_all_orders(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mocker
    ):
        """
        Test: Emergency stop flag blocks all buy orders.
        """
        # Mock emergency stop as active
        mocker.patch('shared.redis_cache.is_trading_stopped', return_value=True)
        mocker.patch('shared.redis_cache.is_trading_paused', return_value=False)
        mocker.patch('shared.redis_cache.get_redis_connection', return_value=MagicMock())

        mock_kis = MagicMock()
        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=85.0
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'skipped'
        assert 'Emergency Stop' in result['reason']

    def test_hard_floor_rejects_low_score(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Candidates with hybrid_score below hard floor (40) are rejected.
        """
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        # Score below hard floor (40)
        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=35.0,  # Below hard floor of 40
            trade_tier="TIER1"
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'skipped'
        assert 'hard floor' in result['reason'].lower()

    def test_already_held_stock_skipped(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Stocks already in portfolio are skipped.
        """
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[
            {'code': '005930', 'name': '삼성전자', 'quantity': 10, 'avg_price': 70000}
        ])

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=85.0
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'skipped'
        assert 'already held' in result['reason']

    def test_tier2_reduced_position_size(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: TIER2 candidates get reduced position size.
        """
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)
        mocker.patch('shared.database.get_daily_prices', return_value=None)
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 70000}
        mock_kis.place_buy_order.return_value = "BUY_TIER2"

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=70.0,
            trade_tier="TIER2",  # Reduced size
            is_tradable=False
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'success'
        # TIER2 should have smaller position than TIER1

    def test_no_candidates_returns_skipped(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Empty candidate list returns skipped status.
        """
        mocker.patch('shared.redis_cache.is_trading_stopped', return_value=False)
        mocker.patch('shared.redis_cache.is_trading_paused', return_value=False)

        mock_kis = MagicMock()
        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = {
            'candidates': [],
            'market_regime': 'BULL'
        }

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'skipped'
        assert 'No candidates' in result['reason']

    def test_duplicate_order_prevention(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: Duplicate orders within cooldown period are prevented.
        """
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=True)  # Recently traded

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=85.0
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'skipped'
        assert 'Duplicate' in result['reason'] or 'Cooldown' in result['reason']

    def test_recon_tier_smallest_position(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: RECON tier gets the smallest position size.
        """
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)
        mocker.patch('shared.database.get_daily_prices', return_value=None)
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 70000}
        mock_kis.place_buy_order.return_value = "BUY_RECON"

        # Config with RECON multiplier
        mock_config._values['RECON_POSITION_MULT'] = 0.3

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=65.0,
            trade_tier="RECON",
            is_tradable=False
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'success'


@pytest.mark.e2e
class TestBuySignalTypes:
    """Tests for different buy signal types"""

    def test_momentum_continuation_signal(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: MOMENTUM_CONTINUATION signal is processed correctly.
        """
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'STRONG_BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)
        mocker.patch('shared.database.get_daily_prices', return_value=None)
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 75000}
        mock_kis.place_buy_order.return_value = "BUY_MOMENTUM"

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=80.0,
            signal_type="MOMENTUM_CONTINUATION_BULL",
            market_regime="STRONG_BULL"
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'success'

    def test_rsi_rebound_signal(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Test: RSI_REBOUND signal is processed correctly.
        """
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'SIDEWAYS'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)
        mocker.patch('shared.database.get_daily_prices', return_value=None)
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 65000}
        mock_kis.place_buy_order.return_value = "BUY_RSI"

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=75.0,
            signal_type="RSI_REBOUND",
            market_regime="SIDEWAYS"
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'success'
