# 📅 2026-01 변경 이력

## 2026-01-21
- **Legacy Service Removal**: `news-crawler` 서비스 완전 제거 (news-collector/analyzer/archiver로 대체 완료).
  - 컨테이너, 서비스 디렉토리, 테스트, DAG 삭제
  - docker-compose.yml, env-vars, scheduler-service 설정 정리
- **Dashboard Refactoring (Feature)**: 대시보드 Backend/Frontend 전면 리팩토링 및 Trading 기능 추가.
  - **Backend**: `portfolio.py`, `market.py` 라우터 분리 및 `DailyAssetSnapshot`, `Redis` 기반 실데이터 연동.
  - **Frontend**: Overview 자산 추이 차트, Market Regime 실시간 표시, Manual Trading (`/trading`) 페이지 및 주문 폼 구현.
- **Naver Finance Refactoring**: 뉴스, 시총, 재무제표 크롤링 로직을 `shared/crawlers/naver.py`로 통합하고 레거시 코드 제거 및 Unit Test 추가.
- **Dashboard UI Refinement**: 포트폴리오 차트 확장(10개), 시스템 Status 페이지 정비("Scheduler Jobs" 제거, "Real-time Watcher" Heartbeat 연결) 및 Frontend 안정화.

## 2026-01-20
- **Performance Logic Refinement**: 투자 성과 대시보드의 수익률 및 MDD 계산 로직 개선.
  - MDD 계산 시 초기 자본금(2억)을 반영하여 Equity Curve 기준으로 재계산 (-80% 오류 해결).
  - `performance_calculator.py`에서 실시간 현재가(`fetch_current_prices_from_kis`)를 조회하여 정확한 평가손익 반영 (0원 오류 해결).
- **Performance API Fixes**: `/api/performance` 라우터 Prefix 수정(404 해결) 및 `MarketRegime` 누락에 따른 임시 Stub 처리(500 해결).
- **KIS Gateway Stabilization**: `fetch_cash_balance` 등 API 호출 시 `Connection reset` 방지를 위한 재시도(Retry) 로직 및 `Connection: close` 헤더 추가.
- **Weekly Factor Analysis DAG 복구 (Critical)**: `weekly_factor_analysis_batch.py`에서 `subprocess.run()` 호출 시 `env=os.environ.copy()`를 추가하여 환경변수(`MARIADB_HOST=mariadb` 등)가 자식 프로세스에 전달되지 않던 버그 수정. Docker 컨테이너 내부에서 `127.0.0.1:3306` 대신 `mariadb:3306`으로 정상 연결 확인.
- **투자 성과 대시보드 (Performance Dashboard)**: 가족 법인 자산운용 관점의 투자 성과 분석 기능 신규 구현.
  - `shared/analysis/performance_calculator.py`: FIFO 매칭 기반 실현 손익 계산, 수수료/거래세(0.23%+0.0015%) 차감한 순수익, MDD(최대 낙폭), Profit Factor 지표 계산 로직 구현
  - `services/dashboard/backend/routers/performance.py`: `/api/performance` API 엔드포인트 (기간 프리셋: 오늘/이번주/이번달/올해/전체)
  - `services/dashboard/frontend/src/pages/Performance.tsx`: 핵심 지표 카드(순수익, 승률, Profit Factor, MDD), 누적 수익 그래프(Recharts), 종목별 상세 테이블 UI
  - 사이드바에 '📊 투자 성과' 메뉴 추가

## 2026-01-19
