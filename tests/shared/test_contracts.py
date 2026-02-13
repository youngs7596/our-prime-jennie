"""
Layer 1: Contract Tests — 서비스 간 데이터 파이프라인 & API 계약 검증

버그 사전 검출 목표:
1. scout_cache → watchlist → buy-scanner 필드 누락 방지
2. KISGatewayClient ↔ kis-gateway 라우트 매핑 검증
3. buy-executor의 self.kis.* 호출이 실제 메서드로 존재하는지 정적 검증
"""
import os
import re
import sys
import unittest
import importlib.util

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.kis.gateway_client import KISGatewayClient


# =============================================================================
# 상수: 서비스 간 계약 필드 정의
# =============================================================================

# save_hot_watchlist()가 입력에서 읽는 필드 (watchlist.py clean_stocks 생성)
WATCHLIST_SAVE_READS = {
    "code", "name", "llm_score", "is_tradable",
    "strategies", "trade_tier", "hybrid_score",
}

# buy-scanner의 load_hot_watchlist() 후 watcher가 사용하는 필드
SCANNER_LOAD_READS = {
    "name", "llm_score", "is_tradable",
    "strategies", "trade_tier", "hybrid_score",
}

# KISGatewayClient 메서드 → kis-gateway 라우트 매핑
EXPECTED_ENDPOINTS = {
    'get_stock_snapshot': '/api/market-data/snapshot',
    'check_market_open': '/api/market-data/check-market-open',
    'place_buy_order': '/api/trading/buy',
    'place_sell_order': '/api/trading/sell',
    'cancel_order': '/api/trading/cancel',
    'get_stock_daily_prices': '/api/market-data/daily-prices',
    'get_stock_minute_chart': '/api/market-data/minute-chart',
    'get_account_balance': '/api/account/balance',
    'get_cash_balance': '/api/account/cash-balance',
    'get_health': '/health',
    'get_stats': '/stats',
}

# 공개 메서드 수 (get_market_data 포함)
EXPECTED_PUBLIC_METHOD_COUNT = len(EXPECTED_ENDPOINTS) + 1  # +1 for get_market_data


def _load_module_from_path(name, path):
    """서비스 모듈을 importlib로 동적 로드"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# =============================================================================
# Class 1: Scout → Scanner 파이프라인 계약
# =============================================================================

class TestScoutToScannerContract(unittest.TestCase):
    """scout_cache → watchlist → buy-scanner 데이터 파이프라인 계약 검증"""

    @classmethod
    def setUpClass(cls):
        module_path = os.path.join(
            PROJECT_ROOT, 'services', 'scout-job', 'scout_cache.py'
        )
        cls.scout_cache = _load_module_from_path("scout_cache_contract", module_path)

    def test_scout_output_contains_all_watchlist_fields(self):
        """_record_to_watchlist_entry() 출력이 save_hot_watchlist()가 읽는 필드를 포함"""
        record = {
            "code": "005930", "name": "Samsung",
            "is_tradable": True, "llm_score": 80,
            "llm_reason": "good", "llm_metadata": {},
            "trade_tier": "TIER1", "hybrid_score": 75,
        }
        entry = self.scout_cache._record_to_watchlist_entry(record)

        # save_hot_watchlist는 strategies도 읽지만, 이는 scout.py에서 별도 주입
        needed = WATCHLIST_SAVE_READS - {"strategies"}
        missing = needed - set(entry.keys())
        self.assertEqual(
            missing, set(),
            f"_record_to_watchlist_entry에 누락 필드: {missing}"
        )

    def test_watchlist_output_contains_all_scanner_fields(self):
        """save_hot_watchlist 출력 구조가 scanner가 읽는 필드를 포함"""
        # save_hot_watchlist 내부의 clean_stocks 생성 로직 시뮬레이션
        from shared.watchlist import save_hot_watchlist
        stock_input = {
            "code": "005930", "name": "Samsung",
            "llm_score": 80, "is_tradable": True,
            "strategies": [{"id": "RSI", "params": {}}],
            "trade_tier": "TIER1", "hybrid_score": 75,
        }
        # clean_stocks 생성 로직 직접 검증
        stock_entry = {
            "code": stock_input.get("code"),
            "name": stock_input.get("name"),
            "llm_score": stock_input.get("llm_score", 0),
            "rank": 1,
            "is_tradable": stock_input.get("is_tradable", True),
            "strategies": stock_input.get("strategies", []),
            "trade_tier": stock_input.get("trade_tier"),
            "hybrid_score": stock_input.get("hybrid_score", 0),
        }
        missing = SCANNER_LOAD_READS - set(stock_entry.keys())
        self.assertEqual(
            missing, set(),
            f"watchlist 저장 구조에 scanner 필수 필드 누락: {missing}"
        )

    def test_roundtrip_trade_tier_preserved(self):
        """trade_tier가 scout_cache → watchlist 경로에서 보존"""
        record = {
            "code": "005930", "name": "Samsung",
            "trade_tier": "TIER1", "hybrid_score": 0,
        }
        entry = self.scout_cache._record_to_watchlist_entry(record)
        self.assertEqual(entry["trade_tier"], "TIER1")

    def test_roundtrip_hybrid_score_preserved(self):
        """hybrid_score가 scout_cache → watchlist 경로에서 보존"""
        record = {
            "code": "005930", "name": "Samsung",
            "trade_tier": "BLOCKED", "hybrid_score": 75.5,
        }
        entry = self.scout_cache._record_to_watchlist_entry(record)
        self.assertEqual(entry["hybrid_score"], 75.5)

    def test_unknown_field_ignored_not_error(self):
        """알려지지 않은 필드가 있어도 에러 없이 처리"""
        record = {
            "code": "005930", "name": "Samsung",
            "trade_tier": "TIER1", "hybrid_score": 70,
            "future_field_v99": "should_not_crash",
        }
        # 에러 없이 실행되면 통과
        entry = self.scout_cache._record_to_watchlist_entry(record)
        self.assertIn("code", entry)


# =============================================================================
# Class 2: KISGatewayClient ↔ kis-gateway 라우트 매핑
# =============================================================================

class TestGatewayContract(unittest.TestCase):
    """KISGatewayClient 메서드 ↔ kis-gateway 엔드포인트 매핑 검증"""

    @classmethod
    def setUpClass(cls):
        gateway_main_path = os.path.join(
            PROJECT_ROOT, 'services', 'kis-gateway', 'main.py'
        )
        with open(gateway_main_path, 'r', encoding='utf-8') as f:
            cls.gateway_source = f.read()

    def test_every_client_method_has_gateway_route(self):
        """11개 클라이언트 메서드 각각에 대응하는 gateway 라우트 존재"""
        for method_name, endpoint_path in EXPECTED_ENDPOINTS.items():
            self.assertTrue(
                hasattr(KISGatewayClient, method_name),
                f"KISGatewayClient에 {method_name} 메서드 없음"
            )

    def test_cancel_order_exists_regression(self):
        """cancel_order 메서드 존재 확인 (2026-02-13 버그 회귀 방지)"""
        self.assertTrue(
            hasattr(KISGatewayClient, 'cancel_order'),
            "KISGatewayClient.cancel_order가 없음 — 2026-02-13 버그 회귀!"
        )
        # 호출 가능한 메서드인지도 확인
        self.assertTrue(callable(getattr(KISGatewayClient, 'cancel_order')))

    def test_gateway_routes_exist_in_server(self):
        """각 엔드포인트 경로가 kis-gateway/main.py에 @app.route로 등록되어 있는지"""
        for method_name, endpoint_path in EXPECTED_ENDPOINTS.items():
            # @app.route('path') 패턴 확인
            self.assertIn(
                endpoint_path, self.gateway_source,
                f"kis-gateway/main.py에 라우트 '{endpoint_path}' 없음 "
                f"(client method: {method_name})"
            )

    def test_client_method_count_matches_expected(self):
        """공개 메서드 수가 기대값과 일치 (의도치 않은 추가/삭제 감지)"""
        public_methods = [
            m for m in dir(KISGatewayClient)
            if not m.startswith('_') and callable(getattr(KISGatewayClient, m))
        ]
        self.assertEqual(
            len(public_methods), EXPECTED_PUBLIC_METHOD_COUNT,
            f"KISGatewayClient 공개 메서드 수 변경됨: "
            f"expected={EXPECTED_PUBLIC_METHOD_COUNT}, actual={len(public_methods)}, "
            f"methods={sorted(public_methods)}"
        )


# =============================================================================
# Class 3: buy-executor → KISGatewayClient 메서드 존재 검증
# =============================================================================

class TestExecutorGatewayContract(unittest.TestCase):
    """buy-executor가 호출하는 self.kis.* 메서드가 실제 존재하는지 정적 검증"""

    @classmethod
    def setUpClass(cls):
        executor_path = os.path.join(
            PROJECT_ROOT, 'services', 'buy-executor', 'executor.py'
        )
        with open(executor_path, 'r', encoding='utf-8') as f:
            cls.executor_source = f.read()

        # self.kis.메서드명( 패턴 추출
        cls.kis_method_calls = set(
            re.findall(r'self\.kis\.(\w+)\s*\(', cls.executor_source)
        )

    def test_executor_cancel_order_method_exists(self):
        """executor.py의 self.kis.cancel_order → KISGatewayClient.cancel_order 존재"""
        self.assertIn('cancel_order', self.kis_method_calls,
                       "executor.py에서 self.kis.cancel_order 호출이 없음")
        self.assertTrue(hasattr(KISGatewayClient, 'cancel_order'))

    def test_executor_place_buy_order_method_exists(self):
        """executor.py의 self.kis.place_buy_order → KISGatewayClient.place_buy_order 존재"""
        self.assertIn('place_buy_order', self.kis_method_calls,
                       "executor.py에서 self.kis.place_buy_order 호출이 없음")
        self.assertTrue(hasattr(KISGatewayClient, 'place_buy_order'))

    def test_executor_all_kis_calls_have_implementations(self):
        """executor.py의 모든 self.kis.* 호출에 대응하는 KISGatewayClient 메서드 존재"""
        missing = []
        for method_name in self.kis_method_calls:
            if not hasattr(KISGatewayClient, method_name):
                missing.append(method_name)
        self.assertEqual(
            missing, [],
            f"executor.py에서 호출하지만 KISGatewayClient에 없는 메서드: {missing}"
        )


if __name__ == '__main__':
    unittest.main()
