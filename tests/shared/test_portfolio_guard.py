# tests/shared/test_portfolio_guard.py
# Portfolio Guard Layer 2 유닛 테스트
# 작업 LLM: Claude Opus 4.6

import pytest
from unittest.mock import MagicMock, patch

from shared.portfolio_guard import PortfolioGuard


class MockConfig:
    """테스트용 ConfigManager"""

    def __init__(self, overrides: dict = None):
        self._values = {
            "PORTFOLIO_GUARD_ENABLED": True,
            "MAX_SECTOR_STOCKS": 3,
            "CASH_FLOOR_STRONG_BULL_PCT": 5.0,
            "CASH_FLOOR_BULL_PCT": 10.0,
            "CASH_FLOOR_SIDEWAYS_PCT": 15.0,
            "CASH_FLOOR_BEAR_PCT": 25.0,
        }
        if overrides:
            self._values.update(overrides)

    def get(self, key, default=None):
        return self._values.get(key, default)

    def get_int(self, key, default=0):
        val = self._values.get(key)
        return int(val) if val is not None else default

    def get_float(self, key, default=0.0):
        val = self._values.get(key)
        return float(val) if val is not None else default

    def get_bool(self, key, default=False):
        val = self._values.get(key)
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        return str(val).lower() in ("true", "1", "yes")


def _make_sector_classifier(group_map: dict = None):
    """SectorClassifier mock 생성. group_map: {stock_code: sector_group}"""
    default_group = "기타"
    sc = MagicMock()
    if group_map:
        sc.get_sector_group.side_effect = lambda code, name: group_map.get(code, default_group)
    else:
        sc.get_sector_group.return_value = default_group
    return sc


# ========================================================================
# 1. check_sector_stock_count 테스트
# ========================================================================
class TestSectorStockCount:

    def test_empty_portfolio_allows(self):
        """빈 포트폴리오 → 항상 통과"""
        config = MockConfig()
        sc = _make_sector_classifier({"005930": "반도체/IT"})
        guard = PortfolioGuard(config, sc)

        result = guard.check_sector_stock_count("005930", "삼성전자", [])
        assert result["passed"] is True
        assert result["current_count"] == 0

    def test_below_limit_allows(self):
        """한도 미만 → 통과"""
        group_map = {"005930": "반도체/IT", "000660": "반도체/IT", "035720": "반도체/IT", "035420": "반도체/IT"}
        config = MockConfig()
        sc = _make_sector_classifier(group_map)
        guard = PortfolioGuard(config, sc)

        portfolio = [
            {"stock_code": "000660", "stock_name": "SK하이닉스"},
            {"stock_code": "035720", "stock_name": "카카오"},
        ]
        result = guard.check_sector_stock_count("005930", "삼성전자", portfolio)
        assert result["passed"] is True
        assert result["current_count"] == 2

    def test_at_limit_rejects(self):
        """한도 도달(3개) → 거부"""
        group_map = {
            "005930": "반도체/IT",
            "000660": "반도체/IT",
            "035720": "반도체/IT",
            "035420": "반도체/IT",
        }
        config = MockConfig()  # MAX_SECTOR_STOCKS=3
        sc = _make_sector_classifier(group_map)
        guard = PortfolioGuard(config, sc)

        portfolio = [
            {"stock_code": "000660", "stock_name": "SK하이닉스"},
            {"stock_code": "035720", "stock_name": "카카오"},
            {"stock_code": "035420", "stock_name": "NAVER"},
        ]
        result = guard.check_sector_stock_count("005930", "삼성전자", portfolio)
        assert result["passed"] is False
        assert result["current_count"] == 3
        assert "종목 수 초과" in result["reason"]

    def test_different_sector_allows(self):
        """다른 섹터 종목은 카운트 안 함"""
        group_map = {
            "005930": "반도체/IT",
            "105560": "금융",
            "055550": "금융",
            "086790": "금융",
        }
        config = MockConfig()
        sc = _make_sector_classifier(group_map)
        guard = PortfolioGuard(config, sc)

        portfolio = [
            {"stock_code": "105560", "stock_name": "KB금융"},
            {"stock_code": "055550", "stock_name": "신한지주"},
            {"stock_code": "086790", "stock_name": "하나금융지주"},
        ]
        # 금융 3개 보유, but IT 종목 매수 → 통과
        result = guard.check_sector_stock_count("005930", "삼성전자", portfolio)
        assert result["passed"] is True
        assert result["current_count"] == 0

    def test_custom_max_sector_stocks(self):
        """MAX_SECTOR_STOCKS 커스텀 설정"""
        group_map = {
            "005930": "반도체/IT",
            "000660": "반도체/IT",
        }
        config = MockConfig({"MAX_SECTOR_STOCKS": 1})
        sc = _make_sector_classifier(group_map)
        guard = PortfolioGuard(config, sc)

        portfolio = [{"stock_code": "000660", "stock_name": "SK하이닉스"}]
        result = guard.check_sector_stock_count("005930", "삼성전자", portfolio)
        assert result["passed"] is False
        assert result["max_allowed"] == 1

    def test_portfolio_with_code_key(self):
        """포트폴리오 dict에 'code' 키 사용"""
        group_map = {"005930": "반도체/IT", "000660": "반도체/IT"}
        config = MockConfig()
        sc = _make_sector_classifier(group_map)
        guard = PortfolioGuard(config, sc)

        portfolio = [{"code": "000660", "name": "SK하이닉스"}]
        result = guard.check_sector_stock_count("005930", "삼성전자", portfolio)
        assert result["passed"] is True
        assert result["current_count"] == 1

    def test_portfolio_item_without_code_skipped(self):
        """코드 없는 포트폴리오 항목은 스킵"""
        group_map = {"005930": "반도체/IT"}
        config = MockConfig()
        sc = _make_sector_classifier(group_map)
        guard = PortfolioGuard(config, sc)

        portfolio = [{"name": "알 수 없음"}]  # code 없음
        result = guard.check_sector_stock_count("005930", "삼성전자", portfolio)
        assert result["passed"] is True
        assert result["current_count"] == 0

    def test_sector_group_returned(self):
        """결과에 sector_group 포함"""
        group_map = {"005930": "반도체/IT"}
        config = MockConfig()
        sc = _make_sector_classifier(group_map)
        guard = PortfolioGuard(config, sc)

        result = guard.check_sector_stock_count("005930", "삼성전자", [])
        assert result["sector_group"] == "반도체/IT"


# ========================================================================
# 2. check_cash_floor 테스트
# ========================================================================
class TestCashFloor:

    def test_strong_bull_floor_5pct(self):
        """STRONG_BULL: 5% 하한선"""
        config = MockConfig()
        guard = PortfolioGuard(config, MagicMock())

        # 총자산 10M, 현금 1M, 매수 0.4M → 현금 0.6M = 6% > 5% → 통과
        result = guard.check_cash_floor(400_000, 1_000_000, 10_000_000, "STRONG_BULL")
        assert result["passed"] is True
        assert result["floor_pct"] == 5.0

    def test_strong_bull_floor_violated(self):
        """STRONG_BULL: 5% 하한선 위반"""
        config = MockConfig()
        guard = PortfolioGuard(config, MagicMock())

        # 총자산 10M, 현금 600K, 매수 200K → 현금 400K = 4% < 5%
        result = guard.check_cash_floor(200_000, 600_000, 10_000_000, "STRONG_BULL")
        assert result["passed"] is False
        assert "현금 하한선 위반" in result["reason"]

    def test_bull_floor_10pct(self):
        """BULL: 10% 하한선"""
        config = MockConfig()
        guard = PortfolioGuard(config, MagicMock())

        # 총자산 10M, 현금 2M, 매수 0.5M → 현금 1.5M = 15% > 10%
        result = guard.check_cash_floor(500_000, 2_000_000, 10_000_000, "BULL")
        assert result["passed"] is True
        assert result["floor_pct"] == 10.0

    def test_bull_floor_violated(self):
        """BULL: 10% 하한선 위반"""
        config = MockConfig()
        guard = PortfolioGuard(config, MagicMock())

        # 총자산 10M, 현금 1.2M, 매수 0.5M → 현금 0.7M = 7% < 10%
        result = guard.check_cash_floor(500_000, 1_200_000, 10_000_000, "BULL")
        assert result["passed"] is False

    def test_sideways_floor_15pct(self):
        """SIDEWAYS: 15% 하한선"""
        config = MockConfig()
        guard = PortfolioGuard(config, MagicMock())

        result = guard.check_cash_floor(500_000, 2_000_000, 10_000_000, "SIDEWAYS")
        assert result["passed"] is True
        assert result["floor_pct"] == 15.0

    def test_bear_floor_25pct(self):
        """BEAR: 25% 하한선"""
        config = MockConfig()
        guard = PortfolioGuard(config, MagicMock())

        # 총자산 10M, 현금 3M, 매수 0.2M → 현금 2.8M = 28% > 25%
        result = guard.check_cash_floor(200_000, 3_000_000, 10_000_000, "BEAR")
        assert result["passed"] is True
        assert result["floor_pct"] == 25.0

    def test_bear_floor_violated(self):
        """BEAR: 25% 하한선 위반"""
        config = MockConfig()
        guard = PortfolioGuard(config, MagicMock())

        # 총자산 10M, 현금 3M, 매수 1M → 현금 2M = 20% < 25%
        result = guard.check_cash_floor(1_000_000, 3_000_000, 10_000_000, "BEAR")
        assert result["passed"] is False

    def test_unknown_regime_uses_sideways_default(self):
        """알 수 없는 국면 → SIDEWAYS 기본값 (15%)"""
        config = MockConfig()
        guard = PortfolioGuard(config, MagicMock())

        # 총자산 10M, 현금 2M, 매수 0.2M → 현금 1.8M = 18% > 15%
        result = guard.check_cash_floor(200_000, 2_000_000, 10_000_000, "UNKNOWN")
        assert result["passed"] is True
        assert result["floor_pct"] == 15.0

    def test_zero_total_assets(self):
        """총자산 0 → 실패"""
        config = MockConfig()
        guard = PortfolioGuard(config, MagicMock())

        result = guard.check_cash_floor(100_000, 100_000, 0, "BULL")
        assert result["passed"] is False
        assert "총자산이 0" in result["reason"]

    def test_exact_boundary_passes(self):
        """정확히 경계값 → 통과"""
        config = MockConfig()
        guard = PortfolioGuard(config, MagicMock())

        # 총자산 10M, 현금 1.5M, 매수 0.5M → 현금 1M = 10% == 10% → 통과 (>=)
        result = guard.check_cash_floor(500_000, 1_500_000, 10_000_000, "BULL")
        assert result["passed"] is True


# ========================================================================
# 3. check_all 통합 테스트
# ========================================================================
class TestCheckAll:

    def _make_guard(self, config_overrides=None, group_map=None):
        config = MockConfig(config_overrides)
        sc = _make_sector_classifier(group_map or {"005930": "반도체/IT"})
        return PortfolioGuard(config, sc)

    def test_both_pass(self):
        """섹터+현금 모두 통과"""
        guard = self._make_guard()
        result = guard.check_all(
            candidate_code="005930",
            candidate_name="삼성전자",
            current_portfolio=[],
            buy_amount=500_000,
            available_cash=5_000_000,
            total_assets=10_000_000,
            market_regime="BULL",
        )
        assert result["passed"] is True
        assert result["shadow"] is False

    def test_sector_rejects(self):
        """섹터 종목 수 초과 → 차단"""
        group_map = {
            "005930": "반도체/IT",
            "000660": "반도체/IT",
            "035720": "반도체/IT",
            "035420": "반도체/IT",
        }
        guard = self._make_guard(group_map=group_map)
        portfolio = [
            {"stock_code": "000660", "stock_name": "SK하이닉스"},
            {"stock_code": "035720", "stock_name": "카카오"},
            {"stock_code": "035420", "stock_name": "NAVER"},
        ]
        result = guard.check_all(
            candidate_code="005930",
            candidate_name="삼성전자",
            current_portfolio=portfolio,
            buy_amount=500_000,
            available_cash=5_000_000,
            total_assets=10_000_000,
            market_regime="BULL",
        )
        assert result["passed"] is False
        assert "섹터 종목 수 초과" in result["reason"]

    def test_cash_floor_rejects(self):
        """현금 하한선 위반 → 차단"""
        guard = self._make_guard()
        result = guard.check_all(
            candidate_code="005930",
            candidate_name="삼성전자",
            current_portfolio=[],
            buy_amount=9_000_000,
            available_cash=9_500_000,
            total_assets=10_000_000,
            market_regime="BULL",  # 10% 하한선
        )
        assert result["passed"] is False
        assert "현금 하한선 위반" in result["reason"]

    def test_shadow_mode_sector(self):
        """PORTFOLIO_GUARD_ENABLED=False → shadow mode (로그만, 차단 안 함)"""
        group_map = {
            "005930": "반도체/IT",
            "000660": "반도체/IT",
            "035720": "반도체/IT",
            "035420": "반도체/IT",
        }
        guard = self._make_guard(
            config_overrides={"PORTFOLIO_GUARD_ENABLED": False},
            group_map=group_map,
        )
        portfolio = [
            {"stock_code": "000660", "stock_name": "SK하이닉스"},
            {"stock_code": "035720", "stock_name": "카카오"},
            {"stock_code": "035420", "stock_name": "NAVER"},
        ]
        result = guard.check_all(
            candidate_code="005930",
            candidate_name="삼성전자",
            current_portfolio=portfolio,
            buy_amount=500_000,
            available_cash=5_000_000,
            total_assets=10_000_000,
            market_regime="BULL",
        )
        # shadow mode: 통과하되 shadow=True
        assert result["passed"] is True
        assert result["shadow"] is True

    def test_shadow_mode_cash(self):
        """Shadow mode: 현금 하한선 위반이어도 차단 안 함"""
        guard = self._make_guard(config_overrides={"PORTFOLIO_GUARD_ENABLED": False})
        result = guard.check_all(
            candidate_code="005930",
            candidate_name="삼성전자",
            current_portfolio=[],
            buy_amount=9_000_000,
            available_cash=9_500_000,
            total_assets=10_000_000,
            market_regime="BULL",
        )
        assert result["passed"] is True
        assert result["shadow"] is True

    def test_fail_fast_sector_before_cash(self):
        """섹터에서 먼저 실패 → 현금 체크 미수행 (fail-fast)"""
        group_map = {
            "005930": "반도체/IT",
            "000660": "반도체/IT",
            "035720": "반도체/IT",
            "035420": "반도체/IT",
        }
        guard = self._make_guard(group_map=group_map)
        portfolio = [
            {"stock_code": "000660", "stock_name": "SK하이닉스"},
            {"stock_code": "035720", "stock_name": "카카오"},
            {"stock_code": "035420", "stock_name": "NAVER"},
        ]
        result = guard.check_all(
            candidate_code="005930",
            candidate_name="삼성전자",
            current_portfolio=portfolio,
            buy_amount=9_000_000,  # 현금 위반이기도 함
            available_cash=9_500_000,
            total_assets=10_000_000,
            market_regime="BULL",
        )
        assert result["passed"] is False
        # 섹터에서 먼저 실패해야 함
        assert "섹터 종목 수 초과" in result["reason"]
        # cash_floor 체크는 checks에 없어야 함 (fail-fast)
        assert "cash_floor" not in result["checks"]


# ========================================================================
# 4. 동적 섹터 캡 (Dynamic Sector Budget) 테스트
# ========================================================================
class TestDynamicSectorCap:

    def test_dynamic_cap_from_redis(self):
        """Redis sector_budget → 동적 한도 적용"""
        group_map = {
            "005930": "반도체/IT",
            "000660": "반도체/IT",
            "035720": "반도체/IT",
            "035420": "반도체/IT",
            "066570": "반도체/IT",
        }
        config = MockConfig({"DYNAMIC_SECTOR_BUDGET_ENABLED": True})
        sc = _make_sector_classifier(group_map)
        guard = PortfolioGuard(config, sc)

        # Redis에서 반도체/IT → HOT(portfolio_cap=5) 반환하도록 mock
        budget = {"반도체/IT": {"tier": "HOT", "watchlist_cap": 5, "portfolio_cap": 5, "effective_watchlist_cap": 5}}
        with patch("shared.portfolio_guard.PortfolioGuard._get_dynamic_sector_cap", return_value=5):
            portfolio = [
                {"stock_code": "000660", "stock_name": "SK하이닉스"},
                {"stock_code": "035720", "stock_name": "카카오"},
                {"stock_code": "035420", "stock_name": "NAVER"},
            ]
            # 기존 MAX_SECTOR_STOCKS=3이면 차단, 동적 cap=5이면 통과
            result = guard.check_sector_stock_count("005930", "삼성전자", portfolio)
            assert result["passed"] is True
            assert result["max_allowed"] == 5

    def test_dynamic_cap_disabled_falls_back(self):
        """DYNAMIC_SECTOR_BUDGET_ENABLED=false → 기존 고정값"""
        group_map = {
            "005930": "반도체/IT",
            "000660": "반도체/IT",
            "035720": "반도체/IT",
            "035420": "반도체/IT",
        }
        config = MockConfig({"DYNAMIC_SECTOR_BUDGET_ENABLED": False, "MAX_SECTOR_STOCKS": 3})
        sc = _make_sector_classifier(group_map)
        guard = PortfolioGuard(config, sc)

        portfolio = [
            {"stock_code": "000660", "stock_name": "SK하이닉스"},
            {"stock_code": "035720", "stock_name": "카카오"},
            {"stock_code": "035420", "stock_name": "NAVER"},
        ]
        result = guard.check_sector_stock_count("005930", "삼성전자", portfolio)
        assert result["passed"] is False
        assert result["max_allowed"] == 3

    def test_dynamic_cap_redis_failure_falls_back(self):
        """Redis 실패 → 기존 고정값 fallback"""
        group_map = {"005930": "반도체/IT", "000660": "반도체/IT", "035720": "반도체/IT", "035420": "반도체/IT"}
        config = MockConfig({"DYNAMIC_SECTOR_BUDGET_ENABLED": True, "MAX_SECTOR_STOCKS": 3})
        sc = _make_sector_classifier(group_map)
        guard = PortfolioGuard(config, sc)

        # _get_dynamic_sector_cap returns None (Redis failure)
        with patch("shared.portfolio_guard.PortfolioGuard._get_dynamic_sector_cap", return_value=None):
            portfolio = [
                {"stock_code": "000660", "stock_name": "SK하이닉스"},
                {"stock_code": "035720", "stock_name": "카카오"},
                {"stock_code": "035420", "stock_name": "NAVER"},
            ]
            result = guard.check_sector_stock_count("005930", "삼성전자", portfolio)
            assert result["passed"] is False
            assert result["max_allowed"] == 3

    def test_dynamic_cap_cool_sector_restricts(self):
        """COOL 섹터 → portfolio_cap=2로 제한"""
        group_map = {"A": "운송", "B": "운송", "C": "운송"}
        config = MockConfig({"DYNAMIC_SECTOR_BUDGET_ENABLED": True, "MAX_SECTOR_STOCKS": 3})
        sc = _make_sector_classifier(group_map)
        guard = PortfolioGuard(config, sc)

        with patch("shared.portfolio_guard.PortfolioGuard._get_dynamic_sector_cap", return_value=2):
            portfolio = [
                {"stock_code": "B", "stock_name": "운송B"},
                {"stock_code": "C", "stock_name": "운송C"},
            ]
            # 기존 MAX_SECTOR_STOCKS=3이면 통과, 동적 cap=2이면 차단
            result = guard.check_sector_stock_count("A", "운송A", portfolio)
            assert result["passed"] is False
            assert result["max_allowed"] == 2
