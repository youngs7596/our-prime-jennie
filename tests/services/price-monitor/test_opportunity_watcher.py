# tests/services/price-monitor/test_opportunity_watcher.py
# OpportunityWatcher 유닛 테스트

"""
OpportunityWatcher 클래스의 핵심 기능을 테스트합니다.

테스트 범위:
- BarAggregator: 틱 → 1분 캔들 집계
- OpportunityWatcher: Hot Watchlist 로드, 매수 신호 감지
- Cooldown 로직
- 관측성 메트릭
"""

import pytest
from unittest.mock import MagicMock, patch
import sys
import os
from datetime import datetime, timezone, timedelta

# Project root setup
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'services', 'price-monitor'))

from opportunity_watcher import BarAggregator, OpportunityWatcher


class TestBarAggregator:
    """BarAggregator 테스트"""
    
    def test_first_tick_creates_new_bar(self):
        """첫 틱이 새 캔들을 생성"""
        aggregator = BarAggregator(bar_interval_seconds=60)
        result = aggregator.update("005930", 50000.0, volume=100)
        
        # 첫 틱은 None 반환 (캔들 미완료)
        assert result is None
        assert "005930" in aggregator.current_bars
        bar = aggregator.current_bars["005930"]
        assert bar['open'] == 50000.0
        assert bar['high'] == 50000.0
        assert bar['low'] == 50000.0
        assert bar['close'] == 50000.0
        assert bar['tick_count'] == 1
    
    def test_tick_updates_ohlcv(self):
        """틱이 OHLCV 업데이트"""
        aggregator = BarAggregator(bar_interval_seconds=60)
        aggregator.update("005930", 50000.0)
        aggregator.update("005930", 50500.0)  # High
        aggregator.update("005930", 49500.0)  # Low
        aggregator.update("005930", 50200.0)  # Close
        
        bar = aggregator.current_bars["005930"]
        assert bar['open'] == 50000.0
        assert bar['high'] == 50500.0
        assert bar['low'] == 49500.0
        assert bar['close'] == 50200.0
        assert bar['tick_count'] == 4
    
    def test_get_recent_bars(self):
        """최근 캔들 조회"""
        aggregator = BarAggregator(bar_interval_seconds=60)
        
        # 완료된 캔들이 없으면 빈 리스트
        recent = aggregator.get_recent_bars("005930", count=5)
        assert recent == []
        
        # 수동으로 완료된 캔들 추가 (테스트용)
        aggregator.completed_bars["005930"] = [
            {'close': 50000}, {'close': 50100}, {'close': 50200}
        ]
        
        recent = aggregator.get_recent_bars("005930", count=2)
        assert len(recent) == 2
        assert recent[-1]['close'] == 50200


class TestOpportunityWatcher:
    """OpportunityWatcher 테스트"""
    
    @pytest.fixture
    def mock_config(self):
        config = MagicMock()
        config.get_bool.return_value = False
        config.get_int.return_value = 60
        config.get_float.return_value = 0.0
        return config
    
    @pytest.fixture
    def mock_publisher(self):
        publisher = MagicMock()
        publisher.publish.return_value = "msg-123"
        return publisher
    
    @pytest.fixture
    def watcher(self, mock_config, mock_publisher):
        """OpportunityWatcher 인스턴스"""
        with patch('opportunity_watcher.redis.from_url') as mock_redis:
            mock_redis.return_value = MagicMock()
            mock_redis.return_value.ping.return_value = True
            
            watcher = OpportunityWatcher(
                config=mock_config,
                tasks_publisher=mock_publisher,
                redis_url="redis://localhost:6379/0"
            )
            return watcher
    
    def test_init_metrics(self, watcher):
        """초기화 시 메트릭 딕셔너리 생성"""
        assert 'tick_count' in watcher.metrics
        assert 'bar_count' in watcher.metrics
        assert 'signal_count' in watcher.metrics
        assert watcher.metrics['tick_count'] == 0
    
    def test_on_price_update_not_in_watchlist(self, watcher):
        """Hot Watchlist에 없는 종목은 무시"""
        watcher.hot_watchlist = {}
        
        result = watcher.on_price_update("005930", 50000.0)
        
        assert result is None
        assert watcher.metrics['tick_count'] == 1
    
    def test_on_price_update_in_watchlist(self, watcher):
        """Hot Watchlist에 있는 종목은 처리"""
        watcher.hot_watchlist = {
            "005930": {"name": "삼성전자", "llm_score": 72}
        }
        
        result = watcher.on_price_update("005930", 50000.0)
        
        # 첫 틱이라 캔들 미완료 → None
        assert result is None
        assert watcher.metrics['tick_count'] == 1
    
    def test_calculate_simple_rsi(self, watcher):
        """RSI 계산 테스트"""
        # 상승 추세
        prices = [100, 102, 104, 106, 108, 110, 112, 114, 116, 118, 
                  120, 122, 124, 126, 128, 130]
        rsi = watcher._calculate_simple_rsi(prices, period=14)
        
        assert rsi is not None
        assert rsi > 50  # 상승 추세라 RSI > 50
    
    def test_calculate_simple_rsi_insufficient_data(self, watcher):
        """데이터 부족 시 RSI None"""
        prices = [100, 101, 102]
        rsi = watcher._calculate_simple_rsi(prices, period=14)
        
        assert rsi is None
    
    def test_get_metrics(self, watcher):
        """메트릭 조회"""
        watcher.hot_watchlist = {"005930": {}}
        watcher.market_regime = "BULL"
        watcher.metrics['tick_count'] = 100
        
        metrics = watcher.get_metrics()
        
        assert metrics['tick_count'] == 100
        assert metrics['hot_watchlist_size'] == 1
        assert metrics['market_regime'] == "BULL"
    
    def test_publish_signal(self, watcher, mock_publisher):
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
        
        result = watcher.publish_signal(signal)
        
        assert result is True
        mock_publisher.publish.assert_called_once()
        assert watcher.metrics['signal_count'] == 1
        assert watcher.metrics['last_signal_time'] is not None
    
    def test_publish_signal_no_publisher(self, mock_config):
        """Publisher 없을 때"""
        with patch('opportunity_watcher.redis.from_url'):
            watcher = OpportunityWatcher(
                config=mock_config,
                tasks_publisher=None,
                redis_url="redis://localhost:6379/0"
            )
            
            result = watcher.publish_signal({})
            assert result is False


class TestCooldown:
    """Cooldown 로직 테스트"""
    
    @pytest.fixture
    def watcher_with_redis(self):
        mock_config = MagicMock()
        mock_publisher = MagicMock()
        
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.exists.return_value = False
        
        with patch('opportunity_watcher.redis.from_url') as mock_from_url:
            mock_from_url.return_value = mock_redis
            
            watcher = OpportunityWatcher(
                config=mock_config,
                tasks_publisher=mock_publisher,
                redis_url="redis://localhost:6379/0"
            )
            watcher._mock_redis = mock_redis
            return watcher
    
    def test_check_cooldown_no_exists(self, watcher_with_redis):
        """Cooldown 키 없으면 True (발행 가능)"""
        watcher_with_redis._mock_redis.exists.return_value = False
        
        result = watcher_with_redis._check_cooldown("005930")
        
        assert result is True
    
    def test_check_cooldown_exists(self, watcher_with_redis):
        """Cooldown 키 있으면 False (발행 불가)"""
        watcher_with_redis._mock_redis.exists.return_value = True
        
        result = watcher_with_redis._check_cooldown("005930")
        
        assert result is False
        assert watcher_with_redis.metrics['cooldown_blocked'] == 1
    
    def test_set_cooldown(self, watcher_with_redis):
        """Cooldown 설정"""
        watcher_with_redis._set_cooldown("005930")
        
        watcher_with_redis._mock_redis.setex.assert_called_once()
        call_args = watcher_with_redis._mock_redis.setex.call_args
        assert call_args[0][0] == "buy_signal_cooldown:005930"
        assert call_args[0][1] == 180  # cooldown_seconds


class TestHotWatchlistLoad:
    """Hot Watchlist 로드 테스트"""
    
    def test_load_hot_watchlist_success(self):
        """Hot Watchlist 로드 성공"""
        mock_config = MagicMock()
        mock_publisher = MagicMock()
        
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.side_effect = [
            "hot_watchlist:v12345",  # active key
            '{"stocks": [{"code": "005930", "name": "삼성전자", "llm_score": 72}], "market_regime": "BULL", "score_threshold": 62}'
        ]
        
        with patch('opportunity_watcher.redis.from_url') as mock_from_url:
            mock_from_url.return_value = mock_redis
            
            watcher = OpportunityWatcher(
                config=mock_config,
                tasks_publisher=mock_publisher,
                redis_url="redis://localhost:6379/0"
            )
            
            result = watcher.load_hot_watchlist()
            
            assert result is True
            assert "005930" in watcher.hot_watchlist
            assert watcher.market_regime == "BULL"
            assert watcher.score_threshold == 62
            assert watcher.metrics['watchlist_loads'] == 1
