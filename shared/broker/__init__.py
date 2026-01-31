# shared/broker/__init__.py
# Version: v1.0
# 멀티 브로커 추상화 패키지
#
# 사용법:
#   from shared.broker import BrokerFactory, BrokerType
#   broker = BrokerFactory.create()  # 환경변수에서 자동 감지
#
# 하위 호환성:
#   기존 코드는 그대로 동작합니다:
#   from shared.kis.gateway_client import KISGatewayClient
#   kis = KISGatewayClient()

from .factory import BrokerFactory, BrokerType
from .interface import BrokerClient, MarketDataProvider
from .types import (
    OrderType,
    OrderSide,
    StockSnapshot,
    OrderResult,
    Holding,
    AccountBalance,
    DailyPrice,
)

__all__ = [
    # Factory
    "BrokerFactory",
    "BrokerType",
    # Interface
    "BrokerClient",
    "MarketDataProvider",
    # Types
    "OrderType",
    "OrderSide",
    "StockSnapshot",
    "OrderResult",
    "Holding",
    "AccountBalance",
    "DailyPrice",
]
