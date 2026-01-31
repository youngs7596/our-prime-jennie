# tests/e2e/fixtures/__init__.py
"""
Test Fixtures for E2E Testing

- Redis fixtures with Streams support
- RabbitMQ mock fixtures
- Database fixtures
"""

from .redis_fixtures import StreamsEnabledFakeRedis, PriceStreamSimulator
from .rabbitmq_fixtures import MockRabbitMQPublisher, MockRabbitMQConsumer, RabbitMQTestBridge

__all__ = [
    'StreamsEnabledFakeRedis',
    'PriceStreamSimulator',
    'MockRabbitMQPublisher',
    'MockRabbitMQConsumer',
    'RabbitMQTestBridge'
]
