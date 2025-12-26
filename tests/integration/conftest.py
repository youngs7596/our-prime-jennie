import pytest
from unittest.mock import MagicMock

@pytest.fixture
def mock_kis(mocker):
    """Mock KIS Gateway Client for E2E tests"""
    mock = MagicMock()
    
    # 기본 설정
    mock.get_cash_balance.return_value = 10_000_000  # 1천만원
    mock.get_stock_snapshot.return_value = {
        'price': 70000,
        'open': 69000,
        'high': 71000,
        'low': 69000,
        'volume': 1000000
    }
    mock.place_buy_order.return_value = "BUY_12345"
    mock.place_sell_order.return_value = "SELL_67890"
    
    return mock

@pytest.fixture
def patch_session_scope(mocker, in_memory_db):
    """Patch shared.db.connection.session_scope to use in-memory DB session"""
    from contextlib import contextmanager
    
    session = in_memory_db['session']
    
    @contextmanager
    def mock_scope(readonly=False):
        yield session
    
    # Patch where session_scope is imported/used
    # Since we are dynamically importing, we need to patch the imported modules AFTER they are imported
    # or patch the shared.db.connection.session_scope globally if they import it using 'from ... import ...' pattern at module level?
    # services/buy-executor/executor.py does: from shared.db.connection import session_scope
    # So patching shared.db.connection.session_scope BEFORE importing those modules might work if they import it at runtime, 
    # BUT they import at module level.
    # So we must patch it in `shared.db.connection` module namespace, so when they import it, they get the mock? 
    # No, 'from' import binds the object. If we patch shared.db.connection.session_scope, we must do it before they import.
    
    mocker.patch('shared.db.connection.session_scope', side_effect=mock_scope)
    return session

@pytest.fixture(autouse=True)
def setup_global_db(in_memory_db):
    """
    Inject in-memory DB into shared.db.connection global state
    so that ensure_engine_initialized() and other checks pass.
    """
    import shared.db.connection as db_conn
    from sqlalchemy.orm import scoped_session
    
    # Save original state
    orig_engine = db_conn._engine
    orig_factory = db_conn._session_factory
    
    # Inject test DB
    db_conn._engine = in_memory_db['engine']
    # Wrap SessionLocal in scoped_session to match expected type (optional but safer)
    db_conn._session_factory = scoped_session(in_memory_db['SessionLocal'])
    
    yield
    
    # Restore state
    db_conn._engine = orig_engine
    db_conn._session_factory = orig_factory

@pytest.fixture(autouse=True)
def mock_redis_connection(mocker):
    """Mock Redis connection for distributed locks"""
    mock_client = mocker.MagicMock()
    # set(..., nx=True) --> True (Lock Acquired)
    mock_client.set.return_value = True
    # get(...) --> None (Cache Miss) to avoid json.loads(MagicMock) failure
    mock_client.get.return_value = None
    
    mocker.patch('shared.redis_cache.get_redis_connection', return_value=mock_client)
    return mock_client

@pytest.fixture
def BuyExecutorClass():
    import os
    import importlib.util
    import sys
    
    # Path: project_root/services/buy-executor/executor.py
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    module_path = os.path.join(base_dir, 'services', 'buy-executor', 'executor.py')
    
    spec = importlib.util.spec_from_file_location("buy_executor_dynamic", module_path)
    module = importlib.util.module_from_spec(spec)
    # We don't necessarily need to register in sys.modules unless there are circular deps or we want cache
    spec.loader.exec_module(module)
    return module.BuyExecutor

@pytest.fixture
def SellExecutorClass():
    import os
    import importlib.util
    import sys
    
    # Path: project_root/services/sell-executor/executor.py
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    module_path = os.path.join(base_dir, 'services', 'sell-executor', 'executor.py')
    
    spec = importlib.util.spec_from_file_location("sell_executor_dynamic", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SellExecutor

