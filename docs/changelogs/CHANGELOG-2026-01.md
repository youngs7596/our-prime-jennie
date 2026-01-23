# 📅 2026-01 변경 이력

## 2026-01-23
- **Chart Phase Engine (Prime Council)**: Weinstein 4단계 이론 기반 차트 위상 분석 엔진 구현 (`shared/hybrid_scoring/chart_phase.py`). MA(20/60/120) 정배열/역배열 감지, Exhaustion(ADX+RSI+Z-Score) 점수화, Stage 4 매수 차단 및 Stage 2 보너스(1.2x) 적용.
- **QuantScorer 연동**: Stage 4 종목 자동 제외, Exhaustion 시 스코어 x0.7 페널티.
- **PriceMonitor 연동**: Stage 3/Exhaustion 감지 시 ATR Multiplier x0.8, Trailing Stop 조기 활성화(x0.7) 및 Drop 축소(x0.7).
- **Rebalance Workflow**: `/rebalance_to [종목]` 슬래시 커맨드 생성 (손절 후 지정 종목 집중 매수).
- **Sector Momentum Penalty (Prime Council)**: "Falling Knife" 섹터(5일 수익률 < -3% 및 역배열) 식별 시, 해당 섹터의 모든 후보 종목에 **-10점 페널티**를 적용하는 로직 구현 (`Scout` Phase 1.5).
- **Trailing Stop 개선**: 활성화 조건 +5%→+10%, 최소 수익률 가드 +5% 추가, ATR 기반에서 고점 대비 -7% 고정으로 변경
- **Scale-out 전략 최적화 (Prime Council 권고)**:
  - 시장 국면별 동적 레벨: BULL +8/15/25/35%, SIDEWAYS +5/10/15/20%, BEAR +3/7/10/15%
  - 4단계 Scale-out (L1~L4) + 최소 거래금액 가드 50만원/50주
  - L4 도달 시 소량 잔여 강제 청산 로직 추가
- **collect_intraday.py**: Scout과 동일한 KOSPI Top 200 Universe 사용하도록 수정
- **Golden Cross Strategy Optimization (Prime Council)**: Jennie, Minji, Junho 3인 합의에 따른 전략 개선.
  - `services/price-monitor/monitor.py`: Hard Stop 기본값 -5% → **-6%** (준호 권고: 변동성 버퍼 확보)
  - 수급 필터 분석: 하드 게이트 아님 확인 (`_check_legendary_pattern`은 SUPER_PRIME 보너스만)
  - Trailing Stop: 기존 +5% 활성화, 1.5×ATR 로직 유지 (변경 불필요)
  - `scripts/verify_investor_data_integrity.py`, `scripts/collect_investor_trading.py` 개선: 골든크로스 거래 누락 수급 데이터 백필

## 2026-01-22
- **Redis Trading Bug Fix (Critical)**: 재매수(새 포지션) 시 이전 거래의 Redis 캐시(High Watermark 등)가 초기화되지 않아 매도 시점이 왜곡되던 버그 수정.
  - `shared/redis_cache.py`: `update_high_watermark` 자동 리셋 로직 및 `reset_trading_state_for_stock` 추가.
  - `executor.py`: 매수 완료 후 상태 초기화 호출 추가.
  - `tests/shared/test_redis_cache.py` 및 `scripts/verify_redis_fix.py`: 검증 코드 추가.

## 2026-01-21
- **DAG Fix**: `daily_asset_snapshot` DAG Docker 환경 호환성 수정.
  - `daily_asset_snapshot_dag.py`: BashOperator에 COMMON_ENV 환경변수 추가
  - `daily_asset_snapshot.py`: Docker 환경 감지 로직 추가, 함수 내 중복 import 제거, SQLAlchemy ORM merge 방식으로 upsert 변경
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
