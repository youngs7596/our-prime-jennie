# 📅 변경 이력 (Change Log)

## 2025-12-21

### Dashboard & Rebranding (v1.3)
- **Dynamic Config**: `Overview` 페이지에 현재 사용 중인 LLM 모델(Provider, Model Name)과 일일 사용량을 동적으로 표시
- **Rebranding**: 대시보드 및 Chrome 탭 타이틀의 "My Supreme Jennie"를 "My Prime Jennie"로 일괄 변경
- **Backend**: `/api/llm/config` 및 `/api/llm/stats` API 추가
- **Configuration**: Scout 및 News Crawler의 운영 시간 체크 로직(07:00~17:00) 원상복귀 및 Judge 모델 로컬(`qwen3:32b`) 전환

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
