# 🤖 my-prime-jennie (CSC) - 자율 진화형 AI 트레이딩 에이전트
> *구 명칭: my-ultra-jennie (Project Jennie)*

**자율 진화형 에이전트 시스템**
my-prime-jennie은 프로젝트의 다음 단계로, AI 에이전트 3인(Jennie, Minji, Junho)이 매일 자율적으로 토론하고, 시스템을 검토하고, 패치를 제안하는 "Daily Council" 기능에 집중합니다.

<div align="center">

![Version](https://img.shields.io/badge/version-2.0.0-blue)
![Python](https://img.shields.io/badge/python-3.12-green)
![Docker](https://img.shields.io/badge/docker-compose-2496ED)
![Airflow](https://img.shields.io/badge/airflow-2.10-017CEE)
![License](https://img.shields.io/badge/license-MIT-yellow)

**멀티 LLM 기반 한국 주식 자율 트레이딩 시스템**

*"AI가 발굴하고, 통계가 검증하고, 사람이 결정한다."*

</div>

---

## 📋 목차

- [AI 세션 관리](#-ai-세션-관리-cross-ide-rules)
- [개요](#-개요)
- [핵심 기능](#-핵심-기능)
- [시스템 아키텍처](#-시스템-아키텍처)
- [서비스 구성](#-서비스-구성)
- [기술 스택](#-기술-스택)
- [빠른 시작](#-빠른-시작)
- [프로젝트 구조](#-프로젝트-구조)
- [주요 모듈](#-주요-모듈)
- [데이터베이스 스키마](#-데이터베이스-스키마)
- [API 문서](#-api-문서)
- [설정](#-설정)
- [테스트](#-테스트)

---

## 🤖 AI 세션 관리 (Cross-IDE Rules)

이 프로젝트는 **Cursor, VS Code, Antigravity, Claude Code** 등 어떤 AI 코딩 환경에서도 일관된 개발 경험을 제공하기 위한 **Cross-IDE 룰 시스템**을 갖추고 있습니다.

### 목적
- 🔄 **IDE/LLM 변경해도** 같은 개발 스타일 유지
- 💰 **토큰 절약** - 전체 히스토리 대신 요약만 로드
- 📋 **작업 연속성** - 세션 간 컨텍스트 인계

### 파일 구조

```
my-prime-jennie/
├── .ai/
│   ├── RULES.md              ← 마스터 룰 (핵심!)
│   └── sessions/             ← 세션 핸드오프 파일 저장
├── .agent/workflows/         ← Antigravity 워크플로우
│   ├── resume.md             ← /resume 명령
│   ├── handoff.md            ← /handoff 명령
│   └── rules.md              ← /rules 명령
├── .cursorrules              ← Cursor IDE용
├── .github/
│   └── copilot-instructions.md  ← VS Code Copilot용
└── CLAUDE.md                 ← Claude Code용
```

### IDE별 동작

| IDE | 룰 파일 | 자동 인식 |
|-----|---------|----------|
| **Cursor** | `.cursorrules` | ✅ 자동 |
| **VS Code Copilot** | `.github/copilot-instructions.md` | ✅ 자동 |
| **Claude Code** | `CLAUDE.md` | ✅ 자동 |
| **Antigravity** | `.agent/workflows/` | 💬 `/resume` 명령 사용 |

### 워크플로우 명령어 (Antigravity)

| 명령어 | 설명 | 언제 사용? |
|--------|------|-----------|
| `/resume` | 이전 세션 이어서 작업 | 새 대화창 시작할 때 |
| `/handoff` | 현재 세션 저장 및 종료 | 토큰 많이 쓰거나 작업 끝날 때 |
| `/rules` | 프로젝트 규칙만 로드 | 규칙 확인만 필요할 때 |

### 사용 예시

```
# 1. 새 대화창에서 이전 작업 이어서 하기
/resume
→ AI: "이전 세션에서 Docker profile 작업했네요. 이어서 할까요?"

# 2. 작업 중간에 정리하고 싶을 때
/handoff 또는 "정리해줘"
→ AI: "세션 저장 완료! .ai/sessions/session-2025-12-12-11-38.md"

# 3. 다른 IDE (Cursor, VS Code)에서는
"이어서 하자" 또는 "세션 파일 읽어줘"
→ 룰 파일 덕분에 자동으로 세션 파일 확인
```

### 권장 타이밍

| 상황 | `/handoff` 권장 |
|------|-----------------|
| 메시지 20~30회 오감 | ✅ 권장 |
| 큰 기능 1개 완료 | ✅ 권장 |
| 파일 5개 이상 수정 | ✅ 권장 |
| AI 응답이 느려짐 | 🚨 필수 |
| 하루 작업 끝 | 🚨 필수 |

---

## 🎯 개요

**my-prime-jennie**는 한국투자증권 Open API를 활용한 AI 기반 자율 트레이딩 에이전트입니다.

3개의 LLM(Gemini, Claude, OpenAI)을 활용한 멀티 에이전트 시스템으로, 정량적 팩터 분석과 LLM 정성 분석을 결합한 **하이브리드 스코어링**으로 투자 판단을 내립니다.

### 주요 특징

| 기능 | 설명 |
|------|------|
| 🧠 **멀티 LLM 판단** | Quant Scorer v2(잠재력) → Unified Analyst(1-pass LLM) 하이브리드 심사 |
| 📊 **하이브리드 스코어링** | 정량 팩터(60%) + LLM 정성 분석(40%) 결합, ±15pt 가드레일 |
| 🎯 **경쟁사 수혜 분석** | 경쟁사 악재 발생 시 반사이익 자동 포착 |
| 📰 **실시간 뉴스 분석** | 뉴스 감성 분석 및 카테고리 자동 분류 |
| 🔄 **마이크로서비스 아키텍처** | Docker Compose 기반 11개 서비스 |
| 📱 **텔레그램 알림** | 매수/매도 체결 실시간 알림 |
| 🛡️ **Fact-Checker** | LLM 환각 탐지 및 Telegram 경고 알림 |
| 🛡️ **Fact-Checker** | LLM 환각 탐지 및 Telegram 경고 알림 |
| 🛡️ **Portfolio Heat Shield** | **[New]** 계좌 파산 방지 (Total Risk Max 5%), 섹터 쏠림 방지 |
| ⚡ **Circuit Breaker** | KIS API 장애 대응 (자동 차단/복구) |
| 📈 **Chart Phase Engine** | **[New]** Weinstein 4단계 차트 파동 분석 (Accumulation/Uptrend/Distribution/Downtrend) |

---

## 🚀 핵심 기능

### 1. Scout Pipeline (종목 발굴)

```
KOSPI+KOSDAQ Universe (200종목)
       ↓
[Phase 1] Quant Scoring v2 (잠재력 기반)
   - 모멘텀20 + 품질20 + 가치20 + 기술10 + 뉴스10 + 수급20 = 100
   - Chart Phase Filter: Stage 4(하락세) 원천 차단
   - Sector Penalty: "Falling Knife" 섹터(-10점)
   - 비용: $0 (LLM 미사용)
   - 상위 25개 종목 선별
       ↓
[Phase 2] Unified Analyst (1-pass LLM, deepseek_cloud)
   - Hunter+Debate+Judge 통합 → run_analyst_scoring()
   - 코드 기반 risk_tag: classify_risk_tag(quant_result)
   - ±15pt 가드레일: llm_score = clamp(raw, quant-15, quant+15)
   - Veto Power: DISTRIBUTION_RISK → is_tradable=False
   - Safety Lock 비대칭: LLM경고 존중 (40:60)
       ↓
Watchlist (상위 15개)
```

> **Legacy 경로**: `SCOUT_USE_UNIFIED_ANALYST=false` 시 기존 2-pass (Hunter→Debate→Judge) 폴백

### 2. 매수/매도 파이프라인

```
[Buy Scanner] → [Buy Executor] → [Price Monitor] → [Sell Executor]
      ↓               ↓                ↓                ↓
 Watchlist 스캔   포지션 사이징      실시간 감시      익절/손절 실행
 기술적 신호 탐지  분산 투자 적용    목표가/손절가    RabbitMQ 연동

**수동 매매(텔레그램) 흐름**

```
Telegram 명령 (/buy, /sell, /sellall)
          ↓
[Command Handler]
 - 인증/레이트리밋/일일 한도
 - DRY_RUN 플래그 포함
 - 큐 발행 (buy-signals / sell-orders)
          ↓
Buy Executor / Sell Executor
 - 기존 리스크/포지션 규칙으로 실행
```
```

### 3. 경쟁사 수혜 분석 시스템

```python
from shared.hybrid_scoring import CompetitorAnalyzer

analyzer = CompetitorAnalyzer()
report = analyzer.analyze('035420')  # NAVER

# 결과 예시
# - 섹터: 이커머스
# - 경쟁사 이벤트: 쿠팡 보안사고
# - 수혜 점수: +10점
# - 디커플링 승률: 62%
```

### 4. 뉴스 카테고리 자동 분류

| 카테고리 | 키워드 | 피해 점수 | 경쟁사 수혜 |
|----------|--------|----------|-------------|
| 보안사고 | 해킹, 유출, 개인정보 | -15점 | +10점 |
| 서비스장애 | 장애, 먹통, 접속불가 | -10점 | +8점 |
| 리콜 | 리콜, 결함, 불량 | -12점 | +7점 |
| 오너리스크 | 구속, 기소, 횡령 | -12점 | +3점 |
| 규제 | 과징금, 제재, 공정위 | -8점 | +5점 |

### 5. Market Flow Analysis (수급 분석)

**"돈의 흐름을 읽는다"**

Scout 파이프라인(Phase 1.8)에서 종목별 투자 주체(외국인/기관/개인)의 매수세를 분석합니다.

- **데이터 소스**: KIS API (`get_investor_trend`)
- **수집 항목**: 외국인 순매수, 기관 순매수, 개인 순매수
- **활용**:
    - LLM 토론 시 근거 자료로 활용 ("외국인이 3일 연속 매집 중입니다.")
    - `MARKET_FLOW_SNAPSHOT` 테이블에 축적하여 향후 패턴 학습에 사용.

### 6. Analyst Module (AI 성과 분석)

**"AI의 실력을 검증한다"**

매일 아침(7시), 전날까지의 AI 매매 의사결정(Hunter/Judge)의 실제 시장 성과(T+5 수익률, 승률)를 분석하여 리포트를 생성합니다.

- **스크립트**: `scripts/analyze_ai_performance.py`
- **주요 기능**:
    - 시장 국면별(Bull/Bear) AI 승률 분석
    - Hunter Score 구간별(S/A/B등급) 성과 검증
    - "고득점인데 손실난 케이스" 피드백 루프 제공

### 7. Self-Healing Pipeline (자율 치유)

**"에러 발생 → 자동 진단 → PR 제안"**

운영 중 발생하는 에러를 표준화된 포맷으로 기록하고, Antigravity Agent가 이를 분석하여 자동으로 수정 PR을 생성하는 파이프라인입니다.

1. **감지 (Detection)**: `FailureReporter`가 에러를 포착하여 `logs/incidents.jsonl`에 기록.
2. **진단 (Diagnosis)**: Agent가 `IncidentReport`를 분석하고 스택 트레이스 기반으로 원인 추론.
3. **제안 (Proposal)**: 수정 가능한 에러(예: 단순 로직, 예외 처리 누락)인 경우 Fix PR 생성.
4. **승인 (Approval)**: 개발자(User)가 PR을 검토하고 승인하면 배포.

> **Guardrails**: 배포 후 이상 징후 감지 시 자동 롤백/거래 중단 (설정: `configs/guardrails.yaml`)

### 8. Fact-Checker (LLM 환각 탐지)

**"AI가 말하는 '사실'을 교차 검증한다"**

LLM이 생성한 분석 결과를 외부 데이터(뉴스, 재무제표 등)와 교차 검증하여 환각(Hallucination)을 탐지합니다.

```python
from shared.fact_checker import FactChecker

checker = FactChecker()
result = checker.verify_claim(
    claim="삼성전자가 2분기 실적을 20% 상회했다",
    stock_code="005930"
)
# Returns: FactCheckResult(is_valid=False, confidence=0.2, reason="실적 발표 전")
```

- **Scout 연동**: Hunter 분석 후 자동 교차 검증
- **Telegram 알림**: `FACT_CHECK_ALERT_ENABLED=true` 시 환각 탐지 시 즉시 알림

### 9. Circuit Breaker (KIS API 장애 대응)

**"API 장애 시 자동 차단 → 복구 시 자동 재개"**

KIS API 연속 실패 시 자동으로 호출을 차단하고, 일정 시간 후 복구를 시도합니다.

```python
from shared.kis.circuit_breaker import CircuitBreaker

cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60)

@cb
def call_kis_api():
    return kis_client.get_balance()
```

| 상태 | 설명 |
|------|------|
| **CLOSED** | 정상 상태, 모든 호출 허용 |
| **OPEN** | 장애 감지, 모든 호출 즉시 실패 반환 |
| **HALF_OPEN** | 복구 시도, 일부 호출만 허용하여 테스트 |

- **상태 변화 알림**: Telegram으로 OPEN/HALF_OPEN/CLOSED 상태 변화 알림

### 10. Risk Management & Safety Guards (Junho's System)

**"Maximize Aggression, Minimize Ruin" (공격성 극대화, 파산 최소화)**

준호(Junho)의 피드백을 반영한 **Risk 1.0% 공격적 트레이딩**과 이를 뒷받침하는 **이중 안전장치**입니다.

- **Portfolio Heat Shield**: 전체 계좌 리스크를 **5%**로 제한. (모든 종목 동시 손절 시에도 -5%로 방어)
- **Dynamic Position Sizing**: 기본 12%, A+ 셋업(LLM≥80) 시 **18%** 베팅.
- **Smart Profit Lock**: ATR 기반으로 수익 반납을 방지하는 동적 익절 트리거.

👉 **상세 내용 보기**: [docs/safety_guards_and_risk.md](docs/safety_guards_and_risk.md)

---

## 🏗 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          my-prime-jennie System                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────────┐    ┌───────────────┐    ┌───────────────┐           │
│  │ News Collector│───▶│    Qdrant     │◀───│  Scout Job    │           │
│  │ (Analyzer/Arch)    │   (RAG)       │    │ (Unified Anl) │           │
│  └───────────────┘    └───────────────┘    └───────────────┘           │
│         │                                          │                    │
│         ▼                                          ▼                    │
│  ┌───────────────┐    ┌───────────────┐    ┌───────────────┐           │
│  │    Redis      │◀───│  KIS Gateway  │───▶│  Buy Scanner  │           │
│  │   (Cache)     │    │               │    │               │           │
│  └───────────────┘    └───────────────┘    └───────────────┘           │
│         │                    │                     │                    │
│         ▼                    ▼                     ▼                    │
│  ┌───────────────┐    ┌───────────────┐    ┌───────────────┐           │
│  │   MariaDB     │◀───│ Price Monitor │───▶│ Buy Executor  │           │
│  │  (Persistent) │    │   (Realtime)  │    │               │           │
│  └───────────────┘    └───────────────┘    └───────────────┘           │
│                              │                     │                    │
│                              ▼                     ▼                    │
│                       ┌───────────────┐    ┌───────────────┐           │
│                       │ Sell Executor │◀───│   RabbitMQ    │           │
│                       │               │    │   (Message)   │           │
│                       └───────────────┘    └───────────────┘           │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│  Dashboard (React + FastAPI)  │  Grafana (Monitoring)  │  Telegram     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 📦 서비스 구성

### 핵심 서비스

| 서비스 | 포트 | 설명 |
|--------|------|------|
| **kis-gateway** | 8080 | 한국투자증권 API 게이트웨이, 토큰 관리 |
| **scout-job** | 8087 | AI 기반 종목 발굴 (Unified Analyst, Quant Scorer v2) |
| **scout-worker** | - | Scout 전용 워커 (포트 바인딩 없음) |
| **buy-scanner** | 8081 | 매수 신호 스캔 (RSI, 볼린저밴드, 돌파) |
| **buy-executor** | 8082 | 매수 주문 실행, 포지션 사이징 |
| **sell-executor** | 8083 | 매도 주문 실행, 익절/손절 |
| **price-monitor** | 8088 | 실시간 가격 모니터링, 매도 신호 발생 |
| **command-handler** | 8091 | 텔레그램 명령 수신 → RabbitMQ 발행 (/buy, /sell, /sellall 등) |
| **news-collector** | - | 네이버 뉴스 수집 (Redis 영속 중복 체크) |
| **news-analyzer** | - | 뉴스 감성/카테고리 분석 (LLM FAST Tier) |
| **news-archiver** | - | 뉴스 벡터 임베딩 및 Qdrant 저장 |
| **daily-briefing** | 8086 | 일간 브리핑 생성 |
| **ollama-gateway** | 11500 | LLM 오케스트레이션 (vLLM/Ollama 투명 전환, Rate Limiter) |
| **dashboard-backend** | 8090 | FastAPI 대시보드 API |
| **dashboard-frontend** | 80 | React 대시보드 UI (Nginx) |
| **telegram-collector** | - | 증권사 리서치 채널 메시지 수집 |
| **macro-aggregator** | - | 매크로 신호 분석 및 집계 |

### 인프라 서비스

| 서비스 | 포트 | 프로파일 | 설명 |
|--------|------|----------|------|
| **vllm-llm** | 8001 | infra | EXAONE 4.0 32B AWQ (메인 추론 엔진) |
| **vllm-embed** | 8002 | infra | KURE-v1 (임베딩 전용) |
| **qdrant** | 6333/6334 | infra | 벡터 DB (뉴스 RAG) |
| **mariadb** | 3307 | infra | 영구 저장소 |
| **redis** | 6379 | infra | 캐시 및 실시간 상태 |
| **rabbitmq** | 5672/15672 | infra | 메시지 큐 (서비스 간 통신) |
| **grafana** | 3300 | infra | 모니터링 대시보드 |
| **loki** | 3400 | infra | 로그 집계 |
| **cloudflared** | - | infra | Cloudflare Tunnel (외부 접근) |
| **jenkins** | 8180 | ci | CI/CD 서버 |
| **airflow** | 8085 | real | 워크플로우 스케줄러 (DAGs) |
| **ollama** | 11434 | gpu-legacy | Ollama (레거시, vLLM 전환 완료) |

### 자동화 작업 (Airflow DAGs)

> DAG 파일은 `dags/` 폴더에 있습니다.

| DAG | 시간 (KST) | 설명 |
|-----|------------|------|
| **scout_job_v1** | 평일 08:30-15:30, 1시간 | AI 종목 발굴 (Unified Analyst + Quant v2) |
| **enhanced_macro_collection** | 평일 07:00, 12:00, 18:00 | 글로벌 매크로 수집 |
| **enhanced_macro_quick** | 평일 09:30-14:30, 1시간 | 장중 매크로 빠른 업데이트 |
| **macro_council** | 평일 07:30 | 3현자 매크로 분석 |
| **collect_minute_chart** | 평일 09:00-15:35, 5분 | 5분봉 수집 |
| **daily_market_data_collector** | 평일 16:00 | KOSPI 일봉 수집 |
| **daily_asset_snapshot** | 평일 15:45 | 일일 자산 스냅샷 |
| **daily_briefing_report** | 평일 17:00 | 브리핑 텔레그램 발송 |
| **daily_ai_performance** | 평일 07:00 | AI 의사결정 성과 분석 |
| **analyst_feedback_update** | 평일 18:00 | 분석가 피드백 |
| **collect_investor_trading** | 평일 18:30 | 수급 데이터 |
| **collect_foreign_holding_ratio** | 평일 18:35 | 외국인 지분율 (pykrx) |
| **collect_dart_filings** | 평일 18:45 | DART 공시 |
| **price_monitor_ops** | 평일 09:00/15:30 | 가격 모니터 시작/중지 |
| **update_naver_sectors_weekly** | 일 20:00 | 네이버 업종 분류 업데이트 |
| **weekly_factor_analysis** | 금 22:00 | 주간 팩터 분석 |
| **data_cleanup_weekly** | 일 03:00 | 오래된 데이터 정리 |

---

## 🛠 기술 스택

### 백엔드
- **Python 3.12** - 핵심 언어
- **Flask / FastAPI** - REST API
- **SQLAlchemy** - ORM
- **Gunicorn / Uvicorn** - WSGI/ASGI 서버

### AI / ML
- **vLLM** - 로컬 LLM 추론 (EXAONE 4.0 32B AWQ, KURE-v1 임베딩)
- **CloudFailoverProvider** - Cloud LLM 자동 failover (OpenRouter → DeepSeek → Ollama Cloud)
- **Anthropic Claude** - 보조 분석, 검증
- **OpenAI GPT** - 토론/판정
- **Google Gemini** - 메인 분석
- **Qdrant** - 벡터 저장소 (뉴스 RAG)

## 🧠 핵심 지능: 탄력적 하이브리드 에이전트 (v2.0)
**"세 명의 회의"** - 세 가지 독특한 페르소나가 이끄는 정교한 의사결정 시스템.

### 아키텍처
- **3-Tier 전략**:
    - **FAST (vLLM `EXAONE 4.0 32B AWQ`)**: 뉴스 감성 분석 & 빠른 반응 (로컬 vLLM).
    - **REASONING (`deepseek_cloud`)**: 심층 분석 (CloudFailoverProvider: OpenRouter → DeepSeek → Ollama Cloud).
    - **THINKING (`deepseek_cloud`)**: 최종 판단 & 전략 (CloudFailoverProvider).

> 🚀 **vLLM 기반 로컬 추론**: EXAONE 4.0 32B AWQ (GPU 0.90) + KURE-v1 임베딩 (GPU 0.05)
> - **총 VRAM 사용량**: ~95% (RTX 3090/4090)
> - **KV Cache**: ~9,792 tokens (`VLLM_MAX_MODEL_LEN=4096`)
> - **부팅 시간**: vllm-embed ~51s, vllm-llm ~120s
> - **REASONING/THINKING**: CloudFailoverProvider로 전환 (비용 최적화 + 품질 향상)

- **탄력성**:
    - **Unified Analyst**: 3→1 LLM 호출 통합, ±15pt 가드레일, 코드 기반 risk_tag.
    - **CloudFailoverProvider**: OpenRouter → DeepSeek → Ollama Cloud 자동 failover.
    - **Quant Scorer v2**: 잠재력 기반 (IC=+0.095, Top20% Hit Rate 70.6%).

### 🎭 스마트 페르소나: 프레임 충돌 토론
기존 에이전트와 달리, 우리의 페르소나는 단순 의견이 아닌 **해석 프레임**의 대립을 기반으로 토론합니다.
- **Minji (분석가)**: **리스크 & 데이터** 관점 (하방 보호).
- **Junho (전략가)**: **기회 & 매크로** 관점 (모멘텀/FOMO).
- **Jennie (심판)**: 토론을 종합하여 최종 실행 결정을 내립니다.

### 데이터
- **MariaDB** - 영구 저장소
- **Redis** - 캐시 및 실시간
- **FinanceDataReader** - 주가 데이터
- **Pandas / NumPy** - 데이터 분석

### 인프라
- **Docker Compose** - 컨테이너 오케스트레이션
- **RabbitMQ** - 메시지 큐
- **Cloudflare Tunnel** - 외부 접근
- **Grafana / Loki** - 모니터링

### 프론트엔드
- **React + TypeScript** - Dashboard
- **Vite** - 빌드 도구

---

## 🚀 빠른 시작

### 사전 요구사항

- Docker & Docker Compose (또는 Docker Desktop for Windows)
- MariaDB (WSL2 또는 Windows에 설치)
- Python 3.12+
- NVIDIA GPU (RTX 3090/4090 권장, vLLM 로컬 추론용)

> ⚠️ **Docker Desktop for Windows 사용 시**: `secrets.json`과 `env-vars-wsl.yaml`에서 `mariadb-host`를 `host.docker.internal`로 설정해야 합니다.

### 1. 환경 설정

     ```bash
# 저장소 클론
git clone https://github.com/youngs7596/my-prime-jennie.git
cd my-prime-jennie

# 시크릿 파일 생성
cp secrets.example.json secrets.json
# secrets.json 편집하여 API 키 입력
```

### 2. secrets.json 설정

```json
{
  "gemini-api-key": "your-gemini-api-key",
  "openai-api-key": "your-openai-api-key",
  "claude-api-key": "your-claude-api-key",
  "dart-api-key": "your-dart-api-key",
  "kis-r-account-no": "your-real-account-number",
  "kis-r-app-key": "your-real-app-key",
  "kis-r-app-secret": "your-real-app-secret",
  "kis-v-account-no": "your-virtual-account-number",
  "kis-v-app-key": "your-virtual-app-key",
  "kis-v-app-secret": "your-virtual-app-secret",
  "telegram-bot-token": "your-telegram-bot-token",
  "telegram-chat-id": "your-telegram-chat-id",
  "cloudflare-tunnel-token": "your-cloudflare-token",
  "mariadb-user": "root",
  "mariadb-password": "your-db-password",
  "mariadb-host": "host.docker.internal",
  "mariadb-database": "jennie_db"
}
```

### 3. 서비스 실행

     ```bash
# 인프라 서비스 먼저 실행 (vLLM 부팅 ~2분 소요)
docker compose --profile infra up -d

# vLLM 부팅 확인 (두 서비스 모두 healthy 대기)
docker compose ps | grep vllm

# Real 모드 (실제 거래)
docker compose --profile real up -d

# Mock 모드 (시뮬레이션)
docker compose --profile mock up -d

# DRY_RUN 강제 켜기 예시 (실수 방지용)
DRY_RUN=true docker compose --profile real up -d command-handler buy-executor sell-executor price-monitor

# 서비스 상태 확인
docker compose ps
```

### 4. 초기 데이터 설정

```bash
# 경쟁사 수혜 분석 테이블 및 데이터 초기화
docker compose run --rm scout-job python scripts/init_competitor_data.py
```

---

## 📅 변경 이력 (Change Log)

전체 변경 이력은 [CHANGELOG.md](./CHANGELOG.md)를 참조하세요.

---

## 📁 프로젝트 구조

```
my-prime-jennie/
├── services/                    # 마이크로서비스
│   ├── scout-job/              # AI 종목 발굴
│   ├── buy-scanner/            # 매수 신호 스캔
│   ├── buy-executor/           # 매수 실행
│   ├── sell-executor/          # 매도 실행
│   ├── price-monitor/          # 가격 모니터링
│   ├── command-handler/        # 텔레그램 명령 처리
│   ├── news-collector/         # [New] 뉴스 수집
│   ├── news-analyzer/          # [New] 뉴스 분석
│   ├── news-archiver/          # [New] 뉴스 저장
│   ├── daily-briefing/         # 일간 브리핑
│   ├── kis-gateway/            # KIS API 게이트웨이
│   ├── scheduler-service/      # 스케줄러
│   ├── cloudflared/            # Cloudflare Tunnel
│   └── dashboard/              # React 대시보드
│       ├── backend/            # FastAPI
│       └── frontend/           # React + TypeScript
│
├── shared/                      # 공유 모듈
│   ├── llm.py                  # LLM 오케스트레이션 (JennieBrain)
│   ├── database.py             # 데이터베이스 유틸리티
│   ├── redis_cache.py          # Redis 캐싱 (의존성 주입 지원)
│   ├── auth.py                 # 인증 및 시크릿 로더
│   ├── config.py               # 설정 관리자
│   ├── rabbitmq.py             # RabbitMQ 클라이언트
│   ├── notification.py         # 텔레그램 알림
│   ├── market_regime.py        # 시장 국면 분석
│   ├── news_classifier.py      # 뉴스 카테고리 분류
│   ├── db/                     # SQLAlchemy 모델
│   │   ├── models.py           # ORM 모델 정의
│   │   ├── connection.py       # DB 연결 관리
│   │   ├── repository.py       # Repository 패턴 (Watchlist, Portfolio)
│   │   └── factor_repository.py # 팩터 분석 Repository
│   ├── hybrid_scoring/         # 하이브리드 스코어링
│   │   ├── quant_scorer.py     # 정량 점수 계산
│   │   ├── hybrid_scorer.py    # 하이브리드 점수 결합
│   │   ├── factor_analyzer.py  # 팩터 분석
│   │   └── competitor_analyzer.py  # 경쟁사 수혜 분석
│   ├── strategies/             # 트레이딩 전략
│   │   ├── pair_trading.py     # 페어 트레이딩
│   │   └── competitor_backtest.py  # 백테스트
│   └── kis/                    # 한국투자증권 API
│       ├── client.py           # KIS 클라이언트
│       └── gateway_client.py   # 게이트웨이 클라이언트
│
├── prompts/                     # LLM 프롬프트
│   └── competitor_benefit_prompt.py
│
├── scripts/                    # 배치 스크립트
│   ├── weekly_factor_analysis_batch.py  # 주간 팩터 분석
│   ├── collect_naver_news.py   # 뉴스 수집
│   ├── collect_dart_filings.py # DART 공시 수집
│   └── run_factor_analysis.py  # 팩터 분석 실행
│
├── configs/                    # 설정 파일
│   └── gpt_v2_strategy_presets.json  # 전략 프리셋
│
├── infrastructure/             # 인프라 설정
│   ├── cloudflared/            # Cloudflare Tunnel 설정
│   ├── env-vars-wsl.yaml       # WSL2 환경변수 (Real)
│   └── env-vars-mock.yaml      # Mock 환경변수
│
├── observability/              # 모니터링
│   ├── grafana/                # Grafana 설정
│   ├── loki/                   # Loki 설정
│   └── promtail/               # Promtail 설정
│
├── tests/                      # 유닛 테스트
│   ├── conftest.py            # pytest fixtures
│   └── shared/                # shared 모듈 테스트
│       ├── db/                # DB Repository 테스트
│       ├── hybrid_scoring/    # 하이브리드 스코어링 테스트
│       └── test_*.py          # 개별 모듈 테스트
│
├── docker-compose.yml          # Docker Compose 설정
├── secrets.json                # API 키 (gitignore)
└── secrets.example.json        # API 키 템플릿
```

---

## 📚 주요 모듈

### JennieBrain (shared/llm.py)

LLM 기반 의사결정 엔진. 멀티 프로바이더(Gemini, Claude, OpenAI)를 지원합니다.

```python
from shared.llm import JennieBrain

brain = JennieBrain()

# 종목 분석 (하이브리드 스코어링)
result = brain.get_jennies_analysis_score_v5(decision_info, quant_context)
# Returns: {'score': 75, 'grade': 'B', 'reason': '...'}

# 뉴스 감성 분석
sentiment = brain.analyze_news_sentiment(title, summary)
# Returns: {'score': 30, 'reason': '악재로 판단'}

# Debate 세션 (Bull vs Bear)
debate_log = brain.run_debate_session(decision_info)

# Judge 최종 판단
judge_result = brain.run_judge_scoring(decision_info, debate_log)
```

### QuantScorer (shared/hybrid_scoring/quant_scorer.py)

정량적 팩터 점수 계산 엔진.

```python
from shared.hybrid_scoring import QuantScorer

scorer = QuantScorer(db_conn, market_regime='BULL')

# 종목 점수 계산
result = scorer.calculate_score(stock_code='005930')
# Returns: QuantScoreResult(
#   momentum_score=75.2,
#   value_score=62.1,
#   quality_score=80.5,
#   technical_score=68.3,
#   final_score=71.5
# )
```

### CompetitorAnalyzer (shared/hybrid_scoring/competitor_analyzer.py)

경쟁사 수혜 분석 모듈.

```python
from shared.hybrid_scoring import CompetitorAnalyzer

analyzer = CompetitorAnalyzer()

# 종목 분석
report = analyzer.analyze('035420')  # NAVER
print(f"수혜 기회: {report.has_opportunity}")
print(f"수혜 점수: +{report.total_benefit_score}")
```

### NewsClassifier (shared/news_classifier.py)

뉴스 카테고리 자동 분류.

```python
from shared.news_classifier import get_classifier

classifier = get_classifier()
result = classifier.classify("쿠팡 3370만명 개인정보 유출")

print(result.category)           # '보안사고'
print(result.sentiment)          # 'NEGATIVE'
print(result.base_score)         # -15
print(result.competitor_benefit) # +10
```

### The Archivist (shared/archivist.py)

**[v1.0] Long-Term Data Strategy implementation.**
Responsibility for the robust recording of all critical data for future AI learning.

- **Decision Ledger**: Records the full context of LLM decisions (Debate, Logic, Outcome).
- **Shadow Radar**: Logs missed opportunities (candidates rejected by filters) for calibration.
- **Market Flow**: Daily snapshot of Foreigner/Institution/Program buy flow.
- **Intraday Data**: targeted 1-minute OHLCV collection for active/rejected candidates.

```python
from shared.archivist import Archivist

archivist = Archivist(session_factory)
archivist.log_decision_ledger({
    'stock_code': '005930',
    'final_decision': 'BUY',
    'reason': 'Dominant market share...',
    'debate_log': '...'
})
```

---

## 🗃 데이터베이스 스키마

### 핵심 테이블

| 테이블 | 설명 |
|--------|------|
| `WATCHLIST` | 관심 종목 목록 + LLM 점수 |
| `PORTFOLIO` | 보유 포트폴리오 |
| `TRADELOG` | 거래 이력 |
| `NEWS_SENTIMENT` | 뉴스 감성 분석 결과 |
| `STOCK_DAILY_PRICES_3Y` | 3년 일봉 데이터 |
| `STOCK_MASTER` | 종목 마스터 (코드, 이름, 섹터) |

### 하이브리드 스코어링 테이블

| 테이블 | 설명 |
|--------|------|
| `FACTOR_METADATA` | 팩터별 IC/IR 통계 |
| `CONDITION_PERFORMANCE` | 복합 조건 성과 |
| `NEWS_FACTOR_STATS` | 뉴스 카테고리별 성과 |

### 경쟁사 수혜 분석 테이블

| 테이블 | 설명 |
|--------|------|
| `INDUSTRY_COMPETITORS` | 산업/경쟁사 매핑 |
| `EVENT_IMPACT_RULES` | 이벤트 영향 규칙 |
| `SECTOR_RELATION_STATS` | 섹터 디커플링 통계 |

---

## 📡 API 문서

### KIS Gateway (8080)

```
GET  /health              # 헬스 체크
GET  /api/token           # 토큰 발급
POST /api/order/buy       # 매수 주문
POST /api/order/sell      # 매도 주문
GET  /api/stock/{code}    # 종목 정보 조회
GET  /api/balance         # 잔고 조회
```

### Scout Job (8087)

```
GET  /health              # 헬스 체크
POST /run                 # Scout 파이프라인 실행
GET  /status              # 파이프라인 상태
```

### Dashboard V2 Backend (8090)

```
GET  /health              # 헬스 체크
GET  /api/watchlist       # Watchlist 조회
GET  /api/portfolio       # 포트폴리오 조회
GET  /api/trades          # 거래 내역
POST /api/commands        # 에이전트 명령
```

---

## ⚙️ 설정

### 환경변수 (infrastructure/env-vars-wsl.yaml)

```yaml
# 데이터베이스
DB_TYPE: MARIADB
MARIADB_HOST: 127.0.0.1
MARIADB_PORT: 3306
MARIADB_USER: root
MARIADB_PASSWORD: your-password
MARIADB_DBNAME: jennie_db

# Redis
REDIS_URL: redis://127.0.0.1:6379/0

# 거래 모드
TRADING_MODE: REAL  # or MOCK

# LLM 점수 기준
MIN_LLM_SCORE: 70  # Real: 70, Mock: 50
```

### Docker Compose 프로파일

```bash
# 인프라 서비스 시작 (먼저 실행 필요)
docker compose --profile infra up -d

# Real 모드 - 실제 거래
docker compose --profile real up -d

# Mock 모드 - 시뮬레이션
docker compose --profile mock up -d

# 또는 한 번에 시작 (infra + real)
docker compose --profile infra --profile real up -d
```

프로파일 요약:
| 프로파일 | 목적 | 비고 |
|----------|------|------|
| `infra` | 인프라 서비스 | MariaDB, Redis, RabbitMQ, Qdrant, Loki, Grafana, Cloudflared, vLLM |
| `real` | 실거래/운영 | 기본 운영용 (infra 프로파일 필요) |
| `mock` | 모의 실행 | 토큰 절약/시뮬레이션 (infra 프로파일 필요) |
| `ci` | CI/CD | Jenkins 서버 |
| `gpu-legacy` | 레거시 GPU | Ollama (vLLM 전환 전 사용) |

### CI/CD (Jenkins)

로컬 WSL2에서 Jenkins 컨테이너가 호스트의 Docker Daemon을 사용해 배포를 진행합니다.

- 위치: `http://localhost:8180` (프로파일 `infra`)
- 이미지: `docker/jenkins/Dockerfile` (Docker CLI 포함)
- 볼륨: `./jenkins_home:/var/jenkins_home`, `/var/run/docker.sock`, `/home/youngs75/projects/my-prime-jennie-main` (배포 전용 워킹트리)
- 파이프라인 동작:
  - `development` 브랜치 push/PR: Unit Test만 실행 (pytest)
  - `main` 브랜치: Unit Test → Docker Build → Deploy (`--profile real`)
- 배포 경로: `/home/youngs75/projects/my-prime-jennie-main` (main 전용 워킹트리, Jenkins가 `git fetch/reset`으로 동기화)
- 필요 Credential: `my-prime-jennie-github` (Username + PAT, scope: `repo`, `admin:repo_hook`)

배포용 워킹트리 준비:
```bash
cd /home/youngs75/projects
git clone https://github.com/youngs7596/my-prime-jennie.git my-prime-jennie-main
cd my-prime-jennie-main && git checkout main
```

재시작:
```bash
docker compose --profile infra down
docker compose --profile infra up -d --build
```

### Mock 모드 설정

Mock 모드는 실제 거래 없이 전체 파이프라인을 테스트할 수 있는 환경입니다.

| 설정 | Real 모드 | Mock 모드 | 설명 |
|------|-----------|-----------|------|
| `TRADING_MODE` | REAL | MOCK | 거래 모드 |
| `DRY_RUN` | false | true | 실제 주문 실행 여부 |
| `MIN_LLM_SCORE` | 70 | 50 | 매수 최소 점수 기준 |
| `RABBITMQ_QUEUE_BUY_SIGNALS` | buy-signals | buy-signals | 텔레그램 매수 요청 전달 큐 |
| `RABBITMQ_QUEUE_SELL_ORDERS` | sell-orders | sell-orders | 텔레그램 매도/청산 전달 큐 |

Mock 모드 특징:
- 🧪 **[MOCK 테스트]** 표시가 텔레그램 알림에 추가
- ⚠️ **[DRY RUN]** 표시로 실제 주문이 아님을 명시
- 💰 LLM 토큰 절약 (토론 생성 건너뜀)

### 텔레그램 수동 명령 (요약)
- 지원 명령: `/pause` `/resume` `/stop 확인|긴급` `/dryrun on|off` `/buy 종목 [수량]` `/sell 종목 [수량|전량]` `/sellall 확인` `/watch` `/unwatch` `/watchlist` `/mute` `/unmute` `/alert` `/alerts` `/status` `/portfolio` `/pnl` `/balance` `/price` `/risk` `/minscore` `/maxbuy` `/config` `/help`
- DRY_RUN이 켜져 있으면 실행 서비스에서 시뮬레이션 처리
- 레이트 리미트(기본 5초) 및 일일 수동 거래 한도(기본 20건) 적용
- 매수/매도/청산은 직접 주문하지 않고 RabbitMQ로 전달 후 executor가 기존 리스크 규칙으로 처리

---

## 📊 모니터링

### Grafana 대시보드

- URL: http://localhost:3300
- 기본 계정: admin / admin

### 로그 조회 (Loki)

```bash
# 특정 서비스 로그
docker compose logs scout-job --tail 50

# Grafana에서 Loki 쿼리
{container_name="scout-job"} |= "ERROR"
```

---

## 🔒 보안 고려사항

- `secrets.json`은 절대 커밋하지 않음 (`.gitignore` 포함)
- API 키는 secrets.json 파일로 관리
- 실제 거래 모드에서는 충분한 테스트 후 운영
- 가상 계좌로 충분히 테스트 후 실계좌 전환

---

## 🧪 테스트

### 테스트 실행

```bash
# 가상환경 활성화
source .venv/bin/activate

# 전체 테스트 실행
pytest tests/shared/ -v

# 커버리지 포함 실행
pytest tests/shared/ --cov=shared --cov-report=html

# 특정 모듈 테스트
pytest tests/shared/hybrid_scoring/ -v
```

### ⚠️ 대규모 테스트 주의사항 (Troubleshooting)

`tests/services/`와 `tests/shared/`를 통합 실행할 때 발생하는 문제는 다음과 같이 해결했습니다.

1.  **전역 모듈 오염 방지**: `sys.modules` 수정은 반드시 `setUp`/`tearDown` 또는 `patch.dict`로 격리해야 합니다. (규칙 위반 시 다른 테스트에 영향을 줌)
2.  **NumPy/Pandas 재로드 문제**: `conftest.py`에서 `pandas`, `numpy`를 미리 임포트하여, 테스트 중 모듈이 언로드/재로드되어 발생하는 C-Extension 에러를 방지했습니다.
3.  **Mocking 주의**: 동적 로드 모듈 테스트 시 `patch.object`를 사용하여 실제 로드된 인스턴스를 모킹해야 합니다.


### 테스트 커버리지

| 모듈 | 테스트 수 | 커버리지 | 설명 |
|------|---------|---------|------|
| `test_redis_cache.py` | 25개 | 99% | Redis 캐싱 (fakeredis 사용) |
| `test_repository.py` | 45개 | 98% | SQLAlchemy ORM (in-memory SQLite) |
| `test_llm_*.py` | 52개 | 43% | LLM 프로바이더 및 JennieBrain |
| `test_utils.py` | 27개 | 93% | 유틸리티 데코레이터 |
| `test_config.py` | 24개 | 100% | ConfigManager |
| `test_auth.py` | 12개 | 100% | 시크릿 로더 |
| `test_market_regime.py` | 18개 | - | 시장 국면 탐지 |
| `test_factor_scoring.py` | 22개 | - | 팩터 스코어링 |
| `test_position_sizing.py` | 15개 | 100% | 포지션 사이징 |
| `test_notification.py` | 16개 | - | 텔레그램 알림 |
| `test_sector_classifier.py` | 18개 | - | 섹터 분류 |
| `hybrid_scoring/` | 106개 | 86%+ | 하이브리드 스코어링 전체 |
| `test_fact_checker.py` | 10개 | - | LLM 환각 탐지 |
| `test_circuit_breaker.py` | 13개 | - | KIS API Circuit Breaker |
| `test_monitoring_alerts.py` | 7개 | - | Telegram 모니터링 알림 |
| **services/** | 130개+ | 56-77% | scout-job, buy/sell-executor, scheduler |
| **총계** | **1250개+** | - | - |

### 테스트 의존성

```txt
pytest>=7.4.0
pytest-cov>=4.1.0
pytest-mock>=3.12.0
pytest-asyncio>=0.21.0
fakeredis>=2.20.0
scipy>=1.11.0
```

---

## 📝 라이선스

MIT License

---

## 🤝 기여

이 프로젝트에 관심을 가져주셔서 감사합니다.

버그 리포트, 기능 제안, PR 모두 환영합니다!

---

<div align="center">

**my-prime-jennie v2.0**

*AI가 발굴하고, 통계가 검증하고, 사람이 결정한다.*

**Last Updated: 2026-02-08**

</div>
