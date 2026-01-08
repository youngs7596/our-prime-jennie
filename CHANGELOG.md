# 📅 변경 이력 (Change Log)

## 2026-01-08
- **Scout Job 아키텍처 분리**: `scout-job`(API) ↔ `scout-worker`(RabbitMQ) 서비스 분리로 Unhealthy 문제 해결, `/scout` 엔드포인트 비동기 트리거 방식 전환
- **LLM 프롬프트 버그 수정**: 0점 점수 방지(Strategic Feedback 방어 문구), Debate 환각 방지 강화, 중복 return 버그 수정
- **tradelog REASON 개선**: "Auto-Rejected" → "RECON tier로 정찰매수 가능" 문구 명확화
- **투자자 매매동향 API 전환**: `pykrx` → KIS Gateway 전환, 수급 조회 3-tier fallback 구현
- **ETF 필터링**: `filter_valid_stocks()` 함수 추가로 ETF/미등록 종목 후보군 제외
- **RabbitMQ Backlog Fix**: `scheduler-service`의 큐(`real.jobs.data.intraday`) 적체 문제를 해결하기 위해 메시지 소비 전용 `scheduler-worker` 서비스를 신규 구현 및 배포 (Docker 이미지 재생성 및 의존성 추가)
- **Dynamic Tier 2 Threshold & Rebuild Fix**: `buy-executor`가 `STRONG_BULL` 시장에서 Tier 2 종목 매수 기준을 58점으로 완화하도록 로직을 수정하고, Docker 이미지 Rebuild(No-Cache)를 통해 코드 변경 사항을 실시간 반영하여 `한국전력` 매수 체결 성공.
- **Portfolio 중복 버그 수정**: `execute_trade_and_log`가 호출자 세션을 무시하고 새 세션을 생성하여 PORTFOLIO에 중복 HOLDING 레코드가 생성되던 버그 수정 (`shared/database/trading.py`)
- **Hunter Score Strategy Integration**: AI Analyst 성과 분석(승률 72%) 기반 전략 고도화 — `buy-scanner`에서 Hunter Score 90+ 종목 가산점(+15%) 및 70- 필터링 적용, `buy-executor`에서 Hunter Score 90+ 종목 안전장치 프리패스(Double Check 면제) 예외 처리 구현.
- **CURRENT_HIGH_PRICE 초기화 추가**: 신규 매수 시 `CURRENT_HIGH_PRICE`를 매수가로 초기화하도록 INSERT 쿼리 수정
- **최고가 DB 동기화 추가**: `price-monitor`의 최고가 갱신 시 Redis뿐 아니라 DB `PORTFOLIO.CURRENT_HIGH_PRICE`도 함께 업데이트 (`shared/redis_cache.py`)
- **MCP 서버 설정**: MariaDB용 MCP 서버(`mysql_mcp_server`) 설정 완료 (`~/.gemini/settings.json`)
- **Super Prime Logic Implementation**: `buy-scanner`에 RSI(<=30) & 수급(20일 평균 거래량 5% 이상 외국인 순매수) 기반의 강력 매수 신호 감지 로직 구현 및 텔레그램 알림 긴급 태그(`[🚨긴급/강력매수]`) 적용.
- **Frontend Lint Fix**: `LogicVisualization.tsx`의 TypeScript 오류 수정 및 타입 안정성 강화.
- **Unit Test Fix (Phase 2)**: `scout-job`(`filter_valid_stocks` Mock), `llm_brain`('RECON' wording, text mismatch) 테스트 오류 추가 수정 (Local E2E 검증 완료).
- **Unit Test Fix**: Jenkins 배포를 막던 `buy-scanner`(`NameError` 수정), `price-monitor`, `dashboard`의 Unit Test 오류 전수 수정 및 59개 테스트 통과 확인.
- **Frontend Build Fix**: `LogicVisualization.tsx`의 TypeScript 오류(`findDay` unused) 수정 및 컴파일 정상화.
- **Architecture Diagram**: Dashboard 내 `PrimeJennieArchitecture` 컴포넌트 및 페이지(`/architecture`) 추가, 사이드바 연동 완료 (v2 Architecture 시각화).
- **Frontend Build Fix (TS6133)**: `PrimeJennieArchitecture.tsx`의 미사용 `React` import 제거로 빌드 오류 해결.


## 2026-01-07
- **Dynamic RECON Score**: 시장 국면별 동적 RECON 점수 적용 (STRONG_BULL=58, BULL=62, SIDEWAYS=65, BEAR=70)
- **Privacy Rule 추가**: `rules.md`에 세션 파일 개인정보 보호 규칙 추가
- **Dual Local LLM 체제 구축**: `exaone3.5:7.8b` (news-crawler용) + `gpt-oss:20b` (Scout Hunter/Judge용) 동시 운영, 뉴스 분석 속도 2배 향상
- **README.md v1.1 업데이트**: Dual LLM 운영 섹션 추가, VRAM 사용량 및 성능 비교 문서화
- **Buy Scanner 간격 단축**: 5분 → 3분으로 변경 (매수 기회 포착 빈도 증가)
- **Portfolio 정리**: 수동 보유 종목 SOLD 처리 및 수동 관리 제외 로직 완전 제거
- **Scout Job 활성화**: `ENABLE_SCOUT_JOB_WORKER=true`, `EXCLUDED_STOCKS=""` 설정
- **Buy Scanner Asset Fix**: 자산 계산 로직을 "관리 자산(WatchList 종목만)" 기준으로 변경
- **Config Warning Suppression**: `ConfigManager.get()`에 `silent` 파라미터 추가로 심볼별 설정 경고 로그 억제
- **DB Cleanup**: Portfolio 중복 데이터 정리 및 수동 매도 종목 SOLD 처리
- **Manual Management Removal**: `daily-briefing/reporter.py`의 수동 관리 동기화 제외 로직 제거
- **News Crawler Optimization**: `news-crawler` LLM 처리 방식을 병렬에서 순차적 배치(Sequential Batch)로 원복하여 처리 속도 2.5배 향상 (~12s/batch).
- **LLM Stability**: `gpt-oss:20b` 모델의 JSON 파싱 오류(`Expecting ',' delimiter`)를 One-Shot Example 프롬프트 추가로 완벽 해결.
- **Rules Update**: `rules.md`에 '주요 의사 결정(Key Decisions)' 섹션 신설 (Local LLM 모델 통일 및 성능 최적화 규칙 등재).
- **Policy Enforcement**: Gemini 모델의 영어 답변 방지를 위한 '최우선 원칙(Critical Rule)' 언어 규정 강화 (Must use Korean).
- **Scheduled Jobs & Data Integrity**: `scheduler-service` 및 Cron 작업(수집/분석) 전체 검증 완료, 누락된 `collect-intraday`(5분), `daily-council`(17:30) 등록.
- **Data Collection Upgrade**: `scripts/collect_dart_filings.py` 및 `scripts/collect_investor_trading.py`를 일일(Daily) 작업으로 격상(18:30/18:45)하고 DB 기반 코드로 수정하여 오류 해결.
- **Backtest Upgrade**: `backtest_gpt_v2.py`가 실제 재무(ROE/PER) 및 수급 데이터를 DB에서 로드하여 팩터 점수에 반영하도록 개선 (Look-Ahead Bias 방지).
- **Optimization Deployment**: `backtest_gpt_v2.py` 실행 오류 수정 및 최적 파라미터(수익률 212%, 익절 6%, RSI 35) 실전 DB/프리셋 적용.
- **Exaone vs GPT-OSS Test**: `scripts/test_exaone_news.py` 구현 및 비교 테스트 완료. Exaone이 속도(<1s vs 3s)와 추론 디테일 면에서 우수함을 확인 (`test_exaone_results_output.txt`).

## 2026-01-05
- **Market Regime Bug Fix**: `shared/market_regime.py`의 `SIDEWAYS` 판단 로직 수정 (이격도 3% 이상 시 SIDEWAYS 점수 0점 강제) - "겁쟁이 봇" 문제 해결
- **LLM Threshold 하향**: `MIN_LLM_SCORE_RECON` 65점 → 63점 (매수 활성화)
- **Backtest Look-ahead Bias 제거**: `backtest_gpt_v2.py`의 장중 가격 시뮬레이션을 시가(Open)+ATR 기반으로 변경
- **Backtest Slippage 적용**: 매수 +0.3%, 매도 -0.3% 슬리피지 추가
- **Data Collection**: `collect_full_market_data_parallel.py` 수정 (import 순서, MAX_WORKERS=1) 및 KOSPI 958종목 데이터 수집
- **Optimization**: 백테스트 최적화 30개 조합 실행, `llm_threshold: 65` 최적값 확인

## 2026-01-04
- **Dashboard Operation Fix**: Resolved `DISABLE_MARKET_OPEN_CHECK` override issue by removing conflicting environment variable in `env-vars-wsl.yaml`, restoring correct DB config priority for `buy-scanner` and `price-monitor` (Dashboard Toggle functional).
## 2026-01-03
- **대시보드 서비스 제어 기능**: System 페이지에서 스케줄러 작업(scout-job, news-crawler 등) 실행/일시정지/재개 직접 제어 가능
  - `routers/scheduler.py`: 스케줄러 서비스 프록시 API 신규 생성
  - `System.tsx`: Scheduler Jobs UI 확장 및 운영 설정(장외 시간 실행) 토글 추가
  - `registry.py`: `DISABLE_MARKET_OPEN_CHECK` 설정 연동 (Operations Settings)
  - `buy-scanner`, `price-monitor`: 환경변수 우선순위 문제 해결 및 ConfigManager 연동 (대시보드 토글 정상화)
- **네이버 금융 종목 뉴스 직접 크롤링**: Google News RSS 대체로 네이버 금융 iframe API 사용, Google News를 Fallback으로 설정
  - `crawl_naver_finance_news()`: 종목코드 기반 뉴스 직접 크롤링 (정확도 향상)
  - `crawl_stock_news_with_fallback()`: Naver 우선, Google Fallback 래퍼 함수
  - 단위 테스트 5개 추가, 통합 테스트 성공 (삼성전자 16건, SK하이닉스 3건)
- **News Crawler 뉴스 소스 필터링 개선**: 3-Phase 구현 완료 (현자 3인 피드백 반영)
  - Phase 1: hostname suffix 매칭, WRAPPER_DOMAINS 분리 (naver/daum/google)
  - Phase 2: URL 패턴 기반 실제 발행일 추출
  - Phase 3: 노이즈 키워드 필터, 제목 해시 중복 제거
- **Google News wrapper URL 문제 해결**: `entry.link`가 `news.google.com`일 때 `source.title`로 신뢰 언론사 검증
- **LLM 모델 변경**: `gpt-oss:20b` → `gemma3:27b` (JSON 출력 안정성 개선)
- **FDR API 장애 대응**: 네이버 금융 시총 스크래핑 Fallback 추가 (`_scrape_naver_finance_top_stocks`)
- **Universe 확장**: WatchList 18개 → KOSPI 200개 종목으로 뉴스 수집 정상화
- **Dashboard Stability & Optimization**: 스케줄러 작업 제어(실행/중지/재개) 로깅 및 에러 핸들링 강화, System API 라우터 분리 및 Redis 캐싱(5s TTL)을 통한 성능 최적화 완료 (`routers/system.py` 신설)

## 2025-12-31 (오후 세션)
- **테스트 격리성 강화**: `conftest.py`에 `isolated_env` 및 `reset_singletons` 픽스처(autouse) 추가로 환경변수/싱글톤 테스트 간섭 원천 차단
- **Daily Council 마이그레이션**: `scripts/build_daily_packet.py` (Dummy 모드/스키마 검증), `scripts/run_daily_council.py` (Mock Council) 구현 및 Smoke Test 검증 완료
- **수익 극대화 전략 활성화**: `refresh_symbol_profiles.py` 실행 성공 (DB 포트/인증 수정), `config/symbol_overrides.json`에 70+ 종목 맞춤 전략 생성 및 Hot Reload 확인
- **Daily Council 고도화 (완료)**: `build_daily_packet.py`의 실제 DB 데이터(`ShadowRadarLog`) 연동, `run_daily_council.py`의 LangChain 제거 및 LLM 파이프라인 최적화, `apply_patch_bundle.py`의 안전성 검증(스키마 자동 보정, 위험 명령어 차단) 완료. DB 포트(3307) 연결 문제 해결 및 전체 통합 테스트 통과.

## 2026-01-02
- **News Crawler Cost Elimination**: `news-crawler`의 임베딩(HuggingFace Local) 및 감성/경쟁사 분석(Ollama Local) 전면 로컬화 완료 (Cloud 비용 100% 절감). Docker 빌드 최적화 및 40개 분석 제한 제거.
- **LLM 감성 분석 최적화 (Phase 1)**: `gpt-oss:20b` + 배치 처리 도입으로 뉴스 감성 분석 속도 **2배 향상** (0.35 → 0.70 items/sec). 한국어 출력 강제 프롬프트 튜닝 적용. (`llm_factory.py`, `llm_prompts.py`, `llm.py`, `crawler.py` 수정)
- **LLM 감성 분석 최적화 (Phase 2)**: `news-crawler`의 LLM 분석 로직을 Sentiment와 Competitor Risk 통합 프롬프트로 단일화하여 처리 속도 및 비용 효율성 극대화. Integration Test(`tests/test_crawler_flow.py`) 추가로 검증 강화.
- **News Crawler Cleanup**: 통합 분석 배포 완료 및 레거시 감성/경쟁사 분석 코드(`crawler.py`) 완전 제거.

## 2025-12-31
- **수익 극대화 전략 4종 구현**: 트레일링 익절, 분할 익절, 상관관계 분산, 기술적 패턴 탐지 강화
  - **트레일링 익절 (ATR Trailing Take Profit)**: 최고가 추적 후 ATR×배수 하락 시 익절. Redis High Watermark 관리.
    - `shared/redis_cache.py`: `update_high_watermark()`, `get_high_watermark()`, `delete_high_watermark()` 추가
    - `services/price-monitor/monitor.py`: 트레일링 익절 로직 추가 (활성화 조건: 수익률 5% 이상)
  - **분할 익절 (Scale-out)**: 수익률 5%/10%/15% 도달 시 25%씩 단계적 매도
    - `shared/redis_cache.py`: `get_scale_out_level()`, `set_scale_out_level()`, `delete_scale_out_level()` 추가
    - `shared/settings/registry.py`: `SCALE_OUT_LEVEL_*` 설정 추가
    - `services/price-monitor/monitor.py`: 수익률별 분할 익절 로직 추가
  - **상관관계 기반 포트폴리오 분산**: 신규 매수 종목과 기존 보유 종목 간 상관관계 분석, 높은 상관관계(0.85+) 시 매수 거부, 중간 상관관계 시 비중 축소
    - `shared/correlation.py`: 상관관계 계산 모듈 신규 생성
    - `shared/settings/registry.py`: `CORRELATION_*` 설정 추가
    - `services/buy-executor/executor.py`: 매수 전 상관관계 체크 및 포지션 조정 로직 추가
  - **기술적 패턴 탐지 강화**: 볼린저밴드 스퀴즈, MACD 다이버전스 추가
    - `shared/strategy.py`: `check_bollinger_squeeze()`, `calculate_macd()`, `check_macd_divergence()` 추가
  - 테스트 51개 추가, 전체 939개 테스트 통과

- **종목별 매수/매도 임계치 시스템**: RSI/거래량/Tier2 조건을 종목별 특성(변동성, 유동성, RSI 분포)에 맞게 개별화. 일률적 기준으로 인한 매수 신호 미발생 문제 해결.
  - `shared/config.py`: `get_*_for_symbol()` API 추가 (종목별 설정 조회)
  - `shared/symbol_profile.py`: RSI P20/P80, 평균 거래량 기반 임계치 자동 산출
  - `services/buy-scanner/scanner.py`, `services/price-monitor/monitor.py`: 종목별 설정 적용
  - `scripts/refresh_symbol_profiles.py`: Scout universe(KOSPI 200개) 전체 프로파일 배치 스크립트, 크론잡 등록(평일 16:40)

## 2025-12-28
- **AI Auditor 구현**: Regex 기반 환각 검증 → Gemini 2.5 Flash LLM 기반으로 교체, 더 정확한 맥락 이해 및 환각 탐지 가능 (`fact_checker.py`)
- **Fact-Checker Enhancement**: 정량 점수(Quant Score) 및 재무 데이터(Snapshot) 컨텍스트 주입으로 Fact-Checker의 환각 오탐지(False Positive) 해결 (`scout_pipeline.py`)
- **AI Auditor Planning**: AI 감사 시스템 도입을 위한 Cloud LLM 가격/성능 분석 완료 (Gemini 2.5 Pro 선정, 일일 예산 제한 설계)
- **Unit Test**: `test_check_quant_context_match` 추가로 Fact-Checker 컨텍스트 검증 로직 강화

## 2025-12-27
- **Py3.12 테스트 정합성**: pandas/numpy/scipy 실사용 기준으로 방어 로직 보강(RSI/MA/크로스 계산), FactorRepository DF 변환 안전화, utils.now 주입으로 MagicMock 충돌 제거, Ollama 테스트 CI 스킵. 로컬/CI/Mock 모드 전체 pytest 통과 확인.
- **Jenkins CI Stability**: Python 3.12 업그레이드, 의존성 (`numpy`/`pandas`) 고정, `pytest` 순차 실행 전환으로 안정성 확보
- **Test Pollution Fix**: `scanner`, `monitor` 등의 테스트 격리 개선 및 `utils` Mock 누수 수정으로 간섭 해결
## 2025-12-26
- **Rules Enhancement**: 구현 검증 원칙에 Integration Test 명시적 포함, 변경 유형별 검증 범위 테이블 개선
- **Feature Integration**: Fact-Checker, Circuit Breaker 알림을 Scout/KIS Gateway 서비스에 연동 완료
- **Quality & Feature Improvements**: Fact-Checker(LLM 환각 탐지), Circuit Breaker(KIS API 장애 대응), Monitoring Alerts(Telegram 알림) 구현 및 E2E 통합 테스트 / 운영 가이드 문서화 완료 (총 136+ tests passed)
- **Unit Test Coverage Improvement (Phase 4 & 5)**: `hybrid_scorer.py` 46%→86%, `news_classifier.py` 34%→96% 달성 (Shared 모듈 전체 안정화 완료)
- **Unit Test Coverage Improvement (Services)**: `services/scout-job`, `buy-executor`, `sell-executor` 테스트 커버리지 확보 및 검증 완료
- **Unit Test Coverage Improvement (Phase 3)**: `llm_providers.py` 25%→43%, OllamaLLMProvider 테스트 8개 추가 (총 22개 테스트 케이스)
- **Unit Test Coverage Improvement (Phase 10)**: `buy-executor` (56%), `sell-executor` (77%), `scheduler-service` (69%) 테스트 커버리지 달성 및 검증 완료
- **Unit Test Coverage Improvement (Phase 2)**: `redis_cache.py` 71%→99%, `db/connection.py` 29%→100%, `db/repository.py` 89%→98%, `gemini.py` 0%→100%, `auth.py` 91%→100% 달성 (총 189개 테스트 케이스)
- **Unit Test Coverage Improvement (Phase 1)**: `position_sizing.py` 96%→100%, `secret_manager.py` 94%→100%, `llm_prompts.py` 90%→100%, `utils.py` 92%→93% 달성 (총 116개 테스트 케이스)
- **MariaDB Deadlock Fix**: `news-crawler` 서비스의 동시 DB 쓰기 시 발생하는 1213 Deadlock 에러에 exponential backoff 재시도 로직 구현
- **LLM Cost Optimization**: Gemini/OpenAI 기본 모델을 비용 효율적인 모델로 변경 (`gemini-2.5-flash`, `gpt-4o-mini`)
- **Config DB Priority**: 운영 튜닝 키 17개에 `db_priority=True` 플래그 추가, Dashboard 수정 시 DB 값 우선 적용
- **Config Cleanup**: 미사용 환경변수 `INVESTMENT_AMOUNT`, `DAILY_BUY_LIMIT_AMOUNT` 삭제
- **Infrastructure Fix**: MariaDB 컨테이너 포트 매핑 (3307:3306) 누락 수정으로 `scout-job` 등의 DB 접속 오류 해결
- **LLM Config Centralization**: `env-vars-wsl.yaml`로 FAST/REASONING/THINKING 프로바이더 설정 일원화
- **Gemini Stabilization**: Rate Limit (429) 대응을 위한 Exponential Backoff 재시도 로직 추가 및 `news-crawler` 동시성 최적화 (5→3)
- **Scout Flexibility**: `scout-job` 실행 시간(07:00~16:00) 윈도우 방식으로 변경하여 휴장일/장전 시간대에도 실행 가능하도록 개선 (Safety Override)
- **News Crawler Fix**: `google-genai` 패키지 누락 수정 및 컨테이너 재빌드

## 2025-12-25
- **LangChain/Gemini**: langchain-google-genai를 google.genai 기반 최신(4.1.2)으로 업데이트하고 Gemini LLM 경로를 신 SDK로 마이그레이션, 스모크 테스트 완료 (임베딩/챗)

- **피드백 시스템 스케줄 등록**: `update_analyst_feedback.py` crontab 등록 (평일 17:00), AI 성과 분석 시간 변경 (07:00→16:40)
- **Project Recon 검증 & 버그 수정**: 정찰병 전략 구현 지시서 기준 검증 완료, RECON tier에서 `is_tradable=True` 누락 로직 수정 (`scout_pipeline.py`)
- **Dashboard Frontend 빌드 수정**: 누락 컴포넌트(Dialog, Label, Badge) 추가, `react-hot-toast` 패키지 추가, Settings.tsx 타입 에러 수정
- **Configuration Refactor**: `scout` & `news-crawler` 장 운영 시간 체크를 전역 설정(`env-vars-wsl.yaml`)으로 바이패스 가능하도록 개선 (Safety Override 포함)
- **Unit Test 추가**: SecretManager, Registry, Config API 테스트 44개 작성 (Coverage 34%)
- **Coverage 설정**: `.coveragerc` 생성 - shared/services 측정, venv/frontend 제외
- **Scout Hotfix**: 휴장일(크리스마스 등) 인식 오류 수정 - 로컬 시간 체크 로직(`/utils.py`) 대신 증권사 Gateway API(`check_market_open`) 연동으로 정확도 확보

- **Scout 최적화**: 정량 필터링 강화 (상위 80% → 40% 통과), Hunter 처리량 약 50% 감소로 LLM 부담 경감
- **gemma3:27b 통합**: 모든 LLM Tier (FAST/REASONING/THINKING)를 gemma3:27b로 통일 - 속도 2배 향상, 안정성 100%
- **Hunter/Judge 로그 상세화**: 정량점수 분해, 핵심지표(PER/PBR/RSI), 경쟁사 수혜 로깅 추가
- **대시보드 UI 개편**: Stripe 스타일 적용 (딥 네이비 배경, 인디고 액센트, 화이트 카드)
- **Oracle 레거시 제거 검증**: Mock 모드 E2E 테스트 완료 - MariaDB/SQLAlchemy 연동, RabbitMQ 메시지 처리, HTTP API 처리 모두 정상 작동 확인 (사이드 이펙트 없음)
- **Mock Mode Testing**: Buy Executor 시작 실패 버그(`IndentationError`) 수정 및 전체 매수/매도 시나리오(Scout→Executor) 검증 완료
- **Portfolio Data Integrity Fix**: `portfolio` 테이블의 중복 보유 내역(현대차, SK스퀘어) 제거 및 `total_buy_amount` 재계산 로직 적용 (데이터 정합성 복구)
- **Critical Bug Fix**: `buy-executor`가 `STOP_LOSS_PRICE`를 DB에 저장하지 않던 심각한 버그 수정 (기본 -5% 자동 설정) 및 기존 누락 데이터(미래에셋생명 등) 일괄 복구 완료
- **Language Policy**: `rules.md`에 AI 답변 언어를 한국어로 강제하는 '최우선 원칙(Critical Rule)' 추가

## 2025-12-23

- **Oracle/OCI 레거시 전면 제거**: 28개 파일에서 Oracle DB 관련 코드 952줄 삭제, MariaDB/SQLAlchemy 단일 체계로 통일 (환경변수, 시크릿, DB 분기 로직, MERGE INTO/DUAL/SYSTIMESTAMP SQL 등)
- **AI Analyst & Stability**: AI Analyst 대시보드 시각화 강화(태그, 스파크라인) 및 Buy Scanner 중복 매수 방지(Redis Lock) 구현

### Public Release (our-prime-jennie v1.0)
- **GitHub 배포**: `our-prime-jennie` Public 저장소 생성 및 배포 완료 (https://github.com/youngs7596/our-prime-jennie)
- **LLM 비용 최적화**: 기본 티어 설정 (FAST→Gemini Flash, REASONING→GPT-5-mini, THINKING→GPT-4o), 월간 예상 비용 문서화
- **Installation Bug Fix**: `install_prime.sh`의 `secrets.json` 권한 문제 수정 (sudo 실행 시 소유권 변경 로직 추가)
- **INSTALL_GUIDE 개선**: Step 순서 정정(5→6), WSL2 systemd 설정 안내 추가, Scout 실행 주기 명확화(30m trigger/4h analysis)
- **프로젝트 치환**: `my-prime-jennie` → `our-prime-jennie` 전체 파일 일괄 변환 스크립트 실행

### Critical Fixes & Incident Resolution (Real Trading)
- **Incident Resolution**: 백그라운드 Real Service 실행으로 인한 "유령 매수(Ghost Trades)"(현대차 73주 불일치) 원인 규명 및 DB 동기화 완료
- **Critical Bug Fixes**: `buy-executor` DB Logging 실패(Stop Loss Default 누락) 및 중복 매도 알림(Sell Logic 누락) 수정
- **Safety Feature**: `EXCLUDED_STOCKS` 환경변수 추가 및 삼성전자(005930) 자동매매 영구 제외 로직 구현 (`scout-job`)
- **Verification**: Mock Docker 환경에서 전체 수정 사항 E2E 검증 완료
- **Documentation**: `INSTALL_GUIDE.md` (Systemd/Logs/Links) 및 `install_prime.sh` (URL fix) 개선 완료

## 2025-12-21

### Dashboard & Rebranding (v1.3)
- **Dynamic Config**: `Overview` 페이지에 현재 사용 중인 LLM 모델(Provider, Model Name)과 일일 사용량을 동적으로 표시
- **Rebranding**: 대시보드 및 Chrome 탭 타이틀의 "My Supreme Jennie"를 "My Prime Jennie"로 일괄 변경
- **Backend**: `/api/llm/config` 및 `/api/llm/stats` API 추가
- **Configuration**: Scout/Crawler 운영 시간 복구, Judge 로컬 전환, 주간 팩터 분석 일정 변경(금 22시)

### Hotfix & Infrastructure (Systemd/Scout)
- **DB Logging Fix**: `buy-executor` 서비스의 `NameError` 및 DB 컬럼명 불일치 수정, 수동 복구 완료 (누락된 거래 기록 복원)
- **Scout Hotfix**: `StrategySelector` 속성 오류 (`STRATEGY_MOMENTUM`) 수정 (Legacy 상수 복구), `scout-job`, `buy-scanner`, `sell-executor` 재배포 완료
- **BuyExecutor Hotfix**: `executor.py` 내 미정의 변수(`db_conn`) 참조로 인한 `NameError` 수정
- **Systemd**: `my-prime-jennie.service` 환경변수 구문 오류 (`Environment=""`) 수정
- **Cron**: 주간 팩터 분석, 일일 브리핑, **일일 AI 성과 분석(Analyst)** 스케줄 등록 완료

### Scout Hybrid Scoring 검증 및 Oracle 레거시 코드 제거
- **Scout Hybrid Scoring 활성화**: `SCOUT_V5_ENABLED` 환경변수 추가로 하이브리드 스코어링 활성화
- **SQLAlchemy 호환성 수정**: `quant_scorer.py`의 4개 함수에서 cursor → SQLAlchemy text() 변환
- **Oracle 레거시 완전 제거**: `factor_analyzer.py` (12개 함수), `financial_data_collector.py` (3개 함수), `database/trading.py` (1개 분기)에서 Oracle 전용 코드 SQLAlchemy로 변환
- **영향**: 섹터별 RSI 가중치, 조건부 승률 보너스, 뉴스 통계가 정상 반영되도록 수정

### Scout 코드 클린업 (Phase 1 완료)
- `scout_pipeline.py`: Deprecated `process_llm_decision_task` 함수 제거 (~110줄)
- `scout_cache.py`: Legacy 캐시 함수 제거 (`_load_llm_cache`, `_save_llm_cache`)
- `scout.py`: v4 Legacy 코드 제거 (~231줄), 중복 정의 및 미사용 import 제거
- 전체 12개 서비스 스캔 완료, 나머지 서비스 deprecated 없음
- **Phase 1 총계: 약 350줄 제거**

### Project Prime Migration (Phase 1: In-Place Modernization)
- **MariaDB Dockerization**: Windows MariaDB → Docker Container (`mariadb:10.11`, Port 3307) 이관 및 데이터 521MB 덤프/복원 완료
- **Infrastructure**: `docker-compose.yml` DB 서비스 추가, `verify_migration.py` 검증 스크립트 작성
- **Automation**: `scripts/install_prime.sh` 유니버셜 설치 스크립트 구현 (Docker, NVIDIA, Python 환경 자동화)
- **Refactoring**: `Carbon Silicons Council` → `my-prime-jennie` 리브랜딩 및 데이터 경로 `/docker_data` 표준화 완료

### Dashboard Refactoring & Script Cleanup (v1.0)
- **Dashboard**: `package.json` v1.0.0 (jennie-dashboard), `main.py` V2 명칭 제거
- **Refactoring**: `utilities/backtest.py`(Heavy) → `backtest_gpt.py`(Lite) 전환 및 5개 중복 스크립트 제거
- **Documentation**: Project Prime (`my-prime-jennie`) 마이그레이션 전략 수정 (In-Place Modernization 후 Clean Copy)

### 서비스 리얼 모드 검증 및 안정화 (v1.2)
- **Real Mode 검증**: `scout-job` 및 `news-crawler` 실제 로직 수행(강제 트리거) 성공 (RabbitMQ 연동, 크롤링, LLM 분석, ChromaDB 저장)
- **버그 수정**:
    - `scout.py`: 캐시 로드 시 `db_conn` 미정의(`NameError`) 수정
    - `llm_providers.py`: Ollama JSON 출력 잘림 현상 수정 (`num_predict`를 4096으로 증설)
    - `shared/database`: `close_pool` 누락 수정 및 Mock Backtest 검증 완료
- **리팩토링**: `utilities/` 정리 및 프로젝트 전반 히스토리성 버전 태그 삭제 완료

### 프로젝트 전체 리팩토링 (Phase 2~4 완료)
- **Shared**: `shared/` 내 레거시 코드 제거 (거래 로직, 버전 태그 등 320라인 감소)
- **Scripts**: `backfill_news_naver.py` 주석 현행화 및 전체 스크립트 문법 검증
- **Utilities**: `backtest.py` 미사용 메서드 제거 및 CLI 인자 도움말 수정
- **총계**: Phase 1~4 포함, 프로젝트 전체에서 약 670라인의 레거시/버전 태그 제거 완료

### 코드 주석 정리 (Phase 3 - 완료)
- `shared/database/trading.py` 13개 태그 제거
- `shared/hybrid_scoring/quant_scorer.py` 55개 태그 제거
- `shared/hybrid_scoring/factor_analyzer.py` 62개 태그 제거
- `shared/db/models.py` 4개 태그 제거
- `services/news-crawler/crawler.py` 4개 태그 제거
- **총 Phase 3에서 138개 히스토리성 버전 태그 제거 (py_compile 검증 완료)**
- 전체 프로젝트에서 200개 이상의 `[vX.X]` 태그 정리 완료

### 코드 주석 정리 (Phase 2)
- `shared/database/` 6개 파일 정리 (`__init__.py`, `rag.py`, `optimization.py`, `commands.py`, `market.py`, `get_trade_logs_snippet.py`)
- `shared/llm_providers.py` 19개 태그 제거
- `shared/financial_data_collector.py`, `shared/analysis/ai_performance.py` 정리
- `shared/hybrid_scoring/` 3개 파일 정리 (`competitor_analyzer.py`, `quant_constants.py`, `schema.py`)
- `scripts/collect_*.py` 5개 파일, `scripts/tag_news_sentiment.py` 정리
- `utilities/wipe_chroma.py` 정리
- 총 60개 이상 히스토리성 버전 태그 추가 제거 (py_compile 검증 완료)

### 문서 한국어 통일 및 버전 v1.0 정리
- `README.md`의 Change Log를 `CHANGELOG.md`로 분리
- 영어 문서 8개 한국어로 번역 (`long_term_data_strategy.md`, `hybrid_llm_system_report.md`, `self_evolution_system.md` 등)
- 프로젝트 전체 버전을 v1.0으로 통일 (문서 + 서비스 코드 13개 파일)
- `.agent/workflows/council-patch.md` 한국어로 번역

### Scout 최적화 (v1.1)
- Smart Skip Filter (`should_skip_hunter`) 구현하여 LLM Hunter 호출 사전 필터링
- 보수적 임계값 (Quant<25, RSI>80, Sentiment<-50) 적용으로 LLM 호출 약 30% 감소 (상승 잠재력 유지)
- `NEWS_REVERSE_SIGNAL_CATEGORIES` AttributeError 수정
- THINKING tier를 GPT-5.2로 통일

### 자기 진화 및 주간 위원회 (v1.1)
- Shadow Radar (놓친 기회 분석), 20일 롤링 성과 윈도우, 일간 자기진화 피드백 루프 구현
- Daily Council → Weekly Council로 전환 (GPT-5.2)
- `guardrails.yaml`을 `docs/design_drafts/`로 이동 (기능 보류)
- `docs/self_evolution_system.md` 추가

---

## 2025-12-20

### 기능 (CSC v1.0 데이터 분석가)
- Analyst 모듈 (`scripts/analyze_ai_performance.py`) 구현하여 AI 결정의 실현 승률/손익 계산
- Data Strategy v1.0 기반 완성 (Archivist + Analyst)

### Scout 로직 업그레이드 (CSC v1.0)
- Factor Analysis를 통해 "역신호" 가설 과학적으로 기각 (뉴스 수익률 +1.20%)
- `quant_scorer.py`에 "외국인 눌림목 매수" 보너스 (+3.0점, 승률 60.4%) 구현
- `llm_prompts.py`에서 부정적 편향 제거
- `scripts/test_scout_v5_1.py`로 검증

### 최적화 (뉴스 크롤러)
- `ThreadPoolExecutor`를 사용하여 뉴스 분석 및 경쟁사 수혜 분석 병렬 처리 (5배 동시성) 구현
- 배치 제한 추가로 Gunicorn 타임아웃 크래시 수정

### Scout 파이프라인 V2 (Judge 로직 업그레이드)
- Judge 로직 개선 (RSI 등 정량 요소 이중 페널티 방지, 시장 국면 가중치 추가)
- Debate 근거 강화 (환각 방지, 출처 태깅 필수)
- 로깅 개선 (실제 모델명 로깅, V2 로그 분석 스크립트)

### 기능 (설정 가능한 로깅)
- `LLM_DEBUG_ENABLED` 토글 추가 (기본값: off)
- 필요 시 디버깅 가능하며 스토리지 낭비 방지

### 핫픽스 (Judge Debate 로그)
- Judge 단계에서 "빈 Debate 로그" 문제 해결
- Ollama Gateway에 `/api/chat` 엔드포인트 구현
- 채팅 완성을 위한 프로바이더 라우팅 로직 수정

### 핫픽스 (뉴스 및 ChromaDB)
- ChromaDB 볼륨 영속성 (`/data`) 수정으로 누락된 뉴스 해결
- Gemini 할당량 우회를 위해 OpenAI (GPT-5 Nano) 사용

### 핫픽스 (섹터 및 Judge 동시성)
- 하드코딩된 매핑 확장 (150+ 종목)으로 "섹터: 미분류" 문제 해결
- 섹터 정보 전파
- Ollama 순차 처리 적용으로 Judge ("빈 Debate 로그") 동시성 문제 수정

### 핫픽스 (Judge 점수 전파)
- `hunter_score` 전파 복원으로 Judge 점수 불일치 해결
- Hunter 데이터 문제 수정 (섹터 '미분류' 로직, 뉴스 날짜 파싱/필터링)
- 디버그 임계값 원복

---

## 2025-12-19

### 핫픽스 (scout-job 안정성)
- `scout-job` 안정성 문제 해결 (Gateway Timeout 600초, Rate Limit 60/분, Qwen3 환각 수정)
- `qwen3:32b` 신뢰성 검증

### 핫픽스 (Ollama 동시성)
- 로컬 Qwen3 모델을 위한 `scout-job` 동시성 최적화 (자동 2 worker 제한)
- Ollama 요청/응답 상세 디버그 로깅 추가

### Ollama Gateway 및 3현자 문서
- 3현자 리뷰 아키텍처 문서 작성
- Ollama Gateway 서비스 구현 (순차 처리, Rate Limiting)
- scout-job/news-crawler Gateway 통합
- news-crawler 간격 20분으로 변경

### 대시보드 개선
- `dashboard-v2` → `dashboard` 리네임
- 신규 API 4개 추가 (Daily Briefing, Market Regime, LLM Stats, 3 Sages Council Review)
- Overview 페이지 UI 개선

### 아키텍처 문서 리팩토링
- 6개 아키텍처 문서 `my-prime-jennie` 프로젝트명 및 LLM 참조 (Gemini/Ollama) 업데이트
- Pair Trading/Backtester 미구현 컴포넌트 제거

### CSC v1.0 마이그레이션
- 프로젝트 브랜딩 `my-prime-jennie` 통일
- FAST tier Gemini 전환
- Docker 21개 컨테이너 마이그레이션
- GitHub 리포지토리 생성

### 핫픽스 (RabbitMQ 시작)
- Docker 프로파일과의 시작 경쟁 조건 해결을 위한 애플리케이션 레벨 재시도 로직 구현

### Cycle 6: 통합 LLM 및 경쟁사 로직 업그레이드
- 모든 로컬 LLM을 `qwen3:32b`로 통일 (24GB VRAM 최적화)
- 뉴스 경쟁사 분석을 키워드 기반에서 LLM 우선 추론으로 업그레이드

### Cycle 6: 인프라 튜닝
- WSL2 듀얼 GPU 분리 (`MESA_D3D12_DEFAULT_ADAPTER_NAME="Radeon"`)로 작업표시줄 깜빡임 해결

### 3현자 에이전트 통합
- Council V1.1 구현 (Minji 에이전트 워크플로우)
- Hunter Score 0 문제 수정 (하이브리드 설정)
- Daily Council 크론 스케줄 (평일 18:00)

### Cycle 6: 문서 동기화
- 버전 정렬 (v1.0) 및 전략 문서 업데이트 (Archivist, Hybrid Scoring)

---

## 2025-12-17

### Cycle 5: 안정화
- Ollama (Qwen3) JSON 파싱 호환성 개선 및 Unit Test 100% (391개) 통과

### Self-Healing 파이프라인
- `FailureReporter`, `IncidentSchema`, `Antigravity Bridge` 구현

### 장기 데이터 전략
- Shadow Radar (필터링 탈락 기록) 및 Intraday Data (1분봉 수집) 구현 완료

### 핫픽스 (장중 데이터)
- Intraday Data Collection API 파싱 오류 수정 및 안정화

### Daily Briefing 업그레이드
- Gemini-2.0-Flash-Exp 도입
- 시장 지수 (KOSPI/KOSDAQ) 연동
- 제니 (Jennie) 페르소나 적용

---

## 2025-12-16

### Cycle 4: 수급 분석 전략
- 외국인/기관 수급 분석 (`get_investor_trend`) 및 Scout 파이프라인 연동

### Cycle 3: 로직 정제
- 키워드 기반 동적 토론자 (Context-Aware Persona) 구현

---

## 2025-12-14

### Scout v1.0 업데이트
- Kill Switch (리스크 필터), Foreign Dip Buying (외국인 수급 눌림목 매수), Real Mode 배포 완료

---

## 2025-12 (주간)

### 데이터베이스 리팩토링
- `shared/database` 패키지로 도메인별 분리 완료 (`market.py`, `trading.py`, `core.py` 등)

---

## 2025-12-08

### 수동 매매 명령어
- 텔레그램 `/buy`, `/sell` 등 지원
