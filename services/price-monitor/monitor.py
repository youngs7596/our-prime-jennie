# monitor.py
# Price Monitor - 실시간 가격 감시 및 매도 신호 발행

import time
import logging
import sys
import os
from datetime import datetime
from threading import Event
import pytz

# shared 패키지 임포트
# sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import shared.database as database
import shared.strategy as strategy
import shared.redis_cache as redis_cache
from shared.redis_cache import (
    update_high_watermark, 
    delete_high_watermark,
    get_scale_out_level,
    set_scale_out_level,
    delete_scale_out_level,
    get_rsi_overbought_sold,
    set_rsi_overbought_sold,
    delete_rsi_overbought_sold,
    set_profit_floor,
    get_profit_floor,
)
from shared.db.connection import session_scope
from shared.db import repository as repo
from shared.notification import TelegramBot

# [Prime Council] Chart Phase Analysis for Trend-Aware Risk Management
try:
    from shared.hybrid_scoring.chart_phase import ChartPhaseAnalyzer
    CHART_PHASE_AVAILABLE = True
except ImportError:
    CHART_PHASE_AVAILABLE = False

logger = logging.getLogger(__name__)

# Redis Streams 지원 (WebSocket 공유 아키텍처)
try:
    from shared.kis.stream_consumer import StreamPriceConsumer
    REDIS_STREAMS_AVAILABLE = True
except ImportError:
    REDIS_STREAMS_AVAILABLE = False


class PriceMonitor:
    """실시간 가격 감시 클래스"""
    
    def __init__(self, kis, config, tasks_publisher, telegram_bot: TelegramBot = None):
        """
        Args:
            kis: KIS API 클라이언트
            config: ConfigManager 인스턴스
            tasks_publisher: RabbitMQPublisher 인스턴스
            telegram_bot: 가격 알림 전송용 텔레그램 봇 (옵션)
        """
        self.kis = kis
        self.config = config
        self.tasks_publisher = tasks_publisher
        self.telegram_bot = telegram_bot
        self.stop_event = Event()
        
        trading_mode = os.getenv("TRADING_MODE", "MOCK")
        self.use_redis_streams = os.getenv("USE_REDIS_STREAMS", "false").lower() == "true"
        self.alert_check_interval = int(os.getenv("PRICE_ALERT_CHECK_INTERVAL", "15"))
        
        # Redis Streams 모드용 consumer
        self.stream_consumer = None
        
        logger.info(f"Price Monitor 설정: TRADING_MODE={trading_mode}, USE_REDIS_STREAMS={self.use_redis_streams}")
        
        self.portfolio_cache = {}
        
        # [Phase: WebSocket 역할 분리] OpportunityWatcher는 buy-scanner로 이관됨
        # price-monitor는 매도 신호 감지에만 집중
        
        # Silent Stall 감지용
        self.last_ws_data_time = 0
    
    def start_monitoring(self, dry_run: bool = True):
        logger.info("=== 가격 모니터링 시작 (Redis Streams Only) ===")
        try:
            # 시장 운영 여부 확인 (휴장/주말/장외면 바로 중단)
            disable_market_open_check = self.config.get_bool("DISABLE_MARKET_OPEN_CHECK", default=False)
            
            if not disable_market_open_check and not dry_run:
                try:
                    # Gateway 클라이언트 등 최소한의 주말/시간 필터
                    kst = pytz.timezone("Asia/Seoul")
                    now = datetime.now(kst)
                    if not (0 <= now.weekday() <= 4 and 8 <= now.hour <= 16):
                        logger.warning("💤 시장 미운영 시간(주말/장외)으로 모니터링을 건너뜁니다.")
                        return
                except Exception as e:
                    logger.error(f"시장 운영 여부 확인 실패: {e}", exc_info=True)
                    return

            # Redis Streams 모드 강제
            if REDIS_STREAMS_AVAILABLE:
                self._monitor_with_redis_streams(dry_run)
            else:
                logger.error("❌ Redis Streams 모듈(shared.kis.stream_consumer)이 없습니다. 모니터링 불가.")
                return

        except Exception as e:
            logger.error(f"❌ 모니터링 중 오류: {e}", exc_info=True)
        finally:
            logger.info("=== 가격 모니터링 종료 ===")
    
    def stop_monitoring(self):
        logger.info("모니터링 중단 신호 수신")
        self.stop_event.set()
        if self.stream_consumer:
            self.stream_consumer.stop()
    
    def _monitor_with_redis_streams(self, dry_run: bool):
        """Redis Streams 모드로 실시간 모니터링 (kis-gateway 공유 WebSocket)"""
        logger.info("=== Redis Streams 모드로 실시간 모니터링 시작 ===")
        
        # 쓰레드에서 호출되므로 DB 초기화 보장
        from shared.db.connection import ensure_engine_initialized
        ensure_engine_initialized()
        
        redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        gateway_url = os.getenv("KIS_GATEWAY_URL", "http://127.0.0.1:8080")
        
        self.stream_consumer = StreamPriceConsumer(redis_url=redis_url)
        last_alert_check = 0
        
        while not self.stop_event.is_set():
            try:
                with session_scope(readonly=True) as session:
                    portfolio = repo.get_active_portfolio(session)
                
                if not portfolio:
                    logger.info("   (Streams) 보유 종목이 없습니다. 60초 후 다시 확인합니다.")
                    time.sleep(60)
                    continue
                
                portfolio_codes = list(set(item['code'] for item in portfolio))
                self.portfolio_cache = {item['id']: item for item in portfolio}
                
                logger.info(f"   (Streams) {len(portfolio_codes)}개 종목 구독 요청 → Gateway...")
                
                # Gateway에 구독 요청 및 Redis Streams 소비 시작
                self.stream_consumer.start_consuming(
                    on_price_func=self._on_websocket_price_update,
                    consumer_group="price-monitor-group",
                    consumer_name=f"price-monitor-{os.getpid()}",
                    codes_to_subscribe=portfolio_codes,
                    gateway_url=gateway_url
                )
                
                logger.info("   (Streams) ✅ Redis Streams 소비 시작!")
                
                last_status_log_time = time.time()
                self.last_ws_data_time = time.time()
                
                while self.stream_consumer.is_connected() and not self.stop_event.is_set():
                    time.sleep(1)
                    now = time.time()
                    
                    # [Heartbeat] Redis에 살아있음을 알림 (5초마다)
                    # Dashboard System 페이지에서 "Real Time Watch Status"를 위해 사용됨
                    if now - last_status_log_time >= 5:
                        try:
                            hb_data = {
                                "status": "online",
                                "service": "price-monitor",
                                "metrics": {
                                    "watching_count": len(self.portfolio_cache),
                                    "updated_at": datetime.now().strftime("%H:%M:%S"),
                                    "pid": os.getpid()
                                }
                            }
                            # shared/redis_cache.py의 유틸리티 사용 (TTL 10초)
                            # Key: monitoring:price_monitor
                            redis_cache.set_redis_data("monitoring:price_monitor", hb_data, ttl=10)
                            
                        except Exception as hb_e:
                             # Heartbeat 실패는 로그만 남기고 무시
                            pass

                    if now - last_status_log_time >= 600:
                        logger.info(f"   (Streams) [상태 체크] 연결 유지 중, 감시: {len(self.portfolio_cache)}개")
                        # last_status_log_time은 600초 로그용으로 유지
                    
                    if now - last_alert_check >= self.alert_check_interval:
                        self._process_price_alerts()
                        last_alert_check = now
                
                if self.stop_event.is_set():
                    break
                
                logger.warning("   (Streams) 연결 끊김. 재연결 시도.")
                
            except Exception as e:
                logger.error(f"❌ (Streams) 모니터링 오류: {e}", exc_info=True)
                time.sleep(60)
        
        if self.stream_consumer:
            self.stream_consumer.stop()
    
    def _check_sell_signal(self, session, stock_code, stock_name, buy_price, current_price, holding, check_db_freshness=True):
        try:
            # 0. PROFIT CALCULATION (Initial)
            profit_pct = ((current_price - buy_price) / buy_price) * 100
            
            # --- [Double-Check Logic] DB 최신 상태 확인 ---
            # check_db_freshness=True이고, 수익률이 비정상적으로 높거나(예: +10% 이상) 매도 신호가 의심될 때
            # 또는 단순히 "모든 매도 신호 발생 직전"에 수행 (안전 제일)
            
            # 여기서는 잠정적으로 신호가 잡힐 것 같으면 DB를 확인하도록 구현
            # (ATR/StopLoss 계산 전 1차 필터링은 과부하 우려가 있으니, 
            #  일단 로직을 태우고 Signal=True가 나오면 그때 검증하는 것이 효율적. 
            #  하지만 buy_price 자체가 틀리면 로직을 태우는 의미가 없으므로,
            #  "수익률이 +5% 이상"이거나 "손실이 -3% 이하"인 변동성 구간에서만 검증하거나,
            #  혹은 간단히 Signal이 Return 되기 직전에 검증합니다.)
            
            # => 전략: 일단 기존 로직대로 Signal을 계산하고, Signal이 True이면 리턴하기 전에 DB와 대조합니다.
            
            daily_prices = database.get_daily_prices(session, stock_code, limit=30)
            
            # ATR 계산 (여러 조건에서 사용)
            atr = None
            if not daily_prices.empty and len(daily_prices) >= 15:
                atr = strategy.calculate_atr(daily_prices, period=14)
            
            potential_signal = None
            
            # =====================================================================
            # 0. Profit Floor Protection (수익 보호 바닥)
            # =====================================================================
            # 수익이 15% 이상 도달하면 바닥을 10%로 설정
            PROFIT_FLOOR_ACTIVATION = 15.0
            PROFIT_FLOOR_LEVEL = 10.0
            
            if profit_pct >= PROFIT_FLOOR_ACTIVATION:
                existing_floor = get_profit_floor(stock_code)
                if not existing_floor:
                    set_profit_floor(stock_code, PROFIT_FLOOR_LEVEL)
                    logger.info(f"🛡️ [{stock_name}] Profit Floor 설정: +{PROFIT_FLOOR_LEVEL}% (현재 +{profit_pct:.1f}%)")
            
            floor = get_profit_floor(stock_code)
            if floor and profit_pct < floor:
                potential_signal = {"signal": True, "reason": f"Profit Floor Hit ({profit_pct:.1f}% < Floor {floor}%)", "quantity_pct": 100.0}
            
            # =====================================================================
            # 0.1 High-Priority Profit Lock (Round Trip 방지) - [NEW]
            # [Minji/Junho] ATR 기반 동적 트리거로 변경: 변동성에 맞춰 조정
            # =====================================================================
            if not potential_signal:
                # ATR 기반 동적 트리거 계산
                atr_pct = (atr / buy_price) * 100 if (atr and buy_price > 0) else 2.0
                profit_lock_l1_trigger = max(2.0, atr_pct * 1.5)  # [Minji] 최소 2%, ATR 기반 동적
                profit_lock_l2_trigger = max(3.5, atr_pct * 2.5)  # L2도 비례 상향
                
                # Level 1: 동적 트리거 도달 시 -> 본전(+0.2% fee/tax 고려) 보장
                if profit_pct >= profit_lock_l1_trigger:
                    lock_stop = 0.2
                    if profit_pct < lock_stop: # 이미 떨어졌으면 즉시 청산
                         potential_signal = {"signal": True, "reason": f"Profit Lock L1 Break (Hit {profit_lock_l1_trigger:.1f}%, Now {profit_pct:.2f}% < {lock_stop}%)", "quantity_pct": 100.0}
                
                # Level 2: 동적 트리거 도달 시 -> +1.0% 이익 보장
                if not potential_signal and profit_pct >= profit_lock_l2_trigger:
                    lock_stop = 1.0
                    # 주의: 여기서는 "도달 이력"이 기준이 되어야 하지만,
                    # 현재 High Watermark가 Trailing 섹션에 있음. 
                    # 간소화를 위해 '현재가' 기준으로 즉시 판단하되,
                    # 엄밀하게는 High Watermark를 먼저 업데이트하고 판정해야 함.
                    pass # 뒤쪽 High Watermark 로직과 통합 고려하여 여기선 pass하고,
                         # Trailing 섹션에서 통합 처리하거나 별도로 High를 관리해야 함.
            
            # [수정] High Watermark 업데이트를 최상단으로 이동 (Profit Lock을 위해)
            watermark = update_high_watermark(stock_code, current_price, buy_price)
            high_price = watermark.get('high_price', current_price)
            high_profit_pct = ((high_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0

            # Profit Lock 실행 (High Price 기준) - ATR 기반 동적 트리거
            if not potential_signal:
                # ATR 기반 동적 트리거 계산 (위에서 이미 계산했으나, 없을 경우 대비)
                atr_pct = (atr / buy_price) * 100 if (atr and buy_price > 0) else 2.0
                profit_lock_l1_trigger = max(2.0, atr_pct * 1.5)
                profit_lock_l2_trigger = max(3.5, atr_pct * 2.5)
                
                # L2: 고점이 L2 트리거 이상이었는데, 현재 수익이 1.0% 미만이면 청산
                if high_profit_pct >= profit_lock_l2_trigger and profit_pct < 1.0:
                    potential_signal = {"signal": True, "reason": f"Profit Lock L2 (High {high_profit_pct:.1f}% >= {profit_lock_l2_trigger:.1f}%, Now {profit_pct:.1f}% < 1.0%)", "quantity_pct": 100.0}
                
                # L1: 고점이 L1 트리거 이상이었는데, 현재 수익이 0.2% 미만이면 청산
                elif high_profit_pct >= profit_lock_l1_trigger and profit_pct < 0.2:
                    potential_signal = {"signal": True, "reason": f"Profit Lock L1 (High {high_profit_pct:.1f}% >= {profit_lock_l1_trigger:.1f}%, Now {profit_pct:.1f}% < 0.2%)", "quantity_pct": 100.0}
            
            # =====================================================================
            # 0.5 MACD Divergence Early Warning
            # =====================================================================
            macd_bearish_warning = False
            if not potential_signal and not daily_prices.empty and len(daily_prices) >= 36:
                macd_div = strategy.check_macd_divergence(daily_prices)
                if macd_div and macd_div.get('bearish_divergence'):
                    macd_bearish_warning = True
                    logger.warning(f"⚠️ [{stock_name}] MACD Bearish Divergence 감지")
            
            # =====================================================================
            # 0.6 [Prime Council] Chart Phase Analysis
            # =====================================================================
            chart_phase_warning = False
            chart_phase_stage = 0
            chart_phase_exhaustion = 0.0
            
            if CHART_PHASE_AVAILABLE and not daily_prices.empty and len(daily_prices) >= 125:
                try:
                    phase_analyzer = ChartPhaseAnalyzer()
                    phase_result = phase_analyzer.analyze(daily_prices)
                    chart_phase_stage = phase_result.stage
                    chart_phase_exhaustion = phase_result.exhaustion_score
                    
                    # Stage 3 (Distribution) 또는 Exhaustion > 40 시 경고
                    if phase_result.stage == 3 or phase_result.exhaustion_score > 40:
                        chart_phase_warning = True
                        logger.warning(f"📊 [{stock_name}] ChartPhase Warning: Stage={phase_result.stage_name}, Exhaustion={phase_result.exhaustion_score:.0f}")
                except Exception as phase_err:
                    logger.debug(f"   (ChartPhase) {stock_code} 오류: {phase_err}")
            
            # =====================================================================
            # 1. 손절 조건 (Stop Loss)
            # =====================================================================
            
            # 1-1. ATR Trailing Stop (손절)
            if not potential_signal and atr:
                mult = self.config.get_float('ATR_MULTIPLIER', default=2.0)
                
                # MACD bearish divergence 시 더 타이트한 스탑
                if macd_bearish_warning:
                    mult = mult * 0.75
                
                # [Prime Council] Stage 3/Exhaustion 시 추가로 타이트하게
                if chart_phase_warning:
                    mult = mult * 0.8  # 추가 20% 조임
                    logger.debug(f"   [{stock_name}] ATR Mult 조정: Stage {chart_phase_stage}, Exhaustion {chart_phase_exhaustion:.0f}")
                
                stop_price = buy_price - (mult * atr)
                if current_price < stop_price:
                    potential_signal = {"signal": True, "reason": f"ATR Stop (Price {current_price:,.0f} < {stop_price:,.0f})", "quantity_pct": 100.0}
            
            # 1-2. Fallback: Fixed Stop Loss
            if not potential_signal:
                stop_loss = self.config.get_float('SELL_STOP_LOSS_PCT', default=-6.0)
                if stop_loss > 0: stop_loss = -stop_loss

                if profit_pct <= stop_loss:
                    potential_signal = {"signal": True, "reason": f"Fixed Stop Loss: {profit_pct:.2f}% (Limit: {stop_loss}%)", "quantity_pct": 100.0}


            # =====================================================================
            # 2. 트레일링 익절 (Trailing Take Profit) - 개선됨
            # =====================================================================
            if not potential_signal:
                trailing_enabled = self.config.get_bool('TRAILING_TAKE_PROFIT_ENABLED', default=True)
                activation_pct = self.config.get_float('TRAILING_TAKE_PROFIT_ACTIVATION_PCT', default=5.0)  # 10% -> 5% 하향 (조기 활성화)
                min_trailing_profit = self.config.get_float('TRAILING_MIN_PROFIT_PCT', default=3.0)  # 5% -> 3% 하향 (최소 보장)
                drop_from_high_pct = self.config.get_float('TRAILING_DROP_FROM_HIGH_PCT', default=3.5)  # 7% -> 3.5% 하향 (타이트하게)
                
                # MACD bearish divergence 시 더 빠른 익절 (20% 조기 활성화)
                if macd_bearish_warning:
                    activation_pct = activation_pct * 0.8
                
                # [Prime Council] Stage 3/Exhaustion 시 조기 활성화 + 타이트한 드롭
                if chart_phase_warning:
                    activation_pct = activation_pct * 0.7  # 30% 조기 활성화 (10% → 7%)
                    drop_from_high_pct = drop_from_high_pct * 0.7  # 더 타이트한 드롭 (7% → 4.9%)
                
                
                # High Watermark는 위에서 이미 업데이트함 (line 260 근처)
                # watermark = update_high_watermark(stock_code, current_price, buy_price)
                # high_price = watermark.get('high_price', current_price)

                if trailing_enabled:
                    # high_profit_pct 이미 계산됨
                    
                    # 조건 1: 고점 수익률이 활성화 조건 이상
                    if high_profit_pct >= activation_pct:
                        # 고점 대비 하락률 기반 스탑 가격 계산 (ATR 대신 %)
                        trailing_stop_price = high_price * (1 - drop_from_high_pct / 100)
                        
                        # 조건 2: 현재가가 스탑 라인 이하
                        # 조건 3: 현재 수익률이 최소 수익률 이상 (핵심 가드!)
                        if current_price <= trailing_stop_price and profit_pct >= min_trailing_profit:
                            potential_signal = {
                                "signal": True,
                                "reason": f"Trailing TP: High {high_price:,.0f} (-{drop_from_high_pct}%) → Stop {trailing_stop_price:,.0f} (Profit: {profit_pct:.1f}%)",
                                "quantity_pct": 100.0
                            }

            # =====================================================================
            # 3. 분할 익절 (Scale-out) - 개선됨
            # =====================================================================
            if not potential_signal:
                scale_out_enabled = self.config.get_bool('SCALE_OUT_ENABLED', default=True)
                if scale_out_enabled and profit_pct > 0:
                    current_level = get_scale_out_level(stock_code)
                    
                    # --- 시장 국면 감지 (MarketRegimeDetector 연동) ---
                    market_regime = "SIDEWAYS"  # 기본값
                    try:
                        regime_data = redis_cache.get_redis_data("market_regime:current")
                        if regime_data:
                            market_regime = regime_data.get("regime", "SIDEWAYS")
                    except Exception:
                        pass
                    
                    # --- 시장 국면별 동적 Scale-out 레벨 설정 ---
                    if market_regime == "BULL":
                        levels = [(3.0, 25.0), (7.0, 25.0), (15.0, 25.0), (25.0, 15.0)]  # L1: 8->3%, L2: 15->7%
                    elif market_regime == "BEAR":
                        levels = [(2.0, 25.0), (5.0, 25.0), (8.0, 25.0), (12.0, 15.0)]   # L1: 3->2%, L2: 7->5%
                    else:  # SIDEWAYS
                        levels = [(3.0, 25.0), (7.0, 25.0), (12.0, 25.0), (18.0, 15.0)]  # L1: 5->3%, L2: 10->7%
                    
                    # --- 최소 거래금액 가드 ---
                    MIN_TRANSACTION_AMOUNT = 500_000  # 50만원
                    MIN_SELL_QUANTITY = 50            # 50주
                    
                    # --- Scale-out L1~L4 처리 ---
                    for level_idx, (target_pct, sell_pct) in enumerate(levels, start=1):
                        if current_level < level_idx and profit_pct >= target_pct:
                            # 매도 수량 계산
                            sell_qty = int(holding['quantity'] * (sell_pct / 100.0)) or 1
                            sell_amount = sell_qty * current_price
                            
                            # 최소 거래금액 가드 체크
                            if sell_amount < MIN_TRANSACTION_AMOUNT or sell_qty < MIN_SELL_QUANTITY:
                                # L4(마지막 레벨)이면 잔여수량 전량 청산
                                if level_idx == 4:
                                    set_scale_out_level(stock_code, level_idx)
                                    potential_signal = {
                                        "signal": True, 
                                        "reason": f"Scale-out L{level_idx}(Force): +{profit_pct:.1f}% [{market_regime}]",
                                        "quantity_pct": 100.0  # 잔여 전량
                                    }
                                    logger.info(f"🔄 [{stock_code}] 소량 잔여 강제 청산: {holding['quantity']}주")
                                else:
                                    # 소량이면 스킵, 다음 레벨까지 대기
                                    logger.info(f"⏭️ [{stock_code}] Scale-out L{level_idx} 스킵: {sell_amount:,.0f}원 < 50만원")
                                break
                            else:
                                set_scale_out_level(stock_code, level_idx)
                                potential_signal = {
                                    "signal": True, 
                                    "reason": f"Scale-out L{level_idx}: +{profit_pct:.1f}% (목표 +{target_pct}%) [{market_regime}]",
                                    "quantity_pct": sell_pct
                                }
                            break

            # =====================================================================
            # 4. RSI 과열 & 5. 고정 목표 & 6. Death Cross & 7. Max Holding
            # =====================================================================
            if not potential_signal:
                # RSI Check
                if not daily_prices.empty and len(daily_prices) >= 15:
                    prices = daily_prices['CLOSE_PRICE'].tolist() + [current_price]
                    rsi = strategy.calculate_rsi(prices[::-1], period=14)
                    threshold = self.config.get_float_for_symbol(stock_code, 'SELL_RSI_OVERBOUGHT_THRESHOLD', default=75.0)
                    min_rsi_profit = self.config.get_float('SELL_RSI_MIN_PROFIT_PCT', default=3.0)
                    rsi_already_sold = get_rsi_overbought_sold(stock_code)

                    if rsi and rsi >= threshold and profit_pct >= min_rsi_profit and not rsi_already_sold:
                        set_rsi_overbought_sold(stock_code, True)
                        potential_signal = {"signal": True, "reason": f"RSI Overbought ({rsi:.1f}, Profit: {profit_pct:.1f}%)", "quantity_pct": 50.0}

            if not potential_signal:
                if not self.config.get_bool('TRAILING_TAKE_PROFIT_ENABLED', default=True):
                    target = self.config.get_float('SELL_TARGET_PROFIT_PCT', default=10.0)
                    if profit_pct >= target:
                        potential_signal = {"signal": True, "reason": f"Target Profit: {profit_pct:.2f}%", "quantity_pct": 100.0}

            if not potential_signal:
                if not daily_prices.empty and len(daily_prices) >= 20:
                    import pandas as pd
                    new_row = pd.DataFrame([{'PRICE_DATE': datetime.now(), 'CLOSE_PRICE': current_price, 'OPEN_PRICE': current_price, 'HIGH_PRICE': current_price, 'LOW_PRICE': current_price}])
                    # df = pd.concat([daily_prices, new_row], ignore_index=True) # Avoid concat overhead if possible, but safe here
                    # To keep it simple and safe:
                    df = pd.concat([daily_prices, new_row], ignore_index=True)
                    if strategy.check_death_cross(df):
                        potential_signal = {"signal": True, "reason": "Death Cross", "quantity_pct": 100.0}

            if not potential_signal:
                if holding.get('buy_date'):
                    days = (datetime.now() - datetime.strptime(holding['buy_date'], '%Y%m%d')).days
                    if days >= self.config.get_int('MAX_HOLDING_DAYS', default=30):
                        potential_signal = {"signal": True, "reason": f"Max Holding Days ({days})", "quantity_pct": 100.0}

            # === [Double-Check Logic] ===
            if potential_signal and check_db_freshness:
                logger.info(f"🕵️ [Double-Check] 매도 신호 감지 ({stock_name}): {potential_signal['reason']} -> DB 검증 시작")
                
                # DB에서 최신 포트폴리오 정보를 다시 조회
                # session은 readonly=True일 수 있으니 주의 (여기선 조회만 하므로 OK)
                fresh_portfolio = repo.get_active_portfolio(session) 
                # (주의: 전체 조회가 비효율적일 수 있으나 현재 보유 종목 수가 적어(10~20개) 허용 범위)
                # 더 나은 방법: repo.get_holding(session, stock_code) 추가 권장
                
                fresh_holding = next((h for h in fresh_portfolio if h['code'] == stock_code), None)
                
                if not fresh_holding:
                    logger.warning(f"⚠️ [Double-Check] DB에 보유 종목 없음! (Zombie State) -> 매도 취소 및 캐시 정리")
                    self.portfolio_cache.pop(holding['id'], None)
                    return None
                
                # 데이터 비교
                db_buy_price = fresh_holding['avg_price']
                cache_buy_price = holding['avg_price']
                
                # 가격 불일치 허용 오차 (부동소수점 고려, 1원 차이도 민감하게 체크)
                if abs(db_buy_price - cache_buy_price) > 1.0:
                    logger.warning(f"⚠️ [Double-Check] 매수가 불일치 발각! Cache: {cache_buy_price:,.0f} vs DB: {db_buy_price:,.0f}")
                    logger.warning(f"   -> 캐시 업데이트 및 신호 재평가 수행")
                    
                    # 캐시 업데이트
                    if holding.get('id') in self.portfolio_cache:
                        self.portfolio_cache[holding['id']].update(fresh_holding)
                        # holding 객체 자체도 업데이트 (참조형이므로)
                        holding['avg_price'] = db_buy_price
                        holding['quantity'] = fresh_holding['quantity']
                    
                    # 재귀 호출 (check_db_freshness=False로 무한 루프 방지)
                    return self._check_sell_signal(session, stock_code, stock_name, db_buy_price, current_price, holding, check_db_freshness=False)
                
                logger.info(f"✅ [Double-Check] DB 검증 완료. 신호 유효함.")
            
            return potential_signal

        except Exception as e:
            logger.error(f"[{stock_name}] 신호 체크 오류: {e}", exc_info=True)
            return None

    def _on_websocket_price_update(self, stock_code, current_price, current_high):
        try:
            # Silent Stall 감지용 타임스탬프 갱신
            self.last_ws_data_time = time.time()
            
            # logger.debug(f"   (WS) [{stock_code}] {current_price}")
            
            # 1. 보유 종목 매도 신호 체크
            holdings = [h for h in self.portfolio_cache.values() if h['code'] == stock_code]
            for h in holdings:
                with session_scope(readonly=True) as session:
                    signal = self._check_sell_signal(session,
                        stock_code, h.get('name', stock_code),
                        h['avg_price'], current_price, h
                    )
                if signal:
                    logger.info(f"🔔 (WS) 매도 신호: {h.get('name', stock_code)}")
                    self._publish_sell_order(signal, h, current_price)
                    
                    # [Jennie's Fix] 전량 매도인 경우에만 캐시 제거 및 Redis 초기화
                    q_pct = signal.get('quantity_pct', 100.0)
                    if q_pct >= 100.0:
                        logger.info(f"   (WS) 전량 매도로 모니터링 캐시 제거: {stock_code}")
                        self.portfolio_cache.pop(h['id'], None)
                        
                        # Redis 상태 초기화 (다음 매매를 위해)
                        delete_rsi_overbought_sold(stock_code)
                        delete_high_watermark(stock_code)
                        delete_scale_out_level(stock_code)
                    else:
                        # 분할 매도인 경우 수량만 업데이트하고 모니터링 유지
                        old_qty = h['quantity']
                        sell_qty = int(old_qty * (q_pct / 100.0)) or 1
                        h['quantity'] -= sell_qty
                        logger.info(f"   (WS) 분할 매도({q_pct}%): {old_qty} -> {h['quantity']} (모니터링 유지)")
            
            # 매수 신호 감시는 buy-scanner가 담당 (Phase: WebSocket 역할 분리)
                    
        except Exception as e:
            logger.error(f"❌ (WS) 오류: {e}")

    def _publish_sell_order(self, signal, holding, current_price):
        q_pct = signal.get('quantity_pct', 100.0)
        qty = int(holding['quantity'] * (q_pct / 100.0)) or 1
        
        payload = {
            "stock_code": holding['code'],
            "stock_name": holding.get('name', holding['code']),
            "quantity": qty,
            "current_price": current_price,
            "sell_reason": signal['reason'],
            "holding_id": holding.get('id')
        }
        
        # RabbitMQPublisher.publish() 사용 (create_task 대신)
        msg_id = self.tasks_publisher.publish(payload)
        if msg_id:
            logger.info(f"   ✅ 매도 요청 발행 완료: {msg_id}")
        else:
            logger.error(f"   ❌ 매도 요청 발행 실패: {holding['code']}")

    # ============================================================================
    # 가격 알림 처리
    # ============================================================================
    def _process_price_alerts(self):
        try:
            alerts = redis_cache.get_price_alerts()
            if not alerts:
                return
            
            trading_mode = os.getenv("TRADING_MODE", "MOCK")
            for code, info in alerts.items():
                target = info.get("target_price")
                alert_type = info.get("alert_type", "above")
                name = info.get("stock_name", code)
                
                current_price = 0
                if trading_mode == "MOCK":
                    with session_scope(readonly=True) as session:
                        prices = database.get_daily_prices(session, code, limit=1)
                        current_price = float(prices['CLOSE_PRICE'].iloc[-1]) if not prices.empty else 0
                else:
                    snap = self.kis.get_stock_snapshot(code)
                    current_price = snap.get("price", 0) if snap else 0
                
                if current_price <= 0:
                    continue
                
                triggered = False
                if alert_type == "above" and current_price >= target:
                    triggered = True
                if alert_type == "below" and current_price <= target:
                    triggered = True
                
                if triggered:
                    redis_cache.delete_price_alert(code)
                    msg = (
                        f"⏰ 가격 알림 도달\n\n"
                        f"{name} ({code})\n"
                        f"목표가: {target:,.0f}원 ({'이상' if alert_type=='above' else '이하'})\n"
                        f"현재가: {current_price:,.0f}원"
                    )
                    if self.telegram_bot:
                        self.telegram_bot.send_message(msg)
                    logger.info(f"[Alert] {code} {alert_type} {target} → {current_price}")
        except Exception as e:
            logger.error(f"가격 알림 처리 오류: {e}", exc_info=True)
