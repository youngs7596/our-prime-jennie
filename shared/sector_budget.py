# shared/sector_budget.py
# 동적 섹터 예산 (Dynamic Sector Budget)
# 작업 LLM: Claude Opus 4.6

"""
섹터 모멘텀 기반으로 watchlist 섹터 캡 + Portfolio Guard 한도를 동적 조정.

문제: Scout watchlist(20개)가 단순 LLM 점수 상위로만 선정되어,
핫 섹터(금융 등)가 8/20 슬롯을 독점. Portfolio Guard 고정 MAX_SECTOR_STOCKS=3으로 차단
→ buy-executor 반복 헛수고, 다른 섹터 기회 상실.

해결: 섹터 모멘텀(활황도) 기반으로 티어(HOT/WARM/COOL) 배정 후
watchlist 섹터 캡 + Portfolio Guard 한도를 동적 조정.

롤백: DYNAMIC_SECTOR_BUDGET_ENABLED=false → 기존 고정값 복원
"""

import json
import logging
import os
from typing import Dict, List, Optional, Tuple

from shared.sector_taxonomy import NAVER_TO_GROUP

logger = logging.getLogger(__name__)

# 티어별 기본 캡
TIER_CAPS = {
    "HOT": {"watchlist_cap": 5, "portfolio_cap": 5},
    "WARM": {"watchlist_cap": 3, "portfolio_cap": 3},
    "COOL": {"watchlist_cap": 2, "portfolio_cap": 2},
}

REDIS_KEY = "sector_budget:active"
REDIS_TTL = 86400  # 24h


def aggregate_sector_analysis_to_groups(
    sector_analysis: Dict[str, dict],
) -> Dict[str, dict]:
    """
    네이버 세분류(~79개) sector_analysis → 시스템 대분류(~14개) 집계.

    Args:
        sector_analysis: analyze_sector_momentum() 결과
            {세분류명: {"avg_return": float, "stock_count": int, "trend_status": str, ...}}

    Returns:
        {대분류명: {"avg_return": float, "stock_count": int, "has_falling_knife": bool}}
    """
    group_data: Dict[str, dict] = {}

    for sub_sector, info in sector_analysis.items():
        group = NAVER_TO_GROUP.get(sub_sector, sub_sector)
        avg_ret = info.get("avg_return", 0.0)
        count = info.get("stock_count", 0)
        trend = info.get("trend_status", "NEUTRAL")

        if group not in group_data:
            group_data[group] = {
                "total_return_weighted": 0.0,
                "total_count": 0,
                "has_falling_knife": False,
            }

        g = group_data[group]
        g["total_return_weighted"] += avg_ret * count
        g["total_count"] += count
        if trend == "FALLING_KNIFE":
            g["has_falling_knife"] = True

    result = {}
    for group, g in group_data.items():
        if g["total_count"] > 0:
            result[group] = {
                "avg_return": g["total_return_weighted"] / g["total_count"],
                "stock_count": g["total_count"],
                "has_falling_knife": g["has_falling_knife"],
            }

    return result


def assign_sector_tiers(
    group_analysis: Dict[str, dict],
) -> Dict[str, str]:
    """
    대분류별 avg_return percentile 기반 티어 배정.

    | 티어 | 조건 |
    |------|------|
    | HOT  | avg_return >= p75 AND > 0% |
    | COOL | avg_return <= p25 AND < 0%, 또는 FALLING_KNIFE |
    | WARM | 나머지 |

    Args:
        group_analysis: aggregate_sector_analysis_to_groups() 결과

    Returns:
        {대분류명: "HOT" | "WARM" | "COOL"}
    """
    if not group_analysis:
        return {}

    returns = sorted(info["avg_return"] for info in group_analysis.values())
    n = len(returns)

    if n == 0:
        return {}

    # percentile 계산 (nearest-rank)
    p25_idx = max(0, int(n * 0.25) - 1)
    p75_idx = min(n - 1, int(n * 0.75))
    p25 = returns[p25_idx]
    p75 = returns[p75_idx]

    tiers = {}
    for group, info in group_analysis.items():
        avg_ret = info["avg_return"]
        falling_knife = info.get("has_falling_knife", False)

        if falling_knife or (avg_ret <= p25 and avg_ret < 0):
            tiers[group] = "COOL"
        elif avg_ret >= p75 and avg_ret > 0:
            tiers[group] = "HOT"
        else:
            tiers[group] = "WARM"

    return tiers


def compute_sector_budget(
    tiers: Dict[str, str],
    portfolio_holdings: Optional[Dict[str, int]] = None,
) -> Dict[str, dict]:
    """
    섹터별 예산(watchlist cap, portfolio cap, effective cap) 계산.

    effective_watchlist_cap = min(watchlist_cap, portfolio_room + 1)
    effective_watchlist_cap = max(1, effective_watchlist_cap)

    Args:
        tiers: {대분류: "HOT"|"WARM"|"COOL"}
        portfolio_holdings: {대분류: 현재 보유 종목 수} (None이면 빈 dict)

    Returns:
        {대분류: {"tier": str, "watchlist_cap": int, "portfolio_cap": int, "effective_watchlist_cap": int}}
    """
    holdings = portfolio_holdings or {}
    budget = {}

    for group, tier in tiers.items():
        caps = TIER_CAPS.get(tier, TIER_CAPS["WARM"])
        wl_cap = caps["watchlist_cap"]
        pf_cap = caps["portfolio_cap"]

        current_held = holdings.get(group, 0)
        portfolio_room = max(0, pf_cap - current_held)
        effective_cap = min(wl_cap, portfolio_room + 1)  # +1 파이프라인 버퍼
        effective_cap = max(1, effective_cap)  # 최소 1 보장

        budget[group] = {
            "tier": tier,
            "watchlist_cap": wl_cap,
            "portfolio_cap": pf_cap,
            "effective_watchlist_cap": effective_cap,
        }

    return budget


def select_with_sector_budget(
    candidates: List[dict],
    budget: Dict[str, dict],
    max_size: int = 20,
    sector_resolver=None,
) -> List[dict]:
    """
    Greedy 알고리즘으로 섹터 예산 내에서 watchlist 선정.

    1. 후보를 LLM 점수 내림차순 정렬
    2. 각 후보의 대분류 섹터 캡 확인
    3. 캡 미달이면 선택, 도달이면 스킵
    4. max_size 채울 때까지 반복
    5. Backfill: 캡으로 max_size 못 채우면 나머지를 점수순으로 채움

    Args:
        candidates: [{"code": str, "name": str, "llm_score": float, ...}]
        budget: compute_sector_budget() 결과
        max_size: 최대 watchlist 크기
        sector_resolver: (code, name) -> 대분류명 함수 (None이면 '기타' 반환)

    Returns:
        선정된 후보 리스트 (최대 max_size개)
    """
    if not candidates:
        return []

    if not budget:
        # 예산 없으면 기존 로직 (점수순 top-N)
        sorted_cands = sorted(candidates, key=lambda x: x.get("llm_score", 0), reverse=True)
        return sorted_cands[:max_size]

    resolver = sector_resolver or (lambda code, name: "기타")

    # 점수 내림차순 정렬
    sorted_cands = sorted(candidates, key=lambda x: x.get("llm_score", 0), reverse=True)

    selected = []
    skipped = []
    sector_counts: Dict[str, int] = {}

    for cand in sorted_cands:
        if len(selected) >= max_size:
            break

        code = cand.get("code", "")
        name = cand.get("name", "")
        group = resolver(code, name)

        # 해당 섹터의 effective_watchlist_cap 조회
        sector_budget = budget.get(group)
        if sector_budget:
            cap = sector_budget["effective_watchlist_cap"]
        else:
            # 예산에 없는 섹터 → WARM 기본값
            cap = TIER_CAPS["WARM"]["watchlist_cap"]

        current = sector_counts.get(group, 0)
        if current < cap:
            selected.append(cand)
            sector_counts[group] = current + 1
        else:
            skipped.append(cand)

    # Backfill: max_size 못 채우면 스킵된 후보에서 점수순으로 채움
    if len(selected) < max_size and skipped:
        remaining = max_size - len(selected)
        selected.extend(skipped[:remaining])

    return selected


def save_sector_budget_to_redis(
    budget: Dict[str, dict],
    redis_client=None,
) -> bool:
    """
    섹터 예산을 Redis에 저장 (TTL 24h).

    Args:
        budget: compute_sector_budget() 결과
        redis_client: Redis 클라이언트 (None이면 자동 연결)

    Returns:
        성공 여부
    """
    try:
        client = redis_client or _get_default_redis()
        if client is None:
            return False

        payload = json.dumps(budget, ensure_ascii=False)
        client.set(REDIS_KEY, payload, ex=REDIS_TTL)
        logger.info(
            f"[Dynamic Sector Budget] Redis 저장 완료: {len(budget)}개 섹터 (TTL={REDIS_TTL}s)"
        )
        return True
    except Exception as e:
        logger.warning(f"[Dynamic Sector Budget] Redis 저장 실패: {e}")
        return False


def load_sector_budget_from_redis(
    redis_client=None,
) -> Optional[Dict[str, dict]]:
    """
    Redis에서 섹터 예산 로드.

    Returns:
        budget dict 또는 None (키 없음/실패)
    """
    try:
        client = redis_client or _get_default_redis()
        if client is None:
            return None

        raw = client.get(REDIS_KEY)
        if raw is None:
            return None

        budget = json.loads(raw)
        return budget
    except Exception as e:
        logger.warning(f"[Dynamic Sector Budget] Redis 로드 실패: {e}")
        return None


def _get_default_redis():
    """기본 Redis 클라이언트 (lazy)"""
    try:
        import redis as redis_lib

        url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        return redis_lib.from_url(url, decode_responses=True)
    except Exception:
        return None
