#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scout_pipeline.fetch_kis_data_task 테스트 스크립트
- 종목 스냅샷/일봉 모킹하여 stock_code/trade_date 포함 여부 확인
"""

from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional
import importlib.util
import pathlib


def _load_fetch_kis_data_task():
    """
    scout_pipeline.py를 안전하게 로드하기 위해 직접 spec 로드 사용
    (디렉터리 이름에 하이픈이 있어 일반 import 불가)
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    target = root / "services" / "scout-job" / "scout_pipeline.py"
    import sys
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location("scout_pipeline", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore
    return module.fetch_kis_data_task


fetch_kis_data_task = _load_fetch_kis_data_task()


class FakeKisApi:
    """KIS API 모킹용"""

    API_CALL_DELAY = 0  # 지연 없음

    def __init__(self, daily_prices: Optional[List[dict]], snapshot: dict):
        self._daily_prices = daily_prices
        self._snapshot = snapshot

    def get_stock_daily_prices(self, stock_code: str, num_days_to_fetch: int = 30):
        return self._daily_prices

    def get_stock_snapshot(self, stock_code: str):
        return self._snapshot


def run_case(title: str, daily_prices, snapshot) -> Tuple[list, dict]:
    print(f"\n=== {title} ===")
    api = FakeKisApi(daily_prices, snapshot)
    stock = {"code": snapshot.get("code", "000000"), "is_tradable": True, "name": "테스트종목"}
    daily, fundamentals = fetch_kis_data_task(stock, api)
    print("일봉 건수:", len(daily))
    print("재무지표:", fundamentals)
    return daily, fundamentals


def main():
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)

    # Case 1: 일봉에 날짜 포함 → trade_date는 일봉 날짜로 설정
    daily_prices_case1 = [
        {"price_date": yesterday, "close_price": 1000, "high_price": 1010, "low_price": 990},
        {"price_date": today, "close_price": 1020, "high_price": 1030, "low_price": 1000},
    ]
    snapshot_case1 = {"code": "123456", "per": 5.5, "pbr": 0.8, "market_cap": 123456789}
    run_case("Case 1: 일봉 데이터 있음", daily_prices_case1, snapshot_case1)

    # Case 2: 일봉 없음 → trade_date는 오늘 날짜로 대체
    daily_prices_case2 = []
    snapshot_case2 = {"code": "654321", "per": 8.1, "pbr": 1.2, "market_cap": 987654321}
    run_case("Case 2: 일봉 데이터 없음", daily_prices_case2, snapshot_case2)


if __name__ == "__main__":
    main()

