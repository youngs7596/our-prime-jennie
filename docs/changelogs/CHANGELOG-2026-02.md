# 2026년 2월 변경 이력 (February 2026)

## 2026-02-03

### Dashboard
- **feat(dashboard)**: Overview 페이지에 Macro Insight 카드 추가
  - 글로벌 지표 (VIX, USD/KRW, KOSPI, KOSDAQ)
  - 투자자별 순매수 (외국인/기관/개인)
  - 트레이딩 권고 (포지션 크기, 손절폭 조정)
  - 허용/회피 전략 및 섹터
  - Sentiment Score, Political Risk Level
  - Backend: `/api/macro/insight` 엔드포인트 추가

### Macro Council
- **fix(macro-council)**: 텔레그램 브리핑 없어도 Council 분석 진행
  - 주말/공휴일에도 글로벌 매크로 데이터만으로 분석 가능
  - 브리핑과 글로벌 데이터 모두 없을 때만 실패

## 2026-02-02

### Macro Integration
- **feat(macro)**: 정치/지정학적 뉴스를 Council LLM 분석에 통합
  - PoliticalNewsClient: RSS 피드 모니터링 (Reuters, BBC, NYT, WSJ, 연합뉴스)
  - Council 프롬프트에 political_risk_level/summary 판단 추가
  - DailyMacroInsight, EnhancedTradingContext 확장

- **feat(macro)**: 투자자 수급 데이터를 Council 분석에 추가
  - GlobalMacroSnapshot에 외국인/기관/개인 순매수 필드 추가
  - pykrx 1.2.x API 호환성 수정

### CI/CD
- **fix(tests)**: Jenkins CI 테스트 실패 수정
  - Finnhub 클라이언트 테스트 mock 개선
  - VIX max_age=72h 반영

---
*Last Updated: 2026-02-03*
