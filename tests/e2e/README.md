# E2E (End-to-End) Tests

## Overview

이 디렉토리는 My Prime Jennie 트레이딩 시스템의 전체 플로우를 테스트하는 E2E 테스트를 포함합니다.

## 디렉토리 구조

```
tests/e2e/
├── README.md
├── conftest.py           # Pytest fixtures
├── mock_server/
│   ├── kis_mock_server.py  # Flask 기반 Mock KIS Gateway
│   └── scenarios.py        # 테스트 시나리오 정의
├── fixtures/
│   ├── redis_fixtures.py   # Redis Streams 시뮬레이터
│   └── rabbitmq_fixtures.py # RabbitMQ Mock
├── test_buy_flow.py       # 매수 플로우 테스트
├── test_sell_flow.py      # 매도 플로우 테스트
├── test_risk_gates.py     # Risk Gate 테스트
├── test_error_handling.py # 에러 핸들링 테스트
└── test_full_cycle.py     # 전체 사이클 테스트
```

## 실행 방법

### 로컬 빠른 테스트 (Mock 모드)

```bash
# E2E 테스트만 실행
.venv/bin/pytest tests/e2e/ -v -m e2e

# 특정 테스트 파일 실행
.venv/bin/pytest tests/e2e/test_buy_flow.py -v

# 특정 테스트 클래스 실행
.venv/bin/pytest tests/e2e/test_buy_flow.py::TestBuyFlow -v
```

### Docker 인프라와 함께 (CI 환경)

```bash
# 인프라 시작
docker-compose -f tests/docker/docker-compose.e2e.yml up -d

# 테스트 실행
.venv/bin/pytest tests/e2e/ -v -m e2e --tb=short

# 인프라 정리
docker-compose -f tests/docker/docker-compose.e2e.yml down
```

## 테스트 카테고리

### 1. Buy Flow (`test_buy_flow.py`)
- ✅ 골든크로스 시그널 → 매수 실행 → DB 업데이트
- ✅ 일일 매수 한도 초과 시 차단
- ✅ Emergency Stop 시 전체 차단
- ✅ LLM 점수 미달 시 스킵
- ✅ 이미 보유 종목 스킵
- ✅ TIER2/RECON 비중 차등화

### 2. Sell Flow (`test_sell_flow.py`)
- ✅ 손절가 도달 → 매도 실행
- ✅ 목표가 도달 → 익절 실행
- ✅ RSI 과열 → 매도 실행
- ✅ 보유 기간 초과 → 시간 청산
- ✅ 수동 매도 허용 (Emergency Stop 중에도)

### 3. Risk Gates (`test_risk_gates.py`)
- ✅ Min Bars (20개 미만 차단)
- ✅ No-Trade Window (09:00-09:15 차단)
- ✅ Danger Zone (14:00-15:00 차단)
- ✅ RSI Guard (RSI > 75 차단)
- ✅ Volume Gate (거래량 2x 초과 주의)
- ✅ VWAP Gate (가격 > VWAP*1.02 주의)
- ✅ Combined Risk (2개 이상 위험 조건 차단)
- ✅ Cooldown (600초 내 재진입 차단)

### 4. Error Handling (`test_error_handling.py`)
- ✅ KIS Gateway 타임아웃 처리
- ✅ KIS Gateway 500 에러 처리
- ✅ Redis 연결 실패 처리
- ✅ RabbitMQ 연결 실패 처리
- ✅ 잘못된 데이터 처리

### 5. Full Cycle (`test_full_cycle.py`)
- ✅ 완전한 Buy→Hold→Sell 사이클
- ✅ 다중 종목 동시 거래
- ✅ 포트폴리오 분산 제한
- ✅ 메시지 큐 통합 테스트
- ✅ 가격 스트림 통합 테스트

## Mock 서버

### KISMockServer

Flask 기반 Mock HTTP 서버로 KIS Gateway API를 시뮬레이션합니다.

**지원 엔드포인트:**
- `GET /health` - 헬스 체크
- `POST /api/trading/buy` - 매수 주문
- `POST /api/trading/sell` - 매도 주문
- `GET /api/market-data/snapshot/<code>` - 현재가 조회
- `GET /api/account/cash-balance` - 예수금 조회
- `GET /api/account/balance` - 잔고 조회
- `GET /api/market-data/check-market-open` - 장 상태

**시나리오:**
- `empty_portfolio` - 빈 포트폴리오 (매수 테스트용)
- `with_holdings` - 보유 종목 있음 (매도 테스트용)
- `stop_loss_scenario` - 손절가 도달 상태
- `take_profit_scenario` - 목표가 도달 상태
- `emergency_stop` - 긴급 중지 활성화
- `server_error` - 서버 에러 시뮬레이션

## Fixture 사용법

```python
@pytest.mark.e2e
def test_example(kis_server, mock_kis_client, e2e_redis, mq_bridge):
    # kis_server: Mock KIS Gateway 서버
    # mock_kis_client: KIS API 클라이언트
    # e2e_redis: Streams 지원 FakeRedis
    # mq_bridge: RabbitMQ 테스트 브릿지

    # 시나리오 활성화
    scenario = kis_server.activate_scenario("empty_portfolio")
    scenario.add_stock("005930", "삼성전자", 70000)

    # 테스트 로직...
```

## 참고사항

- E2E 테스트는 기본 pytest 실행에서 제외됩니다 (`-m 'not e2e'`)
- 명시적으로 `-m e2e` 옵션으로 실행해야 합니다
- 테스트 간 상태 격리를 위해 각 테스트 후 fixture가 자동 정리됩니다
