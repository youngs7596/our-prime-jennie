# Enhanced Macro → Trading Logic 통합 설계

## 현재 상태

### 데이터 흐름 (분리됨)
```
[글로벌 데이터]                    [텔레그램 브리핑]
     │                                  │
     ▼                                  ▼
EnhancedMacroAggregator          telegram-collector
     │                                  │
     ▼                                  ▼
GlobalMacroSnapshot              raw message
     │                                  │
     └──────────┬───────────────────────┘
                ▼
        3현자 Council 분석
                │
                ▼
        DAILY_MACRO_INSIGHT (DB)
                │
                ▼
        get_today_insight() (Redis)
                │
                ▼
        Trading Services (제한적 사용)
```

### 현재 트레이딩 서비스 사용 현황
| 서비스 | 매크로 활용 | 방식 |
|--------|------------|------|
| scout-job | MarketRegimeDetector | KOSPI 가격 기반 (매크로 미사용) |
| buy-scanner | - | 미사용 |
| price-monitor | - | 미사용 |

---

## 목표 설계

### 통합 데이터 흐름
```
07:00 ┌─────────────────────────────────────────────────┐
      │ enhanced_macro_collection_dag                   │
      │                                                 │
      │ [Finnhub] [FRED] [BOK ECOS] [pykrx] [RSS]       │
      │     │        │       │        │       │        │
      │     └────────┴───────┴────────┴───────┘        │
      │                     │                          │
      │                     ▼                          │
      │         GlobalMacroSnapshot                    │
      │                     │                          │
      │                     ▼                          │
      │         ENHANCED_MACRO_SNAPSHOT (DB)           │
      │         macro:snapshot:today (Redis)           │
      └─────────────────────────────────────────────────┘
                            │
07:30 ┌─────────────────────┼───────────────────────────┐
      │ macro_council_dag   │                           │
      │                     ▼                           │
      │         ┌─────────────────────┐                 │
      │         │ GlobalMacroSnapshot │                 │
      │         │  (from Redis/DB)    │                 │
      │         └─────────┬───────────┘                 │
      │                   │                             │
      │         ┌─────────▼───────────┐                 │
      │         │ Telegram Briefing   │                 │
      │         │  (한지영 브리핑)     │                 │
      │         └─────────┬───────────┘                 │
      │                   │                             │
      │                   ▼                             │
      │         ┌─────────────────────┐                 │
      │         │   3현자 Council     │                 │
      │         │  (통합 분석)        │                 │
      │         └─────────┬───────────┘                 │
      │                   │                             │
      │                   ▼                             │
      │         ┌─────────────────────┐                 │
      │         │ EnhancedMacroInsight│ ← 신규          │
      │         │  - sentiment        │                 │
      │         │  - vix_regime       │                 │
      │         │  - position_advice  │                 │
      │         │  - risk_off_level   │                 │
      │         │  - sector_signals   │                 │
      │         └─────────┬───────────┘                 │
      │                   │                             │
      │                   ▼                             │
      │         DAILY_MACRO_INSIGHT (DB)                │
      │         macro:insight:enhanced:{date} (Redis)   │
      └─────────────────────────────────────────────────┘
                            │
08:30 ┌─────────────────────┼───────────────────────────┐
      │ Trading Services    │                           │
      │                     ▼                           │
      │   get_enhanced_trading_context()                │
      │         │                                       │
      │         ├─► scout-job                           │
      │         │     - regime 보정                     │
      │         │     - sector 가중치                   │
      │         │                                       │
      │         ├─► buy-scanner                         │
      │         │     - position_size 조절              │
      │         │     - risk_off 시 진입 제한           │
      │         │     - vix_regime별 전략 선택          │
      │         │                                       │
      │         └─► price-monitor                       │
      │               - stop_loss 배율 조절             │
      │               - trailing_stop 설정              │
      └─────────────────────────────────────────────────┘
```

---

## 핵심 구현 사항

### 1. EnhancedTradingContext (신규)

```python
@dataclass
class EnhancedTradingContext:
    """트레이딩 서비스용 통합 매크로 컨텍스트"""

    # 기본 정보
    context_date: date
    last_updated: datetime

    # VIX 기반 리스크 레벨
    vix_value: Optional[float]
    vix_regime: str  # low_vol, normal, elevated, crisis

    # 포지션 사이징
    position_multiplier: float  # 0.5 ~ 1.3
    max_position_count: int     # 동시 보유 종목 수 제한

    # Risk-Off 상태
    risk_off_level: int         # 0=정상, 1=주의, 2=경계, 3=위험
    risk_off_reasons: List[str]

    # 섹터 신호
    sector_signals: Dict[str, float]  # 섹터별 -1.0 ~ 1.0
    avoid_sectors: List[str]
    favor_sectors: List[str]

    # 전략 힌트
    strategy_hints: List[str]  # ["momentum_ok", "avoid_breakout", ...]

    # 손절/익절 조정
    stop_loss_multiplier: float   # 1.0 ~ 1.5
    take_profit_multiplier: float # 0.8 ~ 1.2

    # 데이터 품질
    data_completeness: float
    data_sources: List[str]
```

### 2. Risk-Off 판단 로직 (3현자 권고 반영)

```python
def calculate_risk_off_level(
    snapshot: GlobalMacroSnapshot,
    insight: DailyMacroInsight
) -> Tuple[int, List[str]]:
    """
    Risk-Off 레벨 계산.

    3현자 권고: RISK_OFF 단독 발동 금지 (다중 지표 확인 필수)

    Returns:
        (level 0-3, reasons)
    """
    signals = []

    # 1. VIX 기반 (단독으로 RISK_OFF 불가)
    if snapshot.vix and snapshot.vix >= 35:
        signals.append(("vix_crisis", 2))
    elif snapshot.vix and snapshot.vix >= 25:
        signals.append(("vix_elevated", 1))

    # 2. 금리 역전 (경기침체 선행지표)
    if snapshot.treasury_spread and snapshot.treasury_spread < 0:
        signals.append(("yield_curve_inverted", 2))

    # 3. 텔레그램 브리핑 sentiment
    if insight and insight.sentiment_score < 30:
        signals.append(("sentiment_bearish", 1))

    # 4. 뉴스 감성
    if snapshot.korea_news_sentiment and snapshot.korea_news_sentiment < -0.3:
        signals.append(("news_negative", 1))

    # 다중 지표 확인: 2개 이상이어야 RISK_OFF
    total_score = sum(s[1] for s in signals)
    reasons = [s[0] for s in signals]

    if len(signals) >= 2 and total_score >= 3:
        return (2, reasons)  # 경계
    elif len(signals) >= 2 and total_score >= 2:
        return (1, reasons)  # 주의
    elif len(signals) >= 3:
        return (3, reasons)  # 위험 (3개 이상 신호)
    else:
        return (0, reasons)  # 정상
```

### 3. 포지션 사이징 로직

```python
def calculate_position_multiplier(
    vix_regime: str,
    risk_off_level: int,
    sentiment_score: int
) -> float:
    """
    포지션 사이즈 배율 계산.

    3현자 권고: 외부 정보 가중치 ≤10%

    Returns:
        0.5 ~ 1.3 배율
    """
    # 기본값: 1.0
    base = 1.0

    # 1. VIX Regime 조정 (±15%)
    vix_adj = {
        "low_vol": 0.10,    # Risk-On: +10%
        "normal": 0.0,
        "elevated": -0.10,  # 주의: -10%
        "crisis": -0.20,    # 위기: -20%
    }.get(vix_regime, 0.0)

    # 2. Risk-Off 레벨 조정 (±20%)
    risk_adj = {
        0: 0.0,
        1: -0.10,  # 주의: -10%
        2: -0.20,  # 경계: -20%
        3: -0.30,  # 위험: -30%
    }.get(risk_off_level, 0.0)

    # 3. Sentiment 조정 (±10%, 외부 가중치 제한)
    # 3현자 권고: 외부 정보 가중치 ≤10%
    if sentiment_score >= 70:
        sent_adj = 0.10
    elif sentiment_score >= 60:
        sent_adj = 0.05
    elif sentiment_score <= 30:
        sent_adj = -0.10
    elif sentiment_score <= 40:
        sent_adj = -0.05
    else:
        sent_adj = 0.0

    # 최종 배율 (0.5 ~ 1.3 범위 제한)
    multiplier = base + vix_adj + risk_adj + sent_adj
    return max(0.5, min(1.3, multiplier))
```

### 4. 서비스별 활용 방안

#### buy-scanner (기회 감시)
```python
async def _evaluate_opportunity(self, stock_code: str, ...):
    # 매크로 컨텍스트 로드
    ctx = get_enhanced_trading_context()

    # 1. Risk-Off 체크
    if ctx.risk_off_level >= 2:
        logger.info(f"[{stock_code}] Risk-Off 경계: 신규 진입 제한")
        return None

    # 2. VIX Regime별 전략 선택
    if ctx.vix_regime == "crisis":
        # 위기 시: 모멘텀/브레이크아웃 전략 비활성화
        allowed_strategies = ["RSI_REBOUND", "BULL_PULLBACK"]
    elif ctx.vix_regime == "elevated":
        # 변동성 높음: 공격적 전략 자제
        allowed_strategies = self.CONSERVATIVE_STRATEGIES
    else:
        allowed_strategies = self.ALL_STRATEGIES

    # 3. 섹터 필터링
    if sector in ctx.avoid_sectors:
        logger.debug(f"[{stock_code}] 회피 섹터: {sector}")
        return None

    # 4. 포지션 사이즈 조절
    position_size = base_size * ctx.position_multiplier
```

#### scout-job (종목 발굴)
```python
def score_candidate(self, stock, ...):
    ctx = get_enhanced_trading_context()

    # 섹터 가중치 조정
    sector = stock.sector
    sector_adj = ctx.sector_signals.get(sector, 0.0)

    # 기본 점수에 섹터 조정 (최대 ±10%)
    adjusted_score = base_score * (1 + sector_adj * 0.1)

    # 선호 섹터 보너스
    if sector in ctx.favor_sectors:
        adjusted_score *= 1.05
```

#### price-monitor (가격 감시)
```python
def calculate_stop_loss(self, entry_price, ...):
    ctx = get_enhanced_trading_context()

    # VIX 높을 때 손절폭 확대
    base_stop_pct = 0.03  # 3%
    adjusted_stop_pct = base_stop_pct * ctx.stop_loss_multiplier

    return entry_price * (1 - adjusted_stop_pct)
```

---

## 구현 계획

### Phase 1: 데이터 파이프라인 완성
1. `save_snapshot_to_db()` 연결
2. DAG 순서 보장 (collection → council)
3. Redis 캐싱 통합

### Phase 2: EnhancedTradingContext 구현
1. `get_enhanced_trading_context()` 함수
2. Risk-Off 판단 로직
3. 포지션 사이징 로직

### Phase 3: 서비스 통합
1. buy-scanner 통합
2. scout-job 통합
3. price-monitor 통합

### Phase 4: 모니터링
1. 정확도 추적
2. 롤백 메커니즘 검증
3. 대시보드 표시

---

## 예상 효과

| 지표 | 현재 | 목표 |
|------|------|------|
| 시장 국면 감지 | KOSPI 가격만 | 글로벌+텔레그램+가격 통합 |
| 포지션 사이징 | 고정 | VIX/Risk-Off 연동 |
| 섹터 로테이션 | 미적용 | Council 분석 기반 |
| 손절 폭 | 고정 3% | 변동성 연동 2-5% |
| Risk-Off 감지 | 없음 | 다중 지표 기반 |
