# my-prime-jennie - LLM Decision Chain

## Legacy 경로 (Hunter → Debate → Judge)

```mermaid
flowchart LR
  Quant[Quant Score\n팩터/시장] --> Hunter[Hunter\nREASONING Tier]
  NewsCtx[RAG 뉴스 컨텍스트] --> Hunter
  CompBenefit[경쟁사 수혜 점수] --> Hunter
  Hunter --> Debate[Debate\nBull vs Bear]
  Debate --> Judge[Judge\nTHINKING Tier]
  Judge --> Decision[최종 승인/거부 + 수량]
  Decision --> Watchlist[Watchlist 업데이트]
```

## Unified Analyst 경로 (현행, `SCOUT_USE_UNIFIED_ANALYST=true`)

3→1 LLM 호출 통합. Hunter+Debate+Judge를 단일 `run_analyst_scoring()` 호출로 대체.

```mermaid
flowchart LR
  Quant[Quant Score v2\n잠재력 기반] --> RiskTag[classify_risk_tag\n코드 기반]
  Quant --> Analyst[Unified Analyst\nREASONING Tier\ndeepseek_cloud]
  NewsCtx[RAG 뉴스 컨텍스트] --> Analyst
  RiskTag --> Calibrator[LLM Calibrator\n±15pt 가드레일]
  Analyst --> Calibrator
  Calibrator --> SafetyLock[Safety Lock\n비대칭 가중치]
  SafetyLock --> Decision[최종 승인/거부]
  RiskTag -->|DISTRIBUTION_RISK| Veto[Veto Power\nis_tradable=False]
  Decision --> Watchlist[Watchlist 업데이트]
```

- **코드 기반 risk_tag**: LLM의 100% CAUTION 편향을 해소하기 위해 `classify_risk_tag(quant_result)`로 산정
- **±15pt 가드레일**: `llm_score = clamp(raw, quant-15, quant+15)` — LLM 점수가 Quant에서 크게 벗어나지 못함
- **Veto Power**: DISTRIBUTION_RISK 태그 시 `is_tradable=False`, `trade_tier=BLOCKED`
- **Safety Lock 비대칭**: LLM 경고 존중 (40:60), LLM<40 가중 (45:55)

