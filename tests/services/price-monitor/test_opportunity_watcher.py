# tests/services/price-monitor/test_opportunity_watcher.py
# OpportunityWatcher 유닛 테스트 (unittest 변환)

"""
OpportunityWatcher 클래스의 핵심 기능을 테스트합니다.

테스트 범위:
- BarAggregator: 틱 → 1분 캔들 집계
- OpportunityWatcher: Hot Watchlist 로드, 매수 신호 감지
- Cooldown 로직
- 관측성 메트릭
"""

import unittest
from unittest.mock import MagicMock, patch
import sys
import os
from datetime import datetime, timezone, timedelta

# Project root setup
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'services', 'price-monitor'))

from opportunity_watcher import BarAggregator, OpportunityWatcher


class TestBarAggregator(unittest.TestCase):
    """BarAggregator 테스트"""
    
    def test_first_tick_creates_new_bar(self):
        """첫 틱이 새 캔들을 생성"""
        aggregator = BarAggregator(bar_interval_seconds=60)
        result = aggregator.update("005930", 50000.0, volume=100)
        
        # 첫 틱은 None 반환 (캔들 미완료)
        self.assertIsNone(result)
        self.assertIn("005930", aggregator.current_bars)
        bar = aggregator.current_bars["005930"]
        self.assertEqual(bar['open'], 50000.0)
        self.assertEqual(bar['high'], 50000.0)
        self.assertEqual(bar['low'], 50000.0)
        self.assertEqual(bar['close'], 50000.0)
        self.assertEqual(bar['tick_count'], 1)
    
    def test_tick_updates_ohlcv(self):
        """틱이 OHLCV 업데이트"""
        aggregator = BarAggregator(bar_interval_seconds=60)
        aggregator.update("005930", 50000.0)
        aggregator.update("005930", 50500.0)  # High
        aggregator.update("005930", 49500.0)  # Low
        aggregator.update("005930", 50200.0)  # Close
        
        bar = aggregator.current_bars["005930"]
        self.assertEqual(bar['open'], 50000.0)
        self.assertEqual(bar['high'], 50500.0)
        self.assertEqual(bar['low'], 49500.0)
        self.assertEqual(bar['close'], 50200.0)
        self.assertEqual(bar['tick_count'], 4)
    
    def test_get_recent_bars(self):
        """최근 캔들 조회"""
        aggregator = BarAggregator(bar_interval_seconds=60)
        
        # 완료된 캔들이 없으면 빈 리스트
        recent = aggregator.get_recent_bars("005930", count=5)
        self.assertEqual(recent, [])
        
        # 수동으로 완료된 캔들 추가 (테스트용)
        aggregator.completed_bars["005930"] = [
            {'close': 50000}, {'close': 50100}, {'close': 50200}
        ]
        
        recent = aggregator.get_recent_bars("005930", count=2)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[-1]['close'], 50200)


class TestOpportunityWatcher(unittest.TestCase):
    """OpportunityWatcher 테스트"""
    
    def setUp(self):
        self.mock_config = MagicMock()
        self.mock_config.get_bool.return_value = False
        self.mock_config.get_int.return_value = 60
        self.mock_config.get_float.return_value = 0.0
        
        self.mock_publisher = MagicMock()
        self.mock_publisher.publish.return_value = "msg-123"

        # mock redis patcher
        self.redis_patcher = patch('opportunity_watcher.redis.from_url')
        self.mock_redis_cls = self.redis_patcher.start()
        self.mock_redis = MagicMock()
        self.mock_redis_cls.return_value = self.mock_redis
        self.mock_redis.ping.return_value = True

        self.watcher = OpportunityWatcher(
            config=self.mock_config,
            tasks_publisher=self.mock_publisher,
            redis_url="redis://localhost:6379/0"
        )

    def tearDown(self):
        self.redis_patcher.stop()
    
    def test_init_metrics(self):
        """초기화 시 메트릭 딕셔너리 생성"""
        self.assertIn('tick_count', self.watcher.metrics)
        self.assertIn('bar_count', self.watcher.metrics)
        self.assertIn('signal_count', self.watcher.metrics)
        self.assertEqual(self.watcher.metrics['tick_count'], 0)
    
    def test_on_price_update_not_in_watchlist(self):
        """Hot Watchlist에 없는 종목은 무시"""
        self.watcher.hot_watchlist = {}
        
        result = self.watcher.on_price_update("005930", 50000.0)
        
        self.assertIsNone(result)
        self.assertEqual(self.watcher.metrics['tick_count'], 1)
    
    def test_on_price_update_in_watchlist(self):
        """Hot Watchlist에 있는 종목은 처리"""
        self.watcher.hot_watchlist = {
            "005930": {"name": "삼성전자", "llm_score": 72}
        }
        
        result = self.watcher.on_price_update("005930", 50000.0)
        
        # 첫 틱이라 캔들 미완료 → None
        self.assertIsNone(result)
        self.assertEqual(self.watcher.metrics['tick_count'], 1)
    
    def test_calculate_simple_rsi(self):
        """RSI 계산 테스트"""
        # 상승 추세
        prices = [100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 
                  120, 122, 124, 126, 128, 130]
        rsi = self.watcher._calculate_simple_rsi(prices, period=14)
        
        self.assertIsNotNone(rsi)
        self.assertGreater(rsi, 50)  # 상승 추세라 RSI > 50
    
    def test_calculate_simple_rsi_insufficient_data(self):
        """데이터 부족 시 RSI None"""
        prices = [100, 101, 102]
        rsi = self.watcher._calculate_simple_rsi(prices, period=14)
        
        self.assertIsNone(rsi)
    
    def test_get_metrics(self):
        """메트릭 조회"""
        self.watcher.hot_watchlist = {"005930": {}}
        self.watcher.market_regime = "BULL"
        self.watcher.metrics['tick_count'] = 100
        
        metrics = self.watcher.get_metrics()
        
        self.assertEqual(metrics['tick_count'], 100)
        self.assertEqual(metrics['hot_watchlist_size'], 1)
        self.assertEqual(metrics['market_regime'], "BULL")
    
    def test_publish_signal(self):
        """신호 발행 테스트"""
        signal = {
            'stock_code': '005930',
            'stock_name': '삼성전자',
            'signal_type': 'GOLDEN_CROSS',
            'signal_reason': '5MA crossed 20MA',
            'current_price': 50000.0,
            'llm_score': 72,
            'market_regime': 'BULL',
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
        
        result = self.watcher.publish_signal(signal)
        
        self.assertTrue(result)
        self.mock_publisher.publish.assert_called_once()
        self.assertEqual(self.watcher.metrics['signal_count'], 1)
        self.assertIsNotNone(self.watcher.metrics['last_signal_time'])
    
    def test_publish_signal_no_publisher(self):
        """Publisher 없을 때"""
        # 별도 인스턴스 생성
        watcher = OpportunityWatcher(
            config=self.mock_config,
            tasks_publisher=None,
            redis_url="redis://localhost:6379/0"
        )
        
        result = watcher.publish_signal({})
        self.assertFalse(result)


class TestCooldown(unittest.TestCase):
    """Cooldown 로직 테스트"""
    
    def setUp(self):
        mock_config = MagicMock()
        mock_config.get_bool.return_value = False
        mock_publisher = MagicMock()
        
        self.redis_patcher = patch('opportunity_watcher.redis.from_url')
        mock_redis_cls = self.redis_patcher.start()
        
        self.mock_redis = MagicMock()
        self.mock_redis.ping.return_value = True
        self.mock_redis.exists.return_value = False
        mock_redis_cls.return_value = self.mock_redis
        
        self.watcher = OpportunityWatcher(
            config=mock_config,
            tasks_publisher=mock_publisher,
            redis_url="redis://localhost:6379/0"
        )
        # 내부 redis 참조도 mock으로
        
    def tearDown(self):
        self.redis_patcher.stop()

    def test_check_cooldown_no_exists(self):
        """Cooldown 키 없으면 True (발행 가능)"""
        self.mock_redis.exists.return_value = False
        
        result = self.watcher._check_cooldown("005930")
        
        self.assertTrue(result)
    
    def test_check_cooldown_exists(self):
        """Cooldown 키 있으면 False (발행 불가)"""
        self.mock_redis.exists.return_value = True
        
        result = self.watcher._check_cooldown("005930")
        
        self.assertFalse(result)
        self.assertEqual(self.watcher.metrics['cooldown_blocked'], 1)
    
    def test_set_cooldown(self):
        """Cooldown 설정"""
        self.watcher._set_cooldown("005930")
        
        self.mock_redis.setex.assert_called_once()
        call_args = self.mock_redis.setex.call_args
        self.assertEqual(call_args[0][0], "buy_signal_cooldown:005930")
        self.assertEqual(call_args[0][1], 180)  # cooldown_seconds


class TestHotWatchlistLoad(unittest.TestCase):
    """Hot Watchlist 로드 테스트"""
    
    def setUp(self):
        self.mock_config = MagicMock()
        self.mock_config.get_bool.return_value = False
        self.mock_publisher = MagicMock()
        
        self.redis_patcher = patch('opportunity_watcher.redis.from_url')
        self.mock_redis_cls = self.redis_patcher.start()
        self.mock_redis = MagicMock()
        self.mock_redis.ping.return_value = True
        self.mock_redis_cls.return_value = self.mock_redis

    def tearDown(self):
        self.redis_patcher.stop()

    def test_load_hot_watchlist_success(self):
        """Hot Watchlist 로드 성공"""
        self.mock_redis.get.side_effect = [
            "hot_watchlist:v12345",  # active key
            '{"stocks": [{"code": "005930", "name": "삼성전자", "llm_score": 72}], "market_regime": "BULL", "score_threshold": 62}'
        ]
        
        watcher = OpportunityWatcher(
            config=self.mock_config,
            tasks_publisher=self.mock_publisher,
            redis_url="redis://localhost:6379/0"
        )
        
        result = watcher.load_hot_watchlist()
        
        self.assertTrue(result)
        self.assertIn("005930", watcher.hot_watchlist)
        self.assertEqual(watcher.market_regime, "BULL")
        self.assertEqual(watcher.score_threshold, 62)
        self.assertEqual(watcher.metrics['watchlist_loads'], 1)

if __name__ == '__main__':
    unittest.main()
