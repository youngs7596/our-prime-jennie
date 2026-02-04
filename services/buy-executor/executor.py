# services/buy-executor/executor.py
# Version: v1.0
# Buy Executor - 매수 결재 및 주문 실행 로직

import logging
from datetime import datetime, timezone, timedelta

# shared 패키지 임포트
# sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import shared.database as database
from shared.db.connection import session_scope
from shared.db import repository as repo
from shared.db.models import StockMinutePrice
import shared.auth as auth
from shared import redis_cache
from shared.position_sizing import PositionSizer
from shared.portfolio_diversification import DiversificationChecker
from shared.sector_classifier import SectorClassifier
from shared.market_regime import MarketRegimeDetector
from shared.strategy_presets import (
    apply_preset_to_config,
    resolve_preset_for_regime,
)
from shared.correlation import check_portfolio_correlation, get_correlation_risk_adjustment

logger = logging.getLogger(__name__)


class BuyExecutor:
    """매수 결재 및 주문 실행 클래스"""

    def __init__(self, kis, config, telegram_bot=None):
        """
        Args:
            kis: KIS API 클라이언트
            config: ConfigManager 인스턴스
            telegram_bot: TelegramBot 인스턴스 (optional)
        """
        self.kis = kis
        self.config = config
        self.telegram_bot = telegram_bot
        
        self.position_sizer = PositionSizer(config)
        self.sector_classifier = SectorClassifier(kis, db_pool_initialized=True)
        self.diversification_checker = DiversificationChecker(config, self.sector_classifier)
        self.market_regime_detector = MarketRegimeDetector()

    def process_buy_signal(self, scan_result: dict, dry_run: bool = True) -> dict:
        """
        매수 신호 처리
        
        Cloud Run은 Stateless이므로 매 요청마다 DB 연결을 직접 생성/종료합니다.
        
        Args:
            scan_result: Buy Scanner로부터 받은 데이터
            dry_run: True면 로그만 기록, False면 실제 주문
        
        Returns:
            {
                "status": "success" | "skipped" | "error",
                "stock_code": "005930",
                "stock_name": "삼성전자",
                "order_no": "12345",
                "quantity": 10,
                "price": 72000,
                "reason": "..."
            }
        """
        logger.info("=== 매수 신호 처리 시작 ===")
        
        # [Emergency Stop Check]
        # Redis에서 실시간으로 플래그 확인 (ConfigManager 캐시 우회)
        if redis_cache.is_trading_stopped():
             logger.warning("⛔ [Emergency Stop] 긴급 중지 상태입니다. 매수 신호를 무시합니다.")
             return {"status": "skipped", "reason": "Emergency Stop Active"}
             
        if redis_cache.is_trading_paused():
             # 수동 매수인 경우는 허용해야 할 수도 있으나, 현재 구조상 RabbitMQ로 들어오는 건 다 자동 매수로 간주될 수 있음.
             # 단, Telegram Manual Buy는 source='telegram-manual'로 옴.
             source = scan_result.get('source', '')
             if source != 'telegram-manual':
                 logger.warning("⏸️ [Paused] 매수 일시 중지 상태입니다.")
                 return {"status": "skipped", "reason": "Trading Paused"}
        
        with session_scope() as session:
            # 1. 후보 확인
            candidates = scan_result.get('candidates', [])
            if not candidates:
                logger.info("매수 후보가 없습니다.")
                return {"status": "skipped", "reason": "No candidates"}
            
            market_regime = scan_result.get('market_regime', 'UNKNOWN')
            shared_regime_cache = None
            if (market_regime in (None, 'UNKNOWN') or
                    not scan_result.get('strategy_preset') or
                    not scan_result.get('risk_setting')): # database -> repo
                shared_regime_cache = database.get_market_regime_cache()
                if shared_regime_cache:
                    market_regime = shared_regime_cache.get('regime', market_regime)

            logger.info(f"시장 상황: {market_regime}, 후보 수: {len(candidates)}개")
            
            preset_info = scan_result.get('strategy_preset', {}) or {}
            preset_name = preset_info.get('name')
            preset_params = preset_info.get('params', {})
            if not preset_params and shared_regime_cache:
                preset_info = shared_regime_cache.get('strategy_preset', {}) or {}
                preset_name = preset_info.get('name')
                preset_params = preset_info.get('params', {})

            if not preset_params:
                preset_name, preset_params = resolve_preset_for_regime(market_regime)
            apply_preset_to_config(self.config, preset_params)
            self.position_sizer.refresh_from_config()
            logger.info("전략 프리셋 적용: %s", preset_name)
            
            # 2. 안전장치 체크
            safety_check = self._check_safety_constraints(session)
            if not safety_check['allowed']:
                logger.warning(f"⚠️ 안전장치 발동: {safety_check['reason']}")
                return {"status": "skipped", "reason": safety_check['reason']}
            
            # 2.5 중복 주문 및 보유 여부 체크 (Idempotency)
            # 이미 보유 중인지 확인
            current_portfolio = repo.get_active_portfolio(session)
            holding_codes = [p['code'] for p in current_portfolio]
            
            # LLM 랭킹 전, 후보 중 이미 보유한 종목 제외
            # 키 호환성 처리 (code 또는 stock_code)
            candidates = [c for c in candidates if c.get('stock_code', c.get('code')) not in holding_codes]
            if not candidates:
                logger.info("모든 후보 종목을 이미 보유 중입니다.")
                return {"status": "skipped", "reason": "All candidates already held"}
                
            # 최근 매수 주문 확인 (중복 실행 방지)
            # 후보 중 하나라도 최근에 매수 시도했으면 건너뛰기 (보수적 접근)
            for candidate in candidates:
                c_code = candidate.get('stock_code', candidate.get('code'))
                c_name = candidate.get('stock_name', candidate.get('name'))
                if repo.was_traded_recently(session, c_code, hours=0.17, trade_type='BUY'): # 최근 10분 내 매수 이력 확인
                    logger.warning(f"⚠️ 최근 매수 주문 이력 존재: {c_name}({c_code}) - 중복 실행 방지")
                    return {"status": "skipped", "reason": f"Duplicate order detected for {c_code}"}
                
                # [New Rule] 최근 1시간(60분) 내 매도 이력 있는 종목 재진입 금지 (세탁/설거지 방지)
                if repo.was_traded_recently(session, c_code, hours=24.0, trade_type='SELL'):
                    logger.warning(f"⏳ 쿨타임(24h): {c_name}({c_code})은 최근 24시간 내 매도 이력이 있어 매수 보류")
                    return {"status": "skipped", "reason": f"Cooldown active (Sold within 24h): {c_code}"}
            
            # [NEW] 2.6 Micro-Timing Check (5분봉 패턴 분석)
            # Shooting Star, Bearish Engulfing 등 단기 고점 패턴 감지 시 매수 지연
            if self.config.get_bool('ENABLE_MICRO_TIMING', default=True):
                timing_result = self._validate_entry_timing(session, candidates)
                if not timing_result['allowed']:
                    logger.warning(f"⏳ [Micro-Timing] 매수 지연: {timing_result['reason']}")
                    return {"status": "skipped", "reason": f"Micro-Timing: {timing_result['reason']}"}
            
            # 3. [Fast Hands] LLM 점수 기반 즉시 선정 (동기 호출 제거)
            # candidates는 이미 buy-scanner에서 필터링되어 넘어옴 (is_tradable=True인 경우만)
            # 하지만 안전을 위해 점수 역순 정렬 후 최고점자 선정
            candidates.sort(key=lambda x: x.get('llm_score', 0), reverse=True)
            selected_candidate = candidates[0]
            
            current_score = selected_candidate.get('llm_score', 0)
            is_tradable = selected_candidate.get('is_tradable', False)
            trade_tier = selected_candidate.get('trade_tier') or ("TIER1" if is_tradable else "TIER2")
            
            # [Phase 3] Realtime Source 빠른 경로 (OpportunityWatcher에서 온 신호)
            signal_source = scan_result.get('source', 'buy-scanner')
            if signal_source == 'opportunity_watcher':
                # Hot Watchlist는 이미 LLM Score 필터 통과 → 중복 점수 체크 스킵
                logger.info(f"⚡ [Realtime] OpportunityWatcher 신호 → LLM 점수 체크 스킵 (score={current_score})")
                # 하지만 llm_scored_at stale 체크는 수행
                
            # [Phase 3] llm_scored_at stale 체크 (준호 제안: 1영업일 이상 지난 점수는 보수적 처리)
            stock_info_data = selected_candidate.get('stock_info') or {}
            llm_scored_at = stock_info_data.get('llm_scored_at') or selected_candidate.get('llm_scored_at')
            if llm_scored_at:
                try:
                    scored_dt = datetime.fromisoformat(llm_scored_at.replace('Z', '+00:00'))
                    now_utc = datetime.now(timezone.utc)
                    age_hours = (now_utc - scored_dt).total_seconds() / 3600
                    
                    # [개선] 영업일 기준 계산 (주말 제외)
                    business_days = 0
                    current_date = scored_dt.date()
                    while current_date < now_utc.date():
                        if current_date.weekday() < 5:  # 월(0)~금(4)
                            business_days += 1
                        current_date += timedelta(days=1)
                    
                    if business_days >= 1:
                        # 영업일 기준: 1일 경과 시 -5점, 2일 이상 시 -10점
                        penalty = 5 if business_days == 1 else 10
                        current_score = max(0, current_score - penalty)
                        logger.warning(f"⚠️ [Stale Score] {business_days}영업일 경과 ({age_hours:.1f}시간) → {penalty}점 감점 (현재: {current_score}점)")
                except Exception as e:
                    logger.debug(f"llm_scored_at 파싱 실패: {e}")
            
            # 점수 확인 (환경변수로 설정 가능, 기본값 70점 - B등급 이상만 매수)
            # Tier2(Scout Judge 미통과) 경로는 별도 최소 점수 적용 (품질 상향)
            base_min_llm_score = self.config.get_int('MIN_LLM_SCORE', default=60)
            tier2_min_llm_score = self.config.get_int('MIN_LLM_SCORE_TIER2', default=65)
            
            # [Dynamic RECON Score] 시장 국면별 RECON 기준 점수 적용
            recon_score_by_regime = {
                MarketRegimeDetector.REGIME_STRONG_BULL: 58,
                MarketRegimeDetector.REGIME_BULL: 62,
                MarketRegimeDetector.REGIME_SIDEWAYS: 65,
                MarketRegimeDetector.REGIME_BEAR: 70,
            }
            # 시장 국면에 따른 동적 점수 사용 (DB 오버라이드 없음)
            recon_min_llm_score = recon_score_by_regime.get(market_regime, tier2_min_llm_score)
            logger.info(f"📊 [Dynamic RECON] 시장 국면({market_regime}) → RECON 기준: {recon_min_llm_score}점")

            if trade_tier == "TIER1":
                min_llm_score = base_min_llm_score
            elif trade_tier == "RECON":
                min_llm_score = recon_min_llm_score
            else:
                # TIER2: 비주력 종목도 강세장(STRONG_BULL)에서는 적극 매수 (RECON 기준 적용)
                # 그 외에는 기본 TIER2 점수(65)와 비교하여 더 유연한 쪽 적용 가능하나, 여기서는 단순화
                if market_regime == MarketRegimeDetector.REGIME_STRONG_BULL:
                     # 강세장 버프: Tier 2 기준을 58점까지 획기적으로 완화 (물 들어올 때 노 젓기)
                     min_llm_score = 58 
                elif market_regime == MarketRegimeDetector.REGIME_BULL:
                     # 상승장 버프: 62점까지 완화
                     min_llm_score = 62
                else:
                     min_llm_score = tier2_min_llm_score

            if current_score < min_llm_score: 
                # [Strategy Refinement] Hunter Score 90+ (Super Prime) Check
                # 스캐너에서 Hunter Score가 높아 추천된 경우, Executor의 최소 점수 기준을 우회
                stock_info_data = selected_candidate.get('stock_info') or {}
                metadata = stock_info_data.get('llm_metadata') or {}
                hunter_score = metadata.get('hunter_score')
                
                # Fallback: 키 위치가 다를 경우 대비
                if hunter_score is None:
                    hunter_score = selected_candidate.get('llm_metadata', {}).get('hunter_score')
                
                try:
                    hunter_score_val = float(hunter_score)
                except (ValueError, TypeError):
                    hunter_score_val = 0.0
                
                is_super_prime = hunter_score_val >= 90.0

                if is_super_prime:
                     logger.info(f"🔓 [Super Prime] Hunter Score({hunter_score_val}) 우수로 점수 미달({current_score} < {min_llm_score}) 예외 통과")
                else:
                    c_name = selected_candidate.get('stock_name', selected_candidate.get('name'))
                    tier_label = trade_tier
                    logger.warning(f"⚠️ 최고점 후보({c_name}) {tier_label} 점수({current_score})가 기준({min_llm_score}점) 미달입니다. 매수 건너뜀.")
                    return {"status": "skipped", "reason": f"Low LLM Score: {current_score} < {min_llm_score}"}

            stock_code = selected_candidate.get('stock_code', selected_candidate.get('code'))
            stock_name = selected_candidate.get('stock_name', selected_candidate.get('name'))
            logger.info(f"✅ [Fast Hands] 최고점 후보 선정: {stock_name}({stock_code}) - {current_score}점 (tier={trade_tier})")
            logger.info(f"   이유: {selected_candidate.get('llm_reason', '')[:100]}...")
            
            # 3.5 분산 락(Distributed Lock)으로 중복 체결 방지 (동시 처리/재전송 대응)
            lock_key = f"lock:buy:{stock_code}"
            r = redis_cache.get_redis_connection()
            if r:
                try:
                    # 180초 내 동일 종목 재매수 시도 차단 (주문/기록의 레이스 방지)
                    acquired = r.set(lock_key, "1", nx=True, ex=180)
                    if not acquired:
                        logger.warning(f"⚠️ 분산 락 획득 실패(중복 실행 방지): {stock_name}({stock_code})")
                        return {"status": "skipped", "reason": f"Duplicate lock active: {stock_code}"}
                except Exception as e:
                    logger.warning(f"⚠️ Redis 락 실패(보수적으로 중단): {e}")
                    return {"status": "skipped", "reason": "Redis lock failure"}
            
            # 4. 계좌 잔고 조회 (순서 변경: 분산 검증에 필요)
            # KIS Gateway의 get_cash_balance 사용
            available_cash = self.kis.get_cash_balance()
            logger.info(f"가용 현금: {available_cash:,}원")

            # 리스크 설정 기본값
            risk_setting = (
                selected_candidate.get('risk_setting')
                or scan_result.get('risk_setting')
                or {}
            )
            if (not risk_setting) and shared_regime_cache:
                risk_setting = shared_regime_cache.get('risk_setting') or {}
            
            # 5. 동적 포지션 사이징 (먼저 수행해야 수량 기반 분산 체크 가능)
            current_price = selected_candidate.get('current_price', 0)
            if not current_price:
                # 실시간 가격 조회
                snapshot = self.kis.get_stock_snapshot(stock_code)
                if not snapshot:
                    logger.error("실시간 가격 조회 실패")
                    return {"status": "error", "reason": "Failed to get current price"}
                current_price = float(snapshot['price'])
            
            # [수정] PositionSizer.calculate_quantity 메서드 사용
            # 기존: calculate_position_size (존재하지 않는 메서드)
            # 변경: calculate_quantity (ATR 등 추가 인자 필요)
            
            # ATR(14) 실계산 (Intraday Priority -> Daily Fallback)
            atr = None
            use_intraday = self.config.get_bool("USE_INTRADAY_ATR", default=True)
            
            if use_intraday and self.config.get_bool('ENABLE_INTRADAY_LOGIC', default=True):
                # [NEW] Intraday ATR
                atr = self.position_sizer.calculate_intraday_atr(session, stock_code)
                if atr:
                    logger.info(f"📐 Intraday ATR 적용: {atr:,.0f}원 (최근 100분 변동성)")
            
            if atr is None:
                # [Fallback] Daily ATR
                try:
                    import shared.strategy as strategy
                    atr_period = self.config.get_int("ATR_PERIOD", default=14)
                    lookback = max(60, atr_period * 3)
                    daily_df = database.get_daily_prices(session, stock_code, limit=lookback, table_name="STOCK_DAILY_PRICES_3Y")
                    if daily_df is not None and not daily_df.empty:
                        atr = strategy.calculate_atr(daily_df, period=atr_period)
                        if atr:
                             logger.info(f"📐 Daily ATR 적용: {atr:,.0f}원 (일간 변동성)")
                except Exception as e:
                    logger.warning(f"⚠️ ATR 실계산 실패(기본값으로 폴백): {e}")
                    atr = None
            
            if atr is None or atr <= 0:
                atr = current_price * 0.02  # 폴백
            
            # ATR 비율 캡: 1% ~ 5%
            atr_pct = atr / current_price if current_price > 0 else 0.02
            atr_pct = max(0.01, min(0.05, atr_pct))
            atr = current_price * atr_pct
            logger.info(f"📐 ATR 적용: {atr:,.0f}원 ({atr_pct*100:.2f}%)")
            
            # 현재 포트폴리오 가치 계산
            portfolio_value = sum([p.get('quantity', 0) * p.get('current_price', p.get('avg_price', 0)) for p in current_portfolio])
            total_assets = available_cash + portfolio_value
            
            # =====================================================================
            # 5.5 상관관계 체크 (포트폴리오 분산 효과 검증)
            # =====================================================================
            correlation_enabled = self.config.get_bool('CORRELATION_CHECK_ENABLED', default=True)
            correlation_adjustment = 1.0  # 기본값: 조정 없음
            
            if correlation_enabled and current_portfolio:
                try:
                    # 매수 예정 종목 가격 조회
                    new_stock_prices_df = database.get_daily_prices(
                        session, stock_code, limit=60, table_name="STOCK_DAILY_PRICES_3Y"
                    )
                    if new_stock_prices_df is not None and not new_stock_prices_df.empty:
                        new_stock_prices = new_stock_prices_df['CLOSE_PRICE'].tolist()
                        
                        # 가격 조회 함수 정의
                        def price_lookup(code):
                            df = database.get_daily_prices(
                                session, code, limit=60, table_name="STOCK_DAILY_PRICES_3Y"
                            )
                            if df is not None and not df.empty:
                                return df['CLOSE_PRICE'].tolist()
                            return None
                        
                        corr_threshold = self.config.get_float('CORRELATION_THRESHOLD', default=0.7)
                        corr_block = self.config.get_float('CORRELATION_BLOCK_THRESHOLD', default=0.85)
                        
                        passed, warning, max_corr = check_portfolio_correlation(
                            stock_code, new_stock_prices, current_portfolio,
                            price_lookup, threshold=corr_threshold, min_periods=30
                        )
                        
                        if max_corr >= corr_block:
                            # 매우 높은 상관관계: 매수 거부
                            logger.warning(f"🚫 상관관계 초과로 매수 거부: {stock_name} (상관관계: {max_corr:.2f} ≥ {corr_block})")
                            return {"status": "skipped", "reason": f"High correlation ({max_corr:.2f}) with existing portfolio"}
                        
                        if warning:
                            logger.warning(warning)
                        
                        # 상관관계에 따른 포지션 조정
                        if self.config.get_bool('CORRELATION_ADJUST_POSITION', default=True):
                            correlation_adjustment = get_correlation_risk_adjustment(max_corr, 1.0)
                            if correlation_adjustment < 1.0:
                                logger.info(f"📊 상관관계 조정: {max_corr:.2f} → 비중 {correlation_adjustment*100:.0f}%")
                except Exception as e:
                    logger.warning(f"⚠️ 상관관계 체크 실패(계속 진행): {e}")
            
            manual_qty = scan_result.get('manual_quantity') or selected_candidate.get('manual_quantity')
            
            if manual_qty:
                position_size = int(manual_qty)
                if position_size <= 0:
                    return {"status": "skipped", "reason": "Invalid manual quantity"}
                if not dry_run:
                    needed = position_size * current_price
                    if needed > available_cash:
                        return {"status": "error", "reason": "Insufficient cash for manual order"}
                logger.info(f"📏 수동 수량 사용: {position_size}주 (사용자 지정)")
            else:
                sizing_result = self.position_sizer.calculate_quantity(
                    stock_code=stock_code,
                    stock_price=current_price,
                    atr=atr,
                    account_balance=available_cash,
                    portfolio_value=portfolio_value
                )
                
                base_quantity = sizing_result.get('quantity', 0)
                
                # 동적 리스크 설정 적용 (비중 조절)
                position_size_ratio = risk_setting.get('position_size_ratio', 1.0)

                # [TIER 비중 차등화] TIER1(1.0) > TIER2(0.5) > RECON(0.3)
                if trade_tier == "TIER2":
                    tier2_mult = self.config.get_float("TIER2_POSITION_MULT", default=0.5)
                    position_size_ratio *= tier2_mult
                    logger.info(f"📏 TIER2 비율 적용: {tier2_mult}")
                
                # [Project Recon] 정찰병(소액) 비중 적용 + 타이트 손절 설정(메타 기록용)
                if trade_tier == "RECON":
                    recon_mult = self.config.get_float("RECON_POSITION_MULT", default=0.3)
                    position_size_ratio *= recon_mult
                    # downstream(사후 분석/리포트/추후 sell-engine 확장)용으로 risk_setting에 남김
                    recon_sl = self.config.get_float("RECON_STOP_LOSS_PCT", default=-0.025)
                    risk_setting = {**(risk_setting or {}), "stop_loss_pct": recon_sl, "recon_mode": True}
                
                # 상관관계 조정 적용
                position_size_ratio *= correlation_adjustment
                
                position_size = int(base_quantity * position_size_ratio)
                
                if position_size < 1 and base_quantity >= 1:
                     logger.warning(f"⚠️ 리스크 비율({position_size_ratio}) 적용 후 수량이 0이 되어 최소 1주로 보정")
                     position_size = 1
                
                logger.info(f"📏 포지션 사이징: 기본 {base_quantity}주 x 비율 {position_size_ratio} = 최종 {position_size}주")
                
                if position_size <= 0:
                    logger.warning(f"포지션 사이즈 계산 결과 0 이하: {position_size} (이유: {sizing_result.get('reason', 'Unknown')})")
                    return {"status": "skipped", "reason": "Position size too small"}

            logger.info(f"포지션 사이즈: {position_size}주, 예상 금액: {position_size * current_price:,}원")

            # 6. 분산 검증 (위에서 구한 수량 사용)
            # Dynamic Limits 적용
            max_sector_pct = self.config.get_float('MAX_SECTOR_PCT', 30.0)
            max_stock_pct = self.config.get_float('MAX_POSITION_VALUE_PCT', 10.0)
            
            if market_regime == MarketRegimeDetector.REGIME_STRONG_BULL:
                max_sector_pct = 50.0
                max_stock_pct = 20.0
                logger.info(f"🚀 [Dynamic Limits] Strong Bull Market: Sector Limit -> 50%, Stock Limit -> 20%")

            is_approved, div_result = self._check_diversification(session,
                selected_candidate, current_portfolio, available_cash, position_size, current_price,
                override_max_sector_pct=max_sector_pct, override_max_stock_pct=max_stock_pct
            )
            
            original_qty = position_size

            if not is_approved:
                # [Optimization] Smart Skip & Dynamic Resizing
                # 섹터 비중 초과로 인한 거절인 경우, 남은 룸만큼만 매수 시도
                if "섹터" in div_result.get('reason', '') and "비중 초과" in div_result.get('reason', ''):
                    current_sector_exposure = div_result.get('current_sector_exposure', 0.0)
                    remaining_room_pct = max_sector_pct - current_sector_exposure
                    
                    # 최소한의 룸(예: 0.5%)은 있어야 매수 진행
                    if remaining_room_pct > 0.5:
                        # [개선] 안전 마진 0.1% 적용 (부동소수점 오차 방지)
                        safe_room_pct = max(0, remaining_room_pct - 0.1)
                        max_allowed_amount = total_assets * (safe_room_pct / 100.0)
                        new_qty = int(max_allowed_amount / current_price)
                        
                        # [Smart Skip] 쪼그라든 수량이 원래 목표의 50% 미만이면 과감히 패스
                        if new_qty > 0:
                            resize_ratio = new_qty / original_qty
                            if resize_ratio < 0.5:
                                logger.info(f"⏭️ Smart Skip: 수량이 너무 적어 패스 ({position_size} -> {new_qty}, {resize_ratio*100:.1f}%)")
                                return {"status": "skipped", "reason": "Smart Skip (Sector Limit)"}
                            
                            logger.info(f"⚠️ 분산 투자 제한으로 수량 조정: {position_size} -> {new_qty} (섹터 여유: {remaining_room_pct:.2f}%, 안전 마진 적용)")
                            position_size = new_qty
                            
                            # 재검증 (혹시 모를 다른 규칙 위반 확인)
                            is_approved_retry, _ = self._check_diversification(session,
                                selected_candidate, current_portfolio, available_cash, position_size, current_price,
                                override_max_sector_pct=max_sector_pct, override_max_stock_pct=max_stock_pct
                            )
                            if not is_approved_retry:
                                return {"status": "skipped", "reason": "Diversification check failed after resize"}
                        else:
                            return {"status": "skipped", "reason": "Resized quantity is 0"}
                    else:
                        logger.warning(f"포트폴리오 분산 기준 위반: {div_result['reason']}")
                        return {"status": "skipped", "reason": "Diversification check failed"}
                
                # 단일 종목 비중 초과로 인한 거절인 경우, 최대 허용 비중만큼만 매수 시도
                elif "단일 종목" in div_result.get('reason', '') and "비중 초과" in div_result.get('reason', ''):
                    # 현재 자산 대비 최대 허용 금액 계산
                    # [개선] 안전 마진 0.1% 적용
                    safe_stock_pct = max(0, max_stock_pct - 0.1)
                    max_allowed_amount = total_assets * (safe_stock_pct / 100.0)
                    new_qty = int(max_allowed_amount / current_price)
                    
                    if new_qty > 0 and new_qty < position_size:
                        # [Smart Skip]
                        resize_ratio = new_qty / original_qty
                        if resize_ratio < 0.5:
                            logger.info(f"⏭️ Smart Skip: 수량이 너무 적어 패스 ({position_size} -> {new_qty}, {resize_ratio*100:.1f}%)")
                            return {"status": "skipped", "reason": "Smart Skip (Stock Limit)"}

                        logger.info(f"⚠️ 단일 종목 제한으로 수량 조정: {position_size} -> {new_qty} (제한: {max_stock_pct}%, 안전 마진 적용)")
                        position_size = new_qty
                        
                        # 재검증
                        is_approved_retry, _ = self._check_diversification(session,
                            selected_candidate, current_portfolio, available_cash, position_size, current_price,
                            override_max_sector_pct=max_sector_pct, override_max_stock_pct=max_stock_pct
                        )
                        if not is_approved_retry:
                            return {"status": "skipped", "reason": "Diversification check failed after resize"}
                    else:
                        return {"status": "skipped", "reason": "Resized quantity is 0 or invalid"}
                else:
                    logger.warning(f"포트폴리오 분산 기준 위반: {div_result['reason']}")
                    return {"status": "skipped", "reason": "Diversification check failed"}
            
            # 7. 매수 주문 실행
            if dry_run:
                logger.info(f"🔧 [DRY_RUN] 매수 주문: {stock_name}({stock_code}) {position_size}주 @ {current_price:,}원")
                order_no = f"DRY_RUN_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            else:
                order_no = self.kis.place_buy_order(
                    stock_code=stock_code,
                    quantity=position_size,
                    price=0  # 시장가
                )
                
                if not order_no:
                    logger.error("매수 주문 실패")
                    return {"status": "error", "reason": "Order failed"}
                
                logger.info(f"✅ 매수 주문 체결: 주문번호 {order_no}")
            
            # 8. DB 기록
            
            # [NEW] Update Risk Setting with Actual ATR Stop Loss
            if atr and current_price > 0:
                atr_mult = self.config.get_float("ATR_MULTIPLIER", 2.0)
                calc_sl_pct = -(atr * atr_mult) / current_price
                # 기존 risk_setting 업데이트 (Stop Loss를 ATR 기반으로 덮어씀)
                if not risk_setting: risk_setting = {}
                risk_setting['stop_loss_pct'] = round(calc_sl_pct, 4)
                risk_setting['atr_used'] = round(atr, 0)
                logger.info(f"🛡️ Dynamic Stop Loss 설정: {calc_sl_pct*100:.2f}% (User Config/LLM 무시, ATR 기반)")

            self._record_trade(
                session=session,
                stock_code=stock_code,
                stock_name=stock_name,
                order_no=order_no,
                quantity=position_size,
                price=current_price,
                buy_signal_type=selected_candidate.get('buy_signal_type', 'UNKNOWN'),
                factor_score=selected_candidate.get('factor_score', 0),
                llm_reason=selected_candidate.get('llm_reason', ''),
                dry_run=dry_run,
                risk_setting=risk_setting,
                is_tradable=selected_candidate.get('is_tradable', False),
                llm_score=selected_candidate.get('llm_score', 0),
                trade_tier=trade_tier,
                tier2_met_count=(selected_candidate.get('key_metrics_dict') or {}).get('tier2_met_count'),
                tier2_conditions_met=(selected_candidate.get('key_metrics_dict') or {}).get('tier2_conditions_met'),
                tier2_conditions_failed=(selected_candidate.get('key_metrics_dict') or {}).get('tier2_conditions_failed'),
            )
            
            # 8.5 [FIX] 새 포지션 시작: 이전 포지션의 Redis 상태 초기화 (오염 데이터 방지)
            # 재매수 시 이전 거래의 high_watermark, scale_out 등이 남아있으면 잘못된 매도 판단 발생
            try:
                redis_cache.reset_trading_state_for_stock(stock_code)
            except Exception as redis_err:
                logger.warning(f"⚠️ Redis 상태 초기화 실패 (매수 계속): {redis_err}")
            
            # 9. 텔레그램 알림 발송
            if self.telegram_bot:
                try:
                    total_amount = position_size * current_price
                    
                    # Mock/Real 모드 및 DRY_RUN 표시
                    trading_mode = self.config.get('TRADING_MODE', default='REAL')
                    mode_indicator = ""
                    if trading_mode == "MOCK":
                        mode_indicator = "🧪 *[MOCK 테스트]*\n"
                    if dry_run:
                        mode_indicator += "⚠️ *[DRY RUN - 실제 주문 없음]*\n"
                    
                    # Judge 통과 여부 확인 (is_tradable: hybrid_score >= 75)
                    is_tradable = selected_candidate.get('is_tradable', False)
                    llm_score = selected_candidate.get('llm_score', 0)
                    
                    # 매수 경로 표시
                    if trade_tier == "TIER1":
                        approval_status = "✅ TIER1 (Judge 통과)"
                    elif trade_tier == "RECON":
                        approval_status = "🕵️ RECON (정찰병: 소액 진입)"
                    else:
                        approval_status = "⚡ TIER2 (Judge 미통과, 기술적 신호로 매수)"
                    
                    # Super Prime Tag
                    tier2_extra = ""
                    if trade_tier != "TIER1":
                        km = selected_candidate.get('key_metrics_dict') or {}
                        conds = km.get('tier2_conditions_met') or []
                        if conds:
                            tier2_extra = f"\n🛡️ *Tier2 조건*: {', '.join(conds[:4])}"
                    
                    header_tag = "💰 *매수 체결*"
                    if selected_candidate.get('is_super_prime') or selected_candidate.get('buy_signal_type') == 'GOLDEN_CROSS_SUPER_PRIME':
                        header_tag = "🚨 *[긴급/강력매수] SUPER PRIME 체결* 🚨"
                    
                    message = f"""{mode_indicator}{header_tag}

📈 *종목*: {stock_name} ({stock_code})
💵 *가격*: {current_price:,}원
📊 *수량*: {position_size}주
💸 *총액*: {total_amount:,}원
📝 *신호*: {selected_candidate.get('buy_signal_type', 'UNKNOWN')}
⭐ *LLM 점수*: {llm_score:.1f}점
🎯 *승인*: {approval_status}{tier2_extra}"""
                    
                    self.telegram_bot.send_message(message)
                    logger.info("✅ 텔레그램 알림 발송 완료")
                except Exception as e:
                    logger.warning(f"⚠️ 텔레그램 알림 발송 실패: {e}")
            
            logger.info("=== 매수 처리 완료 ===")
            return {
                "status": "success",
                "stock_code": stock_code,
                "stock_name": stock_name,
                "order_no": order_no,
                "quantity": position_size,
                "price": current_price,
                "total_amount": position_size * current_price,
                "dry_run": dry_run
            }
            
    def _check_safety_constraints(self, session) -> dict:
        """안전장치 체크"""
        try:
            # 1. 오늘 매수 횟수 확인
            max_buy_count = self.config.get_int('MAX_BUY_COUNT_PER_DAY', default=5)
            today_buy_count = repo.get_today_buy_count(session)
            
            if today_buy_count >= max_buy_count:
                return {
                    "allowed": False,
                    "reason": f"Daily buy limit reached: {today_buy_count}/{max_buy_count}"
                }
            
            # 2. 최대 보유 종목 수 확인
            max_portfolio_size = self.config.get_int('MAX_PORTFOLIO_SIZE', default=10)
            current_portfolio = repo.get_active_portfolio(session)
            
            
            if len(current_portfolio) >= max_portfolio_size:
                return {
                    "allowed": False,
                    "reason": f"Portfolio size limit reached: {len(current_portfolio)}/{max_portfolio_size}"
                }
            
            return {"allowed": True, "reason": "OK"}
            
        except Exception as e:
            logger.error(f"안전장치 체크 오류: {e}", exc_info=True)
            return {"allowed": False, "reason": f"Safety check error: {e}"}
    
    def _check_diversification(self, session, candidate: dict, current_portfolio: list, available_cash: float, position_size: int, current_price: float, override_max_sector_pct: float = None, override_max_stock_pct: float = None) -> tuple:
        """포트폴리오 분산 검증"""
        try:
            # 섹터 정보 조회 (SectorClassifier 사용)
            stock_code = candidate.get('stock_code', candidate.get('code'))
            stock_name = candidate.get('stock_name', candidate.get('name', stock_code))
            sector = self.sector_classifier.get_sector(stock_code, stock_name)
            
            # 포트폴리오 dict 변환 (diversification_checker가 기대하는 형식)
            portfolio_cache = {}
            for item in current_portfolio:
                # 포트폴리오 종목의 섹터 정보도 조회 (없으면 UNKNOWN)
                # DB 스키마에 따라 'code' 또는 'stock_code' 사용
                p_code = item.get('stock_code') or item.get('code')
                if not p_code:
                    continue
                p_name = item.get('stock_name') or item.get('name', p_code)
                item_sector = self.sector_classifier.get_sector(p_code, p_name)
                portfolio_cache[p_code] = {
                    'code': p_code,
                    'name': p_name,
                    'quantity': item.get('quantity', 0),
                    'avg_price': item.get('buy_price', item.get('avg_price')), 
                    'current_price': item.get('current_price', item.get('buy_price', item.get('avg_price'))),
                    'sector': item_sector # 섹터 정보 추가
                }
            
            # 후보 종목 정보 구성
            candidate_stock = {
                'code': stock_code,
                'name': stock_name,
                'price': current_price,
                'quantity': position_size,
                'sector': sector # 섹터 정보 추가
            }
            
            # 분산 체크 호출
            result = self.diversification_checker.check_diversification(
                candidate_stock=candidate_stock,
                portfolio_cache=portfolio_cache,
                account_balance=available_cash,
                override_max_sector_pct=override_max_sector_pct,
                override_max_stock_pct=override_max_stock_pct
            )
            
            if not result['approved']:
                logger.warning(f"분산 기준 위반: {result['reason']}")
                return False, result
            
            return True, result
            
        except Exception as e:
            logger.error(f"분산 검증 오류: {e}", exc_info=True)
            # 에러 시 보수적으로 False 반환
            return False, {'reason': str(e)}

    def _validate_entry_timing(self, session, candidates: list) -> dict:
        """
        [Micro-Timing] 매수 진입 타이밍 검증 (5분봉 패턴 분석)
        대상: 리스트의 첫 번째 후보 (최우선 순위)
        """
        try:
            if not candidates:
                return {"allowed": True, "reason": "No candidates"}
                
            # 최우선 후보만 체크 (어차피 하나만 사니까)
            # 점수순 정렬은 3번 단계에서 하지만, 여기서 미리 살짝 봄
            top_candidate = max(candidates, key=lambda x: x.get('llm_score', 0))
            stock_code = top_candidate.get('stock_code', top_candidate.get('code'))
            stock_name = top_candidate.get('stock_name', top_candidate.get('name'))
            
            from sqlalchemy import select
            
            # 최근 2개 5분봉 조회 (완성봉 기준)
            # 현재 시간 기준 15분 이내 데이터만 유효
             
            # 20분 전 ~ 현재
            check_start_time = datetime.now() - timedelta(minutes=20)
            
            query = select(StockMinutePrice).where(
                StockMinutePrice.stock_code == stock_code,
                StockMinutePrice.price_time >= check_start_time
            ).order_by(StockMinutePrice.price_time.desc()).limit(2)
            
            rows = session.execute(query).scalars().all()
            
            if len(rows) < 2:
                # 데이터 부족 시 Pass (데이터 수집 지연일 수 있으나, 안전하게 Pass or Fail? Plan says 'Pass if stale')
                return {"allowed": True, "reason": "Insufficient minute data (passed safety)"}
            
            # rows[0]: 최신봉 (직전 5분), rows[1]: 이전봉
            curr = rows[0]
            prev = rows[1]
            
            # Data Freshness Check (15분 이상 지연되면 무시하고 진행)
            time_diff = (datetime.now() - curr.price_time).total_seconds()
            if time_diff > 900: # 15분
                return {"allowed": True, "reason": "Data stale (>15m), skipping check"}

            # --- Pattern 1: Shooting Star (유성형) ---
            # 윗꼬리가 몸통의 2배 이상이고, 양봉/음봉 무관하게 고점에서 발생 시 하락 반전 신호
            body = abs(curr.close_price - curr.open_price)
            upper_wick = curr.high_price - max(curr.close_price, curr.open_price)
            
            # 몸통이 너무 작으면(도지) 노이즈일 수 있으므로 최소 가격의 0.1% 이상일 때만 체크? 
            # 아니면 도지형 Shooting Star도 강력하므로 그냥 둠.
            
            if body > 0 and upper_wick > (body * 2.0):
                 # 추가조건: 거래량이 평소보다 좀 터졌는지? (선택)
                 return {"allowed": False, "reason": f"{stock_name}({stock_code}) Shooting Star detected (Wick/Body={upper_wick/body:.1f})"}
            
            # --- Pattern 2: Bearish Engulfing (하락 장악형) ---
            # 1. 이전 봉: 양봉
            # 2. 현재 봉: 음봉
            # 3. 현재 시가 >= 이전 종가 AND 현재 종가 <= 이전 시가 (몸통이 이전 몸통을 감쌈)
            # 4. 거래량: 현재 > 이전 (매도세 압도)
            
            is_prev_bull = prev.close_price > prev.open_price
            is_curr_bear = curr.close_price < curr.open_price
            
            if is_prev_bull and is_curr_bear:
                engulfing = (curr.open_price >= prev.close_price) and (curr.close_price <= prev.open_price)
                vol_confirm = curr.volume > prev.volume
                
                if engulfing and vol_confirm:
                     return {"allowed": False, "reason": f"{stock_name}({stock_code}) Bearish Engulfing detected"}

            return {"allowed": True, "reason": "OK"}
            
        except Exception as e:
            logger.warning(f"Micro-Timing check failed: {e}")
            return {"allowed": True, "reason": "Check Error (Fail-Safe)"}

    def _record_trade(
        self,
        session,
        stock_code: str,
        stock_name: str,
        order_no: str,
        quantity: int,
        price: float,
        buy_signal_type: str,
        factor_score: float,
        llm_reason: str,
        dry_run: bool,
        risk_setting: dict = None,
        is_tradable: bool = False,
        llm_score: float = 0,
        trade_tier: str | None = None,
        tier2_met_count: int | None = None,
        tier2_conditions_met: list | None = None,
        tier2_conditions_failed: list | None = None,
    ):
        """거래 기록"""
        try:
            # 1. PORTFOLIO 테이블에 추가
            # database.add_to_portfolio 함수가 없으므로 직접 SQL 실행 필요하거나 database.py에 해당 함수가 있는지 확인 -> execute_trade_and_log 사용
            # shared/database.py 파일에는 add_to_portfolio 함수가 없고 execute_trade_and_log 함수가 있습니다.
            # 따라서 execute_trade_and_log 함수를 사용해야 합니다.
            
            # execute_trade_and_log 함수 사용
            stock_info = {
                'code': stock_code,
                'name': stock_name
            }
            
            llm_decision = {
                'reason': llm_reason
            }
            
            # Tier/조건 정보를 key_metrics에 포함 (사후 분석/리포트/모니터링용)
            tier = trade_tier or ("TIER1" if is_tradable else "TIER2")
            key_metrics = {
                "factor_score": factor_score,
                "is_dry_run": dry_run,
                "risk_setting": risk_setting or {},
                "tier": tier,
                "llm_score": llm_score,
                "buy_signal_type": buy_signal_type,
            }
            if tier == "TIER2":
                key_metrics["tier2_met_count"] = tier2_met_count
                key_metrics["tier2_conditions_met"] = tier2_conditions_met or []
                key_metrics["tier2_conditions_failed"] = tier2_conditions_failed or []

            # Stop Loss 가격 계산
            # risk_setting의 stop_loss_pct 사용 (기본값 -5.0%)
            stop_loss_pct = (risk_setting or {}).get('stop_loss_pct')
            if stop_loss_pct is None:
                stop_loss_pct = -0.05 # Default 5%
            
            # 절대값이 아닌 음수 비율로 처리
            if stop_loss_pct > 0: stop_loss_pct = -stop_loss_pct
            
            initial_stop_loss_price = price * (1 + stop_loss_pct)

            result = database.execute_trade_and_log(
                connection=session, 
                trade_type='BUY',
                stock_info=stock_info,
                quantity=quantity,
                price=price,
                llm_decision=llm_decision,
                initial_stop_loss_price=initial_stop_loss_price,
                strategy_signal=buy_signal_type,
                key_metrics_dict={
                    **key_metrics
                }
            )

            if not result:
                raise RuntimeError("Failed to execute trade transaction (DB error)")
            
            logger.info("✅ 거래 기록 완료 (Portfolio & TradeLog)")
            
        except Exception as e:
            logger.error(f"거래 기록 오류: {e}", exc_info=True)
            raise
