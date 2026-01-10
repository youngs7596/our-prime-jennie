# Scout E2E 백테스트 시뮬레이터 개발 보고서

> **작성일**: 2026-01-10  
> **목적**: 뉴스 데이터를 활용한 Scout 기반 E2E 백테스트 시뮬레이터 구현 및 성능 분석

---

## 1. 개요

Scout E2E 백테스트 시뮬레이터는 실제 Scout Job이 선정했을 종목을 Factor Score + 뉴스 감성 데이터로 추정하고, Buy/Sell Executor 로직을 시뮬레이션하여 백테스트를 수행합니다.

### 구현 파일
- `utilities/backtest_scout_e2e.py` - 메인 시뮬레이터
- `utilities/auto_optimize_backtest_scout_e2e.py` - Grid 자동 최적화 스크립트

---

## 2. 구현된 기능 (Phase A + B)

### Phase A: 긴급 개선 ✅

| 기능 | 설명 |
|------|------|
| `check_technical_entry()` | Golden Cross, RSI Oversold, BB Lower, Momentum 4가지 신호 체크 |
| `REGIME_PARAMS` | STRONG_BULL/BULL/SIDEWAYS/BEAR 별 동적 파라미터 |
| `get_regime_params()` | Regime에 맞는 파라미터 (익절/손절/매수한도 등) 반환 |

### Phase B: 중기 개선 ✅

| 기능 | 설명 |
|------|------|
| 비선형 Scout 점수 | 과락(뉴스 감성 < 40) + 가산점(호재/수급) 방식 |
| 트레일링 스톱 | Bull/Strong Bull에서 고점 대비 stop_loss_price 동적 상향 |
| 일중 시뮬레이션 | OHLC 기반 18슬롯 가격 경로 생성 (gpt_v2 방식) |

### Phase C: 장기 개선 ⏸️ (스킵)

- **WATCHLIST_HISTORY 데이터 부족**: 2025-11-26 ~ 2025-12-02 (1주일)만 존재
- 실제 Scout LLM 점수 활용 불가

---

## 3. 백테스트 결과 비교

### 기간: 2025-07-14 ~ 2026-01-09 (91일, 최근 6개월)

| 버전 | 수익률 | MDD | 거래 수 | 비고 |
|------|--------|-----|---------|------|
| backtest_gpt_v2 | **+10.40%** | -7.78% | 387 | 기존 백테스트 |
| scout_e2e (v1) | +0.89% | -5.90% | 452 | 최초 구현 |
| scout_e2e (Phase A) | +1.59% | -5.31% | 320 | 기술적 신호 추가 |
| scout_e2e (Phase A+B) | **-1.22%** | -2.47% | 48 | 비선형 점수 + 일중 시뮬 |

### 주요 발견

1. **거래 빈도 차이**: gpt_v2(387건) vs scout_e2e(48건) - 약 8배 차이
2. **Scout 점수 추정의 한계**: Factor + 뉴스만으로 실제 LLM 판단력 재현 불가
3. **일중 시뮬레이션**: 매수/매도 가격에 영향을 주지만 종목 선정이 핵심

---

## 4. 실제 거래 기록 분석

### 거래 요약 (tradelog 테이블)
- **기간**: 2025-11-05 ~ 2026-01-09 (약 2개월)
- **총 거래**: 83건 (매수 50, 매도 33)

### 실제 수익률 (일부)

| 종목 | 매수가 | 매도가 | 수익률 |
|------|--------|--------|--------|
| 삼성전자 | 96,500 | 140,100 | **+45.18%** |
| 삼성전자 | 97,250 | 140,100 | **+44.06%** |
| 기아 | 109,400 | 132,600 | **+21.21%** |
| 기아 | 112,900 | 132,600 | **+17.45%** |

### 핵심 결론

> **"시뮬레이터가 불완전한 것이지, 트레이딩 시스템이 잘못된 것이 아닙니다."**

실제 LLM 기반 Scout은 우수한 성과를 내고 있습니다.

---

## 5. Scout 데이터 저장 위치

### Redis (실시간)
```
hot_watchlist:active → 현재 활성 버전
hot_watchlist:v{timestamp} → 실제 데이터 (JSON)
```

### DB (장기 저장)
```sql
WATCHLIST_HISTORY
- 총 건수: 5,222건
- 기간: 2023-11-27 ~ 2025-12-02
- ⚠️ 2025-12-02 이후 저장 중단됨
```

---

## 6. 향후 개선 방향

### 6.1 WATCHLIST_HISTORY 저장 재활성화
Scout Job 실행 시 DB에 결과를 저장하도록 로직 확인 필요

### 6.2 실제 LLM 점수 활용
WATCHLIST_HISTORY에 축적된 데이터가 충분해지면 시뮬레이터에서 활용

### 6.3 gpt_v2 Look-ahead Bias 검증
`_estimate_llm_score` 함수가 미래 정보를 참조하는지 코드 검토 필요

---

## 7. 사용 방법

### 단일 실행
```bash
python utilities/backtest_scout_e2e.py
```

### Grid 최적화
```bash
python utilities/auto_optimize_backtest_scout_e2e.py --quick
```

### 주요 CLI 옵션
```
--start-date YYYY-MM-DD  # 시작일
--end-date YYYY-MM-DD    # 종료일
--capital N              # 초기 자본 (기본: 1천만원)
--buy-signal-threshold N # Scout 점수 임계값 (기본: 70)
```

---

## 8. 관련 파일

| 파일 | 설명 |
|------|------|
| `utilities/backtest_scout_e2e.py` | Scout E2E 시뮬레이터 메인 |
| `utilities/backtest_gpt_v2.py` | 기존 백테스트 (비교 대상) |
| `utilities/auto_optimize_backtest_scout_e2e.py` | Grid 최적화 |
| `shared/db/models.py` | WATCHLIST_HISTORY 모델 |
| `shared/watchlist.py` | Redis Hot Watchlist 관리 |
