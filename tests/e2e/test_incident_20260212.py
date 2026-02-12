# tests/e2e/test_incident_20260212.py
"""
E2E Tests: 2026-02-12 Production Incident Scenarios

Covers 4 production incidents that caused 0 buy orders:
A. KRX 호가단위 오류 (APBK0506): 지정가 주문 시 tick size 미정렬
B. 모멘텀 지정가 주문 흐름: limit → timeout → cancel → result
C. Regime Guard: KOSPI 실시간 조회 실패 → BEAR 오판정
D. Portfolio Guard 섹터 집중: 동일 대분류 3종목 초과 차단
E. SQL placeholder 불일치: INSERT 컬럼 수 vs %s 수
"""

import re
import pytest
import logging
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from tests.e2e.conftest import create_scan_result

# ---------------------------------------------------------------------------
# Dynamically import align_to_tick_size from buy-executor
# ---------------------------------------------------------------------------
import importlib.util
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_executor_path = os.path.join(PROJECT_ROOT, "services", "buy-executor", "executor.py")
_spec = importlib.util.spec_from_file_location("buy_executor_mod", _executor_path)
_executor_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_executor_mod)

align_to_tick_size = _executor_mod.align_to_tick_size
MOMENTUM_STRATEGIES = _executor_mod.MOMENTUM_STRATEGIES


# ============================================================================
# Class A: KRX Tick Size Alignment
# ============================================================================

@pytest.mark.e2e
class TestKRXTickSizeAlignment:
    """
    KRX 호가 단위 검증.

    2026-02-12 장애: 384,650원 → 385,000원 올림 정렬이 안 되어
    APBK0506 에러 (호가 단위 불일치) 발생.
    """

    def test_actual_incident_price_384650(self):
        """실제 장애 가격: 384,650 → 385,000 (500원 단위)"""
        assert align_to_tick_size(384_650) == 385_000

    def test_actual_incident_price_298893(self):
        """실제 장애 가격: 298,893 → 299,000 (500원 단위, ≤500K)"""
        # 298,893 is in the 200,001~500,000 range → tick=500
        assert align_to_tick_size(298_893) == 299_000

    def test_tier_under_2000_tick_1(self):
        """~2,000원: 1원 단위"""
        assert align_to_tick_size(1_999) == 1_999  # already aligned
        assert align_to_tick_size(1_500) == 1_500
        assert align_to_tick_size(1) == 1

    def test_tier_2001_to_5000_tick_5(self):
        """2,001~5,000원: 5원 단위"""
        assert align_to_tick_size(2_001) == 2_005
        assert align_to_tick_size(3_333) == 3_335
        assert align_to_tick_size(5_000) == 5_000  # exact boundary

    def test_tier_5001_to_20000_tick_10(self):
        """5,001~20,000원: 10원 단위"""
        assert align_to_tick_size(5_001) == 5_010
        assert align_to_tick_size(10_005) == 10_010
        assert align_to_tick_size(20_000) == 20_000

    def test_tier_20001_to_50000_tick_50(self):
        """20,001~50,000원: 50원 단위"""
        assert align_to_tick_size(20_001) == 20_050
        assert align_to_tick_size(34_327) == 34_350  # 실제 종목 가격대 (롯데지주)
        assert align_to_tick_size(50_000) == 50_000

    def test_tier_50001_to_200000_tick_100(self):
        """50,001~200,000원: 100원 단위"""
        assert align_to_tick_size(50_001) == 50_100
        assert align_to_tick_size(70_050) == 70_100
        assert align_to_tick_size(200_000) == 200_000

    def test_tier_200001_to_500000_tick_500(self):
        """200,001~500,000원: 500원 단위"""
        assert align_to_tick_size(200_001) == 200_500
        assert align_to_tick_size(384_000) == 384_000  # already aligned (384000 % 500 == 0)
        assert align_to_tick_size(384_200) == 384_500  # 384200 % 500 = 200 → rounds up
        assert align_to_tick_size(500_000) == 500_000

    def test_tier_over_500000_tick_1000(self):
        """500,000원 초과: 1,000원 단위"""
        assert align_to_tick_size(500_001) == 501_000
        assert align_to_tick_size(550_300) == 551_000
        assert align_to_tick_size(1_000_000) == 1_000_000

    def test_already_aligned_no_change(self):
        """이미 정렬된 가격은 변경하지 않음"""
        assert align_to_tick_size(70_000) == 70_000
        assert align_to_tick_size(385_000) == 385_000
        assert align_to_tick_size(100) == 100

    def test_limit_price_with_premium_tick_aligned(self):
        """프리미엄 적용 후 tick 정렬: 실제 지정가 주문 시나리오"""
        # F&F 384,200원 × 1.003 = 385,352.6 → int=385,352 → 385,500 (500원 단위)
        price = 384_200
        premium = 0.003
        raw = int(price * (1 + premium))
        aligned = align_to_tick_size(raw)
        assert aligned % 500 == 0
        assert aligned >= raw

        # 삼성SDI 550,000원 × 1.003 = 551,650 → int=551,650 → 552,000 (1000원 단위)
        price2 = 550_000
        raw2 = int(price2 * (1 + premium))
        aligned2 = align_to_tick_size(raw2)
        assert aligned2 % 1_000 == 0
        assert aligned2 >= raw2


# ============================================================================
# Class B: Momentum Limit Order Flow
# ============================================================================

@pytest.mark.e2e
class TestMomentumLimitOrderFlow:
    """
    모멘텀 전략 지정가 주문 흐름 테스트.

    MOMENTUM 계열 전략 + MOMENTUM_LIMIT_ORDER_ENABLED=true일 때
    지정가 주문 → timeout → cancel 시도 → 결과에 따라 success/skipped.
    """

    def test_momentum_limit_order_unfilled_cancel(
        self, kis_server, mock_config, buy_executor_class,
        e2e_db, mock_redis_connection, mocker
    ):
        """
        모멘텀 지정가 미체결 → 취소 성공 → skipped.
        """
        scenario = kis_server.activate_scenario("momentum_limit_order")

        mocker.patch('shared.database.get_market_regime_cache', return_value={
            'regime': 'BULL',
            'strategy_preset': {'name': 'BULL_PRESET', 'params': {}}
        })
        mocker.patch('shared.database.get_daily_prices', return_value=None)
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 20_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 384200}
        mock_kis.place_buy_order.return_value = "BUY_LIMIT_001"
        mock_kis.cancel_order.return_value = True  # 미체결 → 취소 성공

        # Enable limit order
        mock_config._values['MOMENTUM_LIMIT_ORDER_ENABLED'] = True
        mock_config._values['MOMENTUM_LIMIT_TIMEOUT_SEC'] = 0  # No sleep

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="383220", stock_name="F&F",
            llm_score=85.0, signal_type="MOMENTUM",
            current_price=384200, market_regime="BULL"
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'skipped'
        assert 'Limit order not filled' in result['reason']
        mock_kis.place_buy_order.assert_called_once()
        mock_kis.cancel_order.assert_called_once()
        # Verify tick-aligned limit price was used
        call_args = mock_kis.place_buy_order.call_args
        limit_price = call_args[1].get('price') or call_args[0][2] if len(call_args[0]) > 2 else call_args[1]['price']
        assert limit_price % 500 == 0  # 200K~500K range → 500원 tick

    def test_momentum_limit_order_filled_success(
        self, kis_server, mock_config, buy_executor_class,
        e2e_db, mock_redis_connection, mocker
    ):
        """
        모멘텀 지정가 체결됨 → cancel 실패 → success.
        """
        scenario = kis_server.activate_scenario("momentum_limit_order")

        mocker.patch('shared.database.get_market_regime_cache', return_value={
            'regime': 'BULL',
            'strategy_preset': {'name': 'BULL_PRESET', 'params': {}}
        })
        mocker.patch('shared.database.get_daily_prices', return_value=None)
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 20_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 384200}
        mock_kis.place_buy_order.return_value = "BUY_LIMIT_002"
        mock_kis.cancel_order.return_value = False  # 이미 체결됨 → 취소 실패

        mock_config._values['MOMENTUM_LIMIT_ORDER_ENABLED'] = True
        mock_config._values['MOMENTUM_LIMIT_TIMEOUT_SEC'] = 0

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="383220", stock_name="F&F",
            llm_score=85.0, signal_type="MOMENTUM",
            current_price=384200, market_regime="BULL"
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'success'
        assert result['stock_code'] == '383220'
        mock_kis.cancel_order.assert_called_once()

    def test_non_momentum_uses_market_order(
        self, kis_server, mock_config, buy_executor_class,
        e2e_db, mock_redis_connection, mocker
    ):
        """
        비모멘텀 전략(GOLDEN_CROSS)은 limit enabled여도 시장가 주문.
        """
        scenario = kis_server.activate_scenario("empty_portfolio")
        scenario.add_stock("005930", "삼성전자", 70000)

        mocker.patch('shared.database.get_market_regime_cache', return_value={
            'regime': 'BULL',
            'strategy_preset': {'name': 'BULL_PRESET', 'params': {}}
        })
        mocker.patch('shared.database.get_daily_prices', return_value=None)
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 10_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 70000}
        mock_kis.place_buy_order.return_value = "BUY_MKT_001"

        mock_config._values['MOMENTUM_LIMIT_ORDER_ENABLED'] = True  # enabled but irrelevant
        mock_config._values['MOMENTUM_LIMIT_TIMEOUT_SEC'] = 0

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="005930", stock_name="삼성전자",
            llm_score=85.0, signal_type="GOLDEN_CROSS",
            current_price=70000, market_regime="BULL"
        )

        result = executor.process_buy_signal(scan_result, dry_run=False)

        assert result['status'] == 'success'
        # Should use market order (price=0)
        call_args = mock_kis.place_buy_order.call_args
        price_arg = call_args[1].get('price', 0)
        assert price_arg == 0  # market order
        mock_kis.cancel_order.assert_not_called()

    def test_dry_run_no_cancel_called(
        self, kis_server, mock_config, buy_executor_class,
        e2e_db, mock_redis_connection, mocker
    ):
        """
        DRY_RUN 모드에서는 cancel_order 호출하지 않음.
        """
        scenario = kis_server.activate_scenario("momentum_limit_order")

        mocker.patch('shared.database.get_market_regime_cache', return_value={
            'regime': 'BULL',
            'strategy_preset': {'name': 'BULL_PRESET', 'params': {}}
        })
        mocker.patch('shared.database.get_daily_prices', return_value=None)
        mocker.patch('shared.database.execute_trade_and_log', return_value=True)

        mock_kis = MagicMock()
        mock_kis.get_cash_balance.return_value = 20_000_000
        mock_kis.get_stock_snapshot.return_value = {'price': 384200}

        mock_config._values['MOMENTUM_LIMIT_ORDER_ENABLED'] = True
        mock_config._values['MOMENTUM_LIMIT_TIMEOUT_SEC'] = 0

        executor = buy_executor_class(kis=mock_kis, config=mock_config)

        scan_result = create_scan_result(
            stock_code="383220", stock_name="F&F",
            llm_score=85.0, signal_type="MOMENTUM",
            current_price=384200, market_regime="BULL"
        )

        result = executor.process_buy_signal(scan_result, dry_run=True)

        assert result['status'] == 'success'
        assert result['dry_run'] is True
        mock_kis.place_buy_order.assert_not_called()
        mock_kis.cancel_order.assert_not_called()

    def test_momentum_strategies_set_complete(self):
        """모멘텀 전략 세트에 4개 전략이 모두 포함됨"""
        expected = {
            "MOMENTUM", "MOMENTUM_CONTINUATION_BULL",
            "SHORT_TERM_HIGH_BREAKOUT", "VCP_BREAKOUT",
        }
        assert MOMENTUM_STRATEGIES == expected


# ============================================================================
# Class C: Regime Guard (Snapshot Failure Fallback)
# ============================================================================

@pytest.mark.e2e
class TestRegimeGuard:
    """
    Regime Guard 테스트.

    2026-02-12 장애: KOSPI 실시간 조회 실패 시 전일 종가 fallback이
    잘못된 BEAR 판정을 내려 모든 매수 차단.

    detect_regime_with_macro()의 fallback 경로를 검증한다.
    """

    def _make_detector(self):
        from shared.market_regime import MarketRegimeDetector
        return MarketRegimeDetector()

    def _make_kospi_df(self, prices: list):
        """Helper: 가격 리스트로 KOSPI DataFrame 생성"""
        import pandas as pd
        dates = pd.date_range(end="2026-02-12", periods=len(prices), freq="B")
        return pd.DataFrame({
            "TRADE_DATE": dates,
            "CLOSE_PRICE": prices,
            "HIGH_PRICE": [p * 1.01 for p in prices],
            "LOW_PRICE": [p * 0.99 for p in prices],
            "VOLUME": [1_000_000_000] * len(prices),
        })

    def test_normal_regime_detection(self):
        """정상: 충분한 데이터로 regime 정상 감지"""
        detector = self._make_detector()
        # Uptrend: 2500 → 2700
        prices = [2500 + i * 10 for i in range(20)]
        df = self._make_kospi_df(prices)
        regime, ctx = detector.detect_regime(df, prices[-1], quiet=True)
        # Should detect some positive regime (BULL or STRONG_BULL)
        assert regime in ("STRONG_BULL", "BULL", "SIDEWAYS")
        assert "error" not in ctx

    def test_insufficient_data_returns_sideways(self):
        """데이터 부족(< 10일) → SIDEWAYS + 에러 메시지"""
        detector = self._make_detector()
        prices = [2600, 2610, 2605, 2620, 2615]  # Only 5 bars
        df = self._make_kospi_df(prices)
        regime, ctx = detector.detect_regime(df, 2615, quiet=True)
        assert regime == "SIDEWAYS"
        assert "데이터 부족" in ctx.get("error", "")

    def test_empty_dataframe_returns_sideways(self):
        """빈 DataFrame → SIDEWAYS"""
        import pandas as pd
        detector = self._make_detector()
        df = pd.DataFrame()
        regime, ctx = detector.detect_regime(df, 0, quiet=True)
        assert regime == "SIDEWAYS"

    def test_macro_import_failure_fallback(self):
        """매크로 모듈 ImportError → 가격 기반 regime으로 fallback"""
        detector = self._make_detector()
        prices = [2500 + i * 10 for i in range(20)]
        df = self._make_kospi_df(prices)

        # Mock import failure for macro_insight
        with patch.dict('sys.modules', {'shared.macro_insight': None}):
            regime, ctx = detector.detect_regime_with_macro(df, prices[-1], quiet=True)
            # Should still return a valid regime (fallback to base)
            assert regime in ("STRONG_BULL", "BULL", "SIDEWAYS", "BEAR", "STRONG_BEAR")

    def test_macro_exception_fallback(self):
        """매크로 조회 예외 → 가격 기반 regime으로 fallback"""
        detector = self._make_detector()
        prices = [2500 + i * 10 for i in range(20)]
        df = self._make_kospi_df(prices)

        with patch('shared.macro_insight.get_macro_regime_adjustment', side_effect=RuntimeError("DB down")):
            regime, ctx = detector.detect_regime_with_macro(df, prices[-1], quiet=True)
            assert regime in ("STRONG_BULL", "BULL", "SIDEWAYS", "BEAR", "STRONG_BEAR")

    def test_macro_adjustment_applied_on_success(self):
        """매크로 조정 정상 적용 → enriched context 포함"""
        detector = self._make_detector()
        prices = [2500 + i * 10 for i in range(20)]
        df = self._make_kospi_df(prices)

        mock_adjustment = {
            "signal_details": {"signal_type": "NEUTRAL"},
            "should_adjust": False,
        }

        with patch('shared.macro_insight.get_macro_regime_adjustment', return_value=mock_adjustment):
            with patch('shared.macro_insight.apply_macro_adjustment_to_regime') as mock_apply:
                mock_apply.return_value = ("BULL", {"macro_influence": {"should_adjust": False}})
                regime, ctx = detector.detect_regime_with_macro(df, prices[-1], quiet=True)
                assert regime == "BULL"
                mock_apply.assert_called_once()

    def test_downtrend_detects_bear(self):
        """하락 추세 → BEAR 감지"""
        detector = self._make_detector()
        # Downtrend: 2700 → 2500
        prices = [2700 - i * 10 for i in range(20)]
        df = self._make_kospi_df(prices)
        regime, ctx = detector.detect_regime(df, prices[-1], quiet=True)
        assert regime in ("BEAR", "STRONG_BEAR")

    def test_regime_context_has_scores(self):
        """regime 결과에 점수(scores) 컨텍스트가 포함됨"""
        detector = self._make_detector()
        prices = [2600 + i * 5 for i in range(20)]
        df = self._make_kospi_df(prices)
        regime, ctx = detector.detect_regime(df, prices[-1], quiet=True)
        # Context should contain regime_scores
        assert "regime_scores" in ctx or "error" in ctx


# ============================================================================
# Class D: Portfolio Guard Sector Concentration
# ============================================================================

@pytest.mark.e2e
class TestPortfolioGuardSectorConcentration:
    """
    Portfolio Guard 섹터 집중도 검증.

    2026-02-12 장애: 금융 섹터 3종목 보유 상태에서 4번째 금융 종목 매수
    시도 시 정상적으로 차단되었으나 테스트 미비.
    """

    def _make_guard(self, config_overrides=None, sector_map=None):
        """PortfolioGuard 인스턴스 생성 헬퍼"""
        from shared.portfolio_guard import PortfolioGuard

        config = MagicMock()
        values = {
            "PORTFOLIO_GUARD_ENABLED": True,
            "MAX_SECTOR_STOCKS": 3,
            "CASH_FLOOR_STRONG_BULL_PCT": 5.0,
            "CASH_FLOOR_BULL_PCT": 10.0,
            "CASH_FLOOR_SIDEWAYS_PCT": 15.0,
            "CASH_FLOOR_BEAR_PCT": 25.0,
        }
        if config_overrides:
            values.update(config_overrides)

        config.get_int.side_effect = lambda k, default=0: int(values.get(k, default))
        config.get_float.side_effect = lambda k, default=0.0: float(values.get(k, default))
        config.get_bool.side_effect = lambda k, default=False: values.get(k, default)

        classifier = MagicMock()
        if sector_map:
            classifier.get_sector_group.side_effect = lambda code, name: sector_map.get(code, "기타")
        else:
            classifier.get_sector_group.return_value = "기타"

        return PortfolioGuard(config, classifier)

    def test_financial_4th_stock_blocked(self):
        """금융 3종목 보유 + 금융 4번째 → 차단"""
        sector_map = {
            "105560": "금융",  # KB금융
            "055550": "금융",  # 신한지주
            "086790": "금융",  # 하나금융지주
            "316140": "금융",  # 우리금융지주 (candidate)
        }
        guard = self._make_guard(sector_map=sector_map)

        portfolio = [
            {"stock_code": "105560", "stock_name": "KB금융"},
            {"stock_code": "055550", "stock_name": "신한지주"},
            {"stock_code": "086790", "stock_name": "하나금융지주"},
        ]

        result = guard.check_sector_stock_count("316140", "우리금융지주", portfolio)
        assert result["passed"] is False
        assert result["current_count"] == 3
        assert result["sector_group"] == "금융"
        assert "섹터 종목 수 초과" in result["reason"]

    def test_financial_3rd_stock_allowed(self):
        """금융 2종목 보유 + 금융 3번째 → 허용 (한도 미도달)"""
        sector_map = {
            "105560": "금융",
            "055550": "금융",
            "086790": "금융",
        }
        guard = self._make_guard(sector_map=sector_map)

        portfolio = [
            {"stock_code": "105560", "stock_name": "KB금융"},
            {"stock_code": "055550", "stock_name": "신한지주"},
        ]

        result = guard.check_sector_stock_count("086790", "하나금융지주", portfolio)
        assert result["passed"] is True
        assert result["current_count"] == 2

    def test_shadow_mode_allows_with_log(self, caplog):
        """Shadow mode (ENABLED=false) → 허용 + 로그"""
        sector_map = {
            "105560": "금융",
            "055550": "금융",
            "086790": "금융",
            "316140": "금융",
        }
        guard = self._make_guard(
            config_overrides={"PORTFOLIO_GUARD_ENABLED": False},
            sector_map=sector_map,
        )

        portfolio = [
            {"stock_code": "105560", "stock_name": "KB금융"},
            {"stock_code": "055550", "stock_name": "신한지주"},
            {"stock_code": "086790", "stock_name": "하나금융지주"},
        ]

        with caplog.at_level(logging.INFO):
            result = guard.check_all(
                candidate_code="316140",
                candidate_name="우리금융지주",
                current_portfolio=portfolio,
                buy_amount=300_000,
                available_cash=5_000_000,
                total_assets=10_000_000,
                market_regime="BULL",
            )

        # Shadow mode: passed=True but sector check internally failed
        assert result["passed"] is True
        assert result["shadow"] is True
        # Shadow log should appear
        shadow_logs = [r for r in caplog.records if "Shadow" in r.message]
        assert len(shadow_logs) >= 1

    def test_different_sector_allowed(self):
        """금융 3종목 보유 + 반도체 종목 → 허용 (다른 섹터)"""
        sector_map = {
            "105560": "금융",
            "055550": "금융",
            "086790": "금융",
            "005930": "반도체",
        }
        guard = self._make_guard(sector_map=sector_map)

        portfolio = [
            {"stock_code": "105560", "stock_name": "KB금융"},
            {"stock_code": "055550", "stock_name": "신한지주"},
            {"stock_code": "086790", "stock_name": "하나금융지주"},
        ]

        result = guard.check_sector_stock_count("005930", "삼성전자", portfolio)
        assert result["passed"] is True
        assert result["current_count"] == 0
        assert result["sector_group"] == "반도체"


# ============================================================================
# Class E: SQL Placeholder Consistency
# ============================================================================

@pytest.mark.e2e
class TestSQLPlaceholderConsistency:
    """
    SQL INSERT 컬럼 수와 %s 플레이스홀더 수 일치 검증.

    2026-02-12 장애: DAILY_MACRO_INSIGHT INSERT문에 35개 컬럼 vs 34개 %s
    불일치로 DB 저장 실패.
    """

    def test_daily_macro_insight_columns_match_placeholders(self):
        """DAILY_MACRO_INSIGHT INSERT: 컬럼 수 == %s 수"""
        import shared.macro_insight.daily_insight as di
        import inspect

        source = inspect.getsource(di.save_insight_to_db)

        # Extract column list between INSERT INTO ... ( ... ) VALUES
        insert_match = re.search(
            r'INSERT\s+INTO\s+DAILY_MACRO_INSIGHT\s*\((.*?)\)\s*VALUES',
            source,
            re.DOTALL | re.IGNORECASE,
        )
        assert insert_match, "INSERT INTO DAILY_MACRO_INSIGHT statement not found"

        columns_str = insert_match.group(1)
        # Count columns (comma-separated identifiers)
        columns = [c.strip() for c in columns_str.split(',') if c.strip()]
        column_count = len(columns)

        # Extract %s placeholders from VALUES clause
        values_match = re.search(
            r'VALUES\s*\((.*?)\)\s*ON\s+DUPLICATE',
            source,
            re.DOTALL | re.IGNORECASE,
        )
        assert values_match, "VALUES clause not found"

        values_str = values_match.group(1)
        placeholder_count = values_str.count('%s')

        assert column_count == placeholder_count, (
            f"Column count ({column_count}) != placeholder count ({placeholder_count}). "
            f"Columns: {columns}"
        )

    def test_daily_macro_insight_params_tuple_length(self):
        """params 튜플 길이가 컬럼 수와 일치하는지 소스 코드 분석으로 검증"""
        import shared.macro_insight.daily_insight as di
        import inspect

        source = inspect.getsource(di.save_insight_to_db)

        # Count columns
        insert_match = re.search(
            r'INSERT\s+INTO\s+DAILY_MACRO_INSIGHT\s*\((.*?)\)\s*VALUES',
            source,
            re.DOTALL | re.IGNORECASE,
        )
        columns_str = insert_match.group(1)
        columns = [c.strip() for c in columns_str.split(',') if c.strip()]
        column_count = len(columns)

        # Verify the params tuple construction matches
        # Find 'params = (' and count items until closing ')'
        params_match = re.search(
            r'params\s*=\s*\((.*?)\)\s*$',
            source,
            re.DOTALL | re.MULTILINE,
        )
        assert params_match, "params tuple not found"

        params_str = params_match.group(1)
        # Count non-empty lines that represent tuple items
        items = [
            line.strip().rstrip(',')
            for line in params_str.split('\n')
            if line.strip() and not line.strip().startswith('#')
        ]
        param_count = len(items)

        assert param_count == column_count, (
            f"params tuple items ({param_count}) != column count ({column_count})"
        )
