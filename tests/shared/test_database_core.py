"""
tests/shared/test_database_core.py

Database Core 유틸리티 테스트 - Helpers, Connection, Config
"""
import os
import pytest
from unittest.mock import patch, MagicMock

# 모듈 경로에 유의하며 import
from shared.database import core


class TestDatabaseHelpers:
    """DB Helper 함수 테스트"""

    def test_is_mariadb(self):
        """_is_mariadb()는 항상 True를 반환해야 함"""
        assert core._is_mariadb() is True

    def test_get_param_placeholder(self):
        """_get_param_placeholder()는 항상 '%s'를 반환해야 함"""
        assert core._get_param_placeholder(1) == "%s"
        assert core._get_param_placeholder(99) == "%s"

    def test_get_table_name_mock(self):
        """MOCK 모드일 때 특정 테이블은 _mock 접미사가 붙어야 함"""
        with patch.dict(os.environ, {"TRADING_MODE": "MOCK"}, clear=False):
            # Target tables
            assert core._get_table_name("Portfolio") == "Portfolio_mock"
            assert core._get_table_name("TradeLog") == "TradeLog_mock"
            assert core._get_table_name("NEWS_SENTIMENT") == "NEWS_SENTIMENT_mock"
            
            # Non-target tables
            assert core._get_table_name("WatchList") == "WatchList"
            assert core._get_table_name("STOCK_DAILY_PRICES_3Y") == "STOCK_DAILY_PRICES_3Y"

    def test_get_table_name_real(self):
        """REAL 모드일 때는 모든 테이블 이름이 그대로여야 함"""
        with patch.dict(os.environ, {"TRADING_MODE": "REAL"}, clear=False):
            assert core._get_table_name("Portfolio") == "Portfolio"
            assert core._get_table_name("TradeLog") == "TradeLog"
            assert core._get_table_name("NEWS_SENTIMENT") == "NEWS_SENTIMENT"


class TestConnectionPool:
    """DB 연결 풀 관리 테스트"""

    @patch('shared.database.core.sa_connection.ensure_engine_initialized')
    @patch('shared.database.core.sa_connection.get_engine')
    def test_init_connection_pool(self, mock_get_engine, mock_ensure_init):
        """연결 풀 초기화 테스트"""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        
        with patch.dict(os.environ, {"DB_POOL_MIN": "10", "DB_POOL_MAX": "20"}):
            pool = core.init_connection_pool(min_sessions=5, max_sessions=10)
            
            assert pool == mock_engine
            # 전역변수 pool 업데이트 확인
            assert core.pool == mock_engine
            
            mock_ensure_init.assert_called_once_with(min_sessions=10, max_sessions=20)

    @patch('shared.database.core.sa_connection.dispose_engine')
    def test_close_pool(self, mock_dispose):
        """연결 풀 종료 테스트"""
        # Setup initial state
        core.pool = MagicMock()
        
        core.close_pool()
        
        assert core.pool is None
        mock_dispose.assert_called_once()

    @patch('shared.database.core.init_connection_pool')
    def test_get_db_connection_init(self, mock_init_pool):
        """get_db_connection 호출 시 pool이 없으면 초기화해야 함"""
        core.pool = None  # Reset pool
        mock_engine = MagicMock()
        mock_init_pool.return_value = mock_engine
        
        # Simulate init_connection_pool setting core.pool (as it does in real code)
        def side_effect(**kwargs):
            core.pool = mock_engine
            return mock_engine
        mock_init_pool.side_effect = side_effect
        
        conn = core.get_db_connection()
        
        mock_init_pool.assert_called_once()
        mock_engine.raw_connection.assert_called_once()


class TestConfigFunctions:
    """Config 테이블 관리 함수 테스트"""

    @patch('shared.database.core.get_session')
    @patch('shared.database.core.sa_repository.get_config')
    def test_get_config(self, mock_repo_get, mock_get_session):
        """설정값 조회 테스트"""
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__.return_value = mock_session
        
        mock_repo_get.return_value = "configured_value"
        
        result = core.get_config(None, "TEST_KEY")
        
        assert result == "configured_value"
        mock_repo_get.assert_called_once_with(mock_session, "TEST_KEY", False)

    @patch('shared.database.core.get_session')
    def test_get_all_config(self, mock_get_session):
        """모든 설정값 조회 테스트"""
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__.return_value = mock_session
        
        # Mock Config objects
        config1 = MagicMock()
        config1.config_key = "KEY1"
        config1.config_value = "VAL1"
        
        config2 = MagicMock()
        config2.config_key = "KEY2"
        config2.config_value = "VAL2"
        
        mock_session.query.return_value.all.return_value = [config1, config2]
        
        # shared.db.models.Config import를 mock 해야 함 (함수 내부 import)
        with patch.dict('sys.modules', {'shared.db.models': MagicMock()}):
            result = core.get_all_config(None)
            
            assert result == {"KEY1": "VAL1", "KEY2": "VAL2"}

    @patch('shared.database.core.get_session')
    @patch('shared.database.core.sa_repository.set_config')
    def test_set_config(self, mock_repo_set, mock_get_session):
        """설정값 저장 테스트"""
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__.return_value = mock_session
        
        mock_repo_set.return_value = True
        
        result = core.set_config(None, "NEW_KEY", "NEW_VAL")
        
        assert result is True
        mock_repo_set.assert_called_once_with(mock_session, "NEW_KEY", "NEW_VAL")

    @patch('shared.database.core.get_session')
    def test_get_config_exception(self, mock_get_session):
        """설정값 조회 예외 발생 테스트"""
        mock_get_session.side_effect = Exception("DB Error")
        result = core.get_config(None, "KEY")
        assert result is None

    @patch('shared.database.core.get_session')
    def test_get_all_config_exception(self, mock_get_session):
        """모든 설정값 조회 예외 발생 테스트"""
        mock_get_session.side_effect = Exception("DB Error")
        result = core.get_all_config(None)
        assert result == {}

    @patch('shared.database.core.get_session')
    def test_set_config_exception(self, mock_get_session):
        """설정값 저장 예외 발생 테스트"""
        mock_get_session.side_effect = Exception("DB Error")
        result = core.set_config(None, "KEY", "VAL")
        assert result is False


class TestAdditionalUtils:
    """추가 유틸리티 함수 테스트"""
    
    @patch('shared.database.core.sa_connection.is_engine_initialized')
    def test_is_sqlalchemy_ready(self, mock_is_init):
        """SQLAlchemy 준비 상태 테스트"""
        mock_is_init.return_value = True
        assert core._is_sqlalchemy_ready() is True
        
        mock_is_init.side_effect = Exception("Error")
        assert core._is_sqlalchemy_ready() is False

    def test_is_pool_initialized(self):
        """연결 풀 초기화 여부 테스트"""
        core.pool = MagicMock()
        assert core.is_pool_initialized() is True
        
        core.pool = None
        assert core.is_pool_initialized() is False

