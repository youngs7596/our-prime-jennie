# tests/shared/broker/test_factory.py
"""BrokerFactory 테스트"""

import pytest
from unittest.mock import patch, MagicMock
import os

from shared.broker import BrokerFactory, BrokerType, BrokerClient


class TestBrokerType:
    """BrokerType enum 테스트"""

    def test_broker_types_exist(self):
        """모든 브로커 타입이 정의되어 있는지 확인"""
        assert BrokerType.KIS.value == "kis"
        assert BrokerType.KIWOOM.value == "kiwoom"
        assert BrokerType.TOSS.value == "toss"
        assert BrokerType.UPBIT.value == "upbit"

    def test_broker_type_from_string(self):
        """문자열에서 BrokerType 생성"""
        assert BrokerType("kis") == BrokerType.KIS
        assert BrokerType("kiwoom") == BrokerType.KIWOOM

    def test_invalid_broker_type(self):
        """잘못된 브로커 타입"""
        with pytest.raises(ValueError):
            BrokerType("invalid")


class TestBrokerFactory:
    """BrokerFactory 테스트"""

    @patch.dict(os.environ, {"BROKER_TYPE": "kis", "USE_KIS_GATEWAY": "true"}, clear=False)
    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_create_kis_broker_from_env(self, mock_create_gateway):
        """환경변수에서 KIS 브로커 생성"""
        mock_client = MagicMock()
        mock_create_gateway.return_value = mock_client

        broker = BrokerFactory.create()

        assert broker is not None
        mock_create_gateway.assert_called_once()

    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_create_kis_broker_explicit(self, mock_create_gateway):
        """명시적 타입으로 KIS 브로커 생성"""
        mock_client = MagicMock()
        mock_create_gateway.return_value = mock_client

        broker = BrokerFactory.create(BrokerType.KIS)

        assert broker is not None
        mock_create_gateway.assert_called_once()

    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_create_broker_with_string_type(self, mock_create_gateway):
        """문자열 타입으로 브로커 생성"""
        mock_client = MagicMock()
        mock_create_gateway.return_value = mock_client

        broker = BrokerFactory.create("kis")

        assert broker is not None

    def test_create_kiwoom_broker_not_implemented(self):
        """키움증권 브로커 미구현 확인"""
        with pytest.raises(NotImplementedError) as exc_info:
            BrokerFactory.create(BrokerType.KIWOOM)

        assert "Kiwoom broker is not yet implemented" in str(exc_info.value)

    def test_create_toss_broker_not_implemented(self):
        """토스증권 브로커 미구현 확인"""
        with pytest.raises(NotImplementedError) as exc_info:
            BrokerFactory.create(BrokerType.TOSS)

        assert "Toss broker is not yet implemented" in str(exc_info.value)

    def test_create_upbit_broker_not_implemented(self):
        """업비트 브로커 미구현 확인"""
        with pytest.raises(NotImplementedError) as exc_info:
            BrokerFactory.create(BrokerType.UPBIT)

        assert "Upbit broker is not yet implemented" in str(exc_info.value)

    def test_create_invalid_broker_type(self):
        """잘못된 브로커 타입으로 생성 시도"""
        with pytest.raises(ValueError) as exc_info:
            BrokerFactory.create("invalid_broker")

        assert "Unknown broker type" in str(exc_info.value)

    def test_get_supported_brokers(self):
        """지원 브로커 목록 조회"""
        brokers = BrokerFactory.get_supported_brokers()

        assert "kis" in brokers
        assert "kiwoom" in brokers
        assert "toss" in brokers
        assert "upbit" in brokers
        assert len(brokers) == 4

    def test_is_implemented_kis(self):
        """KIS 구현 여부 확인"""
        assert BrokerFactory.is_implemented(BrokerType.KIS) is True
        assert BrokerFactory.is_implemented("kis") is True

    def test_is_implemented_others(self):
        """다른 브로커 구현 여부 확인"""
        assert BrokerFactory.is_implemented(BrokerType.KIWOOM) is False
        assert BrokerFactory.is_implemented(BrokerType.TOSS) is False
        assert BrokerFactory.is_implemented(BrokerType.UPBIT) is False

    def test_is_implemented_invalid(self):
        """잘못된 타입 구현 여부 확인"""
        assert BrokerFactory.is_implemented("invalid") is False


class TestBrokerClientProtocol:
    """BrokerClient Protocol 테스트"""

    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_kis_adapter_implements_broker_client(self, mock_create_gateway):
        """KISBrokerAdapter가 BrokerClient 인터페이스를 구현하는지 확인"""
        mock_client = MagicMock()
        mock_create_gateway.return_value = mock_client

        broker = BrokerFactory.create(BrokerType.KIS)

        # Protocol 메서드들이 존재하는지 확인
        assert hasattr(broker, "get_stock_snapshot")
        assert hasattr(broker, "get_stock_daily_prices")
        assert hasattr(broker, "check_market_open")
        assert hasattr(broker, "place_buy_order")
        assert hasattr(broker, "place_sell_order")
        assert hasattr(broker, "get_cash_balance")
        assert hasattr(broker, "get_account_balance")
        assert hasattr(broker, "get_health")

        # 메서드들이 호출 가능한지 확인
        assert callable(broker.get_stock_snapshot)
        assert callable(broker.place_buy_order)
