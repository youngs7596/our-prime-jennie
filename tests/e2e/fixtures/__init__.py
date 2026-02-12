# tests/e2e/fixtures/__init__.py
"""
Test Fixtures for E2E Testing

- Redis fixtures with Streams support
- Trading signal stream mock fixtures
"""

from .redis_fixtures import StreamsEnabledFakeRedis, PriceStreamSimulator
from .stream_fixtures import MockStreamPublisher, MockStreamConsumer, StreamTestBridge

__all__ = [
    'StreamsEnabledFakeRedis',
    'PriceStreamSimulator',
    'MockStreamPublisher',
    'MockStreamConsumer',
    'StreamTestBridge'
]
