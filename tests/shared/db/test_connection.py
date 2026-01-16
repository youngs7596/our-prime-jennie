"""
tests/shared/db/test_connection.py - DB 연결 모듈 Unit Tests
=============================================================

shared/db/connection.py 모듈의 Unit Test입니다.
SQLite in-memory DB와 mocking을 사용하여 실제 MariaDB 없이 테스트합니다.

실행 방법:
    pytest tests/shared/db/test_connection.py -v

커버리지 포함:
    pytest tests/shared/db/test_connection.py -v --cov=shared.db.connection --cov-report=term-missing
"""

import pytest
from unittest.mock import MagicMock, patch


class TestBuildConnectionUrl:
    """_build_connection_url 함수 테스트"""
    
    def test_build_url_from_env_vars(self, monkeypatch):
        """환경변수에서 연결 정보 읽기"""
        from shared.db import connection
        
        # Given: 환경변수 설정
        monkeypatch.setenv("MARIADB_USER", "testuser")
        monkeypatch.setenv("MARIADB_PASSWORD", "testpass")
        monkeypatch.setenv("MARIADB_HOST", "testhost")
        monkeypatch.setenv("MARIADB_PORT", "3307")
        monkeypatch.setenv("MARIADB_DBNAME", "testdb")
        
        # When: URL 생성
        url = connection._build_connection_url()
        
        # Then: 올바른 URL 형식
        assert "mysql+pymysql://" in url
        assert "testuser" in url
        assert "testhost" in url
        assert "3307" in url
        assert "testdb" in url
    
    def test_build_url_password_encoding(self, monkeypatch):
        """특수문자 포함 비밀번호 URL 인코딩"""
        from shared.db import connection
        
        # Given: 특수문자 포함 비밀번호
        monkeypatch.setenv("MARIADB_USER", "user")
        monkeypatch.setenv("MARIADB_PASSWORD", "p@ss#word!")
        monkeypatch.setenv("MARIADB_HOST", "host")
        monkeypatch.setenv("MARIADB_PORT", "3306")
        monkeypatch.setenv("MARIADB_DBNAME", "db")
        
        # When: URL 생성
        url = connection._build_connection_url()
        
        # Then: 특수문자가 인코딩됨
        assert "%40" in url  # @ encoded
        assert "%23" in url  # # encoded
    
    def test_build_url_missing_credentials_raises(self, monkeypatch, mocker):
        """필수 정보 누락 시 ValueError 발생"""
        from shared.db import connection
        
        # Given: 모든 환경변수 제거 및 secrets 반환 None
        monkeypatch.delenv("MARIADB_USER", raising=False)
        monkeypatch.delenv("MARIADB_PASSWORD", raising=False)
        monkeypatch.delenv("MARIADB_HOST", raising=False)
        monkeypatch.delenv("MARIADB_DBNAME", raising=False)
        mocker.patch.object(connection, 'get_secret', return_value=None)
        
        # When/Then: ValueError 발생
        # 실제로는 기본값이 있어서 password만 None이면 발생
        # password가 빈 문자열이 되어 all() 검사 실패
        # 기본값들이 있으므로 이 테스트는 password="" 인 경우를 테스트
        monkeypatch.setenv("MARIADB_USER", "user")
        monkeypatch.setenv("MARIADB_PASSWORD", "")  # 빈 문자열
        monkeypatch.setenv("MARIADB_HOST", "host")
        monkeypatch.setenv("MARIADB_DBNAME", "db")
        
        with pytest.raises(ValueError, match="MariaDB 접속 정보"):
            connection._build_connection_url()


class TestGetDbType:
    """_get_db_type 함수 테스트"""
    
    def test_get_db_type_returns_mariadb(self):
        """DB 타입은 항상 MARIADB"""
        from shared.db import connection
        
        result = connection._get_db_type()
        
        assert result == "MARIADB"


class TestInitEngine:
    """init_engine 함수 테스트"""
    
    def test_init_engine_returns_existing_engine(self, mocker):
        """이미 초기화된 엔진이 있으면 그대로 반환"""
        from shared.db import connection
        
        # Given: 이미 엔진이 있음
        mock_engine = mocker.MagicMock()
        connection._engine = mock_engine
        
        try:
            # When: init_engine 호출
            result = connection.init_engine()
            
            # Then: 기존 엔진 반환
            assert result is mock_engine
        finally:
            # Cleanup
            connection._engine = None
    
    def test_init_engine_with_pool_settings(self, mocker, monkeypatch):
        """연결 풀 설정으로 엔진 초기화"""
        from shared.db import connection
        from sqlalchemy.exc import SQLAlchemyError
        
        # Given: 환경변수 설정
        monkeypatch.setenv("MARIADB_USER", "user")
        monkeypatch.setenv("MARIADB_PASSWORD", "pass")
        monkeypatch.setenv("MARIADB_HOST", "localhost")
        monkeypatch.setenv("MARIADB_PORT", "3306")
        monkeypatch.setenv("MARIADB_DBNAME", "testdb")
        
        # Mock create_engine
        mock_engine = mocker.MagicMock()
        mocker.patch('shared.db.connection.create_engine', return_value=mock_engine)
        mocker.patch('shared.db.connection.scoped_session')
        mocker.patch('shared.db.connection.sessionmaker')
        
        connection._engine = None
        connection._session_factory = None
        
        try:
            # When: init_engine 호출
            result = connection.init_engine(min_sessions=3, max_sessions=15)
            
            # Then: 엔진 생성됨
            assert result is mock_engine
            assert connection._engine is mock_engine
        finally:
            connection.dispose_engine()
    
    def test_init_engine_sqlalchemy_error(self, mocker, monkeypatch):
        """SQLAlchemy 에러 발생 시 예외 전파"""
        from shared.db import connection
        from sqlalchemy.exc import SQLAlchemyError
        
        # Given: 환경변수 설정
        monkeypatch.setenv("MARIADB_USER", "user")
        monkeypatch.setenv("MARIADB_PASSWORD", "pass")
        monkeypatch.setenv("MARIADB_HOST", "localhost")
        monkeypatch.setenv("MARIADB_PORT", "3306")
        monkeypatch.setenv("MARIADB_DBNAME", "testdb")
        
        # Mock create_engine to raise error
        mocker.patch(
            'shared.db.connection.create_engine',
            side_effect=SQLAlchemyError("Connection failed")
        )
        
        connection._engine = None
        connection._session_factory = None
        
        try:
            # When/Then: 예외 발생
            with pytest.raises(SQLAlchemyError):
                connection.init_engine()
            
            # 엔진은 None으로 리셋됨
            assert connection._engine is None
            assert connection._session_factory is None
        finally:
            connection.dispose_engine()


class TestEnsureEngineInitialized:
    """ensure_engine_initialized 함수 테스트"""
    
    def test_ensure_returns_existing_engine(self, mocker):
        """이미 초기화된 엔진이 있으면 그대로 반환"""
        from shared.db import connection
        
        # Given: 이미 엔진이 있음
        mock_engine = mocker.MagicMock()
        connection._engine = mock_engine
        
        try:
            # When: ensure_engine_initialized 호출
            result = connection.ensure_engine_initialized()
            
            # Then: 기존 엔진 반환
            assert result is mock_engine
        finally:
            connection._engine = None
    
    def test_ensure_initializes_new_engine(self, mocker, monkeypatch):
        """엔진이 없으면 새로 초기화"""
        from shared.db import connection
        
        # Given: 환경변수 설정
        monkeypatch.setenv("MARIADB_USER", "user")
        monkeypatch.setenv("MARIADB_PASSWORD", "pass")
        monkeypatch.setenv("MARIADB_HOST", "localhost")
        monkeypatch.setenv("MARIADB_PORT", "3306")
        monkeypatch.setenv("MARIADB_DBNAME", "testdb")
        
        mock_engine = mocker.MagicMock()
        mocker.patch('shared.db.connection.create_engine', return_value=mock_engine)
        mocker.patch('shared.db.connection.scoped_session')
        mocker.patch('shared.db.connection.sessionmaker')
        
        connection._engine = None
        connection._session_factory = None
        
        try:
            # When: ensure_engine_initialized 호출
            result = connection.ensure_engine_initialized()
            
            # Then: 새 엔진 생성됨
            assert result is mock_engine
        finally:
            connection.dispose_engine()
    
    def test_ensure_returns_none_on_error(self, mocker, monkeypatch):
        """초기화 실패 시 None 반환 (예외 발생 안함)"""
        from shared.db import connection
        
        # Given: 환경변수 설정
        monkeypatch.setenv("MARIADB_USER", "user")
        monkeypatch.setenv("MARIADB_PASSWORD", "pass")
        monkeypatch.setenv("MARIADB_HOST", "localhost")
        monkeypatch.setenv("MARIADB_PORT", "3306")
        monkeypatch.setenv("MARIADB_DBNAME", "testdb")
        
        # Mock init_engine to raise error
        mocker.patch(
            'shared.db.connection.init_engine',
            side_effect=Exception("Connection failed")
        )
        
        connection._engine = None
        
        try:
            # When: ensure_engine_initialized 호출
            result = connection.ensure_engine_initialized()
            
            # Then: None 반환 (예외 전파 안됨)
            assert result is None
        finally:
            connection.dispose_engine()


class TestIsEngineInitialized:
    """is_engine_initialized 함수 테스트"""
    
    def test_returns_false_when_not_initialized(self):
        """엔진 미초기화 시 False"""
        from shared.db import connection
        
        connection._engine = None
        
        assert connection.is_engine_initialized() is False
    
    def test_returns_true_when_initialized(self, mocker):
        """엔진 초기화 시 True"""
        from shared.db import connection
        
        mock_engine = mocker.MagicMock()
        connection._engine = mock_engine
        
        try:
            assert connection.is_engine_initialized() is True
        finally:
            connection._engine = None


class TestGetEngine:
    """get_engine 함수 테스트"""
    
    def test_raises_when_not_initialized(self):
        """엔진 미초기화 시 RuntimeError"""
        from shared.db import connection
        
        connection._engine = None
        
        with pytest.raises(RuntimeError, match="SQLAlchemy 엔진이 초기화되지 않았습니다"):
            connection.get_engine()
    
    def test_returns_engine_when_initialized(self, mocker):
        """엔진 초기화 시 엔진 반환"""
        from shared.db import connection
        
        mock_engine = mocker.MagicMock()
        connection._engine = mock_engine
        
        try:
            result = connection.get_engine()
            assert result is mock_engine
        finally:
            connection._engine = None


class TestGetSession:
    """get_session 함수 테스트"""
    
    def test_raises_when_factory_not_initialized(self):
        """세션 팩토리 미초기화 시 RuntimeError"""
        from shared.db import connection
        
        connection._session_factory = None
        
        with pytest.raises(RuntimeError, match="SQLAlchemy 세션 팩토리가 초기화되지 않았습니다"):
            connection.get_session()
    
    def test_returns_session_when_initialized(self, mocker):
        """세션 팩토리 초기화 시 세션 반환"""
        from shared.db import connection
        
        mock_session = mocker.MagicMock()
        mock_factory = mocker.MagicMock(return_value=mock_session)
        connection._session_factory = mock_factory
        
        try:
            result = connection.get_session()
            assert result is mock_session
            mock_factory.assert_called_once()
        finally:
            connection._session_factory = None


class TestSessionScope:
    """session_scope 컨텍스트 매니저 테스트"""
    
    def test_session_scope_commit_on_success(self, mocker):
        """정상 종료 시 commit"""
        from shared.db import connection
        
        mock_session = mocker.MagicMock()
        mock_factory = mocker.MagicMock(return_value=mock_session)
        connection._session_factory = mock_factory
        
        try:
            with connection.session_scope() as session:
                assert session is mock_session
            
            # commit 호출됨
            mock_session.commit.assert_called_once()
            mock_session.close.assert_called_once()
        finally:
            connection._session_factory = None
    
    def test_session_scope_rollback_on_readonly(self, mocker):
        """readonly=True 시 rollback"""
        from shared.db import connection
        
        mock_session = mocker.MagicMock()
        mock_factory = mocker.MagicMock(return_value=mock_session)
        connection._session_factory = mock_factory
        
        try:
            with connection.session_scope(readonly=True) as session:
                pass
            
            # rollback 호출됨 (commit 아님)
            mock_session.rollback.assert_called_once()
            mock_session.commit.assert_not_called()
            mock_session.close.assert_called_once()
        finally:
            connection._session_factory = None
    
    def test_session_scope_rollback_on_exception(self, mocker):
        """예외 발생 시 rollback"""
        from shared.db import connection
        
        mock_session = mocker.MagicMock()
        mock_factory = mocker.MagicMock(return_value=mock_session)
        connection._session_factory = mock_factory
        
        try:
            with pytest.raises(ValueError):
                with connection.session_scope() as session:
                    raise ValueError("Test error")
            
            # rollback 호출됨
            mock_session.rollback.assert_called_once()
            mock_session.close.assert_called_once()
        finally:
            connection._session_factory = None


class TestDisposeEngine:
    """dispose_engine 함수 테스트"""
    
    def test_dispose_cleans_up_all(self, mocker):
        """모든 리소스 정리"""
        from shared.db import connection
        
        mock_engine = mocker.MagicMock()
        mock_factory = mocker.MagicMock()
        
        connection._engine = mock_engine
        connection._session_factory = mock_factory
        connection._engine_config = {"test": "config"}
        
        # When: dispose_engine 호출
        connection.dispose_engine()
        
        # Then: 모두 정리됨
        mock_factory.remove.assert_called_once()
        mock_engine.dispose.assert_called_once()
        assert connection._engine is None
        assert connection._session_factory is None
        assert connection._engine_config == {}
    
    def test_dispose_handles_none_values(self):
        """None 값도 안전하게 처리"""
        from shared.db import connection
        
        connection._engine = None
        connection._session_factory = None
        connection._engine_config = {}
        
        # When: dispose_engine 호출 (예외 없이 수행)
        connection.dispose_engine()
        
        # Then: 여전히 None
        assert connection._engine is None
        assert connection._session_factory is None
