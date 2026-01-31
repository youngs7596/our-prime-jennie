# tests/shared/broker/test_kis_adapter.py
"""KISBrokerAdapter 테스트"""

import pytest
from unittest.mock import patch, MagicMock
import os

from shared.broker.kis.adapter import KISBrokerAdapter


class TestKISBrokerAdapterGatewayMode:
    """KISBrokerAdapter Gateway 모드 테스트"""

    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_init_gateway_mode_explicit(self, mock_create_gateway):
        """명시적 Gateway 모드 초기화"""
        mock_client = MagicMock()
        mock_create_gateway.return_value = mock_client

        adapter = KISBrokerAdapter(use_gateway=True)

        assert adapter.use_gateway is True
        mock_create_gateway.assert_called_once()

    @patch.dict(os.environ, {"USE_KIS_GATEWAY": "true"}, clear=False)
    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_init_gateway_mode_from_env(self, mock_create_gateway):
        """환경변수에서 Gateway 모드 결정"""
        mock_client = MagicMock()
        mock_create_gateway.return_value = mock_client

        adapter = KISBrokerAdapter()

        assert adapter.use_gateway is True

    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_get_stock_snapshot(self, mock_create_gateway):
        """종목 현재가 조회 위임"""
        mock_client = MagicMock()
        mock_client.get_stock_snapshot.return_value = {"stck_prpr": 70000}
        mock_create_gateway.return_value = mock_client

        adapter = KISBrokerAdapter(use_gateway=True)
        result = adapter.get_stock_snapshot("005930")

        mock_client.get_stock_snapshot.assert_called_once_with("005930", is_index=False)
        assert result == {"stck_prpr": 70000}

    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_get_stock_snapshot_index(self, mock_create_gateway):
        """지수 조회"""
        mock_client = MagicMock()
        mock_client.get_stock_snapshot.return_value = {"stck_prpr": 2500}
        mock_create_gateway.return_value = mock_client

        adapter = KISBrokerAdapter(use_gateway=True)
        result = adapter.get_stock_snapshot("0001", is_index=True)

        mock_client.get_stock_snapshot.assert_called_once_with("0001", is_index=True)

    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_get_stock_daily_prices(self, mock_create_gateway):
        """일봉 데이터 조회 위임"""
        mock_client = MagicMock()
        mock_client.get_stock_daily_prices.return_value = [{"date": "20260131"}]
        mock_create_gateway.return_value = mock_client

        adapter = KISBrokerAdapter(use_gateway=True)
        result = adapter.get_stock_daily_prices("005930", num_days=20)

        mock_client.get_stock_daily_prices.assert_called_once_with(
            "005930", num_days_to_fetch=20
        )

    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_check_market_open(self, mock_create_gateway):
        """장 운영일 확인 위임"""
        mock_client = MagicMock()
        mock_client.check_market_open.return_value = True
        mock_create_gateway.return_value = mock_client

        adapter = KISBrokerAdapter(use_gateway=True)
        result = adapter.check_market_open()

        assert result is True
        mock_client.check_market_open.assert_called_once()

    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_place_buy_order(self, mock_create_gateway):
        """매수 주문 위임"""
        mock_client = MagicMock()
        mock_client.place_buy_order.return_value = "ORDER123"
        mock_create_gateway.return_value = mock_client

        adapter = KISBrokerAdapter(use_gateway=True)
        result = adapter.place_buy_order("005930", 10, 70000)

        mock_client.place_buy_order.assert_called_once_with("005930", 10, 70000)
        assert result == "ORDER123"

    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_place_buy_order_market(self, mock_create_gateway):
        """시장가 매수 주문"""
        mock_client = MagicMock()
        mock_client.place_buy_order.return_value = "ORDER456"
        mock_create_gateway.return_value = mock_client

        adapter = KISBrokerAdapter(use_gateway=True)
        result = adapter.place_buy_order("005930", 10)  # price=0 (시장가)

        mock_client.place_buy_order.assert_called_once_with("005930", 10, 0)

    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_place_sell_order(self, mock_create_gateway):
        """매도 주문 위임"""
        mock_client = MagicMock()
        mock_client.place_sell_order.return_value = "ORDER789"
        mock_create_gateway.return_value = mock_client

        adapter = KISBrokerAdapter(use_gateway=True)
        result = adapter.place_sell_order("005930", 5, 75000)

        mock_client.place_sell_order.assert_called_once_with("005930", 5, 75000)
        assert result == "ORDER789"

    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_get_cash_balance(self, mock_create_gateway):
        """현금 잔고 조회 위임"""
        mock_client = MagicMock()
        mock_client.get_cash_balance.return_value = 1000000.0
        mock_create_gateway.return_value = mock_client

        adapter = KISBrokerAdapter(use_gateway=True)
        result = adapter.get_cash_balance()

        assert result == 1000000.0
        mock_client.get_cash_balance.assert_called_once()

    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_get_account_balance(self, mock_create_gateway):
        """계좌 잔고 조회 위임"""
        mock_client = MagicMock()
        mock_client.get_account_balance.return_value = [
            {"code": "005930", "name": "삼성전자", "quantity": 10}
        ]
        mock_create_gateway.return_value = mock_client

        adapter = KISBrokerAdapter(use_gateway=True)
        result = adapter.get_account_balance()

        mock_client.get_account_balance.assert_called_once()
        assert len(result) == 1

    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_get_health(self, mock_create_gateway):
        """Health 체크 위임"""
        mock_client = MagicMock()
        mock_client.get_health.return_value = {"status": "healthy"}
        mock_create_gateway.return_value = mock_client

        adapter = KISBrokerAdapter(use_gateway=True)
        result = adapter.get_health()

        assert result == {"status": "healthy"}

    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_get_market_data(self, mock_create_gateway):
        """MarketData 모듈 접근"""
        mock_client = MagicMock()
        mock_market_data = MagicMock()
        mock_client.get_market_data.return_value = mock_market_data
        mock_create_gateway.return_value = mock_client

        adapter = KISBrokerAdapter(use_gateway=True)
        result = adapter.get_market_data()

        mock_client.get_market_data.assert_called_once()
        assert result == mock_market_data

    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_get_stats_gateway_mode(self, mock_create_gateway):
        """Gateway 통계 조회 (Gateway 모드)"""
        mock_client = MagicMock()
        mock_client.get_stats.return_value = {"requests": 100}
        mock_create_gateway.return_value = mock_client

        adapter = KISBrokerAdapter(use_gateway=True)
        result = adapter.get_stats()

        assert result == {"requests": 100}

    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_client_property(self, mock_create_gateway):
        """내부 클라이언트 접근 (하위 호환성)"""
        mock_client = MagicMock()
        mock_create_gateway.return_value = mock_client

        adapter = KISBrokerAdapter(use_gateway=True)

        assert adapter.client == mock_client


class TestKISBrokerAdapterDirectMode:
    """KISBrokerAdapter 직접 API 모드 테스트"""

    @patch.dict(
        os.environ,
        {
            "USE_KIS_GATEWAY": "false",
            "KIS_APP_KEY": "test_key",
            "KIS_APP_SECRET": "test_secret",
            "TRADING_MODE": "MOCK",
            "KIS_ACCOUNT_PREFIX": "12345678",
            "KIS_ACCOUNT_SUFFIX": "01",
        },
        clear=False,
    )
    @patch("shared.kis.client.KISClient")
    def test_init_direct_mode_from_env(self, mock_kis_client_class):
        """환경변수에서 직접 API 모드 결정"""
        mock_client = MagicMock()
        mock_client.authenticate.return_value = True
        mock_kis_client_class.return_value = mock_client

        adapter = KISBrokerAdapter()

        assert adapter.use_gateway is False
        mock_kis_client_class.assert_called_once()
        mock_client.authenticate.assert_called_once()

    @patch("shared.kis.client.KISClient")
    def test_init_direct_mode_explicit(self, mock_kis_client_class):
        """명시적 직접 API 모드 초기화"""
        mock_client = MagicMock()
        mock_client.authenticate.return_value = True
        mock_kis_client_class.return_value = mock_client

        adapter = KISBrokerAdapter(
            use_gateway=False,
            app_key="test_key",
            app_secret="test_secret",
            trading_mode="MOCK",
        )

        assert adapter.use_gateway is False

    @patch.dict(os.environ, {"USE_KIS_GATEWAY": "false"}, clear=False)
    def test_init_direct_mode_missing_credentials(self):
        """자격 증명 없이 직접 모드 초기화 실패"""
        # KIS_APP_KEY, KIS_APP_SECRET이 없으면 ValueError
        with patch.dict(os.environ, {}, clear=True):
            with patch.dict(os.environ, {"USE_KIS_GATEWAY": "false"}):
                with pytest.raises(ValueError) as exc_info:
                    KISBrokerAdapter(use_gateway=False)

                assert "KIS credentials not found" in str(exc_info.value)

    @patch("shared.kis.client.KISClient")
    def test_init_direct_mode_auth_failure(self, mock_kis_client_class):
        """인증 실패 시 RuntimeError"""
        mock_client = MagicMock()
        mock_client.authenticate.return_value = False
        mock_kis_client_class.return_value = mock_client

        with pytest.raises(RuntimeError) as exc_info:
            KISBrokerAdapter(
                use_gateway=False,
                app_key="test_key",
                app_secret="test_secret",
            )

        assert "authentication failed" in str(exc_info.value)

    @patch("shared.kis.client.KISClient")
    def test_get_stats_direct_mode(self, mock_kis_client_class):
        """Gateway 통계 조회 (직접 모드 - None 반환)"""
        mock_client = MagicMock()
        mock_client.authenticate.return_value = True
        # 직접 모드에서는 get_stats가 없거나 동작하지 않음
        del mock_client.get_stats
        mock_kis_client_class.return_value = mock_client

        adapter = KISBrokerAdapter(
            use_gateway=False,
            app_key="test_key",
            app_secret="test_secret",
        )

        result = adapter.get_stats()
        assert result is None


class TestKISBrokerAdapterIntegration:
    """KISBrokerAdapter 통합 테스트 (실제 클라이언트 사용하지 않음)"""

    @patch("shared.broker.kis.adapter.KISBrokerAdapter._create_gateway_client")
    def test_full_trading_flow(self, mock_create_gateway):
        """전체 거래 흐름 테스트"""
        mock_client = MagicMock()
        mock_client.check_market_open.return_value = True
        mock_client.get_cash_balance.return_value = 5000000.0
        mock_client.get_stock_snapshot.return_value = {"stck_prpr": 70000}
        mock_client.place_buy_order.return_value = "ORDER001"
        mock_create_gateway.return_value = mock_client

        adapter = KISBrokerAdapter(use_gateway=True)

        # 1. 장 운영 확인
        assert adapter.check_market_open() is True

        # 2. 현금 잔고 확인
        cash = adapter.get_cash_balance()
        assert cash == 5000000.0

        # 3. 종목 현재가 조회
        snapshot = adapter.get_stock_snapshot("005930")
        assert snapshot["stck_prpr"] == 70000

        # 4. 매수 주문
        order_no = adapter.place_buy_order("005930", 10)
        assert order_no == "ORDER001"
