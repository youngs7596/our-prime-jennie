# 운영 가이드: Fact-Checker & Circuit Breaker

## 1. Fact-Checker (LLM 환각 탐지)

### 개요
Scout Pipeline에서 LLM이 생성한 뉴스 분석이 원문과 일치하는지 검증합니다.

### 사용법
```python
from shared.fact_checker import get_fact_checker

checker = get_fact_checker()
result = checker.check(
    original_news="삼성전자가 10조원 투자를 발표했다.",
    llm_analysis="삼성전자는 10조원 투자 계획을 밝혔다.",
    stock_name="삼성전자"
)

if result.has_hallucination:
    print(f"경고: {result.warnings}")
```

### 검증 항목
- **숫자 검증**: 분석에 언급된 숫자가 원문에 존재하는지 (40% 이상 일치)
- **날짜 검증**: 분석에 언급된 날짜가 원문에 존재하는지 (50% 이상 일치)
- **키워드 검증**: 핵심 키워드가 원문에 있는지 (40% 이상 일치)

### 결과 해석
| confidence | 의미 |
|------------|------|
| ≥0.7 | 높은 신뢰도, 안전 |
| 0.5~0.7 | 주의 필요, 검토 권장 |
| <0.5 | 환각 가능성 높음, 사용 자제 |

---

## 2. Circuit Breaker (KIS API 장애 대응)

### 개요
KIS API 연속 실패 시 자동 차단하여 시스템 안정성 보장합니다.

### 상태 다이어그램
```
CLOSED ──(5회 실패)──→ OPEN ──(백오프 대기)──→ HALF_OPEN
    ↑                                              │
    └─────────(3회 연속 성공)───────────────────────┘
```

### 사용법
```python
from shared.kis.circuit_breaker import get_kis_circuit_breaker

cb = get_kis_circuit_breaker()

# 함수 보호
@cb.protect
def call_kis_api():
    return kis.get_stock_price("005930")

# 상태 확인
status = cb.get_status()
print(f"상태: {status['state']}, 가용: {status['is_available']}")

# 수동 리셋 (긴급 상황)
cb.reset()
```

### 설정값
| 항목 | 기본값 | 설명 |
|------|--------|------|
| failure_threshold | 5 | OPEN 전환 실패 횟수 |
| success_threshold | 3 | CLOSED 복구 성공 횟수 |
| initial_backoff | 5초 | 초기 대기 시간 |
| max_backoff | 120초 | 최대 대기 시간 |
| backoff_multiplier | 2.0 | 백오프 증가 배수 |

### Exponential Backoff
연속 장애 시 대기 시간이 2배씩 증가합니다:
- 1차 장애: 5초 대기
- 2차 장애: 10초 대기
- 3차 장애: 20초 대기
- ... 최대 120초

---

## 3. 장애 대응 플레이북

### 3.1 Circuit Breaker OPEN 시

1. **확인**: Telegram 알림 또는 로그에서 상태 확인
2. **원인 분석**: KIS API 서버 상태, 네트워크 확인
3. **조치**:
   - 일시적 장애: 자동 복구 대기 (HALF_OPEN → CLOSED)
   - 지속적 장애: 수동 리셋 후 원인 제거
   ```python
   cb = get_kis_circuit_breaker()
   cb.reset()
   ```

### 3.2 환각 경고 발생 시

1. **확인**: 해당 종목의 LLM 분석 내용 검토
2. **조치**:
   - 일시적: 해당 종목 매수 신호 무시
   - 반복적: 프롬프트 검토, 뉴스 소스 확인

### 3.3 서비스 연결 실패 시

1. Docker 상태 확인: `docker compose ps`
2. 로그 확인: `docker compose logs <서비스>`
3. 재시작: `docker compose restart <서비스>`

---

## 4. 모니터링 알림 설정

```python
from shared.monitoring_alerts import init_monitoring_alerts
from shared.notification import TelegramBot

# 초기화
bot = TelegramBot()
alerts = init_monitoring_alerts(bot)

# Circuit Breaker 이벤트
alerts.notify_circuit_breaker_state("KIS_API", "OPEN", failure_count=5, next_retry=10)

# 환각 경고
alerts.notify_hallucination_detected("삼성전자", 0.3, ["원문에 없는 숫자"])
```
