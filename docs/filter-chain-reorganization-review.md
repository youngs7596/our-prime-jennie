# 필터 체인 재배치 (Filter Chain Reorganization) — 3현자 검토 요청서

> **작성일**: 2026-02-08
> **작성 목적**: Scout → Scanner → Executor 3단계 파이프라인의 필터 중복 제거 및 역할 재배치에 대한 전문가 리뷰 요청
> **검토 요청 사항**: 아래 변경의 논리적 타당성, 잠재적 리스크, 개선 제안

---

## 1. 배경 및 문제 인식

### 1.1 시스템 구조

한국 주식시장(KOSPI/KOSDAQ) 자동 매매 시스템으로, 3단계 파이프라인을 거쳐 매수가 실행됩니다:

```
[Scout] 종목 발굴 (1시간 간격, Airflow DAG)
   ↓ Hot Watchlist (Redis)
[Scanner] 실시간 매수 신호 감지 (WebSocket, 1분봉)
   ↓ RabbitMQ (buy-signals)
[Executor] 매수 주문 실행
```

각 단계의 설계 의도:
- **Scout**: "어떤 종목을 볼 것인가" — 200개 유니버스에서 Quant Scoring + LLM 분석으로 종목 선정
- **Scanner**: "언제 살 것인가" — 실시간 가격/거래량 기반 매수 타이밍 포착
- **Executor**: "살 수 있는가, 얼마나 살 것인가" — 포트폴리오 관리, 리스크 제한, 주문 실행

### 1.2 백테스트에서 발견된 문제

2026-02-07 기준, 최근 23일간 345건의 Watchlist 데이터를 분석한 결과:

| 지표 | 값 | 의미 |
|------|-----|------|
| hybrid_score IC (D+5) | **-0.152** | 점수가 높을수록 수익이 **낮음** (역상관) |
| 커트라인(62) 탈락 종목 (50~62점) D+5 | **+7.79%**, Hit 78.8% | 탈락 종목이 통과 종목보다 우수 |
| 커트라인(62) 통과 종목 D+5 | **+3.08%**, Hit 57.0% | 통과 종목 성과가 더 낮음 |

**결론**: 커트라인이 오히려 좋은 종목을 차단하고 있었습니다.

### 1.3 구조적 문제 (변경 전)

#### 문제 1: 동일 필터의 이중 적용
```
Scout: recon_score_by_regime = {STRONG_BULL: 58, BULL: 62, SIDEWAYS: 65, BEAR: 70}
         ↓ (커트라인으로 종목 탈락)
Executor: recon_score_by_regime = {STRONG_BULL: 58, BULL: 62, SIDEWAYS: 65, BEAR: 70}
         ↓ (동일 커트라인으로 다시 검증 → 이미 통과한 종목을 또 걸러냄)
```

Scout에서 이미 커트라인을 적용했는데, Executor에서 **같은 딕셔너리로 같은 검증**을 반복합니다.

#### 문제 2: Executor의 MIN_LLM_SCORE 이중 체크
```
Scout: hybrid_score >= 50 → 승인 → Watchlist 저장
         ↓
Executor: MIN_LLM_SCORE(60) / MIN_LLM_SCORE_TIER2(65) 검증
         → Scout에서 50점으로 승인한 종목을 60/65점 기준으로 다시 차단
```

Scout의 승인 결과를 Executor가 무시하는 구조입니다.

#### 문제 3: Micro-Timing의 잘못된 배치
```
Executor (포트폴리오 관리 단계):
  → _validate_entry_timing() — 5분봉 Shooting Star, Bearish Engulfing 패턴 감지
```

"언제 살 것인가"는 Scanner의 역할인데, 5분봉 타이밍 분석이 Executor에 배치되어 있었습니다.

#### 문제 4: MAX_WATCHLIST_SIZE 하드코딩
```python
MAX_WATCHLIST_SIZE = 15  # 하드코딩, 변경 불가
```

하류에 충분한 필터(Scanner 9개 Risk Gate + Executor 20개 필터)가 있는데, 상류에서 15개로 제한하여 기회를 차단합니다.

---

## 2. 변경 내용 상세

### 2.1 Scout — Hot Watchlist 커트라인 제거

**파일**: `services/scout-job/scout.py`

#### 변경 전 (L1282~L1307)
```python
# 시장 국면별 score_threshold 계산
recon_score_by_regime = {
    "STRONG_BULL": 58, "BULL": 62, "SIDEWAYS": 65, "BEAR": 70,
}
hot_score_threshold = recon_score_by_regime.get(current_regime, 65)

# LLM Score 기준 이상인 종목만 Hot Watchlist로 저장
hot_candidates = [
    s for s in final_approved_list
    if s.get('llm_score', 0) >= hot_score_threshold and s.get('code') != '0001'
]
# LLM Score 내림차순 정렬 + 상위 15개 제한
hot_candidates = sorted(hot_candidates, key=lambda x: x.get('llm_score', 0), reverse=True)[:15]

save_hot_watchlist(
    stocks=hot_candidates,
    market_regime=hot_regime,
    score_threshold=hot_score_threshold
)
```

#### 변경 후
```python
# 커트라인 제거: 승인된 전체 종목을 Hot Watchlist로 저장
# 하류 Scanner(9개 Risk Gate) + Executor(20개 필터)가 충분히 걸러냄
hot_candidates = [s for s in final_approved_list if s.get('code') != '0001']
hot_candidates = sorted(hot_candidates, key=lambda x: x.get('llm_score', 0), reverse=True)

save_hot_watchlist(
    stocks=hot_candidates,
    market_regime=hot_regime,
    score_threshold=0
)
```

#### MAX_WATCHLIST_SIZE 변경 (L1246~L1250)
```python
# 변경 전
MAX_WATCHLIST_SIZE = 15
if trading_context and trading_context.risk_off_level >= 2:
    MAX_WATCHLIST_SIZE = 10

# 변경 후
MAX_WATCHLIST_SIZE = int(os.getenv("MAX_WATCHLIST_SIZE", "25"))
if trading_context and trading_context.risk_off_level >= 2:
    MAX_WATCHLIST_SIZE = max(10, MAX_WATCHLIST_SIZE - 10)
```

### 2.2 Executor — LLM 점수 이중 체크 제거 + Stale Score 변환

**파일**: `services/buy-executor/executor.py`

#### 삭제된 코드 (약 60줄)
- `base_min_llm_score`, `tier2_min_llm_score` 변수
- `recon_score_by_regime` 딕셔너리
- trade_tier별 `min_llm_score` 분기 로직 (TIER1/TIER2/RECON)
- `current_score < min_llm_score` 비교 + Super Prime bypass
- 총 효과: 점수 미달 시 `return {"status": "skipped"}` 하던 로직 전체 제거

#### Stale Score 처리 변환

**변경 전**: 감점 → 점수 미달 시 **매수 차단**
```python
penalty = 5 if business_days == 1 else 10
current_score = max(0, current_score - penalty)
# 이후 current_score < min_llm_score 이면 매수 거부
```

**변경 후**: 포지션 배율 축소 (매수 자체는 허용)
```python
stale_multiplier = 1.0  # 기본값

if business_days >= 2:
    stale_multiplier = 0.3   # 2영업일 이상 → 30% 포지션
elif business_days >= 1:
    stale_multiplier = 0.5   # 1영업일 경과 → 50% 포지션

# 포지션 사이징 단계에서 적용
position_size_ratio *= stale_multiplier
```

### 2.3 Micro-Timing 이동: Executor → Scanner

#### Executor에서 제거
- `_validate_entry_timing()` 메서드 전체 삭제 (약 75줄)
- 호출부 삭제 (L150~L156)
- `from shared.db.models import StockMinutePrice` import 삭제

#### Scanner에 추가

**파일**: `services/buy-scanner/opportunity_watcher.py`

Signal Cooldown 이후, 전략 매칭 직전에 새로운 Risk Gate로 추가:

```python
# Risk Gate: Micro-Timing (Cooldown 이후, 전략 매칭 직전)
if self.config.get_bool('ENABLE_MICRO_TIMING', default=True):
    micro_passed, micro_reason = self._check_micro_timing(recent_bars)
    if not micro_passed:
        return None
```

`_check_micro_timing()` 메서드 (신규):
```python
def _check_micro_timing(self, bars: List[dict]) -> Tuple[bool, str]:
    """
    5분봉 패턴 분석 (Executor에서 이동)
    - Pattern 1: Shooting Star — 윗꼬리 > 몸통 × 2.0
    - Pattern 2: Bearish Engulfing — 이전 양봉을 현재 음봉이 감싸고 거래량 증가
    """
```

**Executor 버전과의 차이**:
- Executor: DB에서 `StockMinutePrice` 직접 쿼리 (추가 I/O)
- Scanner: BarAggregator가 이미 수집한 `recent_bars` 사용 (추가 I/O 없음, 더 효율적)

### 2.4 shared/watchlist.py 단순화

**파일**: `shared/watchlist.py`

`refilter_hot_watchlist_by_regime()` 함수 단순화:

#### 변경 전
```python
recon_score_by_regime = {"STRONG_BULL": 58, "BULL": 62, "SIDEWAYS": 65, "BEAR": 70}
new_threshold = recon_score_by_regime.get(new_regime, 65)
filtered_stocks = [s for s in stocks if s.get('llm_score', 0) >= new_threshold]
```
시장 국면 변경 시 점수 커트라인으로 종목을 탈락시켰습니다.

#### 변경 후
```python
stocks = sorted(stocks, key=lambda x: x.get('llm_score', 0), reverse=True)
save_hot_watchlist(stocks=stocks, market_regime=new_regime, score_threshold=0)
```
커트라인 없이 국면 메타데이터만 갱신합니다.

### 2.5 환경변수 및 설정 레지스트리 정리

**`infrastructure/env-vars-wsl.yaml`**:
```yaml
# 삭제
MIN_LLM_SCORE: "60"
MIN_LLM_SCORE_TIER2: "65"

# 추가
MAX_WATCHLIST_SIZE: "25"
```

**`shared/settings/registry.py`**:
```python
# 삭제 (3개 항목)
"MIN_LLM_SCORE": {"value": 60, "type": "int", ...}
"MIN_LLM_SCORE_TIER2": {"value": 65, "type": "int", ...}
"MIN_LLM_SCORE_RECON": {"value": 65, "type": "int", ...}
```

---

## 3. 변경 전후 필터 배치 비교

### 3.1 변경 전

```
[Scout]
  ... Quant+LLM 분석 → 승인(hybrid>=50) → Watchlist 저장
  → recon_score_by_regime 커트라인(58~70) 적용 ← 여기서 좋은 종목 탈락
  → 상위 15개 제한 (하드코딩) ← 기회 차단
  → Hot Watchlist

[Scanner]
  No-Trade Window → Danger Zone → RSI Guard → Macro Risk
  → Bear Entry Block → Combined Risk → 손절 쿨다운 → 시그널 쿨다운
  → 전략 매칭

[Executor]
  Emergency Stop → 일일 매수 한도 → 최대 보유 종목 수
  → 보유 종목 중복 → 매수/매도 쿨다운
  → Micro-Timing (5분봉 패턴) ← 타이밍 판단이 여기에?
  → MIN_LLM_SCORE 이중 체크 ← Scout와 중복
  → recon_score_by_regime 이중 체크 ← Scout와 동일
  → 분산 락 → 현금 잔고 → 상관관계 → ATR 사이징 → ...
```

### 3.2 변경 후

```
[Scout - 종목 선정]
  ETF/소형주 제거 → Quant Scoring (상위 40%) → Smart Skip
  → Unified Analyst LLM (hybrid_score) → DISTRIBUTION_RISK Veto
  → 승인 (hybrid >= 50) → Watchlist 전체 저장
  → MAX_WATCHLIST_SIZE (25, env var) → Hot Watchlist ← 커트라인 없음

[Scanner - 매수 타이밍]
  No-Trade Window (09:00~09:15) → Danger Zone (14:00~15:00)
  → RSI Guard (≤ 70) → Macro Risk Gate → Bear Entry Block
  → Combined Risk (Volume + VWAP) → 손절 쿨다운 → 시그널 쿨다운
  → Micro-Timing (Shooting Star + Bearish Engulfing) ← Executor에서 이동
  → 전략 매칭 (시장 국면별)

[Executor - 포트폴리오 관리]
  Emergency Stop / Pause → 일일 매수 한도 (6회) → 최대 보유 종목 수 (10)
  → 보유 종목 중복 제거 → 매수/매도 쿨다운
  → Stale Score → 포지션 배율 축소 (0.5/0.3, 차단 아님) ← 변환됨
  → 분산 락 → 현금 잔고 확인 → 상관관계 체크 (0.85 차단, 0.3~0.85 축소)
  → ATR 기반 포지션 사이징 → Trade Tier 배율 (TIER1:1.0, TIER2:0.5, RECON:0.3)
  → 현금 보유 10% 유지 → Portfolio Heat 5% 제한
  → 섹터 집중도 (30%/50%) → 개별 종목 비중 (10%/20%)
```

---

## 4. 기대 효과

### 4.1 정량적 효과 (백테스트 기반 추정)

| 항목 | 변경 전 | 변경 후 예상 | 근거 |
|------|---------|-------------|------|
| Hot Watchlist 평균 종목 수 | ~8개 (커트라인 탈락) | ~15~20개 | 커트라인 제거 |
| 50~62점 종목 매수 기회 | 차단됨 | 매수 가능 | 이 구간 D+5 +7.79%, Hit 78.8% |
| 이중 필터로 인한 False Rejection | 약 30~40% 추정 | 0% | MIN_LLM_SCORE 이중 체크 제거 |
| Micro-Timing 정확도 | DB 쿼리 (지연 가능) | 실시간 바 데이터 | Scanner가 이미 보유한 데이터 활용 |

### 4.2 정성적 효과

1. **역할 명확화**: 각 단계가 자기 역할에만 집중
   - Scout: 종목 선정 → Scanner: 타이밍 → Executor: 포트폴리오 관리

2. **기회 확대**: 커트라인 제거로 50~62점 구간의 우수 종목에 접근 가능

3. **리스크 유지**: 하류 필터(Scanner 10개 Risk Gate + Executor 20개 필터)가 건재하므로, 상류 필터 제거가 리스크 증가로 이어지지 않음

4. **운영 유연성**: `MAX_WATCHLIST_SIZE`가 환경변수로 변경되어 재배포 없이 조절 가능

5. **코드 단순화**: Executor에서 ~135줄 삭제, 중복 딕셔너리(`recon_score_by_regime`) 3곳에서 제거

---

## 5. 잠재적 리스크 및 대응

### 5.1 Scanner 부하 증가

**리스크**: Hot Watchlist 종목 수가 8개 → 20개로 증가하면 WebSocket 구독 및 바 데이터 처리량 증가

**대응**:
- WebSocket은 종목당 구독이므로 25개까지는 문제없음 (Price Monitor 테스트 완료)
- BarAggregator는 인메모리 처리이므로 CPU 부하 미미
- `MAX_WATCHLIST_SIZE` 환경변수로 언제든 축소 가능

### 5.2 저품질 종목 유입

**리스크**: 커트라인 제거로 50점대 종목이 Hot Watchlist에 포함 → 잘못된 매수?

**대응**:
- Scout의 Quant Scoring 상위 40% 필터는 유지됨 (하위 60% 이미 탈락)
- `hybrid_score >= 50` 승인 기준은 유지됨 (50점 미만은 여전히 차단)
- Scanner의 9개 Risk Gate가 실시간으로 필터링
- Executor의 포트폴리오 관리 필터 20개 건재
- Trade Tier에 의한 포지션 차등 (TIER1:100%, TIER2:50%, RECON:30%)

### 5.3 Stale Score 종목의 과도한 매수

**리스크**: 기존에는 오래된 점수 → 차단이었는데, 이제 배율 축소로 변경 → 2일 경과된 종목도 매수 가능

**대응**:
- 2영업일 이상 경과 시 30% 포지션으로 리스크 자체가 매우 작음
- Scout가 1시간 간격으로 실행되므로 정상적 환경에서는 stale 상황 자체가 드묾
- 서비스 장애 등 비정상 상황에서의 안전장치 역할

### 5.4 Micro-Timing 이동 시 누락

**리스크**: Executor에서 DB 쿼리 기반이던 로직을 Scanner의 인메모리 바 데이터로 변경 → 데이터 품질 차이?

**대응**:
- Scanner의 BarAggregator는 실시간 틱을 1분봉으로 집계하므로 **더 최신 데이터**
- Executor에서는 StockMinutePrice 테이블 쿼리 → 수집 지연 가능성 있었음
- 패턴 로직(Shooting Star, Bearish Engulfing) 자체는 동일

---

## 6. 검증 결과

### 6.1 테스트

| 테스트 스위트 | 결과 |
|-------------|------|
| shared + scout-job (1131개) | **전체 통과** |
| buy-executor (20개) | **전체 통과** |
| dashboard configs (10개) | **전체 통과** |
| settings registry (14개) | **전체 통과** |

### 6.2 변경 파일 목록

| 파일 | 변경 유형 | 주요 내용 |
|------|----------|----------|
| `services/scout-job/scout.py` | 수정 | recon_score_by_regime 제거, MAX_WATCHLIST_SIZE env var화 |
| `services/buy-executor/executor.py` | 수정 | MIN_LLM_SCORE 체크 제거, stale→배율 변환, micro-timing 제거 |
| `services/buy-scanner/opportunity_watcher.py` | 수정 | _check_micro_timing() 추가 |
| `shared/watchlist.py` | 수정 | refilter_hot_watchlist_by_regime 단순화 |
| `shared/settings/registry.py` | 수정 | MIN_LLM_SCORE 관련 3개 항목 삭제 |
| `infrastructure/env-vars-wsl.yaml` | 수정 | MIN_LLM_SCORE 삭제, MAX_WATCHLIST_SIZE 추가 |
| 테스트 파일 6개 | 수정 | 삭제된 설정 키 참조 업데이트 |

---

## 7. 검토 요청 사항

3현자에게 아래 관점에서의 검토를 요청합니다:

### 7.1 논리적 타당성
- 커트라인 제거의 근거(IC -0.152, 탈락 종목 우수)가 충분한가?
- Stale Score를 차단→배율 축소로 변환하는 것이 적절한가?
- Micro-Timing을 Executor→Scanner로 이동하는 것이 올바른가?

### 7.2 잠재적 리스크
- 놓친 리스크가 있는가?
- 커트라인 제거로 인한 저품질 종목 유입이 실제로 문제가 될 수 있는가?
- Executor에서 점수 체크를 완전히 제거하는 것이 너무 공격적인가?

### 7.3 개선 제안
- 추가로 제거하거나 이동해야 할 필터가 있는가?
- 새로 추가해야 할 안전장치가 있는가?
- MAX_WATCHLIST_SIZE 기본값 25가 적절한가?

### 7.4 모니터링 계획
- 이 변경의 효과를 측정하기 위해 어떤 지표를 추적해야 하는가?
- A/B 테스트가 필요한가, 아니면 바로 프로덕션 적용해도 되는가?

---

## 부록: 코드 diff 요약

### scout.py — Hot Watchlist 저장 부분
```diff
-            recon_score_by_regime = {
-                "STRONG_BULL": 58, "BULL": 62, "SIDEWAYS": 65, "BEAR": 70,
-            }
-            hot_score_threshold = recon_score_by_regime.get(...)
-            hot_candidates = [s for s in final_approved_list
-                if s.get('llm_score', 0) >= hot_score_threshold and s.get('code') != '0001']
-            hot_candidates = sorted(...)[:15]
-            save_hot_watchlist(stocks=hot_candidates, score_threshold=hot_score_threshold)
+            hot_candidates = [s for s in final_approved_list if s.get('code') != '0001']
+            hot_candidates = sorted(hot_candidates, key=lambda x: x.get('llm_score', 0), reverse=True)
+            save_hot_watchlist(stocks=hot_candidates, score_threshold=0)
```

### executor.py — 점수 체크 → stale 배율
```diff
-            base_min_llm_score = self.config.get_int('MIN_LLM_SCORE', default=60)
-            tier2_min_llm_score = self.config.get_int('MIN_LLM_SCORE_TIER2', default=65)
-            recon_score_by_regime = {STRONG_BULL: 58, BULL: 62, SIDEWAYS: 65, BEAR: 70}
-            ... (trade_tier별 분기, Super Prime bypass 등 ~40줄)
-            if current_score < min_llm_score:
-                return {"status": "skipped", "reason": f"Low LLM Score: ..."}
+            stale_multiplier = 1.0
+            if business_days >= 2:
+                stale_multiplier = 0.3
+            elif business_days >= 1:
+                stale_multiplier = 0.5
+            # 포지션 사이징에서: position_size_ratio *= stale_multiplier
```

### executor.py — micro-timing 제거
```diff
-            if self.config.get_bool('ENABLE_MICRO_TIMING', default=True):
-                timing_result = self._validate_entry_timing(session, candidates)
-                if not timing_result['allowed']:
-                    return {"status": "skipped", ...}
+            # Micro-Timing 체크는 Scanner(opportunity_watcher.py)로 이동됨
```

### opportunity_watcher.py — micro-timing 추가
```diff
+        # [Micro-Timing] 5분봉 패턴 체크 (Executor에서 이동)
+        if self.config.get_bool('ENABLE_MICRO_TIMING', default=True):
+            micro_passed, micro_reason = self._check_micro_timing(recent_bars)
+            if not micro_passed:
+                return None
```
