# tests/e2e/test_filter_chain.py
"""
E2E Tests: Filter Chain Reorganization

Verifies the new filter chain behavior after reorganization:
1. Hard Floor: hybrid_score < 40 → reject
2. Stale Score: business-day-based position reduction (not blocking)
3. Shadow Mode: logging for formerly-blocked scores
4. Integration: end-to-end flow with new filter chain
"""

import logging
import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone, timedelta

from tests.e2e.conftest import create_scan_result


# ============================================================================
# Hard Floor Tests
# ============================================================================

@pytest.mark.e2e
class TestHardFloor:
    """Hard Floor (hybrid_score < 40) E2E verification"""

    def test_score_below_hard_floor_rejected(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """Score=35 is below hard floor 40 → rejected, KIS not called."""
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=35.0,
            trade_tier="TIER1"
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'skipped'
        assert 'hard floor' in result['reason'].lower()
        mock_kis.place_buy_order.assert_not_called()

    def test_score_at_boundary_accepted(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """Score=40 is exactly at hard floor boundary → accepted (not rejected)."""
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)
        mocker.patch('shared.database.get_daily_prices', return_value=None)
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 70000}
        mock_kis.place_buy_order.return_value = "BUY_BOUNDARY"

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=40.0,
            trade_tier="TIER1"
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'success'

    def test_mid_score_now_accepted(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """Score=55 was blocked by old MIN_LLM_SCORE=60 but now passes."""
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)
        mocker.patch('shared.database.get_daily_prices', return_value=None)
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 70000}
        mock_kis.place_buy_order.return_value = "BUY_MID"

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=55.0,
            trade_tier="TIER1"
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'success'
        assert result['stock_code'] == '005930'


# ============================================================================
# Stale Score Tests
# ============================================================================

@pytest.mark.e2e
class TestStaleScoreE2E:
    """Stale Score position reduction E2E verification"""

    def test_fresh_score_full_position(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """Score from 2 hours ago → stale_multiplier=1.0, stale_entry=False."""
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)
        mocker.patch('shared.database.get_daily_prices', return_value=None)
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 70000}
        mock_kis.place_buy_order.return_value = "BUY_FRESH"

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scored_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=70.0,
            llm_scored_at=scored_at,
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'success'
        assert result['stale_entry'] is False
        assert result['stale_multiplier'] == 1.0

    def test_2_business_days_half_position(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Score from 2 business days ago → stale_multiplier=0.5, stale_entry=True.

        The executor counts business days from scored_dt.date()+1 to now.date().
        We reverse-engineer the scored_at to yield exactly 2 business days.
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
        mock_kis.place_buy_order.return_value = "BUY_STALE2"

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        # Find scored_dt such that counting weekdays from scored_dt.date()+1
        # to today yields exactly 2.
        now = datetime.now(timezone.utc)
        scored_dt = now
        biz_counted = 0
        while biz_counted < 2:
            scored_dt -= timedelta(days=1)
            if scored_dt.weekday() < 5:
                biz_counted += 1
        # Now scored_dt.date() is 2 biz days before today.
        # The algorithm counts from scored_dt.date()+1 to now.date(),
        # so we need to go 1 more calendar day back.
        scored_dt -= timedelta(days=1)
        while scored_dt.weekday() >= 5:
            scored_dt -= timedelta(days=1)

        scored_at = scored_dt.replace(hour=15, minute=0, second=0).isoformat()

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=70.0,
            llm_scored_at=scored_at,
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'success'
        assert result['stale_entry'] is True
        assert result['stale_multiplier'] == 0.5

    def test_3_business_days_minimal_position(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Score from 3+ business days ago → stale_multiplier=0.3, stale_entry=True.
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
        mock_kis.place_buy_order.return_value = "BUY_STALE3"

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        # Go back 3 business days from now
        now = datetime.now(timezone.utc)
        scored_dt = now
        biz_counted = 0
        target_biz_days = 3
        while biz_counted < target_biz_days:
            scored_dt -= timedelta(days=1)
            if scored_dt.weekday() < 5:
                biz_counted += 1
        # scored_dt is now 3 business days before today
        # Algorithm counts from scored_dt.date()+1 to now.date(), so go 1 more day back
        scored_dt -= timedelta(days=1)
        while scored_dt.weekday() >= 5:
            scored_dt -= timedelta(days=1)

        scored_at = scored_dt.replace(hour=15, minute=0, second=0).isoformat()

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=70.0,
            llm_scored_at=scored_at,
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'success'
        assert result['stale_entry'] is True
        assert result['stale_multiplier'] == 0.3

    def test_friday_to_monday_no_penalty(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """
        Scored on Friday 15:00, executed on Monday 10:00 → 1 business day.
        stale_multiplier=1.0 (no penalty for weekend gap).

        We mock datetime in the dynamically-loaded executor module so that
        "now" is Monday and scored_at is the preceding Friday.
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
        mock_kis.place_buy_order.return_value = "BUY_WEEKEND"

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        # Friday 15:00 UTC → Monday 10:00 UTC
        friday = datetime(2026, 2, 6, 15, 0, 0, tzinfo=timezone.utc)
        monday = datetime(2026, 2, 9, 10, 0, 0, tzinfo=timezone.utc)

        # Patch datetime.now in the dynamically-loaded module
        import sys
        executor_module = sys.modules.get('buy_executor_dynamic')
        if executor_module:
            original_dt_class = executor_module.datetime

            class MockDatetime(original_dt_class):
                @classmethod
                def now(cls, tz=None):
                    return monday if tz else monday.replace(tzinfo=None)

                @classmethod
                def fromisoformat(cls, s):
                    return original_dt_class.fromisoformat(s)

            mocker.patch.object(executor_module, 'datetime', MockDatetime)

        scored_at = friday.isoformat()
        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=70.0,
            llm_scored_at=scored_at,
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'success'
        assert result['stale_entry'] is False
        assert result['stale_multiplier'] == 1.0


# ============================================================================
# Shadow Mode Tests
# ============================================================================

@pytest.mark.e2e
class TestShadowModeE2E:
    """Shadow Mode logging E2E verification"""

    def test_shadow_log_for_formerly_blocked_score(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker, caplog
    ):
        """
        Score=55 in BULL regime → old cutline was 62, so [Shadow] log appears.
        Buy still succeeds (not blocked).
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
        mock_kis.place_buy_order.return_value = "BUY_SHADOW"

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=55.0,
            market_regime="BULL"
        )

        with caplog.at_level(logging.INFO):
            result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'success'
        # Verify shadow log was emitted
        shadow_logs = [r for r in caplog.records if '[Shadow]' in r.message]
        assert len(shadow_logs) >= 1, f"Expected [Shadow] log but got none. Logs: {[r.message for r in caplog.records]}"

    def test_no_shadow_log_for_high_score(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker, caplog
    ):
        """Score=75 → was not blocked even under old rules, so no [Shadow] log."""
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)
        mocker.patch('shared.database.get_daily_prices', return_value=None)
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 70000}
        mock_kis.place_buy_order.return_value = "BUY_HIGH"

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=75.0,
            market_regime="BULL"
        )

        with caplog.at_level(logging.INFO):
            result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'success'
        # Verify no shadow log
        shadow_logs = [r for r in caplog.records if '[Shadow]' in r.message]
        assert len(shadow_logs) == 0, f"Unexpected [Shadow] log: {[r.message for r in shadow_logs]}"


# ============================================================================
# Integration Tests
# ============================================================================

@pytest.mark.e2e
class TestFilterChainIntegration:
    """Filter chain integration E2E — full flow verification"""

    def test_mid_score_passes_with_shadow_log(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker, caplog
    ):
        """Score=55, formerly blocked → now succeeds + shadow log."""
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)
        mocker.patch('shared.database.get_daily_prices', return_value=None)
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 70000}
        mock_kis.place_buy_order.return_value = "BUY_INT1"

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=55.0,
            market_regime="BULL"
        )

        with caplog.at_level(logging.INFO):
            result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'success'
        mock_kis.place_buy_order.assert_called_once()
        shadow_logs = [r for r in caplog.records if '[Shadow]' in r.message]
        assert len(shadow_logs) >= 1

    def test_hard_floor_blocks_before_position_sizing(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker
    ):
        """Score=30 → hard floor blocks immediately, no KIS API calls."""
        mocker.patch('shared.database.get_market_regime_cache', return_value={'regime': 'BULL'})
        mocker.patch('shared.db.repository.get_today_buy_count', return_value=0)
        mocker.patch('shared.db.repository.get_active_portfolio', return_value=[])
        mocker.patch('shared.db.repository.was_traded_recently', return_value=False)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=30.0,
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'skipped'
        assert 'hard floor' in result['reason'].lower()
        # KIS API should never be called for hard floor rejection
        mock_kis.place_buy_order.assert_not_called()
        mock_kis.get_stock_snapshot.assert_not_called()

    def test_stale_score_reduces_but_allows(
        self, kis_server, mock_config, buy_executor_class, e2e_db, mock_redis_connection, mocker, caplog
    ):
        """
        2 business days elapsed + score=65 → buy succeeds with reduced quantity.
        stale_entry=True, no shadow log (score=65 >= old cutline 62 for BULL).
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
        mock_kis.place_buy_order.return_value = "BUY_STALE_INT"

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        # Calculate scored_at for exactly 2 business days ago
        now = datetime.now(timezone.utc)
        scored_dt = now
        biz_counted = 0
        while biz_counted < 2:
            scored_dt -= timedelta(days=1)
            if scored_dt.weekday() < 5:
                biz_counted += 1
        scored_dt -= timedelta(days=1)
        while scored_dt.weekday() >= 5:
            scored_dt -= timedelta(days=1)
        scored_at = scored_dt.replace(hour=15, minute=0, second=0).isoformat()

        scan_result = create_scan_result(
            stock_code="005930",
            stock_name="삼성전자",
            llm_score=65.0,
            llm_scored_at=scored_at,
            market_regime="BULL"
        )

        with caplog.at_level(logging.INFO):
            result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'success'
        assert result['stale_entry'] is True
        assert result['stale_multiplier'] == 0.5

        # Score=65 >= old cutline (62 for BULL, max with 60) → no shadow
        shadow_logs = [r for r in caplog.records if '[Shadow]' in r.message]
        assert len(shadow_logs) == 0
