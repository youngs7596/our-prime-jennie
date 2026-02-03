# My Prime Jennie - AI Trading System

> Claude Code가 참조하는 시스템 아키텍처 및 운영 지식 문서

## 1. 시스템 개요

한국 주식시장(KOSPI/KOSDAQ) 자동 매매 시스템. MSA 기반 Docker Compose 배포.

### 핵심 구성요소
```
┌─────────────────────────────────────────────────────────────────┐
│                        Airflow Scheduler                         │
│  (DAGs: scout_job, macro_council, collect_*, price_monitor)      │
└─────────────────────────────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│  scout-job  │      │ buy-scanner │      │price-monitor│
│ (종목 발굴) │      │(매수 기회)   │      │ (실시간 감시)│
└─────────────┘      └─────────────┘      └─────────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              ▼
                    ┌─────────────────┐
                    │   buy-executor  │
                    │   sell-executor │
                    │  (주문 실행)    │
                    └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │   kis-gateway   │
                    │  (한투 API 연동)│
                    └─────────────────┘
```

## 2. 서비스 목록

| 서비스 | 포트 | 설명 |
|--------|------|------|
| kis-gateway | 8080 | 한국투자증권 API 게이트웨이 |
| scout-job | 8087 | AI 종목 발굴 (30분 간격) |
| buy-scanner | 8088 | 실시간 매수 기회 감시 |
| buy-executor | 8089 | 매수 주문 실행 |
| sell-executor | 8090 | 매도 주문 실행 |
| price-monitor | 8091 | 실시간 가격 모니터링 |
| command-handler | 8092 | 텔레그램 명령 처리 |
| daily-briefing | 8093 | 일일 브리핑 생성 |
| ollama-gateway | 11500 | 로컬 LLM 요청 큐잉/라우팅 |
| airflow-webserver | 8085 | Airflow UI |
| dashboard-backend | 8100 | 대시보드 API |
| dashboard-frontend | 3000 | 대시보드 UI |

## 3. LLM 구성

### 3.1 로컬 LLM (Ollama via ollama-gateway)
```yaml
# config/env-vars-wsl.yaml 기준
LLM Tiers:
  FAST: exaone3.5:7.8b      # 빠른 응답 (뉴스 요약 등)
  REASONING: gpt-oss:20b    # 복잡한 추론
  THINKING: gpt-oss:20b     # 심층 분석
```

### 3.2 Cloud LLM
- **Gemini (Jennie)**: 메인 분석
- **Claude (Minji)**: 보조 분석, 검증
- **GPT-4o (Junho)**: 토론/판정

### 3.3 3현자 Council
`scripts/ask_prime_council.py`로 3개 LLM 동시 분석 후 종합 리포트 생성
- 비용: ~$0.20/회 (~290원)
- 용도: 매크로 분석, 코드 리뷰, 전략 검토

## 4. 스케줄링 (Airflow)

### DAG 위치
`dags/` 디렉토리

### 주요 스케줄
| DAG | 스케줄 (KST) | 설명 |
|-----|-------------|------|
| scout_job_v1 | 08:30-15:30, 30분 간격 | AI 종목 스캔 (KOSPI+KOSDAQ) |
| enhanced_macro_collection | 07:00, 12:00, 18:00 | 글로벌 매크로 수집 |
| macro_council | 07:30 | 3현자 매크로 분석 |
| collect_intraday | 09:00-15:35, 5분 간격 | 5분봉 수집 |
| daily_market_data_collector | 16:00 | KOSPI 일봉 수집 |
| daily_kosdaq_price_collector | 16:30 | KOSDAQ 일봉 수집 |
| weekly_kosdaq_stock_master | 일요일 22:00 | KOSDAQ 마스터 업데이트 |
| collect_investor_trading | 18:30 | 수급 데이터 |
| collect_dart_filings | 18:45 | DART 공시 |
| analyst_feedback_update | 18:00 | 분석가 피드백 |

## 5. 매매 로직

### 5.1 BuyOpportunityWatcher (`services/buy-scanner/opportunity_watcher.py`)

#### Risk Gates (순차 체크, 하나라도 실패 시 종료)
1. **Min Bars**: 최소 20개 바 필요
2. **No-Trade Window**: 09:00-09:30 진입 금지 (장초 노이즈)
3. **Danger Zone**: 14:00-15:00 진입 금지 (통계적 손실 구간)
4. **RSI Guard**: RSI > 75 진입 금지 (과열)
5. **Volume Gate**: 거래량 > 2x 평균 시 주의
6. **VWAP Gate**: 가격 > VWAP * 1.02 시 주의
7. **Combined Risk**: 2개 이상 위험 조건 시 차단
8. **Cooldown**: 최근 신호 발생 종목 재진입 방지

#### 전략 (Market Regime별)
**Bull Market (BULL, STRONG_BULL):**
- RECON_BULL_ENTRY, MOMENTUM_CONTINUATION
- SHORT_TERM_HIGH_BREAKOUT, VOLUME_BREAKOUT_1MIN
- BULL_PULLBACK, VCP_BREAKOUT, INSTITUTIONAL_ENTRY

**일반 전략:**
- GOLDEN_CROSS, RSI_REBOUND, MOMENTUM

### 5.2 Market Regime Detection (`shared/market_regime.py`)
- STRONG_BULL, BULL, NEUTRAL, BEAR, STRONG_BEAR
- KOSPI/KOSDAQ 지수 + 등락 비율 + 거래대금 기반

## 6. 매크로 인사이트

### 6.1 텔레그램 채널
- **@hedgecat0301**: 키움 한지영 (장 시작 전 브리핑)

### 6.2 데이터 흐름
```
Telegram → telegram-collector → 3현자 Council → DB/Redis
                                                    ↓
                              서비스들 (scout, buy-scanner, price-monitor)
```

### 6.3 DB 테이블
```sql
DAILY_MACRO_INSIGHT (
  INSIGHT_DATE, SENTIMENT, SENTIMENT_SCORE,
  REGIME_HINT, SECTOR_SIGNALS, KEY_THEMES,
  RISK_FACTORS, KEY_STOCKS, COUNCIL_COST_USD, ...
)
```

### 6.4 서비스 활용 함수 (`shared/macro_insight/`)
```python
from shared.macro_insight import (
    get_today_insight,          # 오늘 인사이트 조회
    get_position_multiplier,    # 포지션 사이즈 배율 (0.7~1.3x)
    get_sector_signal,          # 섹터별 신호
    is_high_volatility_regime,  # 고변동성 여부
    get_stop_loss_multiplier,   # 손절 폭 배율
    should_skip_sector,         # 섹터 스킵 여부
)
```

## 7. 주요 디렉토리

```
my-prime-jennie/
├── services/           # 마이크로서비스들
│   ├── scout-job/
│   ├── buy-scanner/
│   ├── buy-executor/
│   ├── sell-executor/
│   ├── price-monitor/
│   ├── kis-gateway/
│   ├── ollama-gateway/
│   ├── airflow/
│   └── ...
├── shared/             # 공유 모듈
│   ├── broker/        # 멀티 브로커 추상화 (NEW)
│   ├── kis/           # 한투 API 클라이언트
│   ├── macro_insight/ # 매크로 인사이트
│   ├── database.py    # DB 연결
│   ├── config.py      # 설정 관리
│   └── market_regime.py
├── dags/               # Airflow DAGs
├── scripts/            # 유틸리티 스크립트
├── config/             # 설정 파일
├── prompts/            # LLM 프롬프트
├── schemas/            # JSON 스키마
└── tests/              # 테스트
```

## 8. 설정 파일

| 파일 | 용도 |
|------|------|
| `docker-compose.yml` | 서비스 정의 |
| `secrets.json` | API 키 (gitignore) |
| `config/env-vars-wsl.yaml` | 환경 변수 |
| `config/secrets.json` | DB/API 자격증명 |
| `Jenkinsfile` | CI/CD 파이프라인 |

## 9. Docker 빌드 최적화

### Layer Caching 패턴
```dockerfile
# 1. 의존성 먼저 (드물게 변경)
COPY requirements.txt /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# 2. 소스 코드 (자주 변경)
COPY shared/ /app/shared/
COPY services/xxx/*.py /app/
```

### BuildKit 활성화
```yaml
# Jenkinsfile
environment {
    DOCKER_BUILDKIT = '1'
    COMPOSE_DOCKER_CLI_BUILD = '1'
}
```

## 10. 테스트

```bash
# 전체 테스트
.venv/bin/pytest tests/ -v

# 특정 서비스 테스트
.venv/bin/pytest tests/services/price-monitor/ -v

# 공유 모듈 테스트
.venv/bin/pytest tests/shared/ -v
```

## 11. 운영 명령어

```bash
# 서비스 로그
docker logs my-prime-jennie-scout-job-1 -f

# Airflow 로그
docker logs my-prime-jennie-airflow-scheduler-1 2>&1 | grep -i error

# 서비스 재시작
docker compose -p my-prime-jennie --profile real up -d --build scout-job

# 전체 재배포
docker compose -p my-prime-jennie --profile real up -d --build --force-recreate
```

## 12. 자주 발생하는 문제

### 12.1 패키지 누락
- 증상: `ModuleNotFoundError: No module named 'xxx'`
- 해결: 해당 서비스의 `requirements.txt`에 패키지 추가
- 예: scout-job에 pytz 누락 → `services/scout-job/requirements.txt`에 추가

### 12.2 Airflow DAG 실패
- 로그 확인: `docker logs my-prime-jennie-airflow-scheduler-1 2>&1 | grep -i "dag_name"`
- 태스크 로그: Airflow UI (localhost:8085) → DAG → Graph → Task → Log

### 12.3 시간 기반 테스트 실패
- 원인: `_check_no_trade_window`, `_check_danger_zone` 등이 현재 시간에 따라 False 반환
- 해결: 테스트에서 해당 메서드 mock 필요

## 13. 세션 Handoff

> **상세 세션 기록**: `.ai/sessions/session-YYYY-MM-DD-HH-MM.md`
> **변경 이력**: `docs/changelogs/CHANGELOG-YYYY-MM.md`

### 최근 세션 요약

| 날짜 | 주제 | 세션 파일 |
|------|------|----------|
| 2026-02-03 | Macro Council 수정, Dashboard Macro Insight 카드 | `session-2026-02-03-21-00.md` |
| 2026-02-02 | 정치 뉴스 Council 통합, 투자자 수급 데이터 | `session-2026-02-02-23-00.md` |

### 현재 시스템 상태 (2026-02-03)

- **Scout**: KOSPI + KOSDAQ 통합 완료 (v1.1)
- **Council**: 정치 뉴스 + 투자자 수급 + 트레이딩 권고 기능 완료
- **Dashboard**: Macro Insight 카드 추가 (VIX, 수급, 전략 권고)
- **트레이딩 서비스**: 매크로 컨텍스트 통합 완료 (buy-scanner, scout-job, price-monitor)
- **테스트**: 1136 passed, 2 skipped

### 주요 데이터 흐름

```
[매크로 수집] enhanced_macro_collection (07:00, 12:00, 18:00)
     ↓
[Council 분석] macro_council (07:30) → DAILY_MACRO_INSIGHT
     ↓
[트레이딩 서비스] EnhancedTradingContext
     ↓
[Dashboard] /api/macro/insight
```

---
*Last Updated: 2026-02-03*
*상세 변경 이력은 `.ai/sessions/` 및 `docs/changelogs/` 참조*
