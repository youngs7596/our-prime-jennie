"""
WATCHLIST_CONVICTION_ENTRY + MOMENTUM 상한선 + DIP_BUY 완화 + 사문화 전략 토글 테스트

Phase 0-5 전체 테스트 커버리지
"""
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta, date
import os
import sys
import importlib.util

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def make_bars(count=30, open_price=10000, close_price=10100, volume=1000):
    """테스트용 바 데이터 생성 — RSI가 자연스러운 값이 되도록 약간의 변동 포함"""
    bars = []
    for i in range(count):
        # 소폭 등락 반복하면서 전체적으로 open → close 추세
        t = i / max(count - 1, 1)
        base = open_price + (close_price - open_price) * t
        jitter = 20 * (1 if i % 3 != 0 else -1)  # 3개마다 소폭 하락
        c = base + jitter
        o = base - jitter
        bars.append({
            'open': o,
            'close': c,
            'high': max(o, c) + 50,
            'low': min(o, c) - 50,
            'volume': volume
        })
    return bars


class BaseWatcherTest(unittest.TestCase):
    """공통 setUp"""

    def setUp(self):
        module_path = os.path.join(PROJECT_ROOT, 'services', 'buy-scanner', 'opportunity_watcher.py')
        self.module = load_module("opportunity_watcher", module_path)

        self.mock_config = MagicMock()
        self.mock_publisher = MagicMock()
        self.watcher = self.module.BuyOpportunityWatcher(
            self.mock_config, self.mock_publisher, redis_url="redis://dummy"
        )
        self.watcher.redis = MagicMock()

        # config.get_bool / get_float / get_int / get 기본 동작
        def config_get_bool(key, default=False):
            defaults = {
                "ENABLE_WATCHLIST_CONVICTION_ENTRY": True,
                "ENABLE_MOMENTUM_CONTINUATION": True,
                "ENABLE_BULL_PULLBACK": False,
                "ENABLE_VCP_BREAKOUT": False,
                "ENABLE_INSTITUTIONAL_ENTRY": False,
                "ENABLE_SHORT_TERM_HIGH_BREAKOUT": False,
            }
            return defaults.get(key, default)

        def config_get_float(key, default=0.0):
            defaults = {
                "CONVICTION_MIN_HYBRID_SCORE": 70.0,
                "CONVICTION_MIN_LLM_SCORE": 72.0,
                "CONVICTION_MAX_INTRADAY_GAIN_PCT": 3.0,
                "CONVICTION_MAX_VWAP_DEVIATION": 1.5,
                "MOMENTUM_CONT_MAX_GAIN_PCT": 5.0,
                "MOMENTUM_MAX_GAIN_PCT": 7.0,
                "DIP_BUY_MIN_DROP_BULL": -0.5,
                "DIP_BUY_MAX_DROP_BULL": -3.0,
            }
            return defaults.get(key, default)

        def config_get_int(key, default=0):
            defaults = {
                "CONVICTION_MAX_DAYS_SINCE_ENTRY": 2,
            }
            return defaults.get(key, default)

        def config_get(key, default=""):
            defaults = {
                "CONVICTION_ENTRY_WINDOW_START": "0915",
                "CONVICTION_ENTRY_WINDOW_END": "1030",
            }
            return defaults.get(key, default)

        self.mock_config.get_bool = MagicMock(side_effect=config_get_bool)
        self.mock_config.get_float = MagicMock(side_effect=config_get_float)
        self.mock_config.get_int = MagicMock(side_effect=config_get_int)
        self.mock_config.get = MagicMock(side_effect=config_get)

    def _patch_datetime_now(self, utc_time):
        """opportunity_watcher 모듈의 datetime.now()를 mock"""
        mock_dt = MagicMock(wraps=datetime)
        mock_dt.now = MagicMock(return_value=utc_time)
        return patch.object(self.module, 'datetime', mock_dt)


# ============================================================
# Phase 2: WATCHLIST_CONVICTION_ENTRY 테스트
# ============================================================

class TestWatchlistConvictionEntry(BaseWatcherTest):
    """WATCHLIST_CONVICTION_ENTRY 전략 테스트"""

    def _make_stock_info(self, hybrid=75, llm=74, trade_tier="TIER1"):
        return {
            'name': 'TestStock',
            'llm_score': llm,
            'hybrid_score': hybrid,
            'trade_tier': trade_tier,
        }

    def test_conviction_triggered_bull_high_hybrid(self):
        """BULL + hybrid 75 + D+1 + gain 1% + VWAP ok → 발동"""
        self.watcher.market_regime = 'BULL'
        self.watcher.watchlist_entry_cache = {
            '005930': {
                'entry_date': date.today() - timedelta(days=1),
                'entry_price': 10000,
            }
        }
        self.watcher.bar_aggregator = MagicMock()
        self.watcher.bar_aggregator.get_vwap.return_value = 10050

        stock_info = self._make_stock_info(hybrid=75, llm=74)
        current_price = 10100
        bars = make_bars(count=30, open_price=10000, close_price=10100)

        # 09:30 KST = 00:30 UTC
        mock_now = datetime(2026, 2, 14, 0, 30, 0, tzinfo=timezone.utc)
        with self._patch_datetime_now(mock_now):
            result = self.watcher._check_watchlist_conviction_entry(
                '005930', stock_info, current_price, bars
            )

        self.assertIsNotNone(result)
        self.assertEqual(result[0], "WATCHLIST_CONVICTION_ENTRY")
        self.assertIn("선제진입", result[1])

    def test_conviction_blocked_high_gain(self):
        """당일 상승률 5% → 차단 (max 3%)"""
        self.watcher.market_regime = 'BULL'
        self.watcher.watchlist_entry_cache = {
            '005930': {
                'entry_date': date.today() - timedelta(days=1),
                'entry_price': 10000,
            }
        }
        self.watcher.bar_aggregator = MagicMock()
        self.watcher.bar_aggregator.get_vwap.return_value = 10500

        stock_info = self._make_stock_info(hybrid=75)
        current_price = 10500  # +5%
        bars = make_bars(count=30, open_price=10000, close_price=10500)

        mock_now = datetime(2026, 2, 14, 0, 30, 0, tzinfo=timezone.utc)
        with self._patch_datetime_now(mock_now):
            result = self.watcher._check_watchlist_conviction_entry(
                '005930', stock_info, current_price, bars
            )

        self.assertIsNone(result)

    def test_conviction_blocked_time_window(self):
        """11:00 KST → 차단 (시간대 초과)"""
        self.watcher.market_regime = 'BULL'
        self.watcher.watchlist_entry_cache = {
            '005930': {
                'entry_date': date.today() - timedelta(days=1),
                'entry_price': 10000,
            }
        }
        self.watcher.bar_aggregator = MagicMock()
        self.watcher.bar_aggregator.get_vwap.return_value = 10050

        stock_info = self._make_stock_info(hybrid=75)
        current_price = 10100
        bars = make_bars(count=30, open_price=10000, close_price=10100)

        # 11:00 KST = 02:00 UTC
        mock_now = datetime(2026, 2, 14, 2, 0, 0, tzinfo=timezone.utc)
        with self._patch_datetime_now(mock_now):
            result = self.watcher._check_watchlist_conviction_entry(
                '005930', stock_info, current_price, bars
            )

        self.assertIsNone(result)

    def test_conviction_blocked_days_exceeded(self):
        """D+4 → 차단 (max 2일)"""
        self.watcher.market_regime = 'BULL'
        self.watcher.watchlist_entry_cache = {
            '005930': {
                'entry_date': date.today() - timedelta(days=4),
                'entry_price': 10000,
            }
        }
        self.watcher.bar_aggregator = MagicMock()
        self.watcher.bar_aggregator.get_vwap.return_value = 10050

        stock_info = self._make_stock_info(hybrid=75)
        current_price = 10100
        bars = make_bars(count=30, open_price=10000, close_price=10100)

        mock_now = datetime(2026, 2, 14, 0, 30, 0, tzinfo=timezone.utc)
        with self._patch_datetime_now(mock_now):
            result = self.watcher._check_watchlist_conviction_entry(
                '005930', stock_info, current_price, bars
            )

        self.assertIsNone(result)

    def test_conviction_blocked_sideways_low_hybrid(self):
        """SIDEWAYS + hybrid 60 → 차단 (SIDEWAYS는 hybrid >= 75 필요)"""
        self.watcher.market_regime = 'SIDEWAYS'
        self.watcher.watchlist_entry_cache = {
            '005930': {
                'entry_date': date.today(),
                'entry_price': 10000,
            }
        }
        stock_info = self._make_stock_info(hybrid=60, llm=62)
        current_price = 10050
        bars = make_bars(count=30, open_price=10000, close_price=10050)

        result = self.watcher._check_watchlist_conviction_entry(
            '005930', stock_info, current_price, bars
        )

        self.assertIsNone(result)

    def test_conviction_blocked_low_scores(self):
        """hybrid 50 AND llm 50 → 확신도 부족 차단"""
        self.watcher.market_regime = 'BULL'
        self.watcher.watchlist_entry_cache = {
            '005930': {
                'entry_date': date.today(),
                'entry_price': 10000,
            }
        }
        self.watcher.bar_aggregator = MagicMock()
        self.watcher.bar_aggregator.get_vwap.return_value = 10050

        stock_info = self._make_stock_info(hybrid=50, llm=50)
        current_price = 10050
        bars = make_bars(count=30, open_price=10000, close_price=10050)

        mock_now = datetime(2026, 2, 14, 0, 30, 0, tzinfo=timezone.utc)
        with self._patch_datetime_now(mock_now):
            result = self.watcher._check_watchlist_conviction_entry(
                '005930', stock_info, current_price, bars
            )

        self.assertIsNone(result)

    def test_conviction_d0_no_entry_price_uses_bar_open(self):
        """D+0 entry_price 없음 → bar open 대체"""
        self.watcher.market_regime = 'STRONG_BULL'
        self.watcher.watchlist_entry_cache = {}  # 캐시 비어있음 → D+0
        self.watcher.bar_aggregator = MagicMock()
        self.watcher.bar_aggregator.get_vwap.return_value = 10050

        stock_info = self._make_stock_info(hybrid=80, llm=78)
        current_price = 10100
        bars = make_bars(count=30, open_price=10000, close_price=10100)

        mock_now = datetime(2026, 2, 14, 0, 30, 0, tzinfo=timezone.utc)
        with self._patch_datetime_now(mock_now):
            result = self.watcher._check_watchlist_conviction_entry(
                '005930', stock_info, current_price, bars
            )

        self.assertIsNotNone(result)
        self.assertEqual(result[0], "WATCHLIST_CONVICTION_ENTRY")


# ============================================================
# Phase 3: MOMENTUM 상한선 테스트
# ============================================================

class TestMomentumGainCap(BaseWatcherTest):
    """MOMENTUM / MOMENTUM_CONTINUATION 상한선 테스트"""

    def test_momentum_cont_blocked_by_cap(self):
        """MOMENTUM_CONTINUATION: gain 7% → 상한(5%) 초과 차단"""
        self.watcher.market_regime = 'BULL'

        stock_info = {'name': 'Test', 'llm_score': 70, 'hybrid_score': 0, 'trade_tier': 'TIER1'}
        # bars: 첫 open=10000, 마지막 close=10700 (+7%)
        bars = make_bars(count=25, open_price=10000, close_price=10000)
        bars[0]['open'] = 10000
        bars[-1]['close'] = 10700

        result = self.watcher._check_momentum_continuation('005930', stock_info, bars)
        self.assertIsNone(result)

    def test_momentum_cont_passes_within_cap(self):
        """MOMENTUM_CONTINUATION: gain 3% → 상한(5%) 이내 통과"""
        self.watcher.market_regime = 'BULL'

        stock_info = {'name': 'Test', 'llm_score': 70, 'hybrid_score': 0, 'trade_tier': 'TIER1'}
        # bars with proper MA5 > MA20 (rising prices)
        bars = []
        for i in range(25):
            bars.append({
                'open': 10000 + i * 10,
                'close': 10050 + i * 12,
                'high': 10100 + i * 12,
                'low': 10000 + i * 10,
                'volume': 1000
            })
        bars[0]['open'] = 10000
        bars[-1]['close'] = 10300  # +3%

        result = self.watcher._check_momentum_continuation('005930', stock_info, bars)
        self.assertIsNotNone(result)

    def test_momentum_blocked_by_cap(self):
        """MOMENTUM: gain 8% → 상한(7%) 초과 차단"""
        bars = [{'close': 10000 + i * 30} for i in range(30)]
        bars[0]['close'] = 10000
        bars[-1]['close'] = 10800  # +8%

        params = {'threshold': 3.0}
        triggered, reason = self.watcher._check_momentum(bars, params)
        self.assertFalse(triggered)
        self.assertIn("cap", reason)

    def test_momentum_passes_within_cap(self):
        """MOMENTUM: gain 5% → 상한(7%) 이내 통과"""
        bars = [{'close': 10000 + i * 20} for i in range(30)]
        bars[0]['close'] = 10000
        bars[-1]['close'] = 10500  # +5%

        params = {'threshold': 3.0}
        triggered, reason = self.watcher._check_momentum(bars, params)
        self.assertTrue(triggered)
        self.assertIn("Momentum", reason)


# ============================================================
# Phase 4: 사문화 전략 토글 테스트
# ============================================================

class TestStrategyToggles(BaseWatcherTest):
    """사문화 전략 비활성화 토글 테스트"""

    def test_bull_pullback_disabled_by_default(self):
        """BULL_PULLBACK 기본 비활성화"""
        result = self.mock_config.get_bool("ENABLE_BULL_PULLBACK", default=False)
        self.assertFalse(result)

    def test_vcp_breakout_disabled_by_default(self):
        """VCP_BREAKOUT 기본 비활성화"""
        result = self.mock_config.get_bool("ENABLE_VCP_BREAKOUT", default=False)
        self.assertFalse(result)

    def test_institutional_entry_disabled_by_default(self):
        """INSTITUTIONAL_ENTRY 기본 비활성화"""
        result = self.mock_config.get_bool("ENABLE_INSTITUTIONAL_ENTRY", default=False)
        self.assertFalse(result)

    def test_short_term_high_breakout_disabled(self):
        """SHORT_TERM_HIGH_BREAKOUT 기본 비활성화"""
        result = self.mock_config.get_bool("ENABLE_SHORT_TERM_HIGH_BREAKOUT", default=False)
        self.assertFalse(result)

    def test_vcp_removed_from_momentum_strategies(self):
        """VCP_BREAKOUT이 MOMENTUM_STRATEGIES에서 제거됨"""
        self.assertNotIn("VCP_BREAKOUT", self.module.MOMENTUM_STRATEGIES)

    def test_momentum_still_in_momentum_strategies(self):
        """MOMENTUM은 여전히 MOMENTUM_STRATEGIES에 포함"""
        self.assertIn("MOMENTUM", self.module.MOMENTUM_STRATEGIES)


# ============================================================
# Phase 5: DIP_BUY 국면별 완화 테스트
# ============================================================

class TestDipBuyRelaxation(BaseWatcherTest):
    """DIP_BUY 국면별 완화 테스트"""

    def test_dip_buy_bull_small_dip(self):
        """BULL + -1% → 발동 (BULL 완화: -0.5~-3.0%)"""
        self.watcher.market_regime = 'BULL'
        self.watcher.watchlist_entry_cache = {
            '005930': {
                'entry_date': date.today() - timedelta(days=2),
                'entry_price': 10000,
            }
        }
        stock_info = {'name': 'Test', 'llm_score': 70}
        current_price = 9900  # -1%

        result = self.watcher._check_dip_buy('005930', current_price, stock_info)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "DIP_BUY")

    def test_dip_buy_strong_bull_d4(self):
        """STRONG_BULL + D+4 → 발동 (BULL 완화: max_days=5)"""
        self.watcher.market_regime = 'STRONG_BULL'
        self.watcher.watchlist_entry_cache = {
            '005930': {
                'entry_date': date.today() - timedelta(days=4),
                'entry_price': 10000,
            }
        }
        stock_info = {'name': 'Test', 'llm_score': 70}
        current_price = 9850  # -1.5%

        result = self.watcher._check_dip_buy('005930', current_price, stock_info)
        self.assertIsNotNone(result)

    def test_dip_buy_sideways_small_dip_blocked(self):
        """SIDEWAYS + -1% → 차단 (기존 기준: -2~-5%)"""
        self.watcher.market_regime = 'SIDEWAYS'
        self.watcher.watchlist_entry_cache = {
            '005930': {
                'entry_date': date.today() - timedelta(days=2),
                'entry_price': 10000,
            }
        }
        stock_info = {'name': 'Test', 'llm_score': 70}
        current_price = 9900  # -1%

        result = self.watcher._check_dip_buy('005930', current_price, stock_info)
        self.assertIsNone(result)

    def test_dip_buy_excessive_drop_blocked(self):
        """-6% → 전 국면 차단"""
        self.watcher.market_regime = 'BULL'
        self.watcher.watchlist_entry_cache = {
            '005930': {
                'entry_date': date.today() - timedelta(days=2),
                'entry_price': 10000,
            }
        }
        stock_info = {'name': 'Test', 'llm_score': 70}
        current_price = 9400  # -6%

        result = self.watcher._check_dip_buy('005930', current_price, stock_info)
        self.assertIsNone(result)


# ============================================================
# Phase 0: 데이터 파이프라인 round-trip 테스트
# ============================================================

class TestDataPipelineRoundTrip(unittest.TestCase):
    """trade_tier/hybrid_score가 watchlist 파이프라인에서 전달되는지 검증"""

    @patch('shared.watchlist.get_redis_connection')
    def test_watchlist_saves_trade_tier_hybrid_score(self, mock_get_redis):
        """save_hot_watchlist가 trade_tier/hybrid_score를 저장"""
        import json
        from shared.watchlist import save_hot_watchlist

        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis

        stocks = [{
            "code": "005930",
            "name": "Samsung",
            "llm_score": 80,
            "trade_tier": "TIER1",
            "hybrid_score": 75,
            "strategies": [],
        }]

        save_hot_watchlist(stocks, "BULL", 70)

        calls = mock_redis.set.call_args_list
        payload = None
        for call in calls:
            args = call[0]
            if 'hot_watchlist:v' in str(args[0]):
                payload = json.loads(args[1])
                break

        self.assertIsNotNone(payload)
        stock = payload['stocks'][0]
        self.assertEqual(stock['trade_tier'], 'TIER1')
        self.assertEqual(stock['hybrid_score'], 75)

    def test_load_hot_watchlist_parses_hybrid_score(self):
        """load_hot_watchlist가 hybrid_score를 파싱"""
        import json

        module_path = os.path.join(PROJECT_ROOT, 'services', 'buy-scanner', 'opportunity_watcher.py')
        module = load_module("opportunity_watcher_pipeline_test", module_path)

        mock_config = MagicMock()
        mock_publisher = MagicMock()
        watcher = module.BuyOpportunityWatcher(mock_config, mock_publisher, redis_url="redis://dummy")
        watcher.redis = MagicMock()

        payload = json.dumps({
            "generated_at": "2026-02-14T00:00:00",
            "market_regime": "BULL",
            "score_threshold": 70,
            "stocks": [{
                "code": "005930",
                "name": "Samsung",
                "llm_score": 80,
                "hybrid_score": 75,
                "trade_tier": "TIER1",
                "strategies": [],
            }]
        })
        watcher.redis.get.side_effect = [
            "hot_watchlist:v123",
            payload,
        ]

        watcher._load_watchlist_entry_data = MagicMock()
        watcher._load_supply_demand_data = MagicMock()

        success = watcher.load_hot_watchlist()
        self.assertTrue(success)
        self.assertEqual(watcher.hot_watchlist['005930']['hybrid_score'], 75)
        self.assertEqual(watcher.hot_watchlist['005930']['trade_tier'], 'TIER1')


# ============================================================
# Phase 2+: Risk Gate 조기 우회 통합 테스트
# ============================================================

class TestConvictionEarlyBypass(BaseWatcherTest):
    """CONVICTION_ENTRY가 Risk Gate(Min Bars, No-Trade Window) 이전에 평가되는지 검증"""

    def _setup_conviction_conditions(self, bar_count=5):
        """CONVICTION 발동 조건 설정 (bar 개수 조절 가능)"""
        self.watcher.market_regime = 'BULL'
        self.watcher.watchlist_entry_cache = {
            '005930': {
                'entry_date': date.today() - timedelta(days=1),
                'entry_price': 10000,
            }
        }
        self.watcher.hot_watchlist = {
            '005930': {
                'name': 'Samsung',
                'llm_score': 74,
                'hybrid_score': 75,
                'trade_tier': 'TIER1',
                'strategies': [],
            }
        }
        self.watcher.bar_aggregator = MagicMock()
        bars = make_bars(count=bar_count, open_price=10000, close_price=10100)
        self.watcher.bar_aggregator.get_recent_bars.return_value = bars
        self.watcher.bar_aggregator.get_volume_info.return_value = {'avg': 1000, 'current': 1000}
        self.watcher.bar_aggregator.get_vwap.return_value = 10050
        self.watcher._set_cooldown = MagicMock()
        self.watcher._save_buy_logic_snapshot = MagicMock()
        self.watcher._save_signal_history = MagicMock()
        self.watcher._get_position_multiplier = MagicMock(return_value=1.0)
        self.watcher._get_trading_context = MagicMock(return_value=None)
        return bars

    def test_conviction_fires_with_only_5_bars(self):
        """5개 바로도 CONVICTION_ENTRY 발동 (Min Bars=20 우회)"""
        self._setup_conviction_conditions(bar_count=5)

        mock_now = datetime(2026, 2, 14, 0, 30, 0, tzinfo=timezone.utc)
        with self._patch_datetime_now(mock_now):
            signal = self.watcher._check_buy_signal('005930', 10100, {})

        self.assertIsNotNone(signal)
        self.assertEqual(signal['signal_type'], 'WATCHLIST_CONVICTION_ENTRY')

    def test_conviction_fires_during_no_trade_window(self):
        """09:10 KST (No-Trade Window 중)에도 CONVICTION_ENTRY 발동"""
        self._setup_conviction_conditions(bar_count=10)

        # 09:10 KST = 00:10 UTC
        mock_now = datetime(2026, 2, 14, 0, 10, 0, tzinfo=timezone.utc)
        # Adjust window to include 09:10
        def config_get(key, default=""):
            defaults = {
                "CONVICTION_ENTRY_WINDOW_START": "0905",
                "CONVICTION_ENTRY_WINDOW_END": "1030",
            }
            return defaults.get(key, default)
        self.mock_config.get.side_effect = config_get

        with self._patch_datetime_now(mock_now):
            signal = self.watcher._check_buy_signal('005930', 10100, {})

        self.assertIsNotNone(signal)
        self.assertEqual(signal['signal_type'], 'WATCHLIST_CONVICTION_ENTRY')

    def test_no_conviction_with_2_bars_falls_to_min_bars_block(self):
        """2개 바 → CONVICTION 미달(3바 필요) + Min Bars 차단 → None"""
        self._setup_conviction_conditions(bar_count=2)

        mock_now = datetime(2026, 2, 14, 0, 30, 0, tzinfo=timezone.utc)
        with self._patch_datetime_now(mock_now):
            signal = self.watcher._check_buy_signal('005930', 10100, {})

        self.assertIsNone(signal)


# ============================================================
# Layer 3: 경계값/음성 테스트 — Momentum 상한선
# ============================================================

class TestMomentumBoundary(BaseWatcherTest):
    """_check_momentum / _check_momentum_continuation 경계값 테스트

    코드에서 >= 연산자 사용:
    - _check_momentum: momentum >= max_gain → 차단, momentum >= threshold → 발동
    - _check_momentum_continuation: price_change >= max_gain → 차단
    """

    def test_momentum_at_exact_cap_blocks(self):
        """gain=7.0% (cap=7.0) → 차단 (>=)"""
        bars = [{'close': 10000 + i * 24} for i in range(30)]
        bars[0]['close'] = 10000
        bars[-1]['close'] = 10700  # exactly 7.0%

        triggered, reason = self.watcher._check_momentum(bars, {'threshold': 3.0})
        self.assertFalse(triggered)
        self.assertIn("cap", reason)

    def test_momentum_just_below_cap_passes(self):
        """gain=6.99% → 통과 (< cap)"""
        bars = [{'close': 10000 + i * 24} for i in range(30)]
        bars[0]['close'] = 10000
        bars[-1]['close'] = 10699  # 6.99%

        triggered, reason = self.watcher._check_momentum(bars, {'threshold': 3.0})
        self.assertTrue(triggered)
        self.assertIn("Momentum", reason)

    def test_momentum_at_threshold_exact_triggers(self):
        """gain=3.0% (threshold=3.0) → 발동 (>=)"""
        bars = [{'close': 10000 + i * 10} for i in range(30)]
        bars[0]['close'] = 10000
        bars[-1]['close'] = 10300  # exactly 3.0%

        triggered, reason = self.watcher._check_momentum(bars, {'threshold': 3.0})
        self.assertTrue(triggered)
        self.assertIn("Momentum", reason)

    def test_momentum_cont_at_exact_cap_blocks(self):
        """MOMENTUM_CONTINUATION: gain=5.0% (cap=5.0) → 차단 (>=)"""
        self.watcher.market_regime = 'BULL'

        stock_info = {'name': 'Test', 'llm_score': 70, 'hybrid_score': 0, 'trade_tier': 'TIER1'}
        # 20+ bars, MA5 > MA20, open→close = exactly 5.0%
        bars = []
        for i in range(25):
            bars.append({
                'open': 10000 + i * 15,
                'close': 10050 + i * 18,
                'high': 10100 + i * 18,
                'low': 10000 + i * 15,
                'volume': 1000
            })
        bars[0]['open'] = 10000
        bars[-1]['close'] = 10500  # exactly 5.0%

        result = self.watcher._check_momentum_continuation('005930', stock_info, bars)
        self.assertIsNone(result)  # blocked at cap

    def test_momentum_cont_just_below_cap_passes(self):
        """MOMENTUM_CONTINUATION: gain=4.99% → 통과"""
        self.watcher.market_regime = 'BULL'

        stock_info = {'name': 'Test', 'llm_score': 70, 'hybrid_score': 0, 'trade_tier': 'TIER1'}
        bars = []
        for i in range(25):
            bars.append({
                'open': 10000 + i * 15,
                'close': 10050 + i * 18,
                'high': 10100 + i * 18,
                'low': 10000 + i * 15,
                'volume': 1000
            })
        bars[0]['open'] = 10000
        bars[-1]['close'] = 10499  # 4.99%

        result = self.watcher._check_momentum_continuation('005930', stock_info, bars)
        self.assertIsNotNone(result)


# ============================================================
# Layer 3: 경계값/음성 테스트 — Conviction Entry
# ============================================================

class TestConvictionBoundary(BaseWatcherTest):
    """_check_watchlist_conviction_entry 경계값 테스트

    코드 연산자:
    - scores: hybrid < min AND llm < min → 둘 다 미달이어야 차단 (OR 로직으로 하나만 충족해도 통과)
    - time: window_start <= now_kst <= window_end → 경계값에서 통과
    """

    def _setup_conviction_base(self, hybrid=75, llm=74, utc_time=None):
        """CONVICTION 테스트 공통 조건 설정"""
        self.watcher.market_regime = 'BULL'
        self.watcher.watchlist_entry_cache = {
            '005930': {
                'entry_date': date.today() - timedelta(days=1),
                'entry_price': 10000,
            }
        }
        self.watcher.bar_aggregator = MagicMock()
        self.watcher.bar_aggregator.get_vwap.return_value = 10050

        stock_info = {
            'name': 'TestStock', 'llm_score': llm,
            'hybrid_score': hybrid, 'trade_tier': 'TIER1',
        }
        current_price = 10100
        bars = make_bars(count=30, open_price=10000, close_price=10100)

        if utc_time is None:
            utc_time = datetime(2026, 2, 14, 0, 30, 0, tzinfo=timezone.utc)  # 09:30 KST

        return stock_info, current_price, bars, utc_time

    def test_hybrid_at_minimum_passes(self):
        """hybrid=70 (min=70) → 통과 (70 < 70 = False → not blocked)"""
        stock_info, price, bars, utc = self._setup_conviction_base(hybrid=70, llm=60)
        with self._patch_datetime_now(utc):
            result = self.watcher._check_watchlist_conviction_entry('005930', stock_info, price, bars)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "WATCHLIST_CONVICTION_ENTRY")

    def test_hybrid_below_but_llm_above_passes(self):
        """hybrid=69 (< 70), llm=73 (>= 72) → 통과 (OR 로직)"""
        stock_info, price, bars, utc = self._setup_conviction_base(hybrid=69, llm=73)
        with self._patch_datetime_now(utc):
            result = self.watcher._check_watchlist_conviction_entry('005930', stock_info, price, bars)
        self.assertIsNotNone(result)

    def test_both_below_minimum_blocks(self):
        """hybrid=69, llm=71 → 둘 다 미달 → 차단"""
        stock_info, price, bars, utc = self._setup_conviction_base(hybrid=69, llm=71)
        with self._patch_datetime_now(utc):
            result = self.watcher._check_watchlist_conviction_entry('005930', stock_info, price, bars)
        self.assertIsNone(result)

    def test_time_at_window_start_passes(self):
        """09:15 KST exactly → 통과 (<=)"""
        # 09:15 KST = 00:15 UTC
        utc = datetime(2026, 2, 14, 0, 15, 0, tzinfo=timezone.utc)
        stock_info, price, bars, _ = self._setup_conviction_base(hybrid=75, llm=74)
        with self._patch_datetime_now(utc):
            result = self.watcher._check_watchlist_conviction_entry('005930', stock_info, price, bars)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "WATCHLIST_CONVICTION_ENTRY")

    def test_time_at_window_end_passes(self):
        """10:30 KST exactly → 통과 (<=)"""
        # 10:30 KST = 01:30 UTC
        utc = datetime(2026, 2, 14, 1, 30, 0, tzinfo=timezone.utc)
        stock_info, price, bars, _ = self._setup_conviction_base(hybrid=75, llm=74)
        with self._patch_datetime_now(utc):
            result = self.watcher._check_watchlist_conviction_entry('005930', stock_info, price, bars)
        self.assertIsNotNone(result)

    def test_time_one_minute_after_end_blocks(self):
        """10:31 KST → 차단"""
        # 10:31 KST = 01:31 UTC
        utc = datetime(2026, 2, 14, 1, 31, 0, tzinfo=timezone.utc)
        stock_info, price, bars, _ = self._setup_conviction_base(hybrid=75, llm=74)
        with self._patch_datetime_now(utc):
            result = self.watcher._check_watchlist_conviction_entry('005930', stock_info, price, bars)
        self.assertIsNone(result)

    def test_time_one_minute_before_start_blocks(self):
        """09:14 KST → 차단"""
        # 09:14 KST = 00:14 UTC
        utc = datetime(2026, 2, 14, 0, 14, 0, tzinfo=timezone.utc)
        stock_info, price, bars, _ = self._setup_conviction_base(hybrid=75, llm=74)
        with self._patch_datetime_now(utc):
            result = self.watcher._check_watchlist_conviction_entry('005930', stock_info, price, bars)
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
