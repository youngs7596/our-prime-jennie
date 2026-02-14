"""
Buy-Scanner 매수 전략 통합 테스트

_check_buy_signal() 전체 파이프라인 관통 테스트:
Risk Gate → 전략 평가 → 신호 생성 (또는 차단)

기존 test_conviction_entry.py (개별 메서드) 와 달리
_check_buy_signal() 경유로 실제 서비스 흐름을 검증한다.
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


# ============================================================
# 바 데이터 헬퍼
# ============================================================

def make_bars(count=30, open_price=10000, close_price=10100, volume=1000):
    """기본 바 데이터 — RSI가 자연스러운 값이 되도록 약간의 변동 포함"""
    bars = []
    for i in range(count):
        t = i / max(count - 1, 1)
        base = open_price + (close_price - open_price) * t
        jitter = 20 * (1 if i % 3 != 0 else -1)
        c = base + jitter
        o = base - jitter
        bars.append({
            'open': o, 'close': c,
            'high': max(o, c) + 50, 'low': min(o, c) - 50,
            'volume': volume,
        })
    return bars


def make_golden_cross_bars(count=30, volume=1000):
    """Golden Cross 발동용 바 — RSI ~60 유지

    패턴: 20바 횡보(10000) → 5바 소폭 하락(9960) → 5바 회복+돌파(10060)
    prev_ma5(bars[-6:-1]): 하락~회복 구간 → MA20 이하
    curr_ma5(bars[-5:]): 회복 구간 → MA20 초과
    RSI: 하락 후 회복이라 ~60 수준
    """
    bars = []
    for i in range(count):
        if i < 20:
            # 횡보 구간 (약간의 진동)
            c = 10000 + (15 if i % 3 != 0 else -15)
        elif i < 25:
            # 소폭 하락 구간
            c = 10000 - (i - 19) * 12  # 9988, 9976, 9964, 9952, 9940
        else:
            # 회복+돌파 구간
            c = 9940 + (i - 24) * 30  # 9970, 10000, 10030, 10060, 10090
        o = c - 10
        bars.append({
            'open': o, 'close': c,
            'high': max(o, c) + 20, 'low': min(o, c) - 20,
            'volume': volume,
        })
    return bars


def make_trending_bars(count=30, start=10000, gain_pct=3.0, volume=1000):
    """상승 추세 바: MA5>MA20 + gain_pct% 상승, RSI ~60 유지

    매 3번째 바마다 소폭 조정(-0.1%)을 넣어 RSI를 억제한다.
    """
    end = start * (1 + gain_pct / 100)
    bars = []
    for i in range(count):
        t = i / max(count - 1, 1)
        base = start + (end - start) * t
        # 매 3번째 바: 소폭 하락 (RSI 과열 방지)
        if i > 0 and i % 3 == 0:
            c = base - (end - start) * 0.03  # 전체 변동의 3% 조정
        else:
            c = base
        o = c - 10
        bars.append({
            'open': o, 'close': c,
            'high': max(o, c) + 20, 'low': min(o, c) - 20,
            'volume': volume,
        })
    # 첫 바와 마지막 바: 확정값
    bars[0]['open'] = start
    bars[0]['close'] = start
    bars[-1]['close'] = end
    return bars


def make_dipping_bars(count=30, entry_price=10000, drop_pct=-1.5, volume=1000):
    """하락 추세 바: entry_price로부터 drop_pct% 하락"""
    end_price = entry_price * (1 + drop_pct / 100)
    bars = []
    for i in range(count):
        t = i / max(count - 1, 1)
        base = entry_price + (end_price - entry_price) * t
        # 매 3번째 바: 소폭 반등 (RSI 자연스럽게)
        if i > 0 and i % 3 == 0:
            c = base + abs(end_price - entry_price) * 0.03
        else:
            c = base
        o = c + 10
        bars.append({
            'open': o, 'close': c,
            'high': max(o, c) + 20, 'low': min(o, c) - 20,
            'volume': volume,
        })
    return bars


# ============================================================
# 공통 기반 클래스
# ============================================================

class IntegrationBaseTest(unittest.TestCase):
    """_check_buy_signal() 통합 테스트 공통 setUp"""

    def setUp(self):
        module_path = os.path.join(PROJECT_ROOT, 'services', 'buy-scanner', 'opportunity_watcher.py')
        self.module = load_module("opportunity_watcher_integ", module_path)

        self.mock_config = MagicMock()
        self.mock_publisher = MagicMock()
        self.watcher = self.module.BuyOpportunityWatcher(
            self.mock_config, self.mock_publisher, redis_url="redis://dummy"
        )
        self.watcher.redis = MagicMock()

        # __init__에서 config mock 전에 설정된 속성 → 명시적 재설정
        self.watcher.momentum_confirmation_bars = 0
        self.watcher.cooldown_seconds = 600

        # config defaults
        self._config_bools = {
            "ENABLE_WATCHLIST_CONVICTION_ENTRY": True,
            "ENABLE_MOMENTUM_CONTINUATION": True,
            "ENABLE_BULL_PULLBACK": False,
            "ENABLE_VCP_BREAKOUT": False,
            "ENABLE_INSTITUTIONAL_ENTRY": False,
            "ENABLE_SHORT_TERM_HIGH_BREAKOUT": False,
            "ENABLE_VOLUME_BREAKOUT_1MIN": False,
            "ENABLE_BEAR_ENTRY_BLOCK": True,
            "ENABLE_MICRO_TIMING": False,
        }
        self._config_floats = {
            "CONVICTION_MIN_HYBRID_SCORE": 70.0,
            "CONVICTION_MIN_LLM_SCORE": 72.0,
            "CONVICTION_MAX_INTRADAY_GAIN_PCT": 3.0,
            "CONVICTION_MAX_VWAP_DEVIATION": 1.5,
            "MOMENTUM_CONT_MAX_GAIN_PCT": 5.0,
            "MOMENTUM_MAX_GAIN_PCT": 7.0,
            "DIP_BUY_MIN_DROP_BULL": -0.5,
            "DIP_BUY_MAX_DROP_BULL": -3.0,
            "RISK_GATE_VOLUME_RATIO": 2.0,
            "RISK_GATE_VWAP_DEVIATION": 0.02,
            "GOLDEN_CROSS_MIN_VOLUME_RATIO": 1.5,
        }
        self._config_ints = {
            "CONVICTION_MAX_DAYS_SINCE_ENTRY": 2,
            "RISK_GATE_RSI_MAX": 70,
            "MOMENTUM_CONFIRMATION_BARS": 0,
            "SIGNAL_COOLDOWN_SECONDS": 600,
        }
        self._config_strs = {
            "CONVICTION_ENTRY_WINDOW_START": "0915",
            "CONVICTION_ENTRY_WINDOW_END": "1030",
        }

        self.mock_config.get_bool = MagicMock(
            side_effect=lambda k, default=False: self._config_bools.get(k, default)
        )
        self.mock_config.get_float = MagicMock(
            side_effect=lambda k, default=0.0: self._config_floats.get(k, default)
        )
        self.mock_config.get_int = MagicMock(
            side_effect=lambda k, default=0: self._config_ints.get(k, default)
        )
        self.mock_config.get = MagicMock(
            side_effect=lambda k, default="": self._config_strs.get(k, default)
        )

        # BarAggregator mock
        self.watcher.bar_aggregator = MagicMock()
        self.watcher.bar_aggregator.get_volume_info.return_value = {
            'current': 1000, 'avg': 1000, 'ratio': 1.0,
        }
        self.watcher.bar_aggregator.get_vwap.return_value = 10050

        # side-effect mocks
        self.watcher._save_buy_logic_snapshot = MagicMock()
        self.watcher._save_signal_history = MagicMock()
        self.watcher._set_cooldown = MagicMock()
        self.watcher._get_trading_context = MagicMock(return_value=None)
        self.watcher._get_position_multiplier = MagicMock(return_value=1.0)
        self.watcher._check_macro_risk_gate = MagicMock(return_value=(True, "OK"))
        self.watcher._get_allowed_strategies = MagicMock(return_value=None)

        # Redis cooldown: not in cooldown
        self.watcher.redis.exists.return_value = False

    def _setup_bars(self, bars):
        """BarAggregator가 bars를 반환하도록 설정"""
        self.watcher.bar_aggregator.get_recent_bars.return_value = bars

    def _setup_watchlist(self, code='005930', name='Samsung', llm=70,
                         hybrid=50, trade_tier='TIER1', strategies=None):
        """hot_watchlist 설정"""
        self.watcher.hot_watchlist = {
            code: {
                'name': name,
                'llm_score': llm,
                'hybrid_score': hybrid,
                'trade_tier': trade_tier,
                'strategies': strategies or [],
            }
        }

    def _patch_time(self, kst_hour, kst_minute):
        """datetime.now() 패치: KST 시간 기준"""
        utc_hour = kst_hour - 9
        utc_time = datetime(2026, 2, 14, utc_hour, kst_minute, 0, tzinfo=timezone.utc)
        mock_dt = MagicMock(wraps=datetime)

        def mock_now(tz=None):
            if tz:
                return utc_time
            return datetime(2026, 2, 14, kst_hour, kst_minute, 0)
        mock_dt.now = MagicMock(side_effect=mock_now)
        return patch.object(self.module, 'datetime', mock_dt)


# ============================================================
# 1. TestGoldenCrossIntegration
# ============================================================

class TestGoldenCrossIntegration(IntegrationBaseTest):
    """GOLDEN_CROSS: _check_buy_signal() 경유 통합 테스트"""

    def _setup_for_golden_cross(self, vol_ratio=1.6):
        self._setup_watchlist(llm=65, hybrid=50)
        self.watcher.market_regime = 'BULL'
        bars = make_golden_cross_bars(count=30, volume=1000)
        self._setup_bars(bars)
        self.watcher.bar_aggregator.get_volume_info.return_value = {
            'current': 1600, 'avg': 1000, 'ratio': vol_ratio,
        }
        self.watcher.bar_aggregator.get_vwap.return_value = 10030

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_golden_cross_triggers(self, mock_sl):
        """10:00 KST + BULL + vol 1.6x → GOLDEN_CROSS 발동"""
        self._setup_for_golden_cross(vol_ratio=1.6)
        with self._patch_time(10, 0):
            signal = self.watcher._check_buy_signal('005930', 10090, {})
        self.assertIsNotNone(signal)
        self.assertEqual(signal['signal_type'], 'GOLDEN_CROSS')

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_golden_cross_weak_volume_blocked(self, mock_sl):
        """vol 0.8x → Weak Volume으로 GOLDEN_CROSS 차단"""
        self._setup_for_golden_cross(vol_ratio=0.8)
        with self._patch_time(10, 0):
            signal = self.watcher._check_buy_signal('005930', 10090, {})
        self.assertIsNone(signal)

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_golden_cross_blocked_danger_zone(self, mock_sl):
        """14:30 KST → Danger Zone 차단"""
        self._setup_for_golden_cross(vol_ratio=1.6)
        with self._patch_time(14, 30):
            signal = self.watcher._check_buy_signal('005930', 10090, {})
        self.assertIsNone(signal)

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_golden_cross_super_prime(self, mock_sl):
        """Legendary Pattern mock → GOLDEN_CROSS_SUPER_PRIME 격상"""
        self._setup_for_golden_cross(vol_ratio=1.6)
        self.watcher._check_legendary_pattern = MagicMock(return_value=True)
        with self._patch_time(10, 0):
            signal = self.watcher._check_buy_signal('005930', 10090, {})
        self.assertIsNotNone(signal)
        self.assertEqual(signal['signal_type'], 'GOLDEN_CROSS_SUPER_PRIME')
        self.assertTrue(signal['is_super_prime'])


# ============================================================
# 2. TestMomentumIntegration
# ============================================================

class TestMomentumIntegration(IntegrationBaseTest):
    """MOMENTUM: _check_buy_signal() 경유 통합 테스트"""

    def _setup_momentum(self, gain_pct=3.0):
        self._setup_watchlist(llm=65, hybrid=50)
        self.watcher.market_regime = 'SIDEWAYS'
        bars = make_trending_bars(count=30, start=10000, gain_pct=gain_pct)
        self._setup_bars(bars)
        # 상승 추세 바는 RSI가 과열(>70) 되므로 RSI를 직접 제어
        self.watcher._calculate_simple_rsi = MagicMock(return_value=55.0)

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_momentum_triggers(self, mock_sl):
        """3% 상승 bars → MOMENTUM 발동"""
        self._setup_momentum(gain_pct=3.0)
        with self._patch_time(10, 30):
            signal = self.watcher._check_buy_signal('005930', 10300, {})
        self.assertIsNotNone(signal)
        self.assertEqual(signal['signal_type'], 'MOMENTUM')

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_momentum_blocked_by_cap(self, mock_sl):
        """8% 상승 → cap(7%) 초과 차단"""
        self._setup_momentum(gain_pct=8.0)
        with self._patch_time(10, 30):
            signal = self.watcher._check_buy_signal('005930', 10800, {})
        self.assertIsNone(signal)

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_momentum_confirmation_bars_pending(self, mock_sl):
        """confirmation_bars=1 → pending 저장, 즉시 None 반환"""
        self._setup_momentum(gain_pct=3.0)
        self.watcher.momentum_confirmation_bars = 1
        with self._patch_time(10, 30):
            signal = self.watcher._check_buy_signal('005930', 10300, {})
        self.assertIsNone(signal)
        self.assertIn('005930', self.watcher.pending_momentum_signals)
        self.assertEqual(
            self.watcher.pending_momentum_signals['005930']['signal_type'],
            'MOMENTUM'
        )


# ============================================================
# 3. TestMomentumContinuationIntegration
# ============================================================

class TestMomentumContinuationIntegration(IntegrationBaseTest):
    """MOMENTUM_CONTINUATION_BULL: _check_buy_signal() 경유 통합 테스트"""

    def _setup_mom_cont(self, regime='BULL', llm=70, gain_pct=3.0):
        self._setup_watchlist(llm=llm, hybrid=50)
        self.watcher.market_regime = regime
        bars = make_trending_bars(count=30, start=10000, gain_pct=gain_pct)
        self._setup_bars(bars)
        # 상승 추세 바는 RSI가 과열(>70) 되므로 RSI를 직접 제어
        self.watcher._calculate_simple_rsi = MagicMock(return_value=55.0)

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_mom_cont_triggers(self, mock_sl):
        """BULL + MA5>MA20 + 3% gain + llm 70 → MOMENTUM_CONTINUATION_BULL"""
        self._setup_mom_cont(regime='BULL', llm=70, gain_pct=3.0)
        with self._patch_time(10, 30):
            signal = self.watcher._check_buy_signal('005930', 10300, {})
        self.assertIsNotNone(signal)
        self.assertEqual(signal['signal_type'], 'MOMENTUM_CONTINUATION_BULL')

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_mom_cont_blocked_sideways(self, mock_sl):
        """SIDEWAYS → MOMENTUM_CONTINUATION 차단"""
        self._setup_mom_cont(regime='SIDEWAYS', llm=70, gain_pct=3.0)
        with self._patch_time(10, 30):
            signal = self.watcher._check_buy_signal('005930', 10300, {})
        if signal:
            self.assertNotEqual(signal['signal_type'], 'MOMENTUM_CONTINUATION_BULL')

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_mom_cont_blocked_low_llm(self, mock_sl):
        """llm 50 → MOMENTUM_CONTINUATION 차단"""
        self._setup_mom_cont(regime='BULL', llm=50, gain_pct=3.0)
        with self._patch_time(10, 30):
            signal = self.watcher._check_buy_signal('005930', 10300, {})
        if signal:
            self.assertNotEqual(signal['signal_type'], 'MOMENTUM_CONTINUATION_BULL')

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_mom_cont_blocked_cap(self, mock_sl):
        """6% gain → cap(5%) 초과 차단"""
        self._setup_mom_cont(regime='BULL', llm=70, gain_pct=6.0)
        with self._patch_time(10, 30):
            signal = self.watcher._check_buy_signal('005930', 10600, {})
        if signal:
            self.assertNotEqual(signal['signal_type'], 'MOMENTUM_CONTINUATION_BULL')


# ============================================================
# 4. TestConvictionEntryIntegration
# ============================================================

class TestConvictionEntryIntegration(IntegrationBaseTest):
    """WATCHLIST_CONVICTION_ENTRY: _check_buy_signal() 경유 통합 테스트"""

    def _setup_conviction(self, bar_count=30, hybrid=75, llm=74):
        self._setup_watchlist(llm=llm, hybrid=hybrid)
        self.watcher.market_regime = 'BULL'
        self.watcher.watchlist_entry_cache = {
            '005930': {
                'entry_date': date.today() - timedelta(days=1),
                'entry_price': 10000,
            }
        }
        bars = make_bars(count=bar_count, open_price=10000, close_price=10100)
        self._setup_bars(bars)
        self.watcher.bar_aggregator.get_vwap.return_value = 10050

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_conviction_triggers_early(self, mock_sl):
        """10:00 KST + hybrid 75 → WATCHLIST_CONVICTION_ENTRY (Risk Gate 이전 조기 발동)"""
        self._setup_conviction(hybrid=75, llm=74)
        with self._patch_time(10, 0):
            signal = self.watcher._check_buy_signal('005930', 10100, {})
        self.assertIsNotNone(signal)
        self.assertEqual(signal['signal_type'], 'WATCHLIST_CONVICTION_ENTRY')

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_conviction_with_5_bars_bypasses_min_bars(self, mock_sl):
        """5개 바만으로 Min Bars(20) 우회 → 발동"""
        self._setup_conviction(bar_count=5, hybrid=75, llm=74)
        with self._patch_time(10, 0):
            signal = self.watcher._check_buy_signal('005930', 10100, {})
        self.assertIsNotNone(signal)
        self.assertEqual(signal['signal_type'], 'WATCHLIST_CONVICTION_ENTRY')

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_conviction_miss_falls_to_golden_cross(self, mock_sl):
        """CONVICTION 미달(no entry cache) + GOLDEN_CROSS 조건 충족 → GOLDEN_CROSS 폴백"""
        self._setup_watchlist(llm=65, hybrid=50)
        self.watcher.market_regime = 'BULL'
        self.watcher.watchlist_entry_cache = {}
        bars = make_golden_cross_bars(count=30, volume=1000)
        self._setup_bars(bars)
        self.watcher.bar_aggregator.get_volume_info.return_value = {
            'current': 1600, 'avg': 1000, 'ratio': 1.6,
        }
        self.watcher.bar_aggregator.get_vwap.return_value = 10030
        with self._patch_time(10, 0):
            signal = self.watcher._check_buy_signal('005930', 10090, {})
        self.assertIsNotNone(signal)
        self.assertEqual(signal['signal_type'], 'GOLDEN_CROSS')

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_all_strategies_miss_returns_none(self, mock_sl):
        """전부 미달 → None"""
        self._setup_watchlist(llm=50, hybrid=50)
        self.watcher.market_regime = 'SIDEWAYS'
        self.watcher.watchlist_entry_cache = {}
        bars = make_bars(count=30, open_price=10000, close_price=10000, volume=1000)
        self._setup_bars(bars)
        with self._patch_time(10, 30):
            signal = self.watcher._check_buy_signal('005930', 10000, {})
        self.assertIsNone(signal)


# ============================================================
# 5. TestDipBuyIntegration
# ============================================================

class TestDipBuyIntegration(IntegrationBaseTest):
    """DIP_BUY: _check_buy_signal() 경유 통합 테스트"""

    def _setup_dip_buy(self, regime='BULL', drop_pct=-1.5, days=2, llm=70):
        self._setup_watchlist(llm=llm, hybrid=50)
        self.watcher.market_regime = regime
        entry_price = 10000
        current_price = entry_price * (1 + drop_pct / 100)
        self.watcher.watchlist_entry_cache = {
            '005930': {
                'entry_date': date.today() - timedelta(days=days),
                'entry_price': entry_price,
            }
        }
        bars = make_dipping_bars(count=30, entry_price=entry_price, drop_pct=drop_pct)
        self._setup_bars(bars)
        return current_price

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_dip_buy_triggers(self, mock_sl):
        """BULL + D+2 + -1.5% → DIP_BUY"""
        price = self._setup_dip_buy(regime='BULL', drop_pct=-1.5, days=2, llm=70)
        with self._patch_time(11, 0):
            signal = self.watcher._check_buy_signal('005930', price, {})
        self.assertIsNotNone(signal)
        self.assertEqual(signal['signal_type'], 'DIP_BUY')

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_dip_buy_blocked_by_cooldown(self, mock_sl):
        """Cooldown 활성 → 차단"""
        price = self._setup_dip_buy(regime='BULL', drop_pct=-1.5, days=2, llm=70)
        self.watcher.redis.exists.return_value = True
        with self._patch_time(11, 0):
            signal = self.watcher._check_buy_signal('005930', price, {})
        self.assertIsNone(signal)

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_dip_buy_sideways_deep_dip(self, mock_sl):
        """SIDEWAYS + -3% → DIP_BUY (기본 기준 -2~-5%)"""
        price = self._setup_dip_buy(regime='SIDEWAYS', drop_pct=-3.0, days=2, llm=70)
        with self._patch_time(11, 0):
            signal = self.watcher._check_buy_signal('005930', price, {})
        self.assertIsNotNone(signal)
        self.assertEqual(signal['signal_type'], 'DIP_BUY')


# ============================================================
# 6. TestRiskGateBlocking
# ============================================================

class TestRiskGateBlocking(IntegrationBaseTest):
    """Risk Gate 개별 차단 검증 (CONVICTION 미달 종목)"""

    def setUp(self):
        super().setUp()
        self._setup_watchlist(llm=50, hybrid=50)
        self.watcher.market_regime = 'SIDEWAYS'
        self.watcher.watchlist_entry_cache = {}

    def _make_flat_bars(self, count=30):
        return make_bars(count=count, open_price=10000, close_price=10000, volume=1000)

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_min_bars_blocks(self, mock_sl):
        """Min Bars(20) 미달(15개) → 차단"""
        bars = self._make_flat_bars(count=15)
        self._setup_bars(bars)
        with self._patch_time(10, 30):
            signal = self.watcher._check_buy_signal('005930', 10000, {})
        self.assertIsNone(signal)

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_no_trade_window_blocks(self, mock_sl):
        """09:10 KST → No-Trade Window 차단"""
        bars = self._make_flat_bars(count=30)
        self._setup_bars(bars)
        with self._patch_time(9, 10):
            signal = self.watcher._check_buy_signal('005930', 10000, {})
        self.assertIsNone(signal)

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_danger_zone_blocks(self, mock_sl):
        """14:30 KST → Danger Zone 차단"""
        bars = self._make_flat_bars(count=30)
        self._setup_bars(bars)
        with self._patch_time(14, 30):
            signal = self.watcher._check_buy_signal('005930', 10000, {})
        self.assertIsNone(signal)

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_rsi_guard_blocks(self, mock_sl):
        """RSI > 70 → 차단"""
        # 급등 bars → RSI=100 (all positive deltas)
        bars = []
        for i in range(30):
            c = 10000 + i * 50
            bars.append({
                'open': c - 10, 'close': c,
                'high': c + 20, 'low': c - 20, 'volume': 1000,
            })
        self._setup_bars(bars)
        with self._patch_time(10, 30):
            signal = self.watcher._check_buy_signal('005930', 11500, {})
        self.assertIsNone(signal)

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_macro_risk_blocks(self, mock_sl):
        """Macro Risk Level 2 → 차단"""
        bars = self._make_flat_bars(count=30)
        self._setup_bars(bars)
        self.watcher._check_macro_risk_gate = MagicMock(
            return_value=(False, "Risk-Off Level 2: Geopolitical")
        )
        with self._patch_time(10, 30):
            signal = self.watcher._check_buy_signal('005930', 10000, {})
        self.assertIsNone(signal)

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_bear_regime_blocks(self, mock_sl):
        """BEAR regime → 차단"""
        bars = self._make_flat_bars(count=30)
        self._setup_bars(bars)
        self.watcher.market_regime = 'BEAR'
        with self._patch_time(10, 30):
            signal = self.watcher._check_buy_signal('005930', 10000, {})
        self.assertIsNone(signal)

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_combined_risk_blocks(self, mock_sl):
        """vol 3x + VWAP 5% → Combined Risk 차단"""
        bars = self._make_flat_bars(count=30)
        self._setup_bars(bars)
        self.watcher.bar_aggregator.get_volume_info.return_value = {
            'current': 3000, 'avg': 1000, 'ratio': 3.0,
        }
        self.watcher.bar_aggregator.get_vwap.return_value = 9500
        with self._patch_time(10, 30):
            signal = self.watcher._check_buy_signal('005930', 10500, {})
        self.assertIsNone(signal)

    def test_sl_cooldown_blocks(self):
        """SL Cooldown → 차단"""
        bars = self._make_flat_bars(count=30)
        self._setup_bars(bars)
        with patch('shared.redis_cache.is_stoploss_blacklisted', return_value=True):
            with self._patch_time(10, 30):
                signal = self.watcher._check_buy_signal('005930', 10000, {})
        self.assertIsNone(signal)


# ============================================================
# 7. TestMomentumConfirmationBar
# ============================================================

class TestMomentumConfirmationBar(IntegrationBaseTest):
    """모멘텀 확인 바 (pending → confirm/discard) 테스트"""

    def _setup_pending_signal(self):
        """MOMENTUM pending 신호를 생성"""
        self._setup_watchlist(llm=65, hybrid=50)
        self.watcher.market_regime = 'SIDEWAYS'
        self.watcher.momentum_confirmation_bars = 1
        bars = make_trending_bars(count=30, start=10000, gain_pct=3.0)
        self._setup_bars(bars)
        # 상승 추세 바는 RSI가 과열(>70) 되므로 RSI를 직접 제어
        self.watcher._calculate_simple_rsi = MagicMock(return_value=55.0)

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_momentum_pending_stored(self, mock_sl):
        """MOMENTUM → pending 저장 + None 반환"""
        self._setup_pending_signal()
        with self._patch_time(10, 30):
            signal = self.watcher._check_buy_signal('005930', 10300, {})
        self.assertIsNone(signal)
        self.assertIn('005930', self.watcher.pending_momentum_signals)

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_pending_confirmed_on_rise(self, mock_sl):
        """다음 봉 상승 → 확인 성공 → signal + publish_signal 호출"""
        self._setup_pending_signal()
        with self._patch_time(10, 30):
            self.watcher._check_buy_signal('005930', 10300, {})

        self.assertIn('005930', self.watcher.pending_momentum_signals)

        completed_bar = {'close': 10350, 'open': 10300, 'high': 10360, 'low': 10290, 'volume': 1200}
        result = self.watcher._check_pending_momentum('005930', completed_bar)
        self.assertIsNotNone(result)
        self.assertEqual(result['signal_type'], 'MOMENTUM')
        self.watcher.tasks_publisher.publish.assert_called_once()

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_pending_discarded_on_fall(self, mock_sl):
        """다음 봉 하락 → 확인 실패 → 폐기"""
        self._setup_pending_signal()
        with self._patch_time(10, 30):
            self.watcher._check_buy_signal('005930', 10300, {})

        completed_bar = {'close': 10200, 'open': 10300, 'high': 10310, 'low': 10180, 'volume': 800}
        result = self.watcher._check_pending_momentum('005930', completed_bar)
        self.assertIsNone(result)
        self.assertNotIn('005930', self.watcher.pending_momentum_signals)


# ============================================================
# 8. TestMultiStrategyPriority
# ============================================================

class TestMultiStrategyPriority(IntegrationBaseTest):
    """전략 우선순위 검증"""

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_conviction_takes_priority(self, mock_sl):
        """CONVICTION + 다른 전략 가능 → CONVICTION 우선 (조기 발동)"""
        self._setup_watchlist(llm=74, hybrid=75)
        self.watcher.market_regime = 'BULL'
        self.watcher.watchlist_entry_cache = {
            '005930': {
                'entry_date': date.today() - timedelta(days=1),
                'entry_price': 10000,
            }
        }
        # 소폭 상승 bars (RSI 낮게 유지, conviction intraday gain < 3%)
        bars = make_bars(count=30, open_price=10000, close_price=10100)
        self._setup_bars(bars)
        self.watcher.bar_aggregator.get_vwap.return_value = 10050
        with self._patch_time(10, 0):
            signal = self.watcher._check_buy_signal('005930', 10100, {})
        self.assertIsNotNone(signal)
        self.assertEqual(signal['signal_type'], 'WATCHLIST_CONVICTION_ENTRY')

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_mom_cont_before_golden_cross(self, mock_sl):
        """BULL + MOM_CONT + GOLDEN_CROSS → MOM_CONT 우선 (BULL 블록이 strategies 루프보다 먼저)"""
        self._setup_watchlist(llm=70, hybrid=50)
        self.watcher.market_regime = 'BULL'
        self.watcher.watchlist_entry_cache = {}
        bars = make_trending_bars(count=30, start=10000, gain_pct=3.0)
        self._setup_bars(bars)
        # 상승 추세 바는 RSI가 과열(>70) 되므로 RSI를 직접 제어
        self.watcher._calculate_simple_rsi = MagicMock(return_value=55.0)
        with self._patch_time(11, 0):
            signal = self.watcher._check_buy_signal('005930', 10300, {})
        self.assertIsNotNone(signal)
        self.assertEqual(signal['signal_type'], 'MOMENTUM_CONTINUATION_BULL')

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_dip_buy_only_when_others_miss(self, mock_sl):
        """DIP_BUY만 가능한 조건 → DIP_BUY"""
        self._setup_watchlist(llm=70, hybrid=50)
        self.watcher.market_regime = 'SIDEWAYS'
        entry_price = 10000
        current_price = entry_price * 0.97  # -3%
        self.watcher.watchlist_entry_cache = {
            '005930': {
                'entry_date': date.today() - timedelta(days=2),
                'entry_price': entry_price,
            }
        }
        bars = make_dipping_bars(count=30, entry_price=entry_price, drop_pct=-3.0)
        self._setup_bars(bars)
        with self._patch_time(11, 0):
            signal = self.watcher._check_buy_signal('005930', current_price, {})
        self.assertIsNotNone(signal)
        self.assertEqual(signal['signal_type'], 'DIP_BUY')


# ============================================================
# 9. TestOnPriceUpdateEndToEnd
# ============================================================

class TestOnPriceUpdateEndToEnd(IntegrationBaseTest):
    """on_price_update() → BarAggregator → _check_buy_signal 흐름"""

    @patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False)
    def test_completed_bar_triggers_signal(self, mock_sl):
        """BarAggregator.update() → completed_bar → _check_buy_signal → 신호"""
        self._setup_watchlist(llm=65, hybrid=50)
        self.watcher.market_regime = 'SIDEWAYS'

        completed_bar = {
            'timestamp': datetime(2026, 2, 14, 1, 30),
            'open': 10000, 'close': 10300, 'high': 10350, 'low': 9980,
            'volume': 1500, 'tick_count': 10,
        }
        self.watcher.bar_aggregator.update = MagicMock(return_value=completed_bar)

        mock_signal = {
            'stock_code': '005930', 'signal_type': 'MOMENTUM',
            'signal_reason': 'test', 'stock_name': 'Samsung',
            'current_price': 10300, 'llm_score': 65,
            'market_regime': 'SIDEWAYS', 'source': 'test',
            'timestamp': '2026-02-14T01:30:00+00:00',
            'trade_tier': 'TIER1', 'is_super_prime': False,
            'position_multiplier': 1.0, 'macro_context': None,
        }
        self.watcher._check_buy_signal = MagicMock(return_value=mock_signal)
        self.watcher._check_pending_momentum = MagicMock(return_value=None)

        result = self.watcher.on_price_update('005930', 10300, 1500)
        self.assertIsNotNone(result)
        self.assertEqual(result['signal_type'], 'MOMENTUM')
        self.watcher._check_buy_signal.assert_called_once()

    def test_no_completed_bar_no_signal(self):
        """BarAggregator.update() → None → 신호 없음"""
        self._setup_watchlist(llm=65, hybrid=50)
        self.watcher.bar_aggregator.update = MagicMock(return_value=None)

        result = self.watcher.on_price_update('005930', 10100, 500)
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
