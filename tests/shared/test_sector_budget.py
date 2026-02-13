# tests/shared/test_sector_budget.py
# 동적 섹터 예산 유닛 테스트
# 작업 LLM: Claude Opus 4.6

import json
import pytest
from unittest.mock import MagicMock, patch

from shared.sector_budget import (
    aggregate_sector_analysis_to_groups,
    assign_sector_tiers,
    compute_sector_budget,
    select_with_sector_budget,
    save_sector_budget_to_redis,
    load_sector_budget_from_redis,
    TIER_CAPS,
    REDIS_KEY,
    REDIS_TTL,
    FALLING_KNIFE_THRESHOLD,
)


# ========================================================================
# 1. aggregate_sector_analysis_to_groups 테스트
# ========================================================================
class TestAggregateSectorAnalysis:

    def test_empty_input(self):
        result = aggregate_sector_analysis_to_groups({})
        assert result == {}

    def test_single_sector_maps_to_group(self):
        sa = {
            "반도체와반도체장비": {"avg_return": 2.5, "stock_count": 10, "trend_status": "NEUTRAL"},
        }
        result = aggregate_sector_analysis_to_groups(sa)
        assert "반도체/IT" in result
        assert result["반도체/IT"]["avg_return"] == 2.5
        assert result["반도체/IT"]["stock_count"] == 10

    def test_multiple_sub_sectors_aggregate(self):
        """같은 대분류의 여러 세분류가 가중평균으로 집계"""
        sa = {
            "반도체와반도체장비": {"avg_return": 3.0, "stock_count": 10, "trend_status": "NEUTRAL"},
            "디스플레이패널": {"avg_return": 1.0, "stock_count": 10, "trend_status": "NEUTRAL"},
        }
        result = aggregate_sector_analysis_to_groups(sa)
        # 가중평균: (3.0*10 + 1.0*10) / 20 = 2.0
        assert result["반도체/IT"]["avg_return"] == pytest.approx(2.0)
        assert result["반도체/IT"]["stock_count"] == 20

    def test_falling_knife_ratio_partial(self):
        """세분류 일부가 FALLING_KNIFE → 비중 계산"""
        sa = {
            "은행": {"avg_return": -2.0, "stock_count": 5, "trend_status": "FALLING_KNIFE"},
            "증권": {"avg_return": 1.0, "stock_count": 15, "trend_status": "NEUTRAL"},
        }
        result = aggregate_sector_analysis_to_groups(sa)
        # 5 / 20 = 0.25
        assert result["금융"]["falling_knife_ratio"] == pytest.approx(0.25)

    def test_falling_knife_ratio_zero(self):
        sa = {
            "은행": {"avg_return": 1.0, "stock_count": 5, "trend_status": "NEUTRAL"},
        }
        result = aggregate_sector_analysis_to_groups(sa)
        assert result["금융"]["falling_knife_ratio"] == 0.0

    def test_falling_knife_ratio_high(self):
        """대부분 종목이 FALLING_KNIFE → 비중 높음"""
        sa = {
            "은행": {"avg_return": -3.0, "stock_count": 15, "trend_status": "FALLING_KNIFE"},
            "증권": {"avg_return": 1.0, "stock_count": 5, "trend_status": "NEUTRAL"},
        }
        result = aggregate_sector_analysis_to_groups(sa)
        # 15 / 20 = 0.75
        assert result["금융"]["falling_knife_ratio"] == pytest.approx(0.75)

    def test_unknown_sector_uses_raw_name(self):
        """NAVER_TO_GROUP에 없는 세분류 → 원본 이름 사용"""
        sa = {
            "미래산업": {"avg_return": 5.0, "stock_count": 3, "trend_status": "NEUTRAL"},
        }
        result = aggregate_sector_analysis_to_groups(sa)
        assert "미래산업" in result

    def test_weighted_average_with_unequal_counts(self):
        """종목 수가 다른 세분류 가중평균"""
        sa = {
            "화학": {"avg_return": 2.0, "stock_count": 20, "trend_status": "NEUTRAL"},
            "석유와가스": {"avg_return": -1.0, "stock_count": 5, "trend_status": "NEUTRAL"},
        }
        result = aggregate_sector_analysis_to_groups(sa)
        # (2.0*20 + (-1.0)*5) / 25 = 35/25 = 1.4
        assert result["에너지/화학"]["avg_return"] == pytest.approx(1.4)


# ========================================================================
# 2. assign_sector_tiers 테스트
# ========================================================================
class TestAssignSectorTiers:

    def test_empty_input(self):
        assert assign_sector_tiers({}) == {}

    def test_single_sector_positive_is_hot(self):
        """하나의 섹터 양수 → HOT (p75 == p25 == 본인)"""
        ga = {"반도체/IT": {"avg_return": 2.0, "stock_count": 10, "falling_knife_ratio": 0.0}}
        tiers = assign_sector_tiers(ga)
        assert tiers["반도체/IT"] == "HOT"

    def test_single_sector_negative_is_cool(self):
        ga = {"반도체/IT": {"avg_return": -2.0, "stock_count": 10, "falling_knife_ratio": 0.0}}
        tiers = assign_sector_tiers(ga)
        assert tiers["반도체/IT"] == "COOL"

    def test_falling_knife_high_ratio_forces_cool(self):
        """FALLING_KNIFE 비중 >= 30% → COOL"""
        ga = {
            "금융": {"avg_return": 5.0, "stock_count": 10, "falling_knife_ratio": 0.5},
            "반도체/IT": {"avg_return": 3.0, "stock_count": 10, "falling_knife_ratio": 0.0},
            "바이오": {"avg_return": 1.0, "stock_count": 10, "falling_knife_ratio": 0.0},
            "자동차": {"avg_return": -1.0, "stock_count": 10, "falling_knife_ratio": 0.0},
        }
        tiers = assign_sector_tiers(ga)
        assert tiers["금융"] == "COOL"  # falling knife ratio 50%

    def test_falling_knife_low_ratio_not_cool(self):
        """FALLING_KNIFE 비중 < 30% → COOL 강제 안 됨"""
        ga = {
            "반도체/IT": {"avg_return": 3.0, "stock_count": 500, "falling_knife_ratio": 0.01},
            "금융": {"avg_return": 2.0, "stock_count": 10, "falling_knife_ratio": 0.0},
            "바이오": {"avg_return": 1.0, "stock_count": 10, "falling_knife_ratio": 0.0},
            "자동차": {"avg_return": -1.0, "stock_count": 10, "falling_knife_ratio": 0.0},
        }
        tiers = assign_sector_tiers(ga)
        # 반도체/IT: fk_ratio=1% → COOL 아님, avg_return 상위 → HOT
        assert tiers["반도체/IT"] == "HOT"

    def test_multi_sector_tier_distribution(self):
        """다수 섹터 → HOT/WARM/COOL 분포"""
        ga = {
            "반도체/IT": {"avg_return": 5.0, "stock_count": 10, "falling_knife_ratio": 0.0},
            "금융": {"avg_return": 3.0, "stock_count": 10, "falling_knife_ratio": 0.0},
            "바이오": {"avg_return": 1.0, "stock_count": 10, "falling_knife_ratio": 0.0},
            "자동차": {"avg_return": 0.5, "stock_count": 10, "falling_knife_ratio": 0.0},
            "소비재": {"avg_return": -0.5, "stock_count": 10, "falling_knife_ratio": 0.0},
            "건설/소재": {"avg_return": -2.0, "stock_count": 10, "falling_knife_ratio": 0.0},
            "철강/소재": {"avg_return": -3.0, "stock_count": 10, "falling_knife_ratio": 0.0},
            "운송": {"avg_return": -4.0, "stock_count": 10, "falling_knife_ratio": 0.0},
        }
        tiers = assign_sector_tiers(ga)
        assert tiers["반도체/IT"] == "HOT"
        assert tiers["운송"] == "COOL"
        assert tiers["철강/소재"] == "COOL"

    def test_all_positive_no_cool(self):
        """모든 수익률 양수 → COOL 조건(< 0) 불충족"""
        ga = {
            "반도체/IT": {"avg_return": 5.0, "stock_count": 10, "falling_knife_ratio": 0.0},
            "금융": {"avg_return": 3.0, "stock_count": 10, "falling_knife_ratio": 0.0},
            "바이오": {"avg_return": 1.0, "stock_count": 10, "falling_knife_ratio": 0.0},
            "자동차": {"avg_return": 0.5, "stock_count": 10, "falling_knife_ratio": 0.0},
        }
        tiers = assign_sector_tiers(ga)
        for group, tier in tiers.items():
            assert tier in ("HOT", "WARM"), f"{group} should not be COOL when all positive"

    def test_zero_return_not_hot(self):
        """avg_return = 0 → HOT 조건(> 0) 불충족"""
        ga = {
            "반도체/IT": {"avg_return": 0.0, "stock_count": 10, "falling_knife_ratio": 0.0},
        }
        tiers = assign_sector_tiers(ga)
        assert tiers["반도체/IT"] == "WARM"


# ========================================================================
# 3. compute_sector_budget 테스트
# ========================================================================
class TestComputeSectorBudget:

    def test_hot_caps(self):
        tiers = {"반도체/IT": "HOT"}
        budget = compute_sector_budget(tiers)
        assert budget["반도체/IT"]["watchlist_cap"] == 5
        assert budget["반도체/IT"]["portfolio_cap"] == 5
        assert budget["반도체/IT"]["tier"] == "HOT"

    def test_warm_caps(self):
        tiers = {"금융": "WARM"}
        budget = compute_sector_budget(tiers)
        assert budget["금융"]["watchlist_cap"] == 3
        assert budget["금융"]["portfolio_cap"] == 3

    def test_cool_caps(self):
        tiers = {"운송": "COOL"}
        budget = compute_sector_budget(tiers)
        assert budget["운송"]["watchlist_cap"] == 2
        assert budget["운송"]["portfolio_cap"] == 2

    def test_effective_cap_no_holdings(self):
        """보유 없으면 effective = min(wl_cap, pf_cap + 1) = min(5, 6) = 5"""
        tiers = {"반도체/IT": "HOT"}
        budget = compute_sector_budget(tiers, portfolio_holdings={})
        assert budget["반도체/IT"]["effective_watchlist_cap"] == 5

    def test_effective_cap_with_holdings(self):
        """HOT(cap=5), 3개 보유 → effective = min(5, 5-3+1) = min(5,3) = 3"""
        tiers = {"금융": "HOT"}
        holdings = {"금융": 3}
        budget = compute_sector_budget(tiers, holdings)
        assert budget["금융"]["effective_watchlist_cap"] == 3

    def test_effective_cap_full_portfolio(self):
        """보유 == portfolio_cap → room=0, effective = min(cap, 0+1) = 1"""
        tiers = {"금융": "WARM"}  # portfolio_cap=3
        holdings = {"금융": 3}
        budget = compute_sector_budget(tiers, holdings)
        assert budget["금융"]["effective_watchlist_cap"] == 1

    def test_effective_cap_over_portfolio(self):
        """보유 > portfolio_cap → room=0 (음수 아님), effective = 1"""
        tiers = {"금융": "COOL"}  # portfolio_cap=2
        holdings = {"금융": 5}
        budget = compute_sector_budget(tiers, holdings)
        assert budget["금융"]["effective_watchlist_cap"] == 1

    def test_empty_tiers(self):
        budget = compute_sector_budget({})
        assert budget == {}


# ========================================================================
# 4. select_with_sector_budget 테스트
# ========================================================================
class TestSelectWithSectorBudget:

    def _make_candidates(self, items):
        """[(code, name, score, sector_group)] → candidates list"""
        return [{"code": c, "name": n, "llm_score": s, "_group": g} for c, n, s, g in items]

    def _resolver(self, code, name):
        """테스트용 섹터 리졸버 (후보에 _group 필드 사용)"""
        # 실제로는 candidates에서 찾아야 하지만, 테스트에서는 외부 맵 사용
        return self._group_map.get(code, "기타")

    def test_empty_candidates(self):
        result = select_with_sector_budget([], {}, 20)
        assert result == []

    def test_empty_budget_falls_back_to_top_n(self):
        """예산 없으면 기존 top-N"""
        cands = [
            {"code": "A", "name": "A", "llm_score": 90},
            {"code": "B", "name": "B", "llm_score": 80},
            {"code": "C", "name": "C", "llm_score": 70},
        ]
        result = select_with_sector_budget(cands, {}, max_size=2)
        assert len(result) == 2
        assert result[0]["code"] == "A"
        assert result[1]["code"] == "B"

    def test_sector_cap_enforced(self):
        """섹터 캡 초과 → 해당 섹터 종목 스킵"""
        self._group_map = {"A": "금융", "B": "금융", "C": "금융", "D": "반도체/IT"}
        cands = [
            {"code": "A", "name": "A", "llm_score": 90},
            {"code": "B", "name": "B", "llm_score": 85},
            {"code": "C", "name": "C", "llm_score": 80},
            {"code": "D", "name": "D", "llm_score": 75},
        ]
        budget = {
            "금융": {"effective_watchlist_cap": 2, "tier": "WARM", "watchlist_cap": 3, "portfolio_cap": 3},
            "반도체/IT": {"effective_watchlist_cap": 3, "tier": "HOT", "watchlist_cap": 5, "portfolio_cap": 5},
        }
        result = select_with_sector_budget(cands, budget, max_size=4, sector_resolver=self._resolver)
        # A(금융), B(금융), D(반도체) selected; C(금융) initially skipped but backfilled
        codes = [r["code"] for r in result]
        assert "A" in codes
        assert "B" in codes
        assert "D" in codes
        # C is backfilled since max_size=4
        assert len(result) == 4

    def test_sector_cap_prevents_over_selection(self):
        """max_size보다 섹터 캡이 더 제한적 → 더 적게 선정되나 backfill"""
        self._group_map = {"A": "금융", "B": "금융", "C": "금융"}
        cands = [
            {"code": "A", "name": "A", "llm_score": 90},
            {"code": "B", "name": "B", "llm_score": 85},
            {"code": "C", "name": "C", "llm_score": 80},
        ]
        budget = {
            "금융": {"effective_watchlist_cap": 1, "tier": "COOL", "watchlist_cap": 2, "portfolio_cap": 2},
        }
        result = select_with_sector_budget(cands, budget, max_size=3, sector_resolver=self._resolver)
        # Only A from first pass, B and C backfilled
        assert len(result) == 3
        assert result[0]["code"] == "A"  # first pass

    def test_backfill_fills_remaining(self):
        """캡으로 max_size 못 채우면 스킵된 종목으로 backfill"""
        self._group_map = {"A": "금융", "B": "금융", "C": "반도체/IT"}
        cands = [
            {"code": "A", "name": "A", "llm_score": 90},
            {"code": "B", "name": "B", "llm_score": 85},
            {"code": "C", "name": "C", "llm_score": 80},
        ]
        budget = {
            "금융": {"effective_watchlist_cap": 1, "tier": "COOL", "watchlist_cap": 2, "portfolio_cap": 2},
            "반도체/IT": {"effective_watchlist_cap": 1, "tier": "COOL", "watchlist_cap": 2, "portfolio_cap": 2},
        }
        # max_size=3: A(금융), C(반도체) from first pass, B(금융) backfilled
        result = select_with_sector_budget(cands, budget, max_size=3, sector_resolver=self._resolver)
        assert len(result) == 3
        codes = [r["code"] for r in result]
        assert codes[0] == "A"  # first selected
        assert codes[1] == "C"  # second (IT)
        assert codes[2] == "B"  # backfilled

    def test_unknown_sector_uses_warm_cap(self):
        """예산에 없는 섹터 → WARM 기본값(3)"""
        self._group_map = {"A": "미분류"}
        cands = [{"code": "A", "name": "A", "llm_score": 90}]
        budget = {"금융": {"effective_watchlist_cap": 1, "tier": "COOL", "watchlist_cap": 2, "portfolio_cap": 2}}
        result = select_with_sector_budget(cands, budget, max_size=1, sector_resolver=self._resolver)
        assert len(result) == 1

    def test_max_size_respected(self):
        """max_size 이상 선정 안 함"""
        self._group_map = {f"S{i}": f"섹터{i}" for i in range(10)}
        cands = [{"code": f"S{i}", "name": f"Stock{i}", "llm_score": 90 - i} for i in range(10)]
        budget = {f"섹터{i}": {"effective_watchlist_cap": 5, "tier": "HOT", "watchlist_cap": 5, "portfolio_cap": 5} for i in range(10)}
        result = select_with_sector_budget(cands, budget, max_size=5, sector_resolver=self._resolver)
        assert len(result) == 5

    def test_score_ordering_preserved(self):
        """선정 순서는 LLM 점수 내림차순"""
        self._group_map = {"A": "금융", "B": "반도체/IT", "C": "바이오"}
        cands = [
            {"code": "A", "name": "A", "llm_score": 90},
            {"code": "B", "name": "B", "llm_score": 85},
            {"code": "C", "name": "C", "llm_score": 80},
        ]
        budget = {
            "금융": {"effective_watchlist_cap": 3, "tier": "HOT", "watchlist_cap": 5, "portfolio_cap": 5},
            "반도체/IT": {"effective_watchlist_cap": 3, "tier": "HOT", "watchlist_cap": 5, "portfolio_cap": 5},
            "바이오": {"effective_watchlist_cap": 3, "tier": "HOT", "watchlist_cap": 5, "portfolio_cap": 5},
        }
        result = select_with_sector_budget(cands, budget, max_size=3, sector_resolver=self._resolver)
        assert result[0]["llm_score"] >= result[1]["llm_score"] >= result[2]["llm_score"]


# ========================================================================
# 5. Redis persistence 테스트
# ========================================================================
class TestRedisPersistence:

    def test_save_success(self):
        mock_redis = MagicMock()
        budget = {"금융": {"tier": "HOT", "watchlist_cap": 5, "portfolio_cap": 5, "effective_watchlist_cap": 5}}
        result = save_sector_budget_to_redis(budget, redis_client=mock_redis)
        assert result is True
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == REDIS_KEY
        assert call_args[1]["ex"] == REDIS_TTL

    def test_save_failure(self):
        mock_redis = MagicMock()
        mock_redis.set.side_effect = Exception("Connection refused")
        result = save_sector_budget_to_redis({"test": {}}, redis_client=mock_redis)
        assert result is False

    def test_load_success(self):
        budget = {"금융": {"tier": "HOT", "watchlist_cap": 5, "portfolio_cap": 5, "effective_watchlist_cap": 5}}
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(budget)
        result = load_sector_budget_from_redis(redis_client=mock_redis)
        assert result == budget

    def test_load_no_key(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        result = load_sector_budget_from_redis(redis_client=mock_redis)
        assert result is None

    def test_load_failure(self):
        mock_redis = MagicMock()
        mock_redis.get.side_effect = Exception("Connection refused")
        result = load_sector_budget_from_redis(redis_client=mock_redis)
        assert result is None

    def test_roundtrip(self):
        """save → load 라운드트립"""
        mock_redis = MagicMock()
        saved_data = {}

        def mock_set(key, value, ex=None):
            saved_data[key] = value

        def mock_get(key):
            return saved_data.get(key)

        mock_redis.set = mock_set
        mock_redis.get = mock_get

        budget = {
            "반도체/IT": {"tier": "HOT", "watchlist_cap": 5, "portfolio_cap": 5, "effective_watchlist_cap": 5},
            "금융": {"tier": "WARM", "watchlist_cap": 3, "portfolio_cap": 3, "effective_watchlist_cap": 3},
        }
        save_sector_budget_to_redis(budget, redis_client=mock_redis)
        loaded = load_sector_budget_from_redis(redis_client=mock_redis)
        assert loaded == budget
