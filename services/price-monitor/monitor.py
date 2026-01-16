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

# OpportunityWatcher는 buy-scanner로 이관됨 (매수 역할 분리)
# from opportunity_watcher import OpportunityWatcher

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
                    
                    if now - last_status_log_time >= 600:
                        logger.info(f"   (Streams) [상태 체크] 연결 유지 중, 감시: {len(self.portfolio_cache)}개")
                        last_status_log_time = now
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
            # 0.5 MACD Divergence Early Warning
            # =====================================================================
            macd_bearish_warning = False
            if not potential_signal and not daily_prices.empty and len(daily_prices) >= 36:
                macd_div = strategy.check_macd_divergence(daily_prices)
                if macd_div and macd_div.get('bearish_divergence'):
                    macd_bearish_warning = True
                    logger.warning(f"⚠️ [{stock_name}] MACD Bearish Divergence 감지")
            
            # =====================================================================
            # 1. 손절 조건 (Stop Loss)
            # =====================================================================
            
            # 1-1. ATR Trailing Stop (손절)
            if not potential_signal and atr:
                mult = self.config.get_float('ATR_MULTIPLIER', default=2.0)
                # MACD bearish divergence 시 더 타이트한 스탑
                if macd_bearish_warning:
                    mult = mult * 0.75
                stop_price = buy_price - (mult * atr)
                if current_price < stop_price:
                    potential_signal = {"signal": True, "reason": f"ATR Stop (Price {current_price:,.0f} < {stop_price:,.0f})", "quantity_pct": 100.0}
            
            # 1-2. Fallback: Fixed Stop Loss
            if not potential_signal:
                stop_loss = self.config.get_float('SELL_STOP_LOSS_PCT', default=-5.0)
                if stop_loss > 0: stop_loss = -stop_loss

                if profit_pct <= stop_loss:
                    potential_signal = {"signal": True, "reason": f"Fixed Stop Loss: {profit_pct:.2f}% (Limit: {stop_loss}%)", "quantity_pct": 100.0}

            # =====================================================================
            # 2. 트레일링 익절 (Trailing Take Profit)
            # =====================================================================
            if not potential_signal:
                trailing_enabled = self.config.get_bool('TRAILING_TAKE_PROFIT_ENABLED', default=True)
                activation_pct = self.config.get_float('TRAILING_TAKE_PROFIT_ACTIVATION_PCT', default=5.0)
                # MACD bearish divergence 시 더 빠른 익절 (20% 조기 활성화)
                if macd_bearish_warning:
                    activation_pct = activation_pct * 0.8
                
                # High Watermark 업데이트
                watermark = update_high_watermark(stock_code, current_price, buy_price)
                high_price = watermark.get('high_price', current_price) # 여기서 high_price는 Redis 기준

                if trailing_enabled and atr:
                    high_profit_pct = ((high_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0
                    
                    if high_profit_pct >= activation_pct:
                        trailing_mult = self.config.get_float('TRAILING_TAKE_PROFIT_ATR_MULT', default=1.5)
                        trailing_stop_price = high_price - (atr * trailing_mult)
                        
                        if current_price <= trailing_stop_price:
                            potential_signal = {
                                "signal": True,
                                "reason": f"Trailing TP: High {high_price:,.0f} → Stop {trailing_stop_price:,.0f} (Profit: {profit_pct:.1f}%)",
                                "quantity_pct": 100.0
                            }

            # =====================================================================
            # 3. 분할 익절 (Scale-out)
            # =====================================================================
            if not potential_signal:
                scale_out_enabled = self.config.get_bool('SCALE_OUT_ENABLED', default=True)
                if scale_out_enabled and profit_pct > 0:
                    current_level = get_scale_out_level(stock_code)
                    
                    level_1_pct = self.config.get_float('SCALE_OUT_LEVEL_1_PCT', default=5.0)
                    level_1_sell = self.config.get_float('SCALE_OUT_LEVEL_1_SELL_PCT', default=25.0)
                    level_2_pct = self.config.get_float('SCALE_OUT_LEVEL_2_PCT', default=10.0)
                    level_2_sell = self.config.get_float('SCALE_OUT_LEVEL_2_SELL_PCT', default=25.0)
                    level_3_pct = self.config.get_float('SCALE_OUT_LEVEL_3_PCT', default=15.0)
                    level_3_sell = self.config.get_float('SCALE_OUT_LEVEL_3_SELL_PCT', default=25.0)
                    
                    if current_level < 1 and profit_pct >= level_1_pct:
                        set_scale_out_level(stock_code, 1)
                        potential_signal = {"signal": True, "reason": f"Scale-out L1: +{profit_pct:.1f}% (목표 +{level_1_pct}%)", "quantity_pct": level_1_sell}
                    
                    elif current_level < 2 and profit_pct >= level_2_pct:
                        set_scale_out_level(stock_code, 2)
                        potential_signal = {"signal": True, "reason": f"Scale-out L2: +{profit_pct:.1f}% (목표 +{level_2_pct}%)", "quantity_pct": level_2_sell}
                    
                    elif current_level < 3 and profit_pct >= level_3_pct:
                        set_scale_out_level(stock_code, 3)
                        potential_signal = {"signal": True, "reason": f"Scale-out L3: +{profit_pct:.1f}% (목표 +{level_3_pct}%)", "quantity_pct": level_3_sell}

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
