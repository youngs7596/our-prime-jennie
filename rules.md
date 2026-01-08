# Cursor용 프로젝트 규칙 (Single Source of Truth)

> **이 저장소의 규칙 정본은 이 파일(`rules.md`) 하나입니다.**  
> `.ai/RULES.md`, `.agent/workflows/*`, `.cursorrules`는 모두 **이 문서를 가리키는 포인터/워크플로우 템플릿**로 유지합니다.

---

## 🚨 최우선 원칙 (Critical Rule)

**"AI는 어떤 상황에서도 반드시 한국어로 대답한다."**

> **⚠️ Gemini 모델 필독 (ATTENTION GEMINI MODELS)**:
> Gemini 계열 모델은 종종 영어로 대답하는 경향이 있는데, 이는 **심각한 규칙 위반**입니다.
> 사용자의 질문이 영어이거나, 코드 변수명이 영어라도 **답변, 설명, 주석은 무조건 한국어**로 작성해야 합니다.

- **절대 원칙**: "English Input" -> "Korean Output"
- 생각(Thought process)은 영어로 할 수 있으나, **최종 답변(Response)은 100% 한국어**여야 합니다.
- 이 규칙은 다른 어떤 기술적/절차적 규칙보다 우선합니다.


---

## 프로젝트 개요

- **프로젝트명**: `my-prime-jennie`
- **목적**: 주식/자산 자동 매매 에이전트 개발 (LLM 기반 판단 + 실제 트레이딩)
- **기술 스택**
  - Backend: Python (FastAPI), Node.js
  - Database: MariaDB, Redis, ChromaDB
  - Infra: Docker Compose, Jenkins
  - Trading API: KIS (한국투자증권)

---

## 개발 품질(퀄리티) 원칙 — Definition of Done

- **정확성 우선**: “왜/어디서/언제” 깨지는지 재현 → 원인 파악 → 최소 변경으로 수정
- **회귀 방지**: 가능한 경우 테스트(또는 최소한 재현 스크립트/검증 로그)를 추가
- **관측 가능성**: 실패 시 조용히 기본값으로 덮지 말고, **명확한 로그/에러**로 드러내기
- **안전성**: 트레이딩/자금 관련 로직은 보수적으로(원자성, idempotency, retry-safe)
- **완료 보고 기준**: “코드 작성”이 아니라 **동작 확인(로그/실행 결과)** 후에만 완료 보고

---

## 작업 시작 전 “필수 질문 3개” (항상 먼저 확인)

- **목표(Goal)**: 무엇을 “사용자 관점에서” 해결해야 하나? (버그 재현/기능 정의/성능 목표 수치)
- **범위(Scope)**: 이번 변경에 **포함/제외**는 무엇인가? (서비스/모듈/환경: REAL vs MOCK)
- **완료 조건(Done)**: 무엇이 확인되면 “끝”인가?
  - 예: 특정 API 응답/로그 1줄, 테스트 1개 통과, 대시보드에서 특정 UI 상태 확인

> 위 3개가 불명확하면 **코드를 먼저 건드리지 말고 질문**하거나, 최소 가정(Assumptions)을 명시하고 진행합니다.

---

## 토큰 절약 + 고퀄 유지 “똘똘한” 진행 규칙

- **검색 우선(Search-first)**
  - 모르는 위치/흐름은 `grep`/`codebase_search`로 먼저 좁힌 뒤, 필요한 파일/구간만 `read_file`
  - 큰 파일은 통째로 읽지 말고 **관련 함수/구간만** 로드
- **최소 컨텍스트 로딩(Load-minimal)**
  - “지금 수정할 코드”에 필요한 import/호출 경로만 확인
  - 같은 파일/같은 구간을 **중복해서 다시 읽지 않기**
- **작은 패치(Small diffs)**
  - 한 번에 많은 것을 바꾸지 말고, 원인-수정-검증이 연결되도록 최소 변경
  - 여러 변경이 필요하면 **작업 단위를 쪼개고 체크리스트로 관리**
- **도구 호출 절약(Batch)**
  - 독립적인 조회/검색은 가능하면 한 번에 묶어서 실행(병렬)
  - 린트/테스트는 “수정한 파일/관련 범위” 위주로 좁혀 실행
- **명확한 가드레일(Guardrails)**
  - 입력 누락/스키마 드리프트는 default=0 같은 **침묵 실패 금지**
  - 계약(스키마/키 경로)은 한 곳(어댑터/모델)로 모아 일관되게 사용

---

## 개발 작업 기본 체크리스트 (최소 비용으로 퀄리티 확보)

- **탐색(필수)**
  - [ ] 증상/요구사항을 1문장으로 정리(Goal)
  - [ ] 관련 코드 위치를 `grep`/`codebase_search`로 좁힘(전체 파일 로드 금지)
  - [ ] 변경 영향 범위(서비스/모듈/데이터/외부 API) 1줄로 기록
- **구현(필수)**
  - [ ] “최소 변경”으로 원인-수정이 연결되게 패치
  - [ ] 트레이딩/중요 데이터 경로는 **원자성/중복 실행 안전(idempotency)** 확인
  - [ ] 침묵 실패(기본값 덮기) 제거: 누락 시 **명확한 로그/에러/가드**
- **검증(필수)**
  - [ ] 수정한 파일에 한해 최소 단위 검증 수행(예: `py_compile`, 좁은 범위 테스트)
  - [ ] 동작 확인 로그/출력 1개 이상 확보(“작동했다” 근거)
  - [ ] 프론트/백엔드 데이터 단위(%, 단위 변환 등) 불일치 점검
- **보고(필수)**
  - [ ] “무엇을/왜/어디를” 바꿨는지 3줄 요약
  - [ ] 사용자에게 즉시 확인할 체크포인트 1~2개 제시
- **승인 게이트(필수)**
  - [ ] 아래는 **사용자 승인 후**만 진행:
    - 삭제(`rm -rf` 등), DB 마이그레이션, `.env`/`secrets.*` 수정, 10개+ 파일 대규모 리팩토링
    - git push/배포/실거래(REAL) 관련 위험 변경
- **롤백 플랜(권장)**
  - [ ] 문제가 생기면 되돌릴 파일/커밋/토글(플래그) 1개를 명시

---

## 부트스트랩(세션 시작) 규칙

새로운 대화/에이전트 세션을 시작하면 **반드시 아래 순서**로 진행합니다.

1. **규칙 로드**
   - `rules.md`(이 문서)를 먼저 읽고 그대로 따릅니다.
2. **최신 세션 파일 로드**
   - `.ai/sessions/`에서 **가장 최근** `session-*.md`를 찾아 읽습니다.
3. **컨텍스트 로딩**
   - 세션 파일의 **"Context for Next Session"**에 적힌 파일을 우선 확인합니다.
   - 세션 파일의 **"Next Steps"**를 기준으로 작업을 이어갑니다.
4. **사용자 브리핑**
   - “이전 세션에서 어디까지 했고, 다음 할 일/로드할 파일은 무엇인지”를 짧게 보고합니다.
   - 마지막에 **"이어서 진행할까요?"**를 확인합니다.

> 참고: `.ai`, `.agent`는 **숨김 폴더**라 기본 목록에서 안 보일 수 있습니다.  
> 쉘에서는 `ls -la`로 확인하세요.

---

## 세션 재개(Resume) 워크플로우

사용자가 “계속 진행”, “이어서”, “resume” 류로 요청하면:

- [ ] `rules.md` 읽기
- [ ] `.ai/sessions/` 최신 `session-*.md` 읽기
- [ ] 세션 내용 기반으로 요약/다음 단계/필요 파일 리스트 브리핑
- [ ] “이어서 진행할까요?” 확인 후 실행

원본: `.agent/workflows/resume.md`

---

## 세션 종료(Handoff) 워크플로우

사용자가 **"정리해줘"**, **"세션 저장"**, **"handoff"**, **"세션 종료"** 등을 말하면:

1. **세션 분석 및 요약 작성**
   - `.ai/sessions/session-YYYY-MM-DD-HH-mm.md` 생성
   - 아래 형식을 따릅니다:

```markdown
# Session Handoff: [제목]

## 요약 (Summary)
[간단한 설명]

## 변경 사항 (Changes)
- [파일]: [변경 내용]

## 다음 단계 (Next Steps)
- [ ] 할 일 항목
```

> ⚠️ **개인정보 보호 (Privacy)**
> 세션 파일 및 CHANGELOG에는 다음 정보를 **포함하지 않습니다**:
> - 구체적인 보유 주식 수량 및 매수/매도 금액
> - 계좌번호, 자산 규모 등 개인 재정 정보
> - API 키, 비밀번호 등 인증 정보
>
> 세션 파일은 Git에 커밋되어 `public` 저장소에 동기화될 수 있으므로,
> 기술적 변경사항 위주로 작성하고 개인정보는 생략합니다.

2. **CHANGELOG 업데이트**
   - `CHANGELOG.md`에 오늘 작업 내용을 **한 줄**로 요약해 추가합니다.
3. **Git 동기화(주의: 사용자 승인 필요 가능)**
   - `git add .`
   - `git commit -m "Session Handoff: [제목]"`
   - `git push origin development`

원본: `.agent/workflows/handoff.md`

---

## Junho 리뷰 기반 패치(council-patch) 워크플로우

목표: 최신 `junho_review.json`의 `action_items_for_minji` / `key_findings`를 코드에 반영합니다.

1. **리뷰 찾기 및 읽기**
   - `reviews/YYYY-MM-DD/`에서 최신 `junho_review.json`을 찾고 읽습니다.
2. **분석 및 계획**
   - 수정 대상 파일을 식별하고(`grep` 활용), 안전하게 적용 계획을 세웁니다.
   - **제약(주의 경로)**: `services/execution_engine.py`, `shared/db/*`는 극도의 주의 없이 수정하지 않습니다.
   - **허용(상대적으로 안전)**: `prompts/`, `scripts/`, `services/scout-job/*.py`, `config/*.yaml`
3. **실행 및 검증**
   - 변경 적용 후 관련 테스트를 실행합니다.
     - Scout 수정 시: `pytest tests/test_scout_pipeline.py`
     - Hunter 수정 시: `pytest tests/test_hunter.py`
4. **마무리**
   - 변경사항 요약 + 커밋/푸시는 **사용자 승인 요청** 후 진행합니다.

원본: `.agent/workflows/council-patch.md`

---

## 토큰 효율(컨텍스트) 규칙

- **주기적 체크포인트**: 큰 기능 완료 시/대화가 길어질 때 중간 정리를 제안
- **컨텍스트 최소화**: 전체 파일보다 관련 함수/클래스 위주로 로드
- **점진적 로딩**: 핵심 파일 → 필요 시 추가 로드

---

## 빌드 / 실행 / 린트

```bash
# 인프라 서비스 시작
docker compose --profile infra up -d

# 실서비스 시작
docker compose --profile real up -d

# 로그 확인
docker compose logs -f [서비스명]

# Python 린트
ruff check .
```

---

## 구현 검증 원칙 (배포 전 품질 게이트)

> ⚠️ **핵심 원칙**: 기능 개발, 코드 리팩토링 등 형상에 변경이 생기면 **Unit Test + Integration Test를 포함한 사전 검증**을 충분히 거친 후 안정적인 버전을 배포합니다.
> 
> 배경: 배포 후 오류 발견 → 다시 디버깅하는 반복을 줄이기 위함입니다.

### 필수 검증 단계 (배포 전 체크리스트)

1. **문법 검증 (Syntax Check)**
   ```bash
   # 변경된 Python 파일 문법 확인
   python -m py_compile [변경된_파일.py]
   ```

2. **Unit Test + Integration Test 실행 (필수)**
   ```bash
   # 변경된 모듈 관련 Unit Test
   pytest tests/shared/[관련_테스트].py -v
   
   # 전체 shared 모듈 Unit Test
   pytest tests/shared/ -v --tb=short
   
   # 서비스 코드 변경 시 해당 서비스 테스트
   pytest tests/services/[서비스명]/ -v
   
   # Integration Test (서비스 간 연동 확인)
   pytest tests/integration/ -v --tb=short
   ```

3. **커버리지 확인 (권장)**
   ```bash
   pytest tests/shared/ --cov=shared --cov-report=term-missing
   ```

4. **로그/실행 결과 확인**
   - 구현 후에는 **로그/실행 결과로 실제 동작 확인**을 우선합니다.
   - 정상 동작이 확인된 경우에만 완료 보고합니다.

### 변경 유형별 검증 범위

| 변경 유형 | 필수 검증 | 권장 검증 |
|-----------|-----------|-----------|
| **새 기능 추가** | Unit Test 작성 + 실행 | Integration Test + 관련 모듈 전체 |
| **버그 수정** | 재현 테스트 → 수정 → 통과 확인 | 회귀 테스트 추가 |
| **리팩토링** | Unit Test + Integration Test 전체 통과 | 커버리지 유지/향상 확인 |
| **의존성 변경** | 전체 테스트 실행 (Unit + Integration) | E2E/Smoke 테스트 |

### 배포 승인 기준

- [ ] 관련 Unit Test + Integration Test **전체 통과** (0 failures)
- [ ] 새 기능의 경우 **테스트 코드 포함**
- [ ] 린트 에러 없음 (`ruff check .`)
- [ ] 로그/실행 결과로 동작 확인 완료

> 💡 **알림**: 테스트 없이 배포하거나, 테스트 실패 상태로 배포를 진행하지 않습니다.
> 테스트가 어려운 경우, 최소한 `py_compile` + 수동 검증 로그를 확보합니다.

---

## 위험 작업 제한(승인 필요)

아래 작업은 **반드시 사용자 승인 후** 실행합니다.

- 파일/디렉토리 삭제 (`rm -rf` 등)
- DB 마이그레이션 변경
- 환경변수/시크릿 수정 (`.env`, `secrets.*`)
- 10개 이상의 파일을 동시에 수정하는 대규모 리팩토링

---

## 커뮤니케이션 규칙

- 한국어로 대화
- 코드 주석은 한국어(기존 스타일 따름)
- 작업 전 짧은 계획 공유, 작업 후 결과 요약

---

## 주요 의사 결정 (Key Decisions)

> 💡 **주요 기술적/정책적 의사 결정 사항은 반드시 이 섹션에 기록하여 팀 전체가 공유해야 합니다.**

### 1. Local LLM 표준화
- **모델 이원화 (Tier별 최적화)**:
  - **FAST Tier (News/Sentiment)**: **`exaone3.5:7.8b`**
    - 이유: 한국어 금융 뉴스 뉘앙스 파악 능력 탁월, 압도적인 처리 속도(0.6~0.9초), 보수적/논리적 추론.
  - **REASONING / THINKING Tier (Strategy/Deep Logic)**: **`gpt-oss:20b`**
    - 이유: 복잡한 전략 수립 및 심층 추론에는 여전히 더 큰 파라미터 모델이 유리.
- **변경 이력**:
  - 2026-01-08: 뉴스 분석(FAST)용으로 `exaone3.5:7.8b` 공식 채택 (vs `gpt-oss:20b` 비교 테스트 결과 기반).
  - 2026-01-07: 모든 Tier를 `gpt-oss:20b`로 통일했으나, 속도 및 한국어 특화 성능 이슈로 FAST Tier 분리.

### 2. Local LLM 성능 최적화 (Batch vs Parallel)
- **배치 처리(Batch Processing) 우선**: 로컬 환경(단일 GPU)에서는 병렬 처리보다 **순차적 배치 처리(Sequential Batch Processing)**가 훨씬 더 높은 처리량(Throughput)과 안정성을 제공합니다.
  - 벤치마크 결과 (2026-01-07):
    - **Sequential Batch (Batch=5)**: ~12초/배치 (Items/sec ≈ 0.42) - **Winner 🏆**
    - **Parallel Processing (Workers=5)**: ~32초/배치 (Items/sec ≈ 0.15) - **Loser** (VRAM Thrashing, Context Switching 비용 과다)
  - **가이드**: `news-crawler` 등 대량 처리 시 `ThreadPoolExecutor` 대신 순차 루프를 사용하고, 프롬프트 내에서 다건(One-Shot Example 포함)을 한 번에 처리하세요.

---


