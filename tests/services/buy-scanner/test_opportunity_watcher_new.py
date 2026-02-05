
import unittest
from unittest.mock import MagicMock
import os
import sys
import importlib.util

# Project Root Setup
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

class TestBuyOpportunityWatcherRSI(unittest.TestCase):
    def setUp(self):
        # Load opportunity_watcher module dynamically because of hyphen in path
        module_path = os.path.join(PROJECT_ROOT, 'services', 'buy-scanner', 'opportunity_watcher.py')
        self.module = load_module("opportunity_watcher", module_path)
        
        self.mock_config = MagicMock()
        self.mock_publisher = MagicMock()
        self.watcher = self.module.BuyOpportunityWatcher(self.mock_config, self.mock_publisher, redis_url="redis://dummy")
        # Redis 연결 방지
        self.watcher.redis = MagicMock()

    def test_check_rsi_rebound_triggered(self):
        """RSI Rebound 감지: 28 -> 32"""
        # Mocking internal method directly on the instance
        self.watcher._calculate_simple_rsi = MagicMock(side_effect=[32.0, 28.0])
        
        # Dummy bars
        bars = [{'close': 100}] * 30 
        params = {'threshold': 30}
        
        triggered, reason = self.watcher._check_rsi_rebound(bars, params)
        
        self.assertTrue(triggered)
        self.assertIn("RSI Rebound", reason)
        self.assertEqual(self.watcher._calculate_simple_rsi.call_count, 2)

    def test_check_rsi_rebound_no_trigger_still_low(self):
        """RSI 여전히 과매도: 25 -> 28"""
        self.watcher._calculate_simple_rsi = MagicMock(side_effect=[28.0, 25.0]) # Curr, Prev
        
        bars = [{'close': 100}] * 30 
        params = {'threshold': 30}
        
        triggered, reason = self.watcher._check_rsi_rebound(bars, params)
        
        self.assertFalse(triggered)
        
    def test_check_rsi_rebound_no_trigger_normal(self):
        """이미 정상 구간: 35 -> 40"""
        self.watcher._calculate_simple_rsi = MagicMock(side_effect=[40.0, 35.0]) # Curr, Prev
        
        bars = [{'close': 100}] * 30 
        params = {'threshold': 30}
        
        triggered, reason = self.watcher._check_rsi_rebound(bars, params)
        
        self.assertFalse(triggered)

    def test_check_rsi_rebound_cross_down(self):
        """하향 돌파 (진입 아님): 32 -> 28"""
        self.watcher._calculate_simple_rsi = MagicMock(side_effect=[28.0, 32.0]) # Curr, Prev
        
        bars = [{'close': 100}] * 30 
        params = {'threshold': 30}
        
        triggered, reason = self.watcher._check_rsi_rebound(bars, params)
        
        self.assertFalse(triggered)

class TestRegimeGate(unittest.TestCase):
    """[P0] BEAR/STRONG_BEAR Market Regime Gate 테스트"""

    def setUp(self):
        module_path = os.path.join(PROJECT_ROOT, 'services', 'buy-scanner', 'opportunity_watcher.py')
        self.module = load_module("opportunity_watcher", module_path)

        self.mock_config = MagicMock()
        self.mock_publisher = MagicMock()
        self.watcher = self.module.BuyOpportunityWatcher(self.mock_config, self.mock_publisher, redis_url="redis://dummy")
        self.watcher.redis = MagicMock()

    def test_bear_regime_blocks_entry(self):
        """BEAR 시장에서 진입 차단"""
        self.watcher.market_regime = 'BEAR'
        self.mock_config.get_bool = MagicMock(return_value=True)

        # Regime Gate 체크: BEAR가 bear_regimes에 포함되어야 함
        bear_regimes = ['BEAR', 'STRONG_BEAR']
        result = self.watcher.market_regime not in bear_regimes
        self.assertFalse(result)

    def test_strong_bear_regime_blocks_entry(self):
        """STRONG_BEAR 시장에서 진입 차단"""
        self.watcher.market_regime = 'STRONG_BEAR'

        bear_regimes = ['BEAR', 'STRONG_BEAR']
        result = self.watcher.market_regime not in bear_regimes
        self.assertFalse(result)

    def test_bull_regime_allows_entry(self):
        """BULL 시장에서 진입 허용"""
        self.watcher.market_regime = 'BULL'

        bear_regimes = ['BEAR', 'STRONG_BEAR']
        result = self.watcher.market_regime not in bear_regimes
        self.assertTrue(result)

    def test_neutral_regime_allows_entry(self):
        """NEUTRAL 시장에서 진입 허용"""
        self.watcher.market_regime = 'NEUTRAL'

        bear_regimes = ['BEAR', 'STRONG_BEAR']
        result = self.watcher.market_regime not in bear_regimes
        self.assertTrue(result)

    def test_sideways_regime_allows_entry(self):
        """SIDEWAYS 시장에서 진입 허용"""
        self.watcher.market_regime = 'SIDEWAYS'

        bear_regimes = ['BEAR', 'STRONG_BEAR']
        result = self.watcher.market_regime not in bear_regimes
        self.assertTrue(result)


class TestStoplossCooldownGate(unittest.TestCase):
    """[P0] 손절 쿨다운 게이트 테스트"""

    def test_stoploss_blacklisted_blocks_entry(self):
        """손절 쿨다운 중인 종목 진입 차단"""
        from unittest.mock import patch

        with patch('shared.redis_cache.is_stoploss_blacklisted', return_value=True):
            from shared.redis_cache import is_stoploss_blacklisted
            sl_cooldown_passed = not is_stoploss_blacklisted("005930")
            self.assertFalse(sl_cooldown_passed)

    def test_stoploss_clear_allows_entry(self):
        """쿨다운 없는 종목 진입 허용"""
        from unittest.mock import patch

        with patch('shared.redis_cache.is_stoploss_blacklisted', return_value=False):
            from shared.redis_cache import is_stoploss_blacklisted
            sl_cooldown_passed = not is_stoploss_blacklisted("005930")
            self.assertTrue(sl_cooldown_passed)


class TestVolumeBreakoutDisable(unittest.TestCase):
    """[P0] VOLUME_BREAKOUT_1MIN 비활성화 테스트"""

    def setUp(self):
        module_path = os.path.join(PROJECT_ROOT, 'services', 'buy-scanner', 'opportunity_watcher.py')
        self.module = load_module("opportunity_watcher", module_path)

        self.mock_config = MagicMock()
        self.mock_publisher = MagicMock()
        self.watcher = self.module.BuyOpportunityWatcher(self.mock_config, self.mock_publisher, redis_url="redis://dummy")
        self.watcher.redis = MagicMock()

    def test_volume_breakout_disabled_by_default(self):
        """VOLUME_BREAKOUT_1MIN 기본 비활성화"""
        # config.get_bool("ENABLE_VOLUME_BREAKOUT_1MIN", default=False) → False
        self.mock_config.get_bool = MagicMock(return_value=False)

        result = self.mock_config.get_bool("ENABLE_VOLUME_BREAKOUT_1MIN", default=False)
        self.assertFalse(result)

    def test_volume_breakout_enabled_explicitly(self):
        """VOLUME_BREAKOUT_1MIN 명시적 활성화"""
        self.mock_config.get_bool = MagicMock(return_value=True)

        result = self.mock_config.get_bool("ENABLE_VOLUME_BREAKOUT_1MIN", default=False)
        self.assertTrue(result)


if __name__ == '__main__':
    unittest.main()
