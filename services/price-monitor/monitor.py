# monitor.py
# Price Monitor - 실시간 가격 감시 및 매도 신호 발행

import time
import logging
import sys
import os
from datetime import datetime
from threading import Event

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
        self.use_websocket = (trading_mode == "REAL")
        self.use_redis_streams = os.getenv("USE_REDIS_STREAMS", "false").lower() == "true"
        self.alert_check_interval = int(os.getenv("PRICE_ALERT_CHECK_INTERVAL", "15"))
        
        # Redis Streams 모드용 consumer
        self.stream_consumer = None
        
        logger.info(f"Price Monitor 설정: TRADING_MODE={trading_mode}, USE_WEBSOCKET={self.use_websocket}, USE_REDIS_STREAMS={self.use_redis_streams}")
        
        self.portfolio_cache = {}
        
        # [Phase: WebSocket 역할 분리] OpportunityWatcher는 buy-scanner로 이관됨
        # price-monitor는 매도 신호 감지에만 집중
        
        # Silent Stall 감지용
        self.last_ws_data_time = 0
    
    def start_monitoring(self, dry_run: bool = True):
        logger.info("=== 가격 모니터링 시작 ===")
        try:
            # 시장 운영 여부 확인 (휴장/주말/장외면 바로 중단)
            # 시장 운영 여부 확인 (휴장/주말/장외면 바로 중단)
            disable_market_open_check = self.config.get_bool("DISABLE_MARKET_OPEN_CHECK", default=False)
            
            if not disable_market_open_check:
                try:
                    if hasattr(self.kis, "check_market_open"):
                        if not self.kis.check_market_open():
                            logger.warning("💤 시장 미운영(휴장/주말/장외)으로 모니터링을 건너뜁니다.")
                            return
                    else:
                        # Gateway 클라이언트 등 최소한의 주말/시간 필터
                        from datetime import datetime
                        import pytz
                        kst = pytz.timezone("Asia/Seoul")
                        now = datetime.now(kst)
                        if not (0 <= now.weekday() <= 4 and 8 <= now.hour <= 16):
                            logger.warning("💤 시장 미운영 시간(주말/장외)으로 모니터링을 건너뜁니다.")
                            return
                except Exception as e:
                    logger.error(f"시장 운영 여부 확인 실패: {e}", exc_info=True)
                    return

            # 모니터링 모드 결정
            if self.use_redis_streams and REDIS_STREAMS_AVAILABLE:
                self._monitor_with_redis_streams(dry_run)
            elif self.use_websocket:
                self._monitor_with_websocket(dry_run)
            else:
                self._monitor_with_polling(dry_run)
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
        
        self.stream_consumer.stop()
    
    def _monitor_with_websocket(self, dry_run: bool):
        logger.info("=== WebSocket 모드로 실시간 모니터링 시작 ===")
        
        last_alert_check = 0
        while not self.stop_event.is_set():
            try:
                with session_scope(readonly=True) as session:
                    portfolio = repo.get_active_portfolio(session)
                
                if not portfolio:
                    logger.info("   (WS) 보유 종목이 없습니다. 60초 후 다시 확인합니다.")
                    time.sleep(60)
                    continue
                
                portfolio_codes = list(set(item['code'] for item in portfolio))
                self.portfolio_cache = {item['id']: item for item in portfolio}
                
                # [Phase: WebSocket 역할 분리] 보유 포트폴리오만 감시 (매도 전용)
                # Hot Watchlist 매수 감시는 buy-scanner가 담당
                all_codes = portfolio_codes
                
                self.kis.websocket.start_realtime_monitoring(
                    portfolio_codes=all_codes,
                    on_price_func=self._on_websocket_price_update
                )
                
                if not self.kis.websocket.connection_event.wait(timeout=15):
                    logger.error("   (WS) ❌ WebSocket 연결 시간(15초) 초과! 재시도합니다.")
                    if self.kis.websocket.ws:
                        self.kis.websocket.ws.close()
                    time.sleep(5)
                    continue
                
                logger.info("   (WS) ✅ WebSocket 연결 확인! 실시간 감시 시작.")
                
                last_status_log_time = time.time()
                self.last_ws_data_time = time.time()  # 연결 시점 초기화
                last_heartbeat_time = 0  # Heartbeat 타이머
                
                while self.kis.websocket.connection_event.is_set() and not self.stop_event.is_set():
                    time.sleep(1)
                    now = time.time()
                    
                    # Silent Stall 감지 (데이터가 60초간 안 들어오면 재연결)
                    # 단, 구독 종목이 있을 때만 체크
                    if len(all_codes) > 0 and (now - self.last_ws_data_time > 60):
                        logger.warning(f"   (WS) ⚠️ Silent Stall 감지! (60초간 데이터 수신 없음) 재연결 시도.")
                        self.kis.websocket.stop()
                        break
                    # Dashboard Heartbeat 제거 (매수 감시는 buy-scanner가 담당)

                    if now - last_status_log_time >= 600:
                        logger.info(f"   (WS) [상태 체크] 연결 유지 중, 감시: {len(self.portfolio_cache)}개")
                        last_status_log_time = now
                    if now - last_alert_check >= self.alert_check_interval:
                        self._process_price_alerts()
                        last_alert_check = now
                
                if self.stop_event.is_set():
                    break
                
                logger.warning("   (WS) WebSocket 연결 끊김. 재연결 시도.")
                
            except Exception as e:
                logger.error(f"❌ (WS) 모니터링 오류: {e}", exc_info=True)
                time.sleep(60)
        
        self.kis.websocket.stop()
    
    def _monitor_with_polling(self, dry_run: bool):
        logger.info("HTTP Polling 모드로 모니터링 시작")
        check_interval = self.config.get_int('PRICE_MONITOR_INTERVAL_SECONDS', default=10)
        
        last_alert_check = 0
        while not self.stop_event.is_set():
            try:
                with session_scope(readonly=True) as session:
                    portfolio = repo.get_active_portfolio(session)
                
                if not portfolio:
                    time.sleep(check_interval)
                    continue
                
                for holding in portfolio:
                    if self.stop_event.is_set(): break
                    
                    stock_code = holding['code']
                    trading_mode = os.getenv("TRADING_MODE", "MOCK")
                    
                    if trading_mode == "MOCK":
                        with session_scope(readonly=True) as session:
                            prices = database.get_daily_prices(session, stock_code, limit=1)
                            current_price = float(prices['CLOSE_PRICE'].iloc[-1]) if not prices.empty else 0
                    else:
                        snap = self.kis.get_stock_snapshot(stock_code)
                        current_price = snap['price'] if snap else 0
                    
                    if current_price <= 0: continue
                    
                    with session_scope(readonly=True) as session: # _check_sell_signal이 session을 받도록 수정
                        signal = self._check_sell_signal(
                            session, stock_code, holding.get('name', stock_code),
                            holding['avg_price'], current_price, holding
                        )
                    
                    if signal:
                        logger.info(f"🔔 매도 신호 발생: {holding.get('name', stock_code)}")
                        self._publish_sell_order(signal, holding, current_price)
                
                # 가격 알림 체크 (주기적)
                now = time.time()
                if now - last_alert_check >= self.alert_check_interval:
                    self._process_price_alerts()
                    last_alert_check = now
                
                time.sleep(check_interval)
            except Exception as e:
                logger.error(f"모니터링 루프 오류: {e}")
                time.sleep(check_interval)
    
    def _check_sell_signal(self, session, stock_code, stock_name, buy_price, current_price, holding):
        try:
            profit_pct = ((current_price - buy_price) / buy_price) * 100
            daily_prices = database.get_daily_prices(session, stock_code, limit=30)
            
            # ATR 계산 (여러 조건에서 사용)
            atr = None
            if not daily_prices.empty and len(daily_prices) >= 15:
                atr = strategy.calculate_atr(daily_prices, period=14)
            
            # =====================================================================
            # 1. 손절 조건 (Stop Loss)
            # =====================================================================
            
            # 1-1. ATR Trailing Stop (손절)
            if atr:
                mult = self.config.get_float('ATR_MULTIPLIER', default=2.0)
                stop_price = buy_price - (mult * atr)
                if current_price < stop_price:
                    return {"signal": True, "reason": f"ATR Stop (Price {current_price:,.0f} < {stop_price:,.0f})", "quantity_pct": 100.0}
            
            # 1-2. Fallback: Fixed Stop Loss
            stop_loss = self.config.get_float('SELL_STOP_LOSS_PCT', default=-5.0)
            
            # [Jennie's Fix] Stop Loss는 항상 음수여야 합니다.
            if stop_loss > 0:
                stop_loss = -stop_loss

            if profit_pct <= stop_loss:
                return {"signal": True, "reason": f"Fixed Stop Loss: {profit_pct:.2f}% (Limit: {stop_loss}%)", "quantity_pct": 100.0}

            # =====================================================================
            # 2. 트레일링 익절 (Trailing Take Profit) - 신규 추가
            # =====================================================================
            
            # High Watermark 업데이트 (최고가 추적)
            watermark = update_high_watermark(stock_code, current_price, buy_price)
            high_price = watermark.get('high_price', current_price)
            
            # 트레일링 익절 조건 체크
            trailing_enabled = self.config.get_bool('TRAILING_TAKE_PROFIT_ENABLED', default=True)
            activation_pct = self.config.get_float('TRAILING_TAKE_PROFIT_ACTIVATION_PCT', default=5.0)
            
            if trailing_enabled and atr:
                # 최고가 기준 수익률
                high_profit_pct = ((high_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0
                
                # 활성화 조건: 최고가 기준 수익이 activation_pct 이상일 때
                if high_profit_pct >= activation_pct:
                    trailing_mult = self.config.get_float('TRAILING_TAKE_PROFIT_ATR_MULT', default=1.5)
                    trailing_stop_price = high_price - (atr * trailing_mult)
                    
                    # 트레일링 익절 발동: 현재가가 트레일링 스탑가 이하
                    if current_price <= trailing_stop_price:
                        return {
                            "signal": True,
                            "reason": f"Trailing TP: High {high_price:,.0f} → Stop {trailing_stop_price:,.0f} (Profit: {profit_pct:.1f}%)",
                            "quantity_pct": 100.0
                        }

            # =====================================================================
            # 3. 분할 익절 (Scale-out) - 수익률 단계별 부분 매도
            # =====================================================================
            scale_out_enabled = self.config.get_bool('SCALE_OUT_ENABLED', default=True)
            
            if scale_out_enabled and profit_pct > 0:
                current_level = get_scale_out_level(stock_code)
                
                # 각 레벨별 설정 조회
                level_1_pct = self.config.get_float('SCALE_OUT_LEVEL_1_PCT', default=5.0)
                level_1_sell = self.config.get_float('SCALE_OUT_LEVEL_1_SELL_PCT', default=25.0)
                level_2_pct = self.config.get_float('SCALE_OUT_LEVEL_2_PCT', default=10.0)
                level_2_sell = self.config.get_float('SCALE_OUT_LEVEL_2_SELL_PCT', default=25.0)
                level_3_pct = self.config.get_float('SCALE_OUT_LEVEL_3_PCT', default=15.0)
                level_3_sell = self.config.get_float('SCALE_OUT_LEVEL_3_SELL_PCT', default=25.0)
                
                # 아직 레벨 1 미도달
                if current_level < 1 and profit_pct >= level_1_pct:
                    set_scale_out_level(stock_code, 1)
                    return {
                        "signal": True,
                        "reason": f"Scale-out L1: +{profit_pct:.1f}% (목표 +{level_1_pct}%)",
                        "quantity_pct": level_1_sell
                    }
                
                # 레벨 1 완료, 레벨 2 미도달
                if current_level < 2 and profit_pct >= level_2_pct:
                    set_scale_out_level(stock_code, 2)
                    return {
                        "signal": True,
                        "reason": f"Scale-out L2: +{profit_pct:.1f}% (목표 +{level_2_pct}%)",
                        "quantity_pct": level_2_sell
                    }
                
                # 레벨 2 완료, 레벨 3 미도달
                if current_level < 3 and profit_pct >= level_3_pct:
                    set_scale_out_level(stock_code, 3)
                    return {
                        "signal": True,
                        "reason": f"Scale-out L3: +{profit_pct:.1f}% (목표 +{level_3_pct}%)",
                        "quantity_pct": level_3_sell
                    }

            # =====================================================================
            # 4. RSI 과열 (추가 Scale-out)
            # =====================================================================
            if not daily_prices.empty and len(daily_prices) >= 15:
                prices = daily_prices['CLOSE_PRICE'].tolist() + [current_price]
                rsi = strategy.calculate_rsi(prices[::-1], period=14)
                threshold = self.config.get_float_for_symbol(stock_code, 'SELL_RSI_OVERBOUGHT_THRESHOLD', default=75.0)
                
                # [Jennie's Fix] 최소 수익률 조건 추가 (사용자 요청: 3%)
                min_rsi_profit = self.config.get_float('SELL_RSI_MIN_PROFIT_PCT', default=3.0)
                
                # 이미 RSI 분할 매도를 했는지 확인
                rsi_already_sold = get_rsi_overbought_sold(stock_code)

                if rsi and rsi >= threshold and profit_pct >= min_rsi_profit and not rsi_already_sold:
                    # Redis에 매도 상태 기록
                    set_rsi_overbought_sold(stock_code, True)
                    return {"signal": True, "reason": f"RSI Overbought ({rsi:.1f}, Profit: {profit_pct:.1f}%)", "quantity_pct": 50.0}

            # =====================================================================
            # 5. 고정 목표 익절 (트레일링 비활성화 시 폴백)
            # =====================================================================
            if not trailing_enabled:
                target = self.config.get_float('SELL_TARGET_PROFIT_PCT', default=10.0)
                if profit_pct >= target:
                    return {"signal": True, "reason": f"Target Profit: {profit_pct:.2f}%", "quantity_pct": 100.0}
            
            # =====================================================================
            # 6. Death Cross
            # =====================================================================
            if not daily_prices.empty and len(daily_prices) >= 20:
                import pandas as pd
                new_row = pd.DataFrame([{'PRICE_DATE': datetime.now(), 'CLOSE_PRICE': current_price, 'OPEN_PRICE': current_price, 'HIGH_PRICE': current_price, 'LOW_PRICE': current_price}])
                df = pd.concat([daily_prices, new_row], ignore_index=True)
                if strategy.check_death_cross(df):
                    return {"signal": True, "reason": "Death Cross", "quantity_pct": 100.0}
            
            # =====================================================================
            # 7. Max Holding Days
            # =====================================================================
            if holding.get('buy_date'):
                days = (datetime.now() - datetime.strptime(holding['buy_date'], '%Y%m%d')).days
                if days >= self.config.get_int('MAX_HOLDING_DAYS', default=30):
                    return {"signal": True, "reason": f"Max Holding Days ({days})", "quantity_pct": 100.0}
            
            return None
        except Exception as e:
            logger.error(f"[{stock_name}] 신호 체크 오류: {e}")
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
