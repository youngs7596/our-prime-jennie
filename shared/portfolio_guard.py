# shared/portfolio_guard.py
# Portfolio Guard Layer 2 — 포트폴리오 수준 리스크 관리
# 작업 LLM: Claude Opus 4.6

"""
개별 종목 필터(DiversificationChecker, PositionSizer)와 별개로,
포트폴리오 전체 구조를 검증하는 독립 모듈.

체크 항목:
1. 섹터 종목 수 제한 (MAX_SECTOR_STOCKS): 동일 대분류에 N개 초과 보유 방지
   - DYNAMIC_SECTOR_BUDGET_ENABLED=true 시 Redis sector_budget에서 동적 한도 사용
2. 현금 하한선 (CASH_FLOOR_*_PCT): 국면별 최소 현금 비율 강제

롤백: PORTFOLIO_GUARD_ENABLED=false → shadow mode (로그만, 차단 안 함)
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class PortfolioGuard:
    """포트폴리오 수준 리스크 가드"""

    # 국면별 현금 하한선 설정 키 매핑
    CASH_FLOOR_KEYS = {
        "STRONG_BULL": "CASH_FLOOR_STRONG_BULL_PCT",
        "BULL": "CASH_FLOOR_BULL_PCT",
        "SIDEWAYS": "CASH_FLOOR_SIDEWAYS_PCT",
        "BEAR": "CASH_FLOOR_BEAR_PCT",
    }

    # 설정 키가 없는 국면의 기본값
    CASH_FLOOR_DEFAULTS = {
        "STRONG_BULL": 5.0,
        "BULL": 10.0,
        "SIDEWAYS": 15.0,
        "BEAR": 25.0,
    }

    def __init__(self, config, sector_classifier):
        """
        Args:
            config: ConfigManager 인스턴스
            sector_classifier: SectorClassifier 인스턴스 (get_sector_group 메서드 필요)
        """
        self.config = config
        self.sector_classifier = sector_classifier

    def _get_dynamic_sector_cap(self, sector_group: str) -> Optional[int]:
        """
        Redis sector_budget에서 해당 섹터의 동적 portfolio_cap 조회.

        Returns:
            동적 한도 (int) 또는 None (비활성/실패/키 없음)
        """
        if not self.config.get_bool("DYNAMIC_SECTOR_BUDGET_ENABLED", default=True):
            return None

        try:
            from shared.sector_budget import load_sector_budget_from_redis

            budget = load_sector_budget_from_redis()
            if budget and sector_group in budget:
                return budget[sector_group].get("portfolio_cap")
        except Exception as e:
            logger.debug(f"[PortfolioGuard] 동적 섹터 캡 조회 실패: {e}")

        return None

    def check_sector_stock_count(
        self,
        candidate_code: str,
        candidate_name: str,
        current_portfolio: List[dict],
    ) -> Dict:
        """
        동일 섹터(대분류) 보유 종목 수 제한 체크.

        DYNAMIC_SECTOR_BUDGET_ENABLED=true 시 Redis에서 동적 한도 사용.
        Redis 실패/비활성 시 기존 MAX_SECTOR_STOCKS 고정값 fallback.

        Args:
            candidate_code: 매수 후보 종목코드
            candidate_name: 매수 후보 종목명
            current_portfolio: 현재 포트폴리오 (list of dict with code/stock_code, name/stock_name)

        Returns:
            {"passed": bool, "reason": str, "sector_group": str, "current_count": int, "max_allowed": int}
        """
        static_max = self.config.get_int("MAX_SECTOR_STOCKS", default=3)
        candidate_group = self.sector_classifier.get_sector_group(candidate_code, candidate_name)

        # 동적 섹터 캡 조회 → 실패 시 고정값
        dynamic_cap = self._get_dynamic_sector_cap(candidate_group)
        max_sector_stocks = dynamic_cap if dynamic_cap is not None else static_max

        # 현재 포트폴리오에서 같은 대분류 종목 수 카운트
        count = 0
        for item in current_portfolio:
            p_code = item.get("stock_code") or item.get("code")
            p_name = item.get("stock_name") or item.get("name", p_code or "")
            if not p_code:
                continue
            p_group = self.sector_classifier.get_sector_group(p_code, p_name)
            if p_group == candidate_group:
                count += 1

        if count >= max_sector_stocks:
            reason = (
                f"섹터 종목 수 초과: '{candidate_group}' 대분류에 이미 {count}종목 보유 "
                f"(한도: {max_sector_stocks})"
            )
            return {
                "passed": False,
                "reason": reason,
                "sector_group": candidate_group,
                "current_count": count,
                "max_allowed": max_sector_stocks,
            }

        return {
            "passed": True,
            "reason": "OK",
            "sector_group": candidate_group,
            "current_count": count,
            "max_allowed": max_sector_stocks,
        }

    def check_cash_floor(
        self,
        buy_amount: float,
        available_cash: float,
        total_assets: float,
        market_regime: str,
    ) -> Dict:
        """
        국면별 현금 하한선 체크.

        매수 후 현금 비율이 국면별 하한선 미만이면 차단.

        Args:
            buy_amount: 매수 예정 금액
            available_cash: 현재 가용 현금
            total_assets: 총자산 (현금 + 주식 평가액)
            market_regime: 시장 국면 (STRONG_BULL, BULL, SIDEWAYS, BEAR)

        Returns:
            {"passed": bool, "reason": str, "cash_after_pct": float, "floor_pct": float}
        """
        if total_assets <= 0:
            return {
                "passed": False,
                "reason": "총자산이 0 이하",
                "cash_after_pct": 0.0,
                "floor_pct": 0.0,
            }

        # 국면별 현금 하한선 조회
        floor_key = self.CASH_FLOOR_KEYS.get(market_regime)
        if floor_key:
            floor_pct = self.config.get_float(
                floor_key, default=self.CASH_FLOOR_DEFAULTS.get(market_regime, 15.0)
            )
        else:
            # 알 수 없는 국면 → SIDEWAYS 기본값 사용
            floor_pct = self.config.get_float(
                "CASH_FLOOR_SIDEWAYS_PCT", default=15.0
            )

        cash_after = available_cash - buy_amount
        cash_after_pct = (cash_after / total_assets) * 100.0

        if cash_after_pct < floor_pct:
            reason = (
                f"현금 하한선 위반: 매수 후 현금 {cash_after_pct:.1f}% < "
                f"하한선 {floor_pct:.1f}% (국면: {market_regime})"
            )
            return {
                "passed": False,
                "reason": reason,
                "cash_after_pct": round(cash_after_pct, 2),
                "floor_pct": floor_pct,
            }

        return {
            "passed": True,
            "reason": "OK",
            "cash_after_pct": round(cash_after_pct, 2),
            "floor_pct": floor_pct,
        }

    def check_all(
        self,
        candidate_code: str,
        candidate_name: str,
        current_portfolio: List[dict],
        buy_amount: float,
        available_cash: float,
        total_assets: float,
        market_regime: str,
    ) -> Dict:
        """
        모든 Portfolio Guard 체크를 순차 실행 (fail-fast).

        PORTFOLIO_GUARD_ENABLED=False면 shadow mode (로그만, 차단 안 함).

        Returns:
            {"passed": bool, "reason": str, "shadow": bool, "checks": dict}
        """
        enabled = self.config.get_bool("PORTFOLIO_GUARD_ENABLED", default=True)
        checks = {}

        # 1. 섹터 종목 수 체크
        sector_result = self.check_sector_stock_count(
            candidate_code, candidate_name, current_portfolio
        )
        checks["sector_stock_count"] = sector_result

        if not sector_result["passed"]:
            if enabled:
                logger.warning(
                    f"🛡️ [PortfolioGuard] {candidate_name}({candidate_code}) 차단: "
                    f"{sector_result['reason']}"
                )
                return {
                    "passed": False,
                    "reason": f"Portfolio Guard: {sector_result['reason']}",
                    "shadow": False,
                    "checks": checks,
                }
            else:
                logger.info(
                    f"👻 [PortfolioGuard:Shadow] {candidate_name}({candidate_code}) "
                    f"차단됐을 것: {sector_result['reason']}"
                )

        # 2. 현금 하한선 체크
        cash_result = self.check_cash_floor(
            buy_amount, available_cash, total_assets, market_regime
        )
        checks["cash_floor"] = cash_result

        if not cash_result["passed"]:
            if enabled:
                logger.warning(
                    f"🛡️ [PortfolioGuard] {candidate_name}({candidate_code}) 차단: "
                    f"{cash_result['reason']}"
                )
                return {
                    "passed": False,
                    "reason": f"Portfolio Guard: {cash_result['reason']}",
                    "shadow": False,
                    "checks": checks,
                }
            else:
                logger.info(
                    f"👻 [PortfolioGuard:Shadow] {candidate_name}({candidate_code}) "
                    f"차단됐을 것: {cash_result['reason']}"
                )

        return {
            "passed": True,
            "reason": "OK",
            "shadow": not enabled,
            "checks": checks,
        }
