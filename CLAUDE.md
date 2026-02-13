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

### 핵심 서비스
| 서비스 | 포트 | 설명 |
|--------|------|------|
| kis-gateway | 8080 | 한국투자증권 API 게이트웨이 |
| scout-job | 8087 | AI 종목 발굴 (1시간 간격) |
| scout-worker | - | Scout 전용 워커 (포트 바인딩 없음) |
| buy-scanner | 8081 | 실시간 매수 기회 감시 |
| buy-executor | 8082 | 매수 주문 실행 |
| sell-executor | 8083 | 매도 주문 실행 |
| price-monitor | 8088 | 실시간 가격 모니터링 |
| command-handler | 8091 | 텔레그램 명령 처리 |
| daily-briefing | 8086 | 일일 브리핑 생성 |
| dashboard-backend | 8090 | 대시보드 API (FastAPI) |
| dashboard-frontend | 80 | 대시보드 UI (Nginx) |
| airflow-webserver | 8085 | Airflow UI |

### 인프라 서비스
| 서비스 | 포트 | 프로파일 | 설명 |
|--------|------|----------|------|
| vllm-llm | 8001 | infra | EXAONE 4.0 32B AWQ (메인 추론) |
| vllm-embed | 8002 | infra | KURE-v1 (임베딩 전용) |
| qdrant | 6333/6334 | infra | 벡터 DB (뉴스 RAG) |
| mariadb | 3307 | infra | 영구 저장소 |
| redis | 6379 | infra | 캐시, 실시간 상태, 메시지 큐 (Redis Streams) |
| grafana | 3300 | infra | 모니터링 대시보드 |
| loki | 3400 | infra | 로그 집계 |
| cloudflared | - | infra | Cloudflare Tunnel |
| jenkins | 8180 | ci | CI/CD 서버 |
| ollama | 11434 | gpu-legacy | Ollama (레거시) |

## 3. LLM 구성

### 3.1 로컬 LLM (vLLM 직접 호출)
```yaml
# OllamaLLMProvider → vLLM OpenAI-compatible API 직접 호출
# vllm-llm: EXAONE 4.0 32B AWQ (포트 8001, VLLM_LLM_URL)
# vllm-embed: KURE-v1 (포트 8002, VLLM_EMBED_URL)

LLM Tiers:
  FAST: exaone3.5:7.8b (로컬 vLLM)  # 빠른 응답 (뉴스 요약 등)
  REASONING: deepseek_cloud           # CloudFailoverProvider (OpenRouter → DeepSeek → Ollama Cloud)
  THINKING: deepseek_cloud            # CloudFailoverProvider (OpenRouter → DeepSeek → Ollama Cloud)
```

### 3.2 Cloud LLM (CloudFailoverProvider)
- **deepseek_cloud**: REASONING/THINKING 티어 (OpenRouter → DeepSeek API → Ollama Cloud 자동 failover)
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
| scout_job_v1 | 08:30-15:30, 1시간 간격 | AI 종목 스캔 (KOSPI+KOSDAQ, Unified Analyst) |
| enhanced_macro_collection | 07:00, 12:00, 18:00 | 글로벌 매크로 수집 |
| enhanced_macro_quick | 09:30-14:30, 1시간 간격 | 장중 매크로 빠른 업데이트 (pykrx) |
| macro_council | 07:30 | 3현자 매크로 분석 |
| collect_minute_chart | 09:00-15:35, 5분 간격 | 5분봉 수집 |
| daily_market_data_collector | 16:00 | KOSPI 일봉 수집 |
| daily_asset_snapshot | 15:45 | 일일 자산 스냅샷 (총자산, 현금, 주식평가) |
| daily_briefing_report | 17:00 | 일일 브리핑 발송 |
| daily_ai_performance | 07:00 | AI 의사결정 성과 분석 |
| analyst_feedback_update | 18:00 | 분석가 피드백 |
| collect_investor_trading | 18:30 | 수급 데이터 |
| collect_foreign_holding_ratio | 18:35 | 외국인 지분율 수집 (pykrx) |
| collect_dart_filings | 18:45 | DART 공시 |
| price_monitor_ops | 09:00 | 가격 모니터 시작 |
| price_monitor_stop_ops | 15:30 | 가격 모니터 중지 |
| update_naver_sectors_weekly | 일요일 20:00 | 네이버 업종 분류 업데이트 (79개 세분류) |
| weekly_factor_analysis | 금요일 22:00 | 주간 팩터 분석 |
| data_cleanup_weekly | 일요일 03:00 | 오래된 데이터 정리 |

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
│   ├── airflow/
│   └── ...
├── shared/             # 공유 모듈
│   ├── broker/        # 멀티 브로커 추상화
│   ├── crawlers/      # 네이버 섹터 크롤러 등
│   ├── db/            # SQLAlchemy 모델, Repository
│   ├── hybrid_scoring/ # Quant Scorer v1/v2, HybridScorer
│   ├── kis/           # 한투 API 클라이언트
│   ├── macro_insight/ # 매크로 인사이트
│   ├── llm.py         # JennieBrain (LLM 오케스트레이션)
│   ├── llm_factory.py # LLMFactory (Tier→Provider 라우팅)
│   ├── llm_providers.py # Provider 구현체 (Ollama, OpenAI, Claude, Gemini, CloudFailover)
│   ├── sector_classifier.py  # 섹터 분류 v4.0 (네이버 기반)
│   ├── sector_taxonomy.py    # NAVER_TO_GROUP 매핑 (79→14)
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

## 8. Quant Scorer v2 & Unified Analyst Pipeline

### 8.1 Quant Scorer v2 (잠재력 기반)
- **ENV**: `QUANT_SCORER_VERSION=v2` (docker-compose.yml)
- **핵심 전환**: "현재 수준" → "변화/개선" (ROE 트렌드, PER 할인, 센티먼트 모멘텀, 외인비율 추세)
- **배점**: 모멘텀 20 + 품질 20 + 가치 20 + 기술 10 + 뉴스 10 + 수급 20 = 100
- **백테스트 결과**: v2 D+5 IC=+0.095 (v1: -0.056), Top20% Hit Rate 70.6%
- **코드**: `quant_scorer.py` (6개 v2 메서드), `quant_constants.py` (V2_* 상수)

### 8.2 Unified Analyst Pipeline
- **3→1 LLM 호출 통합**: Hunter+Debate+Judge → 1회 `run_analyst_scoring()` (REASONING tier)
- **ENV**: `SCOUT_USE_UNIFIED_ANALYST=true`
- **코드 기반 risk_tag**: `classify_risk_tag(quant_result)` — LLM CAUTION 편향 해소
- **±15pt 가드레일**: `llm_score = clamp(raw, quant-15, quant+15)`
- **Veto Power**: DISTRIBUTION_RISK → is_tradable=False, trade_tier=BLOCKED

### 8.3 동적 섹터 예산 (Dynamic Sector Budget)
- **ENV**: `DYNAMIC_SECTOR_BUDGET_ENABLED=true` (false면 기존 고정 MAX_SECTOR_STOCKS 사용)
- **코드**: `shared/sector_budget.py` (핵심 모듈), Scout `scout.py` (Greedy 선정), Portfolio Guard (동적 cap)
- **티어**: HOT(cap 5, p75 & >0%), WARM(cap 3, 기본), COOL(cap 2, p25 & <0% or FALLING_KNIFE)
- **데이터 흐름**: Scout sector_analysis → 대분류 집계 → 티어 배정 → Redis `sector_budget:active` (TTL 24h) → Portfolio Guard 읽기
- **effective_cap**: `min(watchlist_cap, max(0, portfolio_cap - held) + 1)` — 보유 종목 수 반영
- **Fallback**: Redis 실패/비활성 → 기존 MAX_SECTOR_STOCKS=3 고정값

### 8.4 네이버 섹터 분류 (Single Source of Truth)
- **79개 세분류 → 14개 대분류**: `STOCK_MASTER.SECTOR_NAVER` 컬럼
- **초기 실행**: `python utilities/update_naver_sectors.py`
- **주간 배치**: `update_naver_sectors_weekly` DAG (일요일 20:00)

## 9. 설정 파일

| 파일 | 용도 |
|------|------|
| `docker-compose.yml` | 서비스 정의 |
| `secrets.json` | API 키 (gitignore) |
| `infrastructure/env-vars-wsl.yaml` | 환경 변수 |
| `Jenkinsfile` | CI/CD 파이프라인 |

## 10. Docker 빌드 최적화

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

## 11. 테스트

```bash
# 전체 테스트
.venv/bin/pytest tests/ -v

# 특정 서비스 테스트
.venv/bin/pytest tests/services/price-monitor/ -v

# 공유 모듈 테스트
.venv/bin/pytest tests/shared/ -v
```

## 12. 운영 명령어

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

## 13. 자주 발생하는 문제

### 13.1 패키지 누락
- 증상: `ModuleNotFoundError: No module named 'xxx'`
- 해결: 해당 서비스의 `requirements.txt`에 패키지 추가
- 예: scout-job에 pytz 누락 → `services/scout-job/requirements.txt`에 추가

### 13.2 Airflow DAG 실패
- 로그 확인: `docker logs my-prime-jennie-airflow-scheduler-1 2>&1 | grep -i "dag_name"`
- 태스크 로그: Airflow UI (localhost:8085) → DAG → Graph → Task → Log

### 13.3 시간 기반 테스트 실패
- 원인: `_check_no_trade_window`, `_check_danger_zone` 등이 현재 시간에 따라 False 반환
- 해결: 테스트에서 해당 메서드 mock 필요

### 13.4 코드 손실 (CRITICAL - 2026-02-03 사건)

#### 사건 개요
2026-02-02 세션에서 구현한 `Macro.tsx` 프론트엔드 페이지가 완전히 사라짐. 사용자가 분명히 기억하는 기능 (날짜 드롭다운, 자동차 섹터 회피 등)이 존재하지 않았음.

#### 원인 분석
1. 세션 종료 시 `git add` 명령에 **신규 파일이 누락**됨
2. 백엔드 파일만 커밋되고, 프론트엔드 `Macro.tsx`는 스테이징 안됨
3. `git push`는 수행되었으나 해당 파일은 커밋에 포함되지 않음
4. Docker 이미지 재빌드 시 호스트의 uncommitted 파일은 포함되지 않음

#### 복구 방법
Claude 세션 히스토리 (.jsonl 파일)에서 원본 코드 발견:
```bash
# 세션 히스토리 위치
~/.claude/projects/-home-youngs75-projects-my-prime-jennie/*.jsonl

# Write tool 사용 내역에서 file_path로 검색
python3 -c "
import json
with open('SESSION_ID.jsonl') as f:
    for line in f:
        data = json.loads(line)
        # tool_use 중 Write tool의 file_path 확인
"
```

#### 방지책 (필수 체크리스트)

**세션 종료 전:**
```bash
# 1. 모든 변경 확인
git status

# 2. untracked 파일 확인 (신규 파일!)
git ls-files --others --exclude-standard

# 3. 변경 내용 확인
git diff --stat

# 4. 신규 파일 포함하여 스테이징
git add [변경된_파일들] [신규_파일들]

# 5. 커밋 & 푸시
git commit -m "..."
git push
```

**Pre-push 훅 (이미 설치됨):**
`.githooks/pre-push`가 uncommitted 변경을 경고함

#### 교훈
- **신뢰하되 검증하라**: `git add .`보다 명시적 파일 지정이 안전하지만, 반드시 `git status`로 확인
- **신규 파일은 특히 주의**: 기존 파일 수정은 `git diff`로 보이지만, 신규 파일은 `--others` 옵션 필요
- **세션 히스토리는 최후의 보루**: Claude 세션 .jsonl 파일에서 Write tool 내역으로 복구 가능

## 14. 세션 Handoff

> **상세 세션 기록**: `.ai/sessions/session-YYYY-MM-DD-HH-MM.md`
> **변경 이력**: `docs/changelogs/CHANGELOG-YYYY-MM.md`

### 최근 세션 요약

| 날짜 | 주제 | 세션 파일 |
|------|------|----------|
| 2026-02-13 | 동적 섹터 예산 + cancel_order 버그 수정 + 계좌 동기화 | `session-2026-02-13-10-30.md` |
| 2026-02-13 (아침) | Scout Worker 장애 진단: langchain_openai 누락 + 섹터 모멘텀 0% | `session-2026-02-13-08-24.md` |
| 2026-02-12 (밤) | 인프라 단순화: RabbitMQ→Redis Streams, Ollama Gateway 제거 | `session-2026-02-12-23-00.md` |
| 2026-02-12 | news-archiver Qdrant 장애 복구 + pending 자동 복구 | `session-2026-02-12-22-10.md` |
| 2026-02-11 (밤) | 모멘텀 전략 지정가 주문 + 확인 바 (고점 매수 방지) | `session-2026-02-11-23-00.md` |

### 현재 시스템 상태 (2026-02-13)

- **메시징**: RabbitMQ 제거 → Redis Streams (`shared/messaging/trading_signals.py`)
- **LLM**: vLLM 직접 호출 (Ollama Gateway 제거), OllamaLLMProvider → `/v1/chat/completions`
- **Scout**: Unified Analyst Pipeline (1-pass LLM), Quant Scorer v2 프로덕션, **동적 섹터 예산**
- **LLM Stats**: 서비스별 Redis 기록 (scout, briefing, macro_council) — Dashboard 자동 표시
- **벡터DB**: Qdrant + vLLM KURE-v1 임베딩 (langchain-openai)
- **섹터**: 네이버 업종 분류 Single Source of Truth (79개 세분류 → 14개 대분류)
- **뉴스**: Redis 영속 중복 체크 (NewsDeduplicator), pending 자동 복구
- **Dashboard**: Macro Insight 카드, 자산 스냅샷, LLM 사용 통계
- **Portfolio Guard**: 동적 섹터 예산 연동 (HOT/WARM/COOL cap) + 국면별 현금 하한선
- **모멘텀 실행 최적화**: 지정가 주문 + 확인 바 + cancel_order 수정 완료
- **테스트**: 1202 shared + 174 services passed

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
*Last Updated: 2026-02-13*
*상세 변경 이력은 `.ai/sessions/` 및 `docs/changelogs/` 참조*
