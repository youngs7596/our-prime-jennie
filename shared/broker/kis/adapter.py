# shared/broker/kis/adapter.py
# Version: v1.0
# KIS (한국투자증권) 브로커 어댑터
#
# 기존 KISGatewayClient/KISClient를 래핑하여 BrokerClient 인터페이스를 구현합니다.

import os
import logging
from typing import Optional, Dict, Any, List, Union

logger = logging.getLogger(__name__)


class KISBrokerAdapter:
    """
    KIS (한국투자증권) 브로커 어댑터

    기존 KISGatewayClient 또는 KISClient를 래핑하여
    BrokerClient 인터페이스를 구현합니다.

    환경변수:
        USE_KIS_GATEWAY: "true"면 Gateway 사용, "false"면 직접 API 호출
        KIS_GATEWAY_URL: Gateway URL (기본: http://127.0.0.1:8080)
        TRADING_MODE: "REAL" 또는 "MOCK"

    Usage:
        # 기본 (Gateway 사용)
        adapter = KISBrokerAdapter()

        # 직접 API 호출
        adapter = KISBrokerAdapter(use_gateway=False)

        # BrokerClient 인터페이스로 사용
        snapshot = adapter.get_stock_snapshot("005930")
        order_no = adapter.place_buy_order("005930", 10)
    """

    def __init__(
        self,
        use_gateway: Optional[bool] = None,
        gateway_url: Optional[str] = None,
        **kwargs
    ):
        """
        Args:
            use_gateway: Gateway 사용 여부 (기본: 환경변수 USE_KIS_GATEWAY, 없으면 True)
            gateway_url: Gateway URL (use_gateway=True일 때만 사용)
            **kwargs: 추가 설정 (직접 클라이언트용)
        """
        if use_gateway is None:
            use_gateway = os.getenv("USE_KIS_GATEWAY", "true").lower() == "true"

        self._use_gateway = use_gateway

        if use_gateway:
            self._client = self._create_gateway_client(gateway_url)
            logger.info("✅ KISBrokerAdapter initialized (Gateway mode)")
        else:
            self._client = self._create_direct_client(**kwargs)
            logger.info("✅ KISBrokerAdapter initialized (Direct API mode)")

    def _create_gateway_client(self, gateway_url: Optional[str] = None):
        """Gateway 클라이언트 생성"""
        from shared.kis.gateway_client import KISGatewayClient

        if gateway_url:
            return KISGatewayClient(gateway_url=gateway_url)
        return KISGatewayClient()

    def _create_direct_client(self, **kwargs):
        """
        직접 API 클라이언트 생성

        환경변수 또는 kwargs에서 설정을 읽어 KISClient를 생성합니다.
        """
        from shared.kis.client import KISClient

        # 환경변수 또는 kwargs에서 설정 읽기
        app_key = kwargs.get("app_key") or os.getenv("KIS_APP_KEY")
        app_secret = kwargs.get("app_secret") or os.getenv("KIS_APP_SECRET")
        trading_mode = kwargs.get("trading_mode") or os.getenv("TRADING_MODE", "MOCK")

        # 모드에 따른 Base URL
        if trading_mode == "REAL":
            base_url = os.getenv("KIS_BASE_URL", "https://openapi.koreainvestment.com:9443")
        else:
            base_url = os.getenv("KIS_BASE_URL_MOCK", "https://openapivts.koreainvestment.com:29443")

        # 계좌 정보
        account_prefix = kwargs.get("account_prefix") or os.getenv("KIS_ACCOUNT_PREFIX", "")
        account_suffix = kwargs.get("account_suffix") or os.getenv("KIS_ACCOUNT_SUFFIX", "01")
        token_file_path = kwargs.get("token_file_path") or os.getenv("KIS_TOKEN_FILE_PATH")

        if not app_key or not app_secret:
            raise ValueError(
                "KIS credentials not found. "
                "Set KIS_APP_KEY and KIS_APP_SECRET environment variables."
            )

        client = KISClient(
            app_key=app_key,
            app_secret=app_secret,
            base_url=base_url,
            account_prefix=account_prefix,
            account_suffix=account_suffix,
            trading_mode=trading_mode,
            token_file_path=token_file_path,
        )

        # 인증 수행
        if not client.authenticate():
            raise RuntimeError("KIS authentication failed")

        return client

    # ─────────────────────────────────────────────────────────────────────
    # BrokerClient Interface Implementation
    # ─────────────────────────────────────────────────────────────────────

    def get_stock_snapshot(
        self,
        stock_code: str,
        is_index: bool = False
    ) -> Optional[Dict[str, Any]]:
        """종목 현재가 조회"""
        return self._client.get_stock_snapshot(stock_code, is_index=is_index)

    def get_stock_daily_prices(
        self,
        stock_code: str,
        num_days: int = 30
    ) -> Optional[Any]:
        """일봉 데이터 조회"""
        return self._client.get_stock_daily_prices(stock_code, num_days_to_fetch=num_days)

    def check_market_open(self) -> bool:
        """장 운영일 여부 확인"""
        return self._client.check_market_open()

    def place_buy_order(
        self,
        stock_code: str,
        quantity: int,
        price: int = 0
    ) -> Optional[str]:
        """매수 주문"""
        return self._client.place_buy_order(stock_code, quantity, price)

    def place_sell_order(
        self,
        stock_code: str,
        quantity: int,
        price: int = 0
    ) -> Optional[str]:
        """매도 주문"""
        return self._client.place_sell_order(stock_code, quantity, price)

    def get_cash_balance(self) -> float:
        """현금 잔고 조회"""
        return self._client.get_cash_balance()

    def get_account_balance(self) -> Optional[Dict[str, Any]]:
        """계좌 잔고 조회"""
        return self._client.get_account_balance()

    def get_health(self) -> Optional[Dict[str, Any]]:
        """브로커 연결 상태 확인"""
        return self._client.get_health()

    # ─────────────────────────────────────────────────────────────────────
    # KIS-specific Methods (확장 기능)
    # ─────────────────────────────────────────────────────────────────────

    def get_market_data(self):
        """
        MarketData 모듈 프록시 반환

        기존 코드와의 호환성을 위해 제공합니다:
            kis_api.get_market_data().get_investor_trend(...)
        """
        return self._client.get_market_data()

    def get_stats(self) -> Optional[Dict[str, Any]]:
        """Gateway 통계 조회 (Gateway 모드에서만 동작)"""
        if self._use_gateway and hasattr(self._client, "get_stats"):
            return self._client.get_stats()
        return None

    @property
    def use_gateway(self) -> bool:
        """Gateway 사용 여부"""
        return self._use_gateway

    @property
    def client(self):
        """
        내부 클라이언트 직접 접근 (하위 호환성)

        주의: 이 속성은 하위 호환성을 위해서만 제공됩니다.
        가능하면 BrokerClient 인터페이스 메서드를 사용하세요.
        """
        return self._client
