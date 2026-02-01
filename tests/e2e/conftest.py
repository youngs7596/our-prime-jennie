# tests/e2e/conftest.py
"""
E2E Test Configuration and Fixtures

This module provides pytest fixtures for end-to-end testing
of the trading system with mock infrastructure.
"""

import os
import sys
import pytest
import time
import json
import logging
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.e2e.mock_server.kis_mock_server import KISMockServer, MockKISClient
from tests.e2e.mock_server.scenarios import Scenario, ScenarioManager, ResponseMode
from tests.e2e.fixtures.redis_fixtures import StreamsEnabledFakeRedis, PriceStreamSimulator
from tests.e2e.fixtures.rabbitmq_fixtures import (
    MockRabbitMQPublisher,
    MockRabbitMQConsumer,
    RabbitMQTestBridge,
    QueueNames
)

logger = logging.getLogger(__name__)


# ============================================================================
# Server Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def mock_kis_server():
    """
    Session-scoped Mock KIS Gateway server.

    Starts a Flask server in a background thread that simulates
    the KIS Gateway API.
    """
    # Use a random port to avoid conflicts
    import random
    port = random.randint(18000, 19000)

    server = KISMockServer(host="127.0.0.1", port=port)
    server.start(threaded=True)

    # Activate default scenario
    server.activate_scenario("empty_portfolio")

    yield server

    server.stop()


@pytest.fixture
def kis_server(mock_kis_server):
    """
    Function-scoped KIS server that resets state between tests.

    Uses the session-scoped server but resets its state.
    """
    mock_kis_server.clear_history()
    mock_kis_server.scenario_manager.reset_current()
    mock_kis_server.activate_scenario("empty_portfolio")

    yield mock_kis_server


@pytest.fixture
def mock_kis_client(kis_server) -> MockKISClient:
    """
    Mock KIS client connected to the mock server.

    Provides the same interface as the real KIS client.
    """
    return MockKISClient(kis_server)


# ============================================================================
# Redis Fixtures
# ============================================================================

@pytest.fixture
def e2e_redis():
    """
    FakeRedis with Streams support for E2E tests.
    """
    redis = StreamsEnabledFakeRedis(decode_responses=True)
    yield redis
    redis.flushall()


@pytest.fixture
def price_simulator(e2e_redis):
    """
    Price stream simulator for injecting price data.
    """
    simulator = PriceStreamSimulator(e2e_redis, stream_key="kis:prices")
    yield simulator
    simulator.clear()


@pytest.fixture
def mock_redis_connection(mocker, e2e_redis):
    """
    Patch shared.redis_cache to use the E2E fake redis.
    """
    mocker.patch('shared.redis_cache.get_redis_connection', return_value=e2e_redis)
    mocker.patch('shared.redis_cache.reset_redis_connection', return_value=None)

    # Mock specific redis functions
    mocker.patch('shared.redis_cache.is_trading_stopped', return_value=False)
    mocker.patch('shared.redis_cache.is_trading_paused', return_value=False)
    mocker.patch('shared.redis_cache.delete_high_watermark', return_value=None)
    mocker.patch('shared.redis_cache.delete_scale_out_level', return_value=None)
    mocker.patch('shared.redis_cache.delete_profit_floor', return_value=None)

    # Clear any existing keys to avoid lock conflicts
    e2e_redis.flushall()

    return e2e_redis


# ============================================================================
# RabbitMQ Fixtures
# ============================================================================

@pytest.fixture
def mq_bridge():
    """
    RabbitMQ test bridge for message queue testing.
    """
    bridge = RabbitMQTestBridge()

    # Create standard queues
    bridge.create_publisher(QueueNames.BUY_SIGNALS)
    bridge.create_consumer(QueueNames.BUY_SIGNALS)
    bridge.create_publisher(QueueNames.SELL_ORDERS)
    bridge.create_consumer(QueueNames.SELL_ORDERS)

    yield bridge

    bridge.reset()


@pytest.fixture
def buy_signals_publisher(mq_bridge) -> MockRabbitMQPublisher:
    """Publisher for buy signals queue"""
    return mq_bridge.get_publisher(QueueNames.BUY_SIGNALS)


@pytest.fixture
def sell_orders_publisher(mq_bridge) -> MockRabbitMQPublisher:
    """Publisher for sell orders queue"""
    return mq_bridge.get_publisher(QueueNames.SELL_ORDERS)


# ============================================================================
# Database Fixtures
# ============================================================================

@pytest.fixture(scope="function")
def e2e_db():
    """
    In-memory SQLite database for E2E tests.

    Creates all required tables and provides session access.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from shared.db.models import Base

    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        future=True
    )

    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()

    yield {
        "engine": engine,
        "session": session,
        "SessionLocal": SessionLocal
    }

    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def setup_e2e_db(e2e_db, mocker):
    """
    Auto-use fixture that patches DB connection for E2E tests.
    """
    from contextlib import contextmanager
    import shared.db.connection as db_conn

    session = e2e_db['session']

    @contextmanager
    def mock_session_scope(readonly=False):
        try:
            yield session
            if not readonly:
                session.commit()
        except Exception:
            session.rollback()
            raise

    mocker.patch('shared.db.connection.session_scope', side_effect=mock_session_scope)

    # Patch engine state
    orig_engine = db_conn._engine
    orig_factory = db_conn._session_factory
    db_conn._engine = e2e_db['engine']

    from sqlalchemy.orm import scoped_session
    db_conn._session_factory = scoped_session(e2e_db['SessionLocal'])

    yield

    db_conn._engine = orig_engine
    db_conn._session_factory = orig_factory


# ============================================================================
# Executor Fixtures
# ============================================================================

@pytest.fixture
def buy_executor_class():
    """
    Dynamically load BuyExecutor class.
    """
    import importlib.util

    module_path = os.path.join(PROJECT_ROOT, 'services', 'buy-executor', 'executor.py')
    spec = importlib.util.spec_from_file_location("buy_executor_dynamic", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BuyExecutor


@pytest.fixture
def sell_executor_class():
    """
    Dynamically load SellExecutor class.
    """
    import importlib.util

    module_path = os.path.join(PROJECT_ROOT, 'services', 'sell-executor', 'executor.py')
    spec = importlib.util.spec_from_file_location("sell_executor_dynamic", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SellExecutor


@pytest.fixture
def sell_executor_module():
    """
    Dynamically load sell executor module for patching.
    """
    import importlib.util

    module_path = os.path.join(PROJECT_ROOT, 'services', 'sell-executor', 'executor.py')
    spec = importlib.util.spec_from_file_location("sell_executor_dynamic_module", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def buy_executor(buy_executor_class, mock_kis_client, mock_config):
    """
    Configured BuyExecutor instance.
    """
    return buy_executor_class(kis=mock_kis_client, config=mock_config)


@pytest.fixture
def sell_executor(sell_executor_class, mock_kis_client, mock_config):
    """
    Configured SellExecutor instance.
    """
    return sell_executor_class(kis=mock_kis_client, config=mock_config)


# ============================================================================
# Config Fixtures
# ============================================================================

@pytest.fixture
def mock_config():
    """
    Mock ConfigManager for testing.
    """
    config = MagicMock()

    # Default configuration values
    config_values = {
        'TRADING_MODE': 'MOCK',
        'MIN_LLM_SCORE': 60,
        'MIN_LLM_SCORE_TIER2': 65,
        'MAX_BUY_COUNT_PER_DAY': 5,
        'MAX_PORTFOLIO_SIZE': 10,
        'MAX_SECTOR_PCT': 30.0,
        'MAX_POSITION_VALUE_PCT': 10.0,
        'SIGNAL_COOLDOWN_SECONDS': 600,
        'RISK_GATE_RSI_MAX': 70,
        'RISK_GATE_VOLUME_RATIO': 2.0,
        'RISK_GATE_VWAP_DEVIATION': 0.02,
        'GOLDEN_CROSS_MIN_VOLUME_RATIO': 1.5,
        'ATR_PERIOD': 14,
        'TIER2_POSITION_MULT': 0.5,
        'RECON_POSITION_MULT': 0.3,
        'RECON_STOP_LOSS_PCT': -0.025,
        'CORRELATION_CHECK_ENABLED': False,  # Disable for simpler tests
        'ENABLE_RECON_BULL_ENTRY': True,
        'ENABLE_MOMENTUM_CONTINUATION': True,
    }

    def get_value(key, default=None):
        return config_values.get(key, default)

    def get_int(key, default=0):
        return int(config_values.get(key, default))

    def get_float(key, default=0.0):
        return float(config_values.get(key, default))

    def get_bool(key, default=False):
        value = config_values.get(key, default)
        if isinstance(value, bool):
            return value
        return str(value).lower() in ('true', '1', 'yes')

    config.get = get_value
    config.get_int = get_int
    config.get_float = get_float
    config.get_bool = get_bool
    config._values = config_values

    return config


# ============================================================================
# Scenario Fixtures
# ============================================================================

@pytest.fixture
def empty_portfolio_scenario(kis_server):
    """Scenario with empty portfolio for buy tests"""
    return kis_server.activate_scenario("empty_portfolio")


@pytest.fixture
def with_holdings_scenario(kis_server):
    """Scenario with existing holdings for sell tests"""
    return kis_server.activate_scenario("with_holdings")


@pytest.fixture
def stop_loss_scenario(kis_server):
    """Scenario where price has dropped to stop loss level"""
    return kis_server.activate_scenario("stop_loss_scenario")


@pytest.fixture
def take_profit_scenario(kis_server):
    """Scenario where price has risen to take profit level"""
    return kis_server.activate_scenario("take_profit_scenario")


@pytest.fixture
def daily_limit_reached_scenario(kis_server):
    """Scenario where daily buy limit is reached"""
    return kis_server.activate_scenario("daily_limit_reached")


@pytest.fixture
def emergency_stop_scenario(kis_server):
    """Scenario with emergency stop active"""
    return kis_server.activate_scenario("emergency_stop")


@pytest.fixture
def server_error_scenario(kis_server):
    """Scenario that returns server errors"""
    return kis_server.activate_scenario("server_error")


@pytest.fixture
def bull_momentum_scenario(kis_server):
    """Strong bull market scenario"""
    return kis_server.activate_scenario("bull_momentum")


# ============================================================================
# Time Manipulation Fixtures
# ============================================================================

@pytest.fixture
def freeze_time():
    """
    Context manager to freeze time for time-sensitive tests.

    Usage:
        with freeze_time(datetime(2026, 1, 31, 10, 30)):
            # Code runs as if it's 10:30 AM
    """
    @contextmanager
    def _freeze(target_time: datetime):
        with patch('datetime.datetime') as mock_datetime:
            mock_datetime.now.return_value = target_time
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            yield

    return _freeze


@pytest.fixture
def trading_hours():
    """
    Set the current time to be within trading hours (10:00 KST).
    """
    # 10:00 AM KST = 01:00 UTC
    target_time = datetime(2026, 1, 31, 1, 0, 0, tzinfo=timezone.utc)

    with patch('datetime.datetime') as mock_datetime:
        mock_datetime.now.return_value = target_time
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        yield target_time


@pytest.fixture
def no_trade_window():
    """
    Set the current time to be within no-trade window (09:00-09:15 KST).
    """
    # 09:10 AM KST = 00:10 UTC
    target_time = datetime(2026, 1, 31, 0, 10, 0, tzinfo=timezone.utc)

    with patch('datetime.datetime') as mock_datetime:
        mock_datetime.now.return_value = target_time
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        yield target_time


@pytest.fixture
def danger_zone():
    """
    Set the current time to be within danger zone (14:00-15:00 KST).
    """
    # 14:30 PM KST = 05:30 UTC
    target_time = datetime(2026, 1, 31, 5, 30, 0, tzinfo=timezone.utc)

    with patch('datetime.datetime') as mock_datetime:
        mock_datetime.now.return_value = target_time
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        yield target_time


# ============================================================================
# Helper Functions
# ============================================================================

def create_scan_result(stock_code: str, stock_name: str, llm_score: float = 80.0,
                       signal_type: str = "GOLDEN_CROSS", current_price: float = 70000,
                       market_regime: str = "BULL", is_tradable: bool = True,
                       trade_tier: str = "TIER1") -> dict:
    """
    Create a scan result for buy executor testing.
    """
    return {
        'candidates': [{
            'stock_code': stock_code,
            'stock_name': stock_name,
            'llm_score': llm_score,
            'is_tradable': is_tradable,
            'trade_tier': trade_tier,
            'buy_signal_type': signal_type,
            'current_price': current_price,
            'llm_reason': f'Test reason for {stock_name}'
        }],
        'market_regime': market_regime,
        'strategy_preset': {'name': 'TEST_PRESET', 'params': {}},
        'source': 'test'
    }


def create_portfolio_item(stock_code: str, stock_name: str, quantity: int,
                          avg_price: float, created_at: datetime = None) -> dict:
    """
    Create a portfolio item for testing.
    """
    return {
        'id': 1,
        'code': stock_code,
        'name': stock_name,
        'quantity': quantity,
        'avg_price': avg_price,
        'buy_price': avg_price,
        'current_price': avg_price,
        'created_at': created_at or datetime.now(timezone.utc),
        'stop_loss_price': avg_price * 0.95,
        'high_price': avg_price
    }


# Export helper functions
@pytest.fixture
def scan_result_factory():
    """Factory for creating scan results"""
    return create_scan_result


@pytest.fixture
def portfolio_item_factory():
    """Factory for creating portfolio items"""
    return create_portfolio_item
