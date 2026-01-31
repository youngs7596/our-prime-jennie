# shared/broker/types.py
# Version: v1.0
# 브로커 공통 데이터 타입 정의

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from enum import Enum


class OrderType(Enum):
    """주문 유형"""
    MARKET = "market"  # 시장가
    LIMIT = "limit"    # 지정가


class OrderSide(Enum):
    """주문 방향"""
    BUY = "buy"
    SELL = "sell"


@dataclass
class StockSnapshot:
    """종목 현재가 정보"""
    code: str                      # 종목 코드
    name: Optional[str] = None     # 종목명
    price: float = 0.0             # 현재가
    change: float = 0.0            # 전일 대비
    change_rate: float = 0.0       # 등락률 (%)
    volume: int = 0                # 거래량
    open_price: float = 0.0        # 시가
    high_price: float = 0.0        # 고가
    low_price: float = 0.0         # 저가
    prev_close: float = 0.0        # 전일 종가

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StockSnapshot":
        """딕셔너리에서 StockSnapshot 생성"""
        return cls(
            code=data.get("code", data.get("stock_code", "")),
            name=data.get("name", data.get("stock_name")),
            price=float(data.get("price", data.get("stck_prpr", 0))),
            change=float(data.get("change", data.get("prdy_vrss", 0))),
            change_rate=float(data.get("change_rate", data.get("prdy_ctrt", 0))),
            volume=int(data.get("volume", data.get("acml_vol", 0))),
            open_price=float(data.get("open_price", data.get("stck_oprc", 0))),
            high_price=float(data.get("high_price", data.get("stck_hgpr", 0))),
            low_price=float(data.get("low_price", data.get("stck_lwpr", 0))),
            prev_close=float(data.get("prev_close", data.get("stck_sdpr", 0))),
        )


@dataclass
class OrderResult:
    """주문 실행 결과"""
    success: bool
    order_no: Optional[str] = None
    message: Optional[str] = None

    @classmethod
    def success_result(cls, order_no: str) -> "OrderResult":
        return cls(success=True, order_no=order_no)

    @classmethod
    def failure_result(cls, message: str) -> "OrderResult":
        return cls(success=False, message=message)


@dataclass
class Holding:
    """보유 종목 정보"""
    code: str                      # 종목 코드
    name: str                      # 종목명
    quantity: int                  # 보유 수량
    avg_price: float               # 평균 매입가
    current_price: float           # 현재가

    @property
    def eval_amount(self) -> float:
        """평가 금액"""
        return self.current_price * self.quantity

    @property
    def profit_loss(self) -> float:
        """평가 손익"""
        return (self.current_price - self.avg_price) * self.quantity

    @property
    def profit_loss_rate(self) -> float:
        """수익률 (%)"""
        if self.avg_price == 0:
            return 0.0
        return ((self.current_price - self.avg_price) / self.avg_price) * 100


@dataclass
class AccountBalance:
    """계좌 잔고 정보"""
    cash_balance: float            # 주문 가능 현금
    total_asset: float             # 총 자산
    stock_eval: float              # 주식 평가액
    total_profit_loss: float       # 총 평가 손익
    holdings: List[Holding]        # 보유 종목 리스트


@dataclass
class DailyPrice:
    """일봉 데이터"""
    date: str                      # 날짜 (YYYYMMDD)
    open_price: float              # 시가
    high_price: float              # 고가
    low_price: float               # 저가
    close_price: float             # 종가
    volume: int                    # 거래량
    change_rate: float = 0.0       # 등락률 (%)
