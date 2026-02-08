# 📊 Dashboard 현황 분석 및 개선점 문서

> **분석 일시**: 2026-02-08 11:25 KST  
> **분석 범위**: Dashboard 전체 7개 페이지 UI/UX 및 백엔드 연동

---

## 📋 개요

Dashboard의 모든 페이지를 브라우저에서 직접 순회하고, 소스 코드를 분석하여 현재 상태와 수정이 필요한 부분을 정리했습니다.

### 페이지 목록
| 페이지 | 파일 | 상태 | 코드 규모 |
|--------|------|------|-----------|
| Overview | `Overview.tsx` | 🔴 **대규모 정리 필요** | 813줄 |
| Portfolio | `Portfolio.tsx` | ✅ 정상 | 526줄 |
| Scout | `Scout.tsx` | 🔴 **UI 업데이트 필요** | 408줄 |
| Macro Council | `MacroCouncil.tsx` | ⚠️ 데이터 없음 | 673줄 |
| System | `System.tsx` | ⚠️ Watcher offline | 785줄 |
| Analytics | `Analytics.tsx` | 🔴 **401 에러** | 723줄 |
| Settings | `Settings.tsx` | ✅ 정상 | 403줄 |

---

## 🔴 긴급 수정 필요 (P0)

### 1. Analytics 페이지 401 Unauthorized 에러

**현상**: Analytics 페이지 접속 시 "Request failed with status code 401" 에러 발생

**원인**: 프론트엔드 로그인 기능은 제거했으나, 백엔드 API에서 여전히 `verify_token` 인증을 요구

**관련 코드** (`main.py` 271-275줄):
```python
app.include_router(portfolio.router, dependencies=[Depends(verify_token)])
app.include_router(market.router, dependencies=[Depends(verify_token)])
app.include_router(airflow.router, dependencies=[Depends(verify_token)])
app.include_router(logs.router, dependencies=[Depends(verify_token)])
app.include_router(logic.router, dependencies=[Depends(verify_token)])
```

**수정 방안**:
- `services/dashboard/backend/main.py`: 라우터 등록 시 `dependencies=[Depends(verify_token)]` 제거
- `services/dashboard/backend/routers/performance.py`: `_get_verify_token()` 및 관련 `Depends` 제거

---

### 2. Scout 페이지 UI 대규모 업데이트 필요

**현상**: Scout 페이지가 **이미 폐기된 3-Phase 파이프라인**을 기준으로 UI가 구성되어 있음

**현재 UI (폐기됨)**:
- 3-Phase LLM Pipeline: Hunter Scout → Bull vs Bear Debate → Final Judge
- 각 Phase별 모델명 `gpt-oss:20b` 하드코딩

**실제 구현 (Unified Analyst 1-Pass)**:
- 단일 LLM 호출로 Hunter + Debate + Judge 통합
- 비용 1/3, 토큰 1/3 절감
- `risk_tag`는 코드 기반 계산 (`classify_risk_tag()`)
- 환경변수 `SCOUT_USE_UNIFIED_ANALYST=true` (기본값)

**관련 코드**:

| 파일 | 내용 |
|------|------|
| `services/dashboard/frontend/src/pages/Scout.tsx` | 3-Phase UI 표시 (폐기됨) |
| `services/scout-job/scout.py` (1220-1260줄) | Unified vs Legacy 분기 |
| `services/scout-job/scout_pipeline.py` (621-854줄) | `process_unified_analyst_task()` |

**수정 방안**:
1. **Frontend**: Scout.tsx UI를 1-Pass 구조로 전면 개편
   - "3-Phase Pipeline" → "Unified Analyst" 로 변경
   - 단일 분석 단계로 시각화 단순화
   - 모델명 동적 조회 (API 연동)

2. **Backend**: 레거시 코드 제거 (아래 별도 항목 참조)

---

### 3. Scout 백엔드 레거시 코드 제거 필요

**현상**: `SCOUT_USE_UNIFIED_ANALYST=false` 분기와 관련된 2-Pass 레거시 코드가 남아있음

**관련 코드** (`services/scout-job/scout.py` 1257-1323줄):
```python
else:
    # =====================================================
    # Legacy: 2-pass (Hunter → Debate+Judge)
    # =====================================================
    logger.info("🔄 Legacy Mode (Hunter → Debate+Judge, 2-pass)")
    # ... 100줄 이상의 레거시 코드
```

**제거 대상**:

| 파일 | 제거 대상 |
|------|----------|
| `services/scout-job/scout.py` | `use_unified_analyst` 분기문 및 `else` 블록 (1257-1323줄) |
| `services/scout-job/scout_pipeline.py` | `process_phase1_hunter_v5_task()` (215-360줄) |
| `services/scout-job/scout_pipeline.py` | `process_phase23_judge_v5_task()` (363-618줄) |

**수정 방안**:
- `SCOUT_USE_UNIFIED_ANALYST` 환경변수 및 분기 제거
- `process_phase1_hunter_v5_task()`, `process_phase23_judge_v5_task()` 함수 삭제
- 관련 import 정리
- 약 **400줄** 코드 삭제 예상

---

## ⚠️ 일반 개선 필요 (P1)

### 4. Overview 페이지 중복 컴포넌트 제거 필요

**현상**: Market Regime, 3현자 데일리 리뷰가 Macro Council 페이지로 이동했지만 Overview에 여전히 존재

**제거 대상 컴포넌트** (`services/dashboard/frontend/src/pages/Overview.tsx`):
- 시장 국면 (Market Regime) 섹션
- 3현자 데일리 리뷰 섹션
- Macro Insight 섹션

---

### 5. LLM 사용 통계 데이터 수집 문제

**현상**: LLM 사용 통계가 모두 0회, 0토큰으로 표시됨

**추정 원인**:
- LLM 호출 시 통계 데이터가 DB/Redis에 저장되지 않음
- `llmApi.getUsageStats()` API 엔드포인트 확인 필요
- JennieBrain 호출 시 통계 로깅 누락 가능성

**수정 방안**:
- LLM 호출 후 통계 저장 로직 확인/추가
- 모델명도 실제 사용 모델(DeepSeek vLLM)로 업데이트 필요

---

### 6. Market Regime "미구현" 표시

**현상**: Overview 페이지에서 시장 국면이 "🚧 미구현"으로 표시

**관련 코드** (`Overview.tsx` 468-473줄):
```typescript
{(!marketRegime?.regime || marketRegime?.regime === 'UNKNOWN' || marketRegime?.regime === 'ERROR') && '🚧 미구현'}
```

**수정 방안**:
- `marketApi.getRegime()` 백엔드 API 구현 확인 필요
- 실제 KOSPI 데이터 기반 Bull/Bear/Sideways 판단 로직 연결

---

### 7. System 페이지 Real-time Watcher Offline

**현상**: "Monitoring offline - check Price Monitor" 경고 표시

**점검 사항**:
- `price-monitor` 서비스 WebSocket/SSE 연결 상태 확인
- Redis Pub/Sub 또는 소켓 연결 문제 가능성

---

### 8. 불필요한 파일 정리

**현상**: `Login.tsx` 파일이 여전히 존재 (4,536 bytes)

**수정 방안**:
- `services/dashboard/frontend/src/pages/Login.tsx` 삭제
- 관련 import 및 라우트 정리 확인

---

## 📄 페이지별 상세 분석

### 1️⃣ Overview (홈)

**주요 컴포넌트**:
- 총 자산/수익/보유 종목/Scout Pipeline 카드
- 자산 추이 차트 (30일)
- 포트폴리오 구성 파이 차트
- 최근 거래 목록
- ~~Scout-Debate-Judge Pipeline 상태~~ (→ Scout 페이지로 통합)
- ~~Market Regime~~ (→ Macro 페이지로 이동)
- ~~Macro Insight (Council 분석)~~ (→ Macro 페이지로 이동)
- LLM 사용 통계 (⚠️ 데이터 수집 문제)
- ~~3현자 데일리 리뷰~~ (→ Macro 페이지로 이동)

**확인된 이슈**:
- Market Regime, 3현자 리뷰: Macro 페이지로 이동했으나 Overview에 중복 존재
- LLM 통계: 데이터 수집이 제대로 안 됨 (0회/0토큰 표시)

---

### 2️⃣ Portfolio

**상태**: ✅ 정상 작동

**주요 컴포넌트**:
- Positions 탭: 보유 종목 목록, 정렬/필터
- Trading 탭: 거래 내역

**확인 결과**:
- UI 정상 렌더링
- 보유 종목 없음 (정상 상태)
- 정렬 및 검색 기능 작동

---

### 3️⃣ Scout (⚠️ UI 업데이트 필요)

**현재 UI (폐기된 구조)**:
- 3-Phase LLM Pipeline 시각화 (Hunter → Debate → Judge)
- 각 Phase별 `gpt-oss:20b` 표시

**실제 구현 (Unified Analyst)**:
- 1회 LLM 호출로 통합 분석
- 비용/토큰 1/3 절감
- risk_tag는 코드 기반 계산

**필요 작업**:
1. UI를 1-Pass 구조로 전면 개편
2. 백엔드 레거시 코드 제거

---

### 4️⃣ Macro Council

**상태**: ⚠️ 데이터 없음 (정상 - 스케줄 실행 전)

**주요 컴포넌트**:
- Global Snapshot (VIX, USD/KRW 등)
- 투자자별 수급 현황
- Council 분석 결과
- 매크로 인사이트 이력

**확인 결과**:
- "Council 분석 데이터 없음" 표시
- 매일 오전 7:30 KST 실행 스케줄 안내 표시

---

### 5️⃣ System (인프라 모니터링)

**탭 구성** (5개):
- Infrastructure: Docker 컨테이너 상태
- Workflows: Airflow DAG 관리
- Logs: 서비스별 로그 스트리밍
- Architecture: 시스템 아키텍처
- Operations: 운영 명령어

**확인된 이슈**:
- Real-time Watcher Status: "Monitoring offline"
- Docker 컨테이너: 30개 모두 healthy 상태

---

### 6️⃣ Analytics

**상태**: 🔴 **401 에러로 사용 불가**

**탭 구성** (2개):
- Performance: 투자 성과 분석
- AI Analyst: AI 분석가 성과

**필수 수정**:
- 백엔드 `verify_token` 인증 제거 필요

---

### 7️⃣ Settings

**상태**: ✅ 정상 작동

**탭 구성** (2개):
- General: 시스템 설정값 관리
- Factors: 매매 팩터 설정

**확인 결과**:
- Config 테이블 정상 로드
- 수정 모달 작동 확인
- Factors 탭 정상 표시

---

## 🔧 수정 작업 요약

| 우선순위 | 작업 | 파일 | 예상 난이도 |
|----------|------|------|-------------|
| P0 | Analytics 401 에러 수정 | `backend/main.py`, `routers/performance.py` | 🟢 Easy |
| P0 | **Scout UI 전면 개편 (3-Phase → 1-Pass)** | `Scout.tsx` | 🔴 Major |
| P0 | **Scout 백엔드 레거시 코드 제거** | `scout.py`, `scout_pipeline.py` | 🟡 Medium |
| P0 | **Overview 중복 컴포넌트 제거** | `Overview.tsx` | 🟡 Medium |
| P1 | LLM 통계 데이터 수집 문제 해결 | `JennieBrain`, `llmApi` | 🟡 Medium |
| P1 | Market Regime API 연결 | `backend/main.py`, `Overview.tsx` | 🟡 Medium |
| P1 | Login.tsx 파일 삭제 | `pages/Login.tsx` | 🟢 Easy |
| P2 | Watcher 연결 점검 | `price-monitor` 서비스 | 🟡 Medium |
