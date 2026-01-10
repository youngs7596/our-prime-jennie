"""
tests/integration/test_websocket_buy_flow.py
WebSocket 기반 매수 흐름 E2E 테스트

테스트 흐름:
1. Redis에 Hot Watchlist 설정
2. BuyOpportunityWatcher 초기화
3. Mock WebSocket 서버 연결
4. 가격 업데이트 수신 및 매수 신호 감지
5. RabbitMQ 발행 확인
"""

import pytest
import os
import sys
import json
import time
import threading
from unittest.mock import MagicMock, patch

# Project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)

# Buy-scanner 모듈 동적 로드
import importlib.util


def load_module(name, path):
    """동적 모듈 로드 (hyphenated directory 대응)"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class TestWebSocketBuyFlow:
    """WebSocket 기반 매수 흐름 E2E 테스트"""
    
    @pytest.fixture
    def mock_redis(self):
        """Mock Redis 클라이언트"""
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.exists.return_value = False  # cooldown 없음
        mock_redis.get.side_effect = self._redis_get_side_effect
        mock_redis.setex.return_value = True
        return mock_redis
    
    def _redis_get_side_effect(self, key):
        """Redis GET 응답 모킹"""
        if key == "hot_watchlist:active":
            return "hot_watchlist:v_test"
        elif key == "hot_watchlist:v_test":
            return json.dumps({
                "stocks": [
                    {"code": "005930", "name": "삼성전자", "llm_score": 75, "hunter_params": {}},
                    {"code": "000660", "name": "SK하이닉스", "llm_score": 70, "hunter_params": {}}
                ],
                "market_regime": "BULL",
                "score_threshold": 60
            })
        return None
    
    @pytest.fixture
    def mock_publisher(self):
        """Mock RabbitMQ Publisher"""
        publisher = MagicMock()
        publisher.publish.return_value = "msg-12345"
        return publisher
    
    @pytest.fixture
    def mock_config(self):
        """Mock ConfigManager"""
        config = MagicMock()
        config.get_bool.return_value = False
        config.get_int.return_value = 60
        config.get_float.return_value = 0.0
        return config
    
    def test_opportunity_watcher_initialization(self, mock_redis, mock_publisher, mock_config):
        """BuyOpportunityWatcher 초기화 테스트"""
        # 모듈 로드
        opportunity_watcher_mod = load_module(
            "opportunity_watcher",
            os.path.join(PROJECT_ROOT, "services/buy-scanner/opportunity_watcher.py")
        )
        BuyOpportunityWatcher = opportunity_watcher_mod.BuyOpportunityWatcher
        
        with patch('opportunity_watcher.redis.from_url', return_value=mock_redis):
            watcher = BuyOpportunityWatcher(
                config=mock_config,
                tasks_publisher=mock_publisher,
                redis_url="redis://localhost:6379/0"
            )
            
            # 초기화 확인
            assert watcher is not None
            assert watcher.tasks_publisher == mock_publisher
            
            # Hot Watchlist 로드
            result = watcher.load_hot_watchlist()
            assert result is True
            assert "005930" in watcher.hot_watchlist
            assert watcher.market_regime == "BULL"
    
    def test_price_update_triggers_signal_check(self, mock_redis, mock_publisher, mock_config):
        """가격 업데이트 시 신호 체크 테스트"""
        opportunity_watcher_mod = load_module(
            "opportunity_watcher",
            os.path.join(PROJECT_ROOT, "services/buy-scanner/opportunity_watcher.py")
        )
        BuyOpportunityWatcher = opportunity_watcher_mod.BuyOpportunityWatcher
        
        with patch('opportunity_watcher.redis.from_url', return_value=mock_redis):
            watcher = BuyOpportunityWatcher(
                config=mock_config,
                tasks_publisher=mock_publisher,
                redis_url="redis://localhost:6379/0"
            )
            watcher.load_hot_watchlist()
            
            # 가격 업데이트 전송
            result = watcher.on_price_update("005930", 70000.0, volume=10000)
            
            # 첫 틱은 캔들 미완료로 None
            assert result is None
            assert watcher.metrics['tick_count'] == 1
    
    def test_signal_publication(self, mock_redis, mock_publisher, mock_config):
        """매수 신호 발행 테스트"""
        opportunity_watcher_mod = load_module(
            "opportunity_watcher",
            os.path.join(PROJECT_ROOT, "services/buy-scanner/opportunity_watcher.py")
        )
        BuyOpportunityWatcher = opportunity_watcher_mod.BuyOpportunityWatcher
        
        with patch('opportunity_watcher.redis.from_url', return_value=mock_redis):
            watcher = BuyOpportunityWatcher(
                config=mock_config,
                tasks_publisher=mock_publisher,
                redis_url="redis://localhost:6379/0"
            )
            
            # 매수 신호 발행
            signal = {
                'stock_code': '005930',
                'stock_name': '삼성전자',
                'signal_type': 'GOLDEN_CROSS',
                'signal_reason': 'Test signal',
                'current_price': 70000,
                'llm_score': 75,
                'market_regime': 'BULL',
                'timestamp': '2026-01-09T12:00:00+00:00'
            }
            
            result = watcher.publish_signal(signal)
            
            assert result is True
            mock_publisher.publish.assert_called_once()
            assert watcher.metrics['signal_count'] == 1


class TestMockWebSocketConnection:
    """Mock WebSocket 서버 연결 테스트 (선택적 - 서버 실행 필요)"""
    
    @pytest.mark.skip(reason="Mock WebSocket 서버가 실행 중일 때만 테스트")
    def test_websocket_connection(self):
        """SocketIO 연결 테스트"""
        import socketio
        
        sio = socketio.Client()
        connected = threading.Event()
        price_updates = []
        
        @sio.on('connected')
        def on_connected(data):
            print(f"연결 성공: {data}")
            connected.set()
        
        @sio.on('price_update')
        def on_price_update(data):
            price_updates.append(data)
            print(f"가격 업데이트: {data}")
        
        try:
            sio.connect('http://localhost:9443', wait_timeout=10)
            assert connected.wait(timeout=5), "연결 타임아웃"
            
            # 종목 구독
            sio.emit('subscribe', {'codes': ['005930', '000660']})
            
            # 가격 업데이트 대기 (10초)
            time.sleep(10)
            
            assert len(price_updates) > 0, "가격 업데이트 수신 실패"
            
        finally:
            sio.disconnect()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
