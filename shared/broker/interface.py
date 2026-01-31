# shared/broker/interface.py
# Version: v1.0
# 브로커 클라이언트 공통 인터페이스 정의 (Protocol)

from typing import Protocol, Optional, Dict, Any, List, Union, runtime_checkable
import pandas as pd


@runtime_checkable
class BrokerClient(Protocol):
    """
    모든 브로커가 구현해야 하는 공통 인터페이스

    이 Protocol을 구현하면:
    - KIS (한국투자증권)
    - Kiwoom (키움증권)
    - Toss (토스증권)
    - Upbit (업비트, 암호화폐)
    등 다양한 증권사 API를 동일한 인터페이스로 사용할 수 있습니다.

    Usage:
        from shared.broker import BrokerFactory
        broker = BrokerFactory.create()  # 환경변수에서 자동 감지

        # 시세 조회
        snapshot = broker.get_stock_snapshot("005930")

        # 매수 주문
        order_no = broker.place_buy_order("005930", 10)
    """

    # ─────────────────────────────────────────────────────────────────────
    # Market Data (시세 조회)
    # ─────────────────────────────────────────────────────────────────────

    def get_stock_snapshot(
        self,
        stock_code: str,
        is_index: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        종목 현재가 조회

        Args:
            stock_code: 종목 코드 (예: "005930")
            is_index: 지수 여부 (KOSPI/KOSDAQ 지수 조회 시 True)

        Returns:
            현재가 정보 딕셔너리 또는 None
            {
                'stck_prpr': 현재가,
                'prdy_vrss': 전일대비,
                'prdy_ctrt': 등락률,
                'acml_vol': 거래량,
                ...
            }
        """
        ...

    def get_stock_daily_prices(
        self,
        stock_code: str,
        num_days: int = 30
    ) -> Optional[Union[pd.DataFrame, List[Dict]]]:
        """
        일봉 데이터 조회

        Args:
            stock_code: 종목 코드
            num_days: 조회할 일수 (기본: 30일)

        Returns:
            일봉 데이터 (DataFrame 또는 리스트) 또는 None
        """
        ...

    def check_market_open(self) -> bool:
        """
        오늘이 장 운영일(거래 가능일)인지 확인

        Returns:
            True: 장 운영일 (평일 & 비휴일)
            False: 휴장일 (주말 또는 공휴일)
        """
        ...

    # ─────────────────────────────────────────────────────────────────────
    # Trading (주문)
    # ─────────────────────────────────────────────────────────────────────

    def place_buy_order(
        self,
        stock_code: str,
        quantity: int,
        price: int = 0
    ) -> Optional[str]:
        """
        매수 주문

        Args:
            stock_code: 종목 코드
            quantity: 수량
            price: 가격 (0이면 시장가)

        Returns:
            주문번호 또는 None (실패 시)
        """
        ...

    def place_sell_order(
        self,
        stock_code: str,
        quantity: int,
        price: int = 0
    ) -> Optional[str]:
        """
        매도 주문

        Args:
            stock_code: 종목 코드
            quantity: 수량
            price: 가격 (0이면 시장가)

        Returns:
            주문번호 또는 None (실패 시)
        """
        ...

    # ─────────────────────────────────────────────────────────────────────
    # Account (계좌)
    # ─────────────────────────────────────────────────────────────────────

    def get_cash_balance(self) -> float:
        """
        현금 잔고 (주문 가능 금액) 조회

        Returns:
            주문 가능 현금 (원)
        """
        ...

    def get_account_balance(self) -> Optional[Dict[str, Any]]:
        """
        계좌 잔고 조회 (보유 종목 포함)

        Returns:
            계좌 잔고 정보 또는 None
            {
                'holdings': [
                    {'code': '005930', 'name': '삼성전자', 'quantity': 10, ...},
                    ...
                ],
                'cash_balance': 1000000,
                ...
            }
        """
        ...

    # ─────────────────────────────────────────────────────────────────────
    # Health (상태 확인)
    # ─────────────────────────────────────────────────────────────────────

    def get_health(self) -> Optional[Dict[str, Any]]:
        """
        브로커 연결 상태 확인

        Returns:
            상태 정보 딕셔너리 또는 None
            {
                'status': 'healthy' | 'unhealthy',
                'latency_ms': 응답시간,
                ...
            }
        """
        ...


class MarketDataProvider(Protocol):
    """
    MarketData 모듈을 별도로 제공하는 브로커용 인터페이스

    일부 브로커(KIS)는 시세 조회 기능을 별도 모듈로 제공합니다.
    이 인터페이스를 통해 investor_trend 등 추가 시세 기능에 접근할 수 있습니다.
    """

    def get_market_data(self) -> Any:
        """
        MarketData 모듈 반환

        Returns:
            MarketData 인스턴스 (get_investor_trend 등 메서드 보유)
        """
        ...
