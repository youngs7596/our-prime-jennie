# tests/services/scout-job/test_hot_watchlist.py
# Hot Watchlist 관련 함수 유닛 테스트

"""
scout_cache.py의 Hot Watchlist 함수를 테스트합니다.

테스트 범위:
- save_hot_watchlist: Redis 저장 (버저닝/스왑)
- get_hot_watchlist: Redis 로드
- refilter_hot_watchlist_by_regime: 시장 국면 재필터링
"""

import pytest
from unittest.mock import MagicMock, patch
import sys
import os
import json

# Project root setup
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'services', 'scout-job'))


class TestSaveHotWatchlist:
    """save_hot_watchlist 테스트"""
    
    @pytest.fixture
    def mock_redis(self):
        with patch('scout_cache._get_redis') as mock_get:
            mock_r = MagicMock()
            mock_get.return_value = mock_r
            yield mock_r, mock_get
    
    def test_save_hot_watchlist_success(self, mock_redis):
        """Hot Watchlist 저장 성공"""
        from scout_cache import save_hot_watchlist
        
        mock_r, _ = mock_redis
        mock_r.get.return_value = None  # 이전 active 버전 없음
        
        stocks = [
            {'code': '005930', 'name': '삼성전자', 'llm_score': 72, 'is_tradable': True},
            {'code': '000660', 'name': 'SK하이닉스', 'llm_score': 68, 'is_tradable': True},
        ]
        
        result = save_hot_watchlist(
            stocks=stocks,
            market_regime='STRONG_BULL',
            score_threshold=58
        )
        
        assert result is True
        mock_r.set.assert_called()  # 버전 키와 active 포인터 설정
        mock_r.expire.assert_called()  # TTL 설정
    
    def test_save_hot_watchlist_no_redis(self):
        """Redis 연결 없을 때 실패"""
        with patch('scout_cache._get_redis') as mock_get:
            mock_get.return_value = None
            from scout_cache import save_hot_watchlist
            
            result = save_hot_watchlist([], 'BULL', 62)
            
            assert result is False
    
    def test_save_hot_watchlist_excludes_kospi(self, mock_redis):
        """KOSPI 지수(0001)는 제외"""
        from scout_cache import save_hot_watchlist
        
        mock_r, _ = mock_redis
        
        stocks = [
            {'code': '0001', 'name': 'KOSPI', 'llm_score': 0, 'is_tradable': False},
            {'code': '005930', 'name': '삼성전자', 'llm_score': 72, 'is_tradable': True},
        ]
        
        result = save_hot_watchlist(
            stocks=stocks,
            market_regime='BULL',
            score_threshold=62
        )
        
        assert result is True
        # set 호출 시 payload에 0001이 포함되지 않았는지 확인
        set_calls = mock_r.set.call_args_list
        # 첫 번째 set 호출이 버전 키 저장
        version_set_call = set_calls[0]
        payload_str = version_set_call[0][1]
        payload = json.loads(payload_str)
        stock_codes = [s['code'] for s in payload['stocks']]
        assert '0001' not in stock_codes
        assert '005930' in stock_codes


class TestGetHotWatchlist:
    """get_hot_watchlist 테스트"""
    
    def test_get_hot_watchlist_success(self):
        """Hot Watchlist 로드 성공"""
        with patch('scout_cache._get_redis') as mock_get:
            mock_r = MagicMock()
            mock_get.return_value = mock_r
            
            payload = {
                'stocks': [{'code': '005930', 'name': '삼성전자', 'llm_score': 72}],
                'market_regime': 'BULL',
                'score_threshold': 62
            }
            mock_r.get.side_effect = [
                'hot_watchlist:v12345',  # active key
                json.dumps(payload)
            ]
            
            from scout_cache import get_hot_watchlist
            
            result = get_hot_watchlist()
            
            assert result is not None
            assert result['market_regime'] == 'BULL'
            assert len(result['stocks']) == 1
    
    def test_get_hot_watchlist_no_active(self):
        """active 포인터 없을 때"""
        with patch('scout_cache._get_redis') as mock_get:
            mock_r = MagicMock()
            mock_get.return_value = mock_r
            mock_r.get.return_value = None  # active 포인터 없음
            
            from scout_cache import get_hot_watchlist
            
            result = get_hot_watchlist()
            
            assert result is None
    
    def test_get_hot_watchlist_no_redis(self):
        """Redis 연결 없을 때"""
        with patch('scout_cache._get_redis') as mock_get:
            mock_get.return_value = None
            from scout_cache import get_hot_watchlist
            
            result = get_hot_watchlist()
            
            assert result is None


class TestRefilterHotWatchlistByRegime:
    """refilter_hot_watchlist_by_regime 테스트"""
    
    def test_refilter_same_regime_skips(self):
        """동일 시장 국면이면 스킵"""
        with patch('scout_cache._get_redis') as mock_get, \
             patch('scout_cache.get_hot_watchlist') as mock_get_list:
            mock_r = MagicMock()
            mock_get.return_value = mock_r
            mock_get_list.return_value = {
                'stocks': [{'code': '005930', 'llm_score': 72}],
                'market_regime': 'BULL',
                'score_threshold': 62
            }
            
            from scout_cache import refilter_hot_watchlist_by_regime
            
            result = refilter_hot_watchlist_by_regime('BULL')  # 동일 국면
            
            assert result is True
    
    def test_refilter_bear_higher_threshold(self):
        """BEAR 전환 시 더 높은 threshold 적용"""
        with patch('scout_cache._get_redis') as mock_get, \
             patch('scout_cache.get_hot_watchlist') as mock_get_list, \
             patch('scout_cache.save_hot_watchlist') as mock_save:
            mock_r = MagicMock()
            mock_get.return_value = mock_r
            mock_get_list.return_value = {
                'stocks': [
                    {'code': '005930', 'llm_score': 72, 'name': '삼성전자', 'is_tradable': True},
                    {'code': '000660', 'llm_score': 65, 'name': 'SK하이닉스', 'is_tradable': True},
                ],
                'market_regime': 'BULL',
                'score_threshold': 62
            }
            mock_save.return_value = True
            
            from scout_cache import refilter_hot_watchlist_by_regime
            
            result = refilter_hot_watchlist_by_regime('BEAR')  # BEAR = 70점 기준
            
            assert result is True
            # save_hot_watchlist 호출 확인
            mock_save.assert_called_once()
            call_args = mock_save.call_args
            saved_stocks = call_args.kwargs.get('stocks') or call_args[1].get('stocks') or call_args[0][0]
            # BEAR 기준(70점) 이상인 종목만 남음 → 005930(72점)만
            assert len(saved_stocks) == 1
            assert saved_stocks[0]['code'] == '005930'
    
    def test_refilter_empty_watchlist(self):
        """빈 Hot Watchlist는 스킵"""
        with patch('scout_cache._get_redis') as mock_get, \
             patch('scout_cache.get_hot_watchlist') as mock_get_list:
            mock_r = MagicMock()
            mock_get.return_value = mock_r
            mock_get_list.return_value = None  # 빈 리스트
            
            from scout_cache import refilter_hot_watchlist_by_regime
            
            result = refilter_hot_watchlist_by_regime('BULL')
            
            assert result is True
