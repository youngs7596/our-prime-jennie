# 2026년 2월 변경 이력 (February 2026)

## 2026-02-06
### Airflow 배치 최적화 & 중복 DAG 정리
- **perf(dags)**: `weekly_factor_analysis` → `--analysis-only` 모드 (Step 1~4 수집은 별도 DAG/서비스 담당, ~20분→~5분)
- **perf(scripts)**: `collect_investor_trading` 이중 sleep 제거 (KIS Gateway rate limit이 제어, ~26분→~5분)
- **fix(scripts)**: `collect_prices_fdr` 개별 종목 타임아웃 추가 (FDR API hang 방지)
- **cleanup(dags)**: `collect_daily_prices`(FDR) DAG 삭제 (`daily_market_data_collector`와 중복)
- **perf(dags)**: `enhanced_macro_collection` 12:00 실행 시 pykrx 중복 수집 스킵

### vLLM max-model-len 확장 & 토큰 초과 통계
- **fix(ollama-gateway)**: vLLM `max-model-len` 4096→8192 확장, `gpu-memory-utilization` 0.82→0.88
- **feat(ollama-gateway)**: max_tokens 클램핑 (max_model_len//2 초과 시 자동 축소) + 토큰 초과 통계 (`/stats` → `token_stats`)

### DeepSeek V3.2 Cloud Failover & Scout 비용 최적화
- **feat(llm)**: `CloudFailoverProvider` 구현 (DeepSeek API → OpenRouter → Ollama Cloud 3-tier failover)
- **refactor(llm)**: 로컬 `gpt-oss:20b` fallback 제거 (RTX 3090은 vLLM exaone+kure 전용)
- **perf(llm)**: Retry/대기시간 축소 (Cloud retry 5→2회, base delay 3→1s, internal retry 3→2)
- **perf(scout)**: Scout job 스케줄 30분→1시간 변경 (월 비용 $31.7→$16.9)

### P0 트레이딩 로직 개선 & Ollama Gateway Rate Limit 최적화
- **feat(buy-scanner)**: P0 트레이딩 로직 3건 구현 (Council 합의)
  - BEAR/STRONG_BEAR Market Regime Gate (신규 진입 차단)
  - 손절 종목 5거래일 쿨다운 (Redis TTL 기반)
  - VOLUME_BREAKOUT_1MIN 기본 비활성화 (수익률 -0.34%)
- **feat(ollama-gateway)**: 엔드포인트별 + 모델별 차등 Rate Limit 구현
  - embed: 3000/min, exaone(FAST): 120/min, heavy: 60/min
  - 동적 `key_func`로 모델별 별도 Redis 버킷 분리
- **fix(infra)**: `SCOUT_UNIVERSE_SIZE=5` 하드코딩 원복 (200), Redis Stream consumer group 생성

## 2026-02-05
### DeepSeek PoC & Hybrid Gateway Architecture
- **feat(ollama-gateway)**: Implemented **Hybrid Cloud Proxy** in Ollama Gateway
  - Intercepts `:cloud` models and proxies to `https://ollama.com` via `OLLAMA_API_KEY`
  - Automated fallback to local `gpt-oss:20b` if cloud quota/API fails
- **feat(scout)**: Deployed **DeepSeek V3.2 Cloud** PoC & Implemented "Strict Gatekeeper" Logic
  - Updated `docker-compose.yml` to use `deepseek-v3.2:cloud` via Gateway
  - Engineered Asymmetric Hunter Prompt (+10/-30) to fix low win rate (18%) and over-trading
- **perf(gateway)**: Resolved Rate Limiting & Scalability issues
  - Increased `OLLAMA_RATE_LIMIT` (60/min -> 1000/min) for parallel embedding/fast-track processing
  - Resolved persistent Circuit Breaker 503 errors via Redis state reset
- **refactor(llm)**: Removed Gemini Fallback logic from `shared/llm.py` & `llm_factory.py` (User Request)

## 2026-02-04
### Buy Scanner
- **fix(buy-scanner)**: Resolved data silence issue
  - Identified Market Close Auction (15:20 KST) as cause of silence (Normal behavior)
  - Fixed `inspect_redis.py` to target correct versioned watchlist key (`hot_watchlist:active`)
  - Confirmed 24-hour Repurchase Restriction logic blocks re-entry after selling
- **fix(buy-executor)**: Verified Repurchase Restriction
  - Confirmed `executor.py` logic blocks buying stocks sold within 24h
  - Verified `TRADELOG` contains 24 sell records blocking re-entry

### CI/CD
- **fix(jenkins)**: Add Python3 to Docker Build/Deploy stages
  - Modified `Jenkinsfile` to run build/deploy in `docker:dind` container
  - Added runtime installation of `python3` and `git` to fix `python3: not found`
  - Added host volume mount for in-place deployment
  - **fix(jenkins)**: Fix deploy skip on re-run
    - Added fallback to `HEAD~1..HEAD` commit range if `ORIG_HEAD..HEAD` is empty (e.g., during retry)

### Research & Optimization
- **feat(strategy)**: Dividend data collection for backtest
  - Added `DividendHistory` model to `shared/db/models.py`
  - Created `scripts/collect_dividend_data.py` (pykrx-based)
  - Collected 1,545 dividend records (KOSPI top 200, 2015-2025)
  - Council approved: need backtest before live trading
- **perf(docker)**: RabbitMQ CPU optimization
  - Added Erlang scheduler flags (`-+sbwt none`) to `docker-compose.yml`
  - Fixed `beam.smp` 1000% CPU spike issue in WSL2 environment

### Intraday Integration
- **feat(scout)**: Smart Scouter (Intraday Momentum)
  - Added Phase 1.9 in `scout.py` to detect real-time volume spikes (>180%) and price trends
  - Utilizes 5-minute OHLCV data for immediate opportunity detection
- **feat(executor)**: Micro-Timing Buy Execution
  - Added `_validate_entry_timing` to block entries on Shooting Star / Bearish Engulfing patterns
  - Prevents buying at local highs (Bull Trap prevention)
- **feat(risk)**: Dynamic ATR Risk Management
  - Implemented `calculate_intraday_atr` (100-min window) in `PositionSizer`
  - Overrides default Stop Loss with Intraday ATR-based dynamic stop
- **test**: Verified all features with `scripts/verify_intraday_features.py`


- **perf(docker)**: Docker Image Optimization & AI Model Switch
  - Switched embedding model: `sentence-transformers` -> `Ollama (daynice/kure-v1)`
  - Reduced `scout-job` image size (15.8GB -> ~500MB) via Multi-stage Build
  - Reduced `news-archiver` image size (13GB -> ~400MB)
  - Enabled concurrency in `ollama-gateway` (3 models: gpt-oss, exaone, kure-v1)
- **refactor(db)**: Migrate Vector DB (ChromaDB -> Qdrant)
  - Replaced `chromadb` with `qdrant` (Rust-based, lighter, faster)
  - Updated `news-archiver` & `scout-job` to use `QdrantVectorStore`
  - Added Qdrant Dashboard (port 6333)

### Macro Council
- **fix(macro)**: `OpportunityWatcher`에서 `BuyExecutor`로의 Macro Context(risk settings) 전달 누락 수정 (완료)
  - `OpportunityWatcher.publish_signal`에 `risk_setting` 주입 로직 추가
  - `BuyExecutor`가 `position_size_ratio`와 `stop_loss_pct`를 수신하도록 페이로드 구조 개선

- **fix(macro-council)**: Dashboard Macro Council 페이지 데이터 표시 문제 수정
  - `save_insight_to_db`에 VIX_VALUE, USD_KRW, KOSPI_INDEX 등 글로벌 스냅샷 컬럼 추가
  - `/api/council/daily-review` API를 `DAILY_MACRO_INSIGHT`에서 리뷰 파싱하도록 수정
  - `council_cost_usd` Decimal→Number 형변환 추가 (TypeError 수정)

- **fix(enhanced-macro)**: 부분 수집 시 NULL 덮어쓰기 버그 수정
  - `--sources` 옵션 사용 시 마지막 태스크가 이전 값을 NULL로 덮어쓰는 문제
  - `collect_enhanced_macro.py`에 `merge_snapshots` 함수 추가
  - 저장 전 기존 스냅샷과 병합하여 수집된 값만 업데이트

### Airflow DAGs
- **fix(dags)**: DAG 환경변수 및 타임아웃 설정 개선
  - `macro_council_dag.py`, `utility_jobs_dag.py`에 DB 환경변수 추가
  - `collect_daily_prices` 태스크에 `execution_timeout=30분` 설정
  - 브리핑 없을 때 graceful exit (exit 0) 로직 추가

## 2026-02-03

### Dashboard
- **feat(dashboard)**: Overview 페이지에 Macro Insight 카드 추가
  - 글로벌 지표 (VIX, USD/KRW, KOSPI, KOSDAQ)
  - 투자자별 순매수 (외국인/기관/개인)
  - 트레이딩 권고 (포지션 크기, 손절폭 조정)
  - 허용/회피 전략 및 섹터
  - Sentiment Score, Political Risk Level
  - Backend: `/api/macro/insight` 엔드포인트 추가

- **feat(dashboard)**: Macro Council 전용 페이지 추가
  - 사이드바에 "Macro" 메뉴 추가 (`/macro-council`)
  - Council 분석 결과 상세 표시
  - 글로벌 지표, 투자자 수급, 트레이딩 권고
  - 정치/지정학적 리스크 분석
  - 3현자 Council 리뷰 섹션

- **feat(dashboard)**: Macro Council 페이지 기능 보강
  - Market Regime hint 표시 추가
  - Opportunity Factors (기회 요인) 섹션 추가
  - Sector Signals (섹터별 bullish/bearish 신호) 표시
  - Source Info (출처 채널, 분석가) 표시
  - 날짜 선택 드롭다운 추가 (`/api/macro/dates` 연동)

### Macro Council
- **fix(macro-council)**: 텔레그램 브리핑 없어도 Council 분석 진행
  - 주말/공휴일에도 글로벌 매크로 데이터만으로 분석 가능
  - 브리핑과 글로벌 데이터 모두 없을 때만 실패

### Code Quality
- **incident**: 2026-02-02 세션에서 구현한 `Macro.tsx` 코드 손실 발견
  - 원인: `git add` 명령에 프론트엔드 파일 누락 (백엔드만 커밋됨)
  - 조치: Claude 세션 히스토리에서 원본 코드 발견, 기능 복구
  - 예방: `.githooks/pre-push` 훅 추가, RULES.md에 코드 손실 방지 규칙 추가

## 2026-02-02

### Macro Integration
- **feat(macro)**: 정치/지정학적 뉴스를 Council LLM 분석에 통합
  - PoliticalNewsClient: RSS 피드 모니터링 (Reuters, BBC, NYT, WSJ, 연합뉴스)
  - Council 프롬프트에 political_risk_level/summary 판단 추가
  - DailyMacroInsight, EnhancedTradingContext 확장

- **feat(macro)**: 투자자 수급 데이터를 Council 분석에 추가
  - GlobalMacroSnapshot에 외국인/기관/개인 순매수 필드 추가
  - pykrx 1.2.x API 호환성 수정

### CI/CD
- **fix(tests)**: Jenkins CI 테스트 실패 수정
  - Finnhub 클라이언트 테스트 mock 개선
  - VIX max_age=72h 반영
  - `scheduler-service` 테스트 Race Condition 해결 (Unique DB Path 적용)
  - **fix(db)**: Qdrant 컬렉션(`rag_stock_data`) 자동 생성 로직 추가 (404 에러 해결)
  - **fix(archiver)**: 누락된 모듈 임포트 추가 (`RecursiveCharacterTextSplitter`)
- **cleanup**: Legacy ChromaDB 코드 및 스크립트 제거 (Qdrant 전면 전환)
- **fix(scout)**: 누락된 의존성 패키지 추가 (`filelock`) - KIS 인증 모듈 필수
- **test(shared)**: Circuit Breaker 테스트 Flaky 현상 해결 (`time.sleep` -> `mock.patch`)
- **fix(frontend)**: Macro 데이터(`vix_value` 등) `toFixed` 타입 에러 해결 (`Number()` 래핑)

---
*Last Updated: 2026-02-03*
