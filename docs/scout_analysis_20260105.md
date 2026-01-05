# `scout.py` 서비스 분석 보고서 (2026-01-05)

## 1. 개요 (Overview)

`scout.py`는 대한민국 주식 시장에서 잠재력 있는 투자 종목을 자동으로 발굴하기 위해 설계된 **하이브리드형 종목 분석 및 추천 파이프라인**입니다. 이 시스템은 순수 데이터 기반의 정량적 분석(Quantitative Analysis)과 대규모 언어 모델(LLM)을 활용한 정성적 분석(Qualitative Analysis)을 결합하여, 인간 애널리스트의 의사결정 과정을 모방하고 자동화하는 것을 목표로 합니다.

주요 특징은 다음과 같습니다.
- **다중 소스 기반 후보군 발굴**: 시가총액, 섹터 모멘텀, 뉴스 등 다양한 소스에서 후보 종목을 수집합니다.
- **다단계 LLM 평가**: 'Hunter-Debate-Judge'의 3단계 LLM 파이프라인을 통해 종목을 심층 분석합니다.
- **자기 진화 시스템**: 과거 데이터를 학습하여 스스로의 분석 로직(팩터 가중치, 전략 파라미터)을 최적화합니다.
- **효율성 및 안정성**: 데이터 사전 조회, 스마트 스킵, Rust 백엔드 연동 등을 통해 성능과 안정성을 확보합니다.

---

## 2. 핵심 아키텍처 (Core Architecture)

### 2.1. 하이브리드 종목 발굴 (Hybrid Universe Generation)

`scout_universe.py`에서 정의된 5가지 소스를 결합하여 초기 후보군을 생성합니다.

1.  **동적 우량주**: KOSPI 시가총액 상위 종목을 동적으로 수집하여 시장의 중심주를 포함합니다.
2.  **정적 우량주**: 사전에 정의된 핵심 우량주 목록을 포함하여 안정성을 확보합니다.
3.  **섹터 모멘텀**: 최근 시장에서 강세를 보이는 '핫 섹터'를 분석하고 해당 섹터의 주도주를 편입하여 시장 트렌드를 반영합니다.
4.  **RAG (뉴스 기반)**: ChromaDB 벡터 데이터베이스를 활용하여 '실적 호재', '수주' 등 긍정적 키워드와 관련된 뉴스에 등장하는 종목을 발굴합니다.
5.  **모멘텀 팩터**: 과거 특정 기간 동안 시장 대비 높은 상대 수익률을 보인 종목을 추가하여 추세 추종 전략을 구사합니다.

### 2.2. 다단계 LLM 평가 파이프라인 (Scout v5)

`scout_pipeline.py`는 LLM을 활용한 다단계 분석의 핵심입니다.

1.  **정량 점수 계산 (Quant Scoring)**: `QuantScorer`가 LLM 호출 전에 재무, 기술, 수급 데이터를 바탕으로 1차 점수를 산출합니다. 이 점수는 단기(D+5)와 장기(D+60) 전략을 모두 고려하는 `Dual Track` 방식으로 계산됩니다.
2.  **스마트 스킵 (Smart Skip)**: 정량 점수가 낮거나, RSI 과매수 상태인 종목 등 성공 확률이 낮은 후보는 LLM 분석을 건너뛰어 비용과 시간을 절약합니다.
3.  **Phase 1: Hunter**: 1차 LLM 분석 단계입니다. 정량 점수, 최신 뉴스, 수급 데이터, 그리고 **분석가의 과거 피드백**을 컨텍스트로 받아 종목의 잠재력을 평가하고 1차 점수(Hunter Score)를 부여합니다.
4.  **Phase 2-3: Debate & Judge**: Hunter를 통과한 종목들을 대상으로 최종 의사결정을 내립니다.
    - **Debate**: Bull(긍정) vs Bear(부정) 역할을 맡은 두 가상 전문가가 토론하며 투자 아이디어의 장단점을 입체적으로 분석합니다.
    - **Judge**: 토론 내용과 모든 컨텍스트를 종합하여 최종 투자 적격 여부와 점수를 판정합니다.

### 2.3. 기술 스택 (Technology Stack)

- **주요 언어**: Python, Rust (`strategy_core` 모듈)
- **데이터베이스**: MariaDB (ORM: SQLAlchemy)
- **캐시/상태 관리**: Redis
- **벡터 DB**: ChromaDB
- **LLM 오케스트레이션**: `LLMFactory`를 통해 Ollama(로컬), Gemini, OpenAI 등 다양한 LLM 프로바이더를 동적으로 선택 및 폴백(Fallback)합니다.

---

## 3. 상세 동작 순서 (Detailed Execution Flow)

1.  **Phase 0: 초기화 (Initialization)**
    - 운영 시간 확인 후 KIS API, LLM, DB 클라이언트 등 모든 서비스를 초기화합니다.

2.  **Phase 1: 후보 종목 발굴 (Candidate Generation)**
    - `scout_universe.py`를 통해 5가지 소스(동적/정적 우량주, 섹터 모멘텀, RAG, 모멘텀 팩터)에서 중복을 제거한 후보군을 생성합니다.

3.  **Phase 2: 데이터 보강 및 사전 처리 (Data Enrichment & Prefetch)**
    - `prefetch_all_data` 함수가 후보 종목의 최신 가격, 거래량, 뉴스, 수급 데이터를 병렬로 미리 조회하여 API 병목을 최소화합니다.
    - `Archivist`가 수급 데이터를 `MARKET_FLOW_SNAPSHOT` 테이블에 기록합니다.

4.  **Phase 3: 하이브리드 스코어링 (Hybrid Scoring)**
    - `MarketRegimeDetector`가 KOSPI 지수 움직임을 기반으로 현재 시장 국면(상승/하락/횡보)을 판단합니다.
    - `QuantScorer`가 모든 후보에 대해 정량 점수를 계산하고, 하위 20%를 1차 필터링합니다.
    - `should_skip_hunter` 함수가 LLM 호출 대상을 '스마트 스킵' 로직으로 압축합니다.
    - **Hunter** LLM이 1차 분석 후 기준 점수(60점) 미만 종목을 탈락시킵니다.
    - **Judge** LLM이 최종 토론 및 분석 후 투자 승인(75점 이상) 여부를 결정합니다.
    - `HybridScorer`가 정량 점수와 Judge 점수를 결합하여 최종 점수를 산출하며, 두 점수 차이가 클 경우 'Safety Lock'을 발동시켜 보수적으로 점수를 조정합니다.

5.  **Phase 4: 최종 선정 및 저장 (Final Selection & Persistence)**
    - 최종 승인된 종목 중 상위 15개만 선택하는 **쿼터제**를 적용합니다.
    - 선정된 종목을 `Watchlist` 테이블에 저장하고, `financial_data_collector`를 통해 상세 재무 데이터를 업데이트합니다.
    - `Archivist`가 LLM의 모든 의사결정 과정을 `LLM_DECISION_LEDGER`에, 아쉽게 놓친 기회는 `SHADOW_RADAR_LOG`에 기록하여 데이터 자산을 축적합니다.
    - Redis에 파이프라인 최종 완료 상태와 결과를 저장하여 대시보드에 표시합니다.

---

## 4. 주요 특징 및 강점 (Key Features & Strengths)

### 4.1. 자기 진화 시스템 (Self-Evolving System)

- **`FactorAnalyzer`**: 주기적으로 각 투자 팩터(모멘텀, 가치 등)의 유효성을 시장 데이터로 검증(IC, IR 계산)하고, 그 결과를 `FACTOR_METADATA` 테이블에 저장합니다. `QuantScorer`는 이 통계를 동적으로 참조하여 팩터 가중치를 조절합니다.
- **`scout_optimizer.py`**: 백테스트를 통해 전략 파라미터(RSI 임계값 등)를 자동으로 최적화하고, LLM의 검증을 거쳐 `CONFIG` 테이블에 반영합니다.
- **Analyst Feedback Loop**: Redis에 저장된 분석가(사용자)의 피드백/전략을 LLM 프롬프트에 포함시켜, 시간이 지남에 따라 분석 모델이 더 정교해집니다.

### 4.2. 효율성 및 안정성 (Efficiency & Stability)

- **Polyglot 아키텍처**: 성능에 민감한 기술적 지표 계산(RSI, ATR 등)은 Rust로 구현된 `strategy_core` 모듈을 사용하여 Python의 성능 한계를 극복합니다.
- **데이터 사전 조회 (Prefetch)**: API 호출과 DB 조회를 병렬로 미리 처리하여 파이프라인의 병목 현상을 최소화합니다.
- **견고한 오류 처리**: `shared/utils.py`의 데코레이터들은 API 호출 실패 시 지수 백오프(Exponential Backoff)를 적용한 자동 재시도 로직을 수행하며, 최종 실패 시 `FailureReporter`를 통해 Incident Report를 생성합니다.

### 4.3. 정교한 분석 모델 (Sophisticated Analysis Model)

- **Dual Track 정량 분석**: `QuantScorer`는 단기(D+5)와 장기(D+60) 성과를 예측하는 두 가지 전략을 동시에 사용하여, 단기적으로는 RSI와 수급을, 장기적으로는 ROE와 뉴스의 장기 효과를 중시합니다.
- **경쟁사 수혜 분석**: `CompetitorAnalyzer`는 경쟁사의 악재(공장 화재, CEO 리스크 등)를 감지하고, 이를 통해 반사이익을 얻을 수 있는 종목에 가산점을 부여하여 산업 생태계 내에서의 관계를 분석합니다.
- **동적 프롬프트 엔지니어링**: `llm_prompts.py`의 프롬프트들은 정량 분석 결과, 시장 국면, 분석가 피드백 등을 동적으로 주입하여 LLM이 항상 최적의 컨텍스트를 가지고 판단하도록 유도합니다.

---

## 5. 결론 (Conclusion)

`scout.py` 서비스는 단순한 자동화 스크립트를 넘어, 시장 데이터와 상호작용하며 스스로 학습하고 진화하는 지능형 시스템입니다. 정량적 데이터와 정성적 컨텍스트를 균형 있게 활용하는 하이브리드 접근 방식, 그리고 실패로부터 배우는 피드백 루프는 이 시스템이 장기적으로 시장 변화에 적응하며 꾸준한 성과를 낼 수 있는 강력한 기반이 됩니다.