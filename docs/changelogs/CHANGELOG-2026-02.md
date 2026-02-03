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

- **feat(dashboard)**: Macro Council 전용 페이지 추가
  - 사이드바에 "Macro" 메뉴 추가 (`/macro-council`)
  - Council 분석 결과 상세 표시
  - 글로벌 지표, 투자자 수급, 트레이딩 권고
  - 정치/지정학적 리스크 분석
  - 3현자 Council 리뷰 섹션

- **feat(dashboard)**: Macro Council 페이지 기능 보강
  - Market Regime hint 표시 추가
  - Opportunity Factors (기회 요인) 섹션 추가
  - Sector Signals (섹터별 bullish/bearish 신호) 표시
  - Source Info (출처 채널, 분석가) 표시
  - 날짜 선택 드롭다운 추가 (`/api/macro/dates` 연동)

### Macro Council
- **fix(macro-council)**: 텔레그램 브리핑 없어도 Council 분석 진행
  - 주말/공휴일에도 글로벌 매크로 데이터만으로 분석 가능
  - 브리핑과 글로벌 데이터 모두 없을 때만 실패

### Code Quality
- **incident**: 2026-02-02 세션에서 구현한 `Macro.tsx` 코드 손실 발견
  - 원인: `git add` 명령에 프론트엔드 파일 누락 (백엔드만 커밋됨)
  - 조치: Claude 세션 히스토리에서 원본 코드 발견, 기능 복구
  - 예방: `.githooks/pre-push` 훅 추가, RULES.md에 코드 손실 방지 규칙 추가

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
