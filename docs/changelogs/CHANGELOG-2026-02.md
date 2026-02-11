# 2026년 2월 변경 이력 (February 2026)

## 2026-02-11
### Macro Council 구조화 JSON 파이프라인 + 토큰 효율화
- **refactor(macro)**: subprocess+regex → 구조화 JSON 직접 호출 (`generate_json()` / `generate_json_with_thinking()`)
  - 전략가(DeepSeek v3.2) → 리스크분석가(DeepSeek v3.2) → 수석심판(Claude Opus 4.6 Extended Thinking)
  - 비용: ~$0.215/회 ($0.43/일), 기존 대비 67% 절감
- **feat(llm)**: `ClaudeLLMProvider.generate_json_with_thinking()` Extended Thinking 메서드 추가
- **feat(macro)**: 3개 스키마 + 3개 프롬프트 파일 신규 (전략가/리스크분석가/수석심판)
- **perf(macro)**: 전략가 출력에서 개별 종목(key_stocks), key_themes 제거 (토큰 낭비 방지)
- **fix(macro)**: sector_signals 복원 (trading_context.py 섹터 회피 폴백에 필수)
- **refactor(dashboard)**: MacroCouncil 시장 분석 섹션 4개 카드 제거 (종목/테마 UI)
- **test**: 31개 macro council 파이프라인 테스트 신규, 전체 통과

## 2026-02-10
### Portfolio Guard Layer 2 (포트폴리오 수준 리스크 관리)
- **feat(shared)**: `PortfolioGuard` 클래스 신규 — 섹터 종목 수 제한 + 국면별 현금 하한선
  - `check_sector_stock_count()`: 동일 대분류(14개) MAX_SECTOR_STOCKS(3) 초과 방지
  - `check_cash_floor()`: STRONG_BULL:5%, BULL:10%, SIDEWAYS:15%, BEAR:25%
  - `check_all()`: fail-fast + shadow mode (PORTFOLIO_GUARD_ENABLED=false)
- **feat(executor)**: Portfolio Guard를 포지션 사이징 후, 분산 검증 전에 삽입
- **feat(registry)**: 7개 설정 추가 (PORTFOLIO_GUARD_ENABLED, MAX_SECTOR_STOCKS, CASH_FLOOR_*_PCT)
- **test**: 24개 유닛 + 3개 통합 테스트 추가, 전체 1140 shared + 26 buy-executor passed

## 2026-02-09
### Scout 워치리스트 매수불가 종목 사전 제거
- **feat(scout)**: 워치리스트에서 보유 중/매도 쿨다운(24h) 종목 사전 제거 — 빈 슬롯에 다음 순위 자동 충원
- **fix(repository)**: `get_recently_traded_stocks_batch()` 중복 실행 버그 수정 + `trade_type` 필터 파라미터 추가
- **test**: 8개 테스트 추가 (repository 2 + scout pre-filter 6), 전체 1201 passed

## 2026-02-08
### 필터 체인 재배치 + E2E 검증 (3현자 리뷰 반영)
- **refactor(executor)**: Hard Floor 도입 (hybrid_score<40 거부), MIN_LLM_SCORE 이중 체크 제거
- **feat(executor)**: Stale Score 배율 축소 (차단→2영업일:0.5, 3영업일+:0.3), 주말 처리 (금→월=정상)
- **feat(executor)**: Shadow Mode 로깅 (기존 기준이면 차단됐을 종목 `[Shadow]` 태그)
- **refactor(scanner)**: `_check_micro_timing()` Executor→Scanner 이동
- **refactor(scout)**: `recon_score_by_regime` 커트라인 제거, `MAX_WATCHLIST_SIZE` env var 도입
- **refactor(registry)**: MIN_LLM_SCORE, MIN_LLM_SCORE_TIER2, MIN_LLM_SCORE_RECON 삭제
- **test(e2e)**: `test_filter_chain.py` 신규 12개 E2E 테스트 (Hard Floor/Stale Score/Shadow Mode/통합)
- **test**: Jenkins 빌드 #322 SUCCESS (1304 passed), 전체 72 E2E PASS, 서비스 정상 구동 확인

### Daily Briefing Claude Opus 4.6 전환 + 뉴스 조회 수정
- **feat(briefing)**: LLM을 deepseek_cloud(THINKING tier) → Claude Opus 4.6 직접 호출로 전환 (`BRIEFING_LLM_MODEL` 환경변수 오버라이드 가능)
- **fix(briefing)**: NEWS_SENTIMENT 쿼리 SQL 에러 수정 (STOCK_NAME→STOCK_MASTER JOIN, HEADLINE→NEWS_TITLE, Collation 충돌 해소)
- **fix(llm)**: ClaudeLLMProvider secrets.json 자동 조회 폴백 추가, auth.py에 claude-api-key 매핑 추가

### collect_investor_trading pykrx 리팩터링
- **perf(scripts)**: `collect_investor_trading.py` KIS Gateway 순차호출(~530초) → pykrx 전종목 일괄(~3초) 전환
- **refactor(job-worker)**: `collect-investor-trading` timeout 600→120초

### 대시보드 개선
- **refactor(dashboard)**: Login.tsx 삭제, Overview/Scout/System 페이지 개선
- **refactor(dashboard)**: Sidebar 정리, API 클라이언트 개선

### News Collector Redis 영속 중복 체크
- **feat(news)**: `NewsDeduplicator` 클래스 구현 — Redis SET 기반 영속 뉴스 중복 체크 (날짜별 키, 3일 TTL)
- **fix(news)**: news-collector 인메모리 dedup → Redis 영속 dedup 전환 (컨테이너 재시작 시 중복 발행 방지)
- **test**: NewsDeduplicator 테스트 18개 추가 (shared 1113 + 18 전체 통과)

## 2026-02-07
### vLLM 부팅 안정화 & 인프라 정리
- **fix(docker)**: vLLM `--model` → positional argument (v0.13 deprecation 대응)
- **refactor(docker)**: vLLM 프로파일 `gpu` → `infra` 통합 (부팅 3단계→2단계)
- **feat(docker)**: `ollama-gateway` → vLLM `depends_on` (service_healthy) 자동 대기
- **fix(autostart)**: `systemd_autostart.sh` gpu 프로파일 누락 수정, chromadb 참조 제거
- **fix(docker)**: chromadb orphan 컨테이너 정리 (서비스 정의 없이 depends_on만 남아있던 상태)
- **perf(vllm)**: VRAM 최적화 — llm 0.82→0.90, embed 0.10→0.05 (KV cache 1,840→9,792 토큰)
- **fix(ollama-gateway)**: 동적 max_tokens 클램핑 (프롬프트 길이 추정 기반, 고정 절반 cap 대체)
- **fix(ollama-gateway)**: `VLLM_MAX_MODEL_LEN=4096` 명시 (기본값 8192와 실제 불일치 해소)
- **fix(systemd)**: `ExecStop`에 `--profile infra` 추가 (vLLM 포함 전체 종료)

### 네이버 업종 분류 기반 섹터 통합 & Unified Analyst Pipeline
- **feat(sector)**: 네이버 금융 79개 업종 세분류를 Single Source of Truth로 통합 (3종 분산 섹터 분류 제거)
  - 크롤러 3개, sector_taxonomy 대분류 매핑, 배치 스크립트, DB 컬럼 추가 (SECTOR_NAVER, SECTOR_NAVER_GROUP)
  - SectorClassifier v4.0: SECTOR_NAVER 우선 조회, scout_universe/factor_analyzer SECTOR_MAPPING 삭제
  - Council 섹터 매칭 양방향 부분문자열 매칭으로 수정 (exact match 버그 수정)
- **feat(scout)**: Unified Analyst Pipeline — 3→1 LLM 호출 통합 (Hunter+Debate+Judge → run_analyst_scoring)
  - 코드 기반 classify_risk_tag() (LLM 100% CAUTION 편향 해소)
  - ±15pt 가드레일, SCOUT_USE_UNIFIED_ANALYST=true 환경변수 토글
- **test**: 1049 shared + 18 scout-job 테스트 전체 통과

### FOREIGN_HOLDING_RATIO 수집 & Quant Scorer v2 프로덕션 전환
- **feat(data)**: `collect_foreign_holding_ratio.py` 신규 — pykrx 기반 외인보유비율 수집/백필 (DDL 자동 실행)
- **feat(dags)**: `collect_foreign_holding_ratio` DAG 추가 (18:35 KST, collect_investor_trading 이후)
- **feat(quant)**: `QUANT_SCORER_VERSION=v2` 프로덕션 전환 (D+5 IC: v1=-0.071 → v2=+0.106)
- **fix(scripts)**: `backtest_v2_historical.py`, `dryrun_v1_v2_comparison.py` — FOREIGN_HOLDING_RATIO 실제 DB 데이터 활용

### Factor Alpha P0+P1+P2 구현 & 백테스트 검증
- **feat(quant)**: P1 Quant Scorer 패치 3건 구현
  - P1-2 Recon Protection 강화: RSI 보호 해제 50-70→50-59, 1M 모멘텀>0 필수
  - P1-3 고점+과열 감점: DD>-3% & RSI>70 → -1.5점 (단순 DD 감점 대체)
  - P1-4 수급 추세 반전: 외인 매도전환 -2점, 매수전환 +1.5점
- **feat(llm)**: P2 LLM 스코어링 구조 개선
  - Hunter/Judge 점수 조정 범위 ±15/20 → ±30 (LLM Calibrator 확장)
  - `risk_tag` 출력 추가 (BULLISH/NEUTRAL/CAUTION/DISTRIBUTION_RISK)
  - DISTRIBUTION_RISK → Veto Power (is_tradable=False, trade_tier=BLOCKED)
  - Safety Lock 비대칭: LLM 경고 존중 (40:60), LLM<40 가중 (45:55)
- **fix(data)**: P0 주말/공휴일 가격 데이터 필터링 (DB 삽입 전)
- **fix(database)**: `save_to_watchlist_history`에 LLM 메타데이터 저장 활성화
  - `[LLM_METADATA]{json}` 마커 임베딩 (기존 현재 테이블과 동일하게)
- **feat(scripts)**: 백테스트 스크립트 4종 추가
  - `backtest_grid.py`: 216조합 그리드 탐색
  - `backtest_p1p2_validation.py`: P1+P2 패치 효과 검증 (4주)
  - `dryrun_p1_patches.py`: P1 패치 드라이런
  - `recollect_prices_fdr.py`: FDR 가격 재수집
- **docs**: 백테스트 분석 문서 (`docs/backtest-analysis-2026-02-07.md`)

### Factor Alpha Study & Smart Money 5D 최적화
- **feat(quant)**: Smart Money 5D 조건부 보너스 구현 (15점 기본 + 최대 3점 보너스)
  - `investor_trading_df` 파라미터로 5일 누적 외인+기관 순매수 전달
  - sm_ratio > 2% (강한 매집)일 때만 보너스 가산 → 중립 시 기존 팩터 희석 방지
- **fix(quant)**: `calculate_supply_demand_score()` 중복 dip-buying 보너스 블록 제거
- **perf(quant)**: 백테스트 기반 가중치 최적화 (15점 > 25점 > 20점 > 18점 검증)
  - 가중치 배분, 윈도우 비교(3/5/10일), "이미 오른 종목" 분석 등 6개 백테스트 수행
  - 기관 합산이 노이즈 추가 확인 (foreign_flow_10d IR=1.445 >> smart_money_5d IR=0.120)
- **feat(scout)**: `scout_pipeline.py`에 투자자 매매 동향 DB 조회 연결
- **test(quant)**: 13개 테스트 추가 (supply_demand, constants, investor_trading)

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

### RAG 검색 품질 개선 & Qdrant 필터 수정
- **feat(scout)**: 다중 쿼리 검색 전략 구현 (`_generate_news_search_queries()` - 실적/수주/리스크 + 섹터별 쿼리)
- **feat(scout)**: RAG 후보 발굴 개선 (4개 테마 쿼리 + 7일 필터 + 중복 제거)
- **feat(news)**: page_content 메타데이터 강화 (`[종목명(코드)] 제목 | 출처 | 날짜` 신규 포맷)
- **fix(scout)**: Qdrant 필터를 네이티브 `models.Filter`로 교체 (langchain-qdrant 1.1.0 dict 필터 미지원 → RAG 0건 버그 수정)
- **결과**: RAG 후보 0개 → 35개, Scout 소요시간 541초 → 417초 (-23%)

### Jenkins 파이프라인 단순화
- **refactor(jenkins)**: Smart Build(`smart_build.py`) 의존성 제거 → `docker compose up -d --build` 단일 명령
- **fix(jenkins)**: `docker:dind` → `docker:cli` (ENTRYPOINT 오류 수정)
- **결과**: Jenkinsfile Build & Deploy 54줄 → 17줄, BuildKit 레이어 캐시가 변경 감지 대체

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
*Last Updated: 2026-02-11 14:17 KST*
