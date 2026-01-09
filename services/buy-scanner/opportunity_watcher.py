# services/buy-scanner/opportunity_watcher.py
# Version: v1.0
# Hot Watchlist 실시간 매수 신호 감지 (WebSocket 기반)
# buy-scanner가 매수용 WebSocket을 담당

import time
import logging
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from threading import Lock, Event
from typing import Dict, Optional, List

import redis

logger = logging.getLogger(__name__)


class BarAggregator:
    """
    실시간 틱 데이터를 1분 캔들로 집계
    """
    
    def __init__(self, bar_interval_seconds: int = 60):
        self.bar_interval = bar_interval_seconds
        self.current_bars: Dict[str, dict] = {}
        self.completed_bars: Dict[str, List[dict]] = defaultdict(list)
        self.lock = Lock()
        self.max_bar_history = 30
        
    def update(self, stock_code: str, price: float, volume: int = 0) -> Optional[dict]:
        """새 틱 데이터 수신 시 호출"""
        now = datetime.now(timezone.utc)
        bar_timestamp = self._get_bar_timestamp(now)
        
        with self.lock:
            if stock_code not in self.current_bars:
                self.current_bars[stock_code] = {
                    'timestamp': bar_timestamp,
                    'open': price,
                    'high': price,
                    'low': price,
                    'close': price,
                    'volume': volume,
                    'tick_count': 1
                }
                return None
            
            bar = self.current_bars[stock_code]
            
            if bar_timestamp > bar['timestamp']:
                completed = bar.copy()
                self.completed_bars[stock_code].append(completed)
                if len(self.completed_bars[stock_code]) > self.max_bar_history:
                    self.completed_bars[stock_code].pop(0)
                
                self.current_bars[stock_code] = {
                    'timestamp': bar_timestamp,
                    'open': price,
                    'high': price,
                    'low': price,
                    'close': price,
                    'volume': volume,
                    'tick_count': 1
                }
                return completed
            
            bar['high'] = max(bar['high'], price)
            bar['low'] = min(bar['low'], price)
            bar['close'] = price
            bar['volume'] += volume
            bar['tick_count'] += 1
            
            return None
    
    def _get_bar_timestamp(self, dt: datetime) -> datetime:
        seconds = dt.second + (dt.minute * 60)
        bar_seconds = (seconds // self.bar_interval) * self.bar_interval
        return dt.replace(
            minute=bar_seconds // 60,
            second=bar_seconds % 60,
            microsecond=0
        )
    
    def get_recent_bars(self, stock_code: str, count: int = 20) -> List[dict]:
        with self.lock:
            return list(self.completed_bars.get(stock_code, []))[-count:]


class BuyOpportunityWatcher:
    """
    매수용 Hot Watchlist 실시간 감시
    (buy-scanner 전용, 매수 신호 감지 및 발행)
    """
    
    def __init__(self, config, tasks_publisher, redis_url: str = None):
        """
        Args:
            config: ConfigManager 인스턴스
            tasks_publisher: RabbitMQPublisher (buy-signals 큐)
            redis_url: Redis 연결 URL
        """
        self.config = config
        self.tasks_publisher = tasks_publisher
        self.bar_aggregator = BarAggregator(bar_interval_seconds=60)
        self.stop_event = Event()
        
        # Redis 연결
        redis_url = redis_url or "redis://127.0.0.1:6379/0"
        try:
            self.redis = redis.from_url(redis_url, decode_responses=True)
            self.redis.ping()
            logger.info("✅ BuyOpportunityWatcher Redis 연결 성공")
        except Exception as e:
            logger.warning(f"⚠️ BuyOpportunityWatcher Redis 연결 실패: {e}")
            self.redis = None
        
        self.hot_watchlist: Dict[str, dict] = {}
        self.market_regime = 'SIDEWAYS'
        self.score_threshold = 65
        self.last_watchlist_load = 0
        self.watchlist_refresh_interval = 60
        
        # Cooldown (중복 시그널 방지)
        self.cooldown_seconds = 180
        
        # 메트릭
        self.metrics = {
            'tick_count': 0,
            'bar_count': 0,
            'signal_count': 0,
            'cooldown_blocked': 0,
            'watchlist_loads': 0,
            'last_tick_time': None,
            'last_signal_time': None,
        }
        
    def load_hot_watchlist(self) -> bool:
        """Redis에서 Hot Watchlist 로드"""
        if not self.redis:
            return False
        
        try:
            version_key = self.redis.get("hot_watchlist:active")
            if not version_key:
                logger.debug("Hot Watchlist active 버전 없음")
                return False
            
            data = self.redis.get(version_key)
            if not data:
                return False
            
            payload = json.loads(data)
            stocks = payload.get('stocks', [])
            
            self.hot_watchlist = {
                s['code']: {
                    'name': s.get('name', s['code']),
                    'llm_score': s.get('llm_score', 0),
                    'rank': s.get('rank', 99),
                    'is_tradable': s.get('is_tradable', True),
                    'strategies': s.get('strategies', []),
                    'trade_tier': s.get('trade_tier'),
                }
                for s in stocks
            }
            
            self.market_regime = payload.get('market_regime', 'SIDEWAYS')
            self.score_threshold = payload.get('score_threshold', 65)
            self.last_watchlist_load = time.time()
            
            logger.info(f"🔥 Hot Watchlist 로드: {len(self.hot_watchlist)}개 종목 "
                       f"(regime: {self.market_regime}, threshold: {self.score_threshold})")
            self.metrics['watchlist_loads'] += 1
            return True
            
        except Exception as e:
            logger.error(f"Hot Watchlist 로드 실패: {e}")
            return False
    
    def get_watchlist_codes(self) -> List[str]:
        """WebSocket 구독 대상 종목 코드 반환"""
        if time.time() - self.last_watchlist_load > self.watchlist_refresh_interval:
            self.load_hot_watchlist()
        return list(self.hot_watchlist.keys())
    
    def on_price_update(self, stock_code: str, price: float, volume: int = 0) -> Optional[dict]:
        """실시간 가격 업데이트 수신"""
        self.metrics['tick_count'] += 1
        self.metrics['last_tick_time'] = datetime.now(timezone.utc).isoformat()
        
        if stock_code not in self.hot_watchlist:
            return None
        
        completed_bar = self.bar_aggregator.update(stock_code, price, volume)
        
        if completed_bar:
            self.metrics['bar_count'] += 1
            return self._check_buy_signal(stock_code, price, completed_bar)
        
        return None
    
    def _check_buy_signal(self, stock_code: str, current_price: float, 
                          completed_bar: dict) -> Optional[dict]:
        """매수 신호 체크"""
        stock_info = self.hot_watchlist.get(stock_code, {})
        strategies = stock_info.get('strategies', [])
        
        if not strategies:
            strategies = [
                {"id": "GOLDEN_CROSS", "params": {"short_window": 5, "long_window": 20}},
                {"id": "RSI_OVERSOLD", "params": {"threshold": 30}}
            ]

        recent_bars = self.bar_aggregator.get_recent_bars(stock_code, count=30)
        if len(recent_bars) < 20:
             return None

        if not self._check_cooldown(stock_code):
            return None
            
        signal_type = None
        signal_reason = ""
        
        for strat in strategies:
            strat_id = strat.get('id')
            params = strat.get('params', {})
            
            if strat_id == "GOLDEN_CROSS":
                triggered, reason = self._check_golden_cross(recent_bars, params)
                if triggered:
                    signal_type = "GOLDEN_CROSS"
                    signal_reason = reason
                    break
            
            elif strat_id == "RSI_OVERSOLD":
                triggered, reason = self._check_rsi_oversold(recent_bars, params)
                if triggered:
                    signal_type = "RSI_OVERSOLD"
                    signal_reason = reason
                    break
                    
            elif strat_id == "BB_LOWER":
                triggered, reason = self._check_bb_lower(recent_bars, params, current_price)
                if triggered:
                    signal_type = "BB_LOWER"
                    signal_reason = reason
                    break
            
            elif strat_id == "MOMENTUM":
                triggered, reason = self._check_momentum(recent_bars, params)
                if triggered:
                    signal_type = "MOMENTUM"
                    signal_reason = reason
                    break

        if not signal_type:
            return None
        
        self._set_cooldown(stock_code)
        logger.info(f"🔔 [{stock_code}] {signal_type} 신호 감지: {signal_reason}")
        
        signal = {
            'stock_code': stock_code,
            'stock_name': stock_info.get('name', stock_code),
            'signal_type': signal_type,
            'signal_reason': signal_reason,
            'current_price': current_price,
            'llm_score': stock_info.get('llm_score', 0),
            'market_regime': self.market_regime,
            'source': 'buy_scanner_websocket',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'trade_tier': stock_info.get('trade_tier', 'TIER1'),
        }
        
        return signal

    def _check_golden_cross(self, bars: List[dict], params: dict) -> tuple:
        closes = [b['close'] for b in bars]
        short_w = params.get('short_window', 5)
        long_w = params.get('long_window', 20)
        
        if len(closes) < long_w:
            return False, ""
            
        ma_short = sum(closes[-short_w:]) / short_w
        ma_long = sum(closes[-long_w:]) / long_w
        
        prev_closes = closes[:-1]
        prev_ma_short = sum(prev_closes[-short_w:]) / short_w if len(prev_closes) >= short_w else ma_short
        
        if (prev_ma_short <= ma_long) and (ma_short > ma_long):
            return True, f"MA({short_w}) crossed above MA({long_w})"
        return False, ""

    def _check_rsi_oversold(self, bars: List[dict], params: dict) -> tuple:
        closes = [b['close'] for b in bars]
        threshold = params.get('threshold', 30)
        rsi = self._calculate_simple_rsi(closes, period=14)
        
        if rsi and rsi <= threshold:
            return True, f"RSI={rsi:.1f} <= {threshold}"
        return False, ""

    def _check_bb_lower(self, bars: List[dict], params: dict, current_price: float) -> tuple:
        closes = [b['close'] for b in bars]
        period = params.get('period', 20)
        
        if len(closes) < period:
            return False, ""
            
        recent = closes[-period:]
        ma = sum(recent) / period
        variance = sum([(x - ma) ** 2 for x in recent]) / period
        std_dev = variance ** 0.5
        lower_band = ma - (2 * std_dev)
        
        if current_price <= lower_band:
            return True, f"Price({current_price}) <= BB_Lower({lower_band:.1f})"
        return False, ""

    def _check_momentum(self, bars: List[dict], params: dict) -> tuple:
        closes = [b['close'] for b in bars]
        threshold = params.get('threshold', 3.0)
        if len(closes) < 2:
            return False, ""
            
        momentum = ((closes[-1] - closes[0]) / closes[0]) * 100
        if momentum >= threshold:
            return True, f"Momentum={momentum:.1f}% >= {threshold}%"
        return False, ""

    def _calculate_simple_rsi(self, prices: List[float], period: int = 14) -> Optional[float]:
        if len(prices) < period + 1:
            return None
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        recent_deltas = deltas[-(period):]
        
        gains = [d for d in recent_deltas if d > 0]
        losses = [-d for d in recent_deltas if d < 0]
        
        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 0
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _check_cooldown(self, stock_code: str) -> bool:
        if not self.redis:
            return True
        
        try:
            cooldown_key = f"buy_signal_cooldown:{stock_code}"
            if self.redis.exists(cooldown_key):
                self.metrics['cooldown_blocked'] += 1
                return False
            return True
        except Exception:
            return True
    
    def _set_cooldown(self, stock_code: str) -> None:
        if not self.redis:
            return
        
        try:
            cooldown_key = f"buy_signal_cooldown:{stock_code}"
            self.redis.setex(cooldown_key, self.cooldown_seconds, "1")
        except Exception as e:
            logger.warning(f"Cooldown 설정 실패: {e}")
    
    def publish_signal(self, signal: dict) -> bool:
        """매수 신호 RabbitMQ 발행"""
        if not self.tasks_publisher:
            logger.warning("RabbitMQ Publisher 없음 - 신호 발행 불가")
            return False
        
        try:
            candidate = {
                'code': signal['stock_code'],
                'name': signal['stock_name'],
                'stock_code': signal['stock_code'],
                'stock_name': signal['stock_name'],
                'buy_signal_type': signal['signal_type'],
                'key_metrics_dict': {
                    'signal': signal['signal_type'],
                    'reason': signal['signal_reason'],
                    'source': 'realtime_websocket',
                },
                'current_price': signal['current_price'],
                'llm_score': signal['llm_score'],
                'is_tradable': True,
                'trade_tier': signal.get('trade_tier', 'TIER1'),
                'factor_score': 500.0,
            }
            
            payload = {
                'candidates': [candidate],
                'market_regime': signal['market_regime'],
                'scan_timestamp': signal['timestamp'],
                'source': 'buy_scanner_websocket',
            }
            
            msg_id = self.tasks_publisher.publish(payload)
            if msg_id:
                logger.info(f"✅ 매수 신호 발행: {signal['stock_code']} - {signal['signal_type']} (ID: {msg_id})")
                self.metrics['signal_count'] += 1
                self.metrics['last_signal_time'] = datetime.now(timezone.utc).isoformat()
                return True
            else:
                logger.error(f"❌ 매수 신호 발행 실패: {signal['stock_code']}")
                return False
                
        except Exception as e:
            logger.error(f"매수 신호 발행 오류: {e}")
            return False
    
    def get_metrics(self) -> dict:
        return {
            **self.metrics,
            'hot_watchlist_size': len(self.hot_watchlist),
            'market_regime': getattr(self, 'market_regime', 'UNKNOWN'),
        }

    def publish_heartbeat(self):
        """대시보드 모니터링용 Heartbeat"""
        if not self.redis:
            return
            
        try:
            metrics = self.get_metrics()
            metrics['updated_at'] = datetime.now(timezone.utc).isoformat()
            
            key = "monitoring:buy_scanner_websocket"
            self.redis.setex(key, 15, json.dumps(metrics))
        except Exception as e:
            logger.debug(f"Heartbeat 발행 실패: {e}")
    
    def stop(self):
        """감시 중단"""
        self.stop_event.set()
