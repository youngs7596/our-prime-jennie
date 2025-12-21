# 🏗️ 데이터 축적 유틸리티 구현 보고서 (Cycle 2)

이 문서는 [장기 데이터 전략](./long_term_data_strategy.md)에 필요한 데이터 축적 프레임워크의 기술적 구현을 상세히 설명합니다.

**구현 날짜**: 2025-12-16
**상태**: 배포 완료

## 1. 데이터베이스 스키마 업데이트 (`shared/db/models.py`)

중요한 "기억" 및 "컨텍스트" 데이터를 캡처하기 위해 4개의 새로운 테이블을 도입했습니다.

### A. `LLM_DECISION_LEDGER` (Priority 1)
*   **목적**: "두뇌의 기억". 결정이 내려진 이유를 기록합니다.
*   **주요 필드**:
    *   `debate_log`: Bull vs. Bear 토론의 전체 텍스트
    *   `dominant_keywords`: 주요 테마의 JSON 목록 (예: ["리튬", "전쟁"])
    *   `final_decision`: 매수 / 매도 / 보유 / NO_DECISION
    *   `hunter_score`: 결정 시점의 정량 점수

### B. `SHADOW_RADAR_LOG` (Priority 2)
*   **목적**: "놓친 기회" 추적기
*   **주요 필드**:
    *   `rejection_stage`: 실패한 단계 (Hunter / Gate / Judge)
    *   `rejection_reason`: 필터링된 이유
    *   `trigger_type`: 나중에 되돌아보게 만든 이벤트 (예: PRICE_SURGE)

### C. `MARKET_FLOW_SNAPSHOT` (Priority 2.5)
*   **목적**: 일일 시장 조류 추적
*   **주요 필드**:
    *   `foreign_net_buy`: 외국인 순매수
    *   `institution_net_buy`: 기관 순매수
    *   `program_net_buy`: 프로그램 매매 순매수
    *   `data_type`: DAILY

### D. `STOCK_MINUTE_PRICE` (Priority 3)
*   **목적**: 상세한 진입/이탈 및 패턴 분석을 위한 고해상도 데이터
*   **주요 필드**:
    *   `price_time`: 분봉의 타임스탬프
    *   `open`, `high`, `low`, `close`, `volume`

---

## 2. 공유 유틸리티 (`shared/archivist.py`)

### Archivist
모든 별개의 로깅 작업을 안전하게 처리하기 위해 중앙 집중형 클래스 `Archivist`를 생성했습니다.
*   **패턴**: `session_factory`를 사용하여 자체 데이터베이스 세션을 관리하며, 필요한 경우 메인 트랜잭션과 독립적으로 로그가 커밋되도록 보장합니다 (현재는 긴밀하게 통합됨).
*   **탄력성**: 데이터베이스 작업을 try/except 블록으로 감싸서 로깅 실패가 메인 트레이딩 또는 분석 파이프라인을 크래시시키지 않도록 합니다.

---

## 3. Scout 통합

`Archivist`가 `Scout` 서비스의 메인 실행 루프에 주입되었습니다.
*   **Judge 로그**: 구체적으로, `process_phase23_judge_v5_task`가 이제 archivist를 받고 debate/judge 단계 완료 시 전체 결정 컨텍스트를 `LLM_DECISION_LEDGER`에 자동으로 기록합니다.

---

## 4. 데이터 수집 스크립트 (`scripts/`)

주기적 데이터 수집을 위해 두 개의 새로운 독립 스크립트가 개발되었습니다.

### `scripts/collect_market_flow.py`
*   **스케줄**: 평일 16:00 KST
*   **로직**:
    1.  KIS API 인증
    2.  **활성 Watchlist**를 순회
    3.  `inquire-investor` 및 `inquire-program-trade` 엔드포인트 호출
    4.  Archivist를 통해 `MARKET_FLOW_SNAPSHOT`에 스냅샷 기록

### `scripts/collect_intraday_data.py`
*   **스케줄**: 평일 16:05 KST
*   **로직**:
    1.  KIS API 인증
    2.  **활성 Watchlist**를 순회
    3.  당일 1분봉 OHLCV 데이터 조회
    4.  잠재적 중복/재실행을 처리하기 위해 `session.merge`를 사용하여 `STOCK_MINUTE_PRICE`에 레코드 upsert

---

## 5. 자동화 (Cron)

WSL2 환경에서 시스템 레벨 cron job이 구성되었습니다:

```bash
# [CSC v1.0] 데이터 축적
# 수급 스냅샷 (평일 16:00 KST)
0 16 * * 1-5 ... python3 scripts/collect_market_flow.py ...

# 타겟팅된 장중 데이터 (평일 16:05 KST)
5 16 * * 1-5 ... python3 scripts/collect_intraday_data.py ...
```

로그는 모니터링 및 디버깅을 위해 `logs/cron/`에 보존됩니다.
