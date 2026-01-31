# Multi-Broker Gateway Abstraction

> 멀티 증권사 API를 통합하는 추상화 레이어

## 개요

`shared/broker` 패키지는 다양한 증권사 API를 동일한 인터페이스로 사용할 수 있게 해주는 추상화 레이어입니다.

## 지원 브로커

| 브로커 | 상태 | 설명 |
|--------|------|------|
| KIS (한국투자증권) | ✅ 구현됨 | Gateway/Direct 모드 지원 |
| Kiwoom (키움증권) | ⏳ TODO | REST API 2025.03 출시 |
| Toss (토스증권) | ❌ 미구현 | 공개 API 없음 |
| Upbit (업비트) | ❌ 미구현 | 암호화폐 거래소 |

## 사용법

### 기본 사용

```python
from shared.broker import BrokerFactory, BrokerType

# 환경변수에서 자동 감지 (BROKER_TYPE, USE_KIS_GATEWAY)
broker = BrokerFactory.create()

# 또는 명시적 지정
broker = BrokerFactory.create(BrokerType.KIS)
broker = BrokerFactory.create("kis")
```

### 시세 조회

```python
# 종목 현재가
snapshot = broker.get_stock_snapshot("005930")
print(f"삼성전자: {snapshot['stck_prpr']}원")

# 일봉 데이터
daily = broker.get_stock_daily_prices("005930", num_days=30)
```

### 주문

```python
# 시장가 매수
order_no = broker.place_buy_order("005930", quantity=10)

# 지정가 매도
order_no = broker.place_sell_order("005930", quantity=5, price=75000)
```

### 계좌 조회

```python
# 현금 잔고
cash = broker.get_cash_balance()

# 보유 종목
holdings = broker.get_account_balance()
```

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `BROKER_TYPE` | `kis` | 사용할 브로커 (kis, kiwoom, toss, upbit) |
| `USE_KIS_GATEWAY` | `true` | KIS Gateway 사용 여부 |
| `KIS_GATEWAY_URL` | `http://127.0.0.1:8080` | KIS Gateway URL |

## 패키지 구조

```
shared/broker/
├── __init__.py          # 공개 인터페이스 export
├── interface.py         # BrokerClient Protocol 정의
├── types.py             # 공통 데이터 타입
├── factory.py           # BrokerFactory 클래스
├── README.md            # 이 문서
└── kis/                 # KIS 구현
    ├── __init__.py
    └── adapter.py       # KISBrokerAdapter
```

## BrokerClient 인터페이스

모든 브로커 어댑터는 다음 메서드를 구현해야 합니다:

```python
class BrokerClient(Protocol):
    # Market Data
    def get_stock_snapshot(self, stock_code: str, is_index: bool = False) -> Optional[Dict]: ...
    def get_stock_daily_prices(self, stock_code: str, num_days: int = 30) -> Optional[Any]: ...
    def check_market_open(self) -> bool: ...

    # Trading
    def place_buy_order(self, stock_code: str, quantity: int, price: int = 0) -> Optional[str]: ...
    def place_sell_order(self, stock_code: str, quantity: int, price: int = 0) -> Optional[str]: ...

    # Account
    def get_cash_balance(self) -> float: ...
    def get_account_balance(self) -> Optional[Dict]: ...

    # Health
    def get_health(self) -> Optional[Dict]: ...
```

## 새 브로커 추가 방법

1. `shared/broker/{broker}/adapter.py` 생성
2. `BrokerClient` 인터페이스 구현
3. `BrokerFactory`에 생성 로직 추가
4. 테스트 작성

예시:
```python
# shared/broker/kiwoom/adapter.py
class KiwoomBrokerAdapter:
    def __init__(self, api_key: str = None, ...):
        self._client = KiwoomClient(api_key, ...)

    def get_stock_snapshot(self, stock_code: str, is_index: bool = False):
        # 키움 API 호출
        return self._client.get_current_price(stock_code)

    # ... 나머지 메서드 구현
```

## 하위 호환성

기존 코드는 변경 없이 그대로 동작합니다:

```python
# 기존 방식 (계속 동작)
from shared.kis.gateway_client import KISGatewayClient
kis = KISGatewayClient()

# 새 권장 방식
from shared.broker import BrokerFactory
broker = BrokerFactory.create()
```

## TODO

- [ ] **키움증권 REST API 연동** (https://openapi.kiwoom.com)
  - 2025년 3월 출시된 REST API
  - Windows/Mac/Linux 지원
  - IP 기반 인증
- [ ] 업비트 API 연동 (암호화폐)
- [ ] 공통 데이터 타입으로 응답 정규화

---
*Created: 2026-01-31*
