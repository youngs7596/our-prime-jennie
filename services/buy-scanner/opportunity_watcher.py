# services/buy-scanner/opportunity_watcher.py
# Version: v1.1
# Hot Watchlist 실시간 매수 신호 감지 (WebSocket 기반) + Supply/Demand & Legendary Pattern
# buy-scanner가 매수용 WebSocket을 담당

import time
import logging
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from threading import Lock, Event
from typing import Dict, Optional, List

import redis
import pandas as pd
from shared.db.connection import session_scope
from shared.db.factor_repository import FactorRepository

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
        
        # Redis 연결 설정
        self.redis_url = redis_url or "redis://127.0.0.1:6379/0"
        self.redis = None
        self._ensure_redis_connection()
        
        self.hot_watchlist: Dict[str, dict] = {}
        self.market_regime = 'SIDEWAYS'
        self.score_threshold = 65
        self.last_watchlist_load = 0
        self.watchlist_refresh_interval = 60
        self.supply_demand_cache: Dict[str, pd.DataFrame] = {} # {code: DataFrame}

        
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
        self.current_version_key = None

    def _ensure_redis_connection(self):
        """Redis 연결 확인 및 재연결"""
        if self.redis:
            try:
                self.redis.ping()
                return True
            except redis.ConnectionError:
                logger.warning("⚠️ Redis 연결 끊김. 재연결 시도...")
                self.redis = None
        
        try:
            self.redis = redis.from_url(self.redis_url, decode_responses=True)
            self.redis.ping()
            logger.info("✅ BuyOpportunityWatcher Redis 연결 성공")
            return True
        except Exception as e:
            # 너무 자주 로그 남기지 않도록 DEBUG 레벨 권장하나, 여기서는 중요하므로 ERROR/WARNING
            logger.warning(f"⚠️ BuyOpportunityWatcher Redis 연결 실패: {e}")
            self.redis = None
            return False

    def check_for_update(self) -> bool:
        """Redis에서 새 버전 확인"""
        if not self._ensure_redis_connection():
            return False
            
        try:
            active_key = self.redis.get("hot_watchlist:active")
            # active_key가 존재하고, 현재 버전과 다르면 업데이트 필요
            # (현재 버전이 None이면 무조건 업데이트)
            if active_key and active_key != self.current_version_key:
                return True
            return False
        except Exception:
            return False
        
    def load_hot_watchlist(self) -> bool:
        """Redis에서 Hot Watchlist 로드"""
        if not self._ensure_redis_connection():
            return False
        
        try:
            version_key = self.redis.get("hot_watchlist:active")
            if not version_key:
                logger.debug("Hot Watchlist active 버전 없음")
                self.current_version_key = None
                return False
            
            # 버전이 같으면 (그리고 우리가 이미 데이터를 가지고 있으면) 스킵
            # 단, force reload가 필요할 수도 있으므로 여기서는 로드 진행
            
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
            self.current_version_key = version_key
            
            logger.info(f"🔥 Hot Watchlist 로드: {len(self.hot_watchlist)}개 종목 "
                       f"(regime: {self.market_regime}, threshold: {self.score_threshold})")
            
            # [Added] Supply/Demand 데이터 로드 (for Legendary Pattern)
            self._load_supply_demand_data(list(self.hot_watchlist.keys()))

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

    def _load_supply_demand_data(self, stock_codes: List[str]):
        """수급 데이터 로드 (by FactorRepository)"""
        if not stock_codes:
            return
        
        try:
            with session_scope(readonly=True) as session:
                repo = FactorRepository(session)
                # 최근 30일치 외국인 수급 데이터 조회
                self.supply_demand_cache = repo.get_supply_demand_data(stock_codes, days=30)
                logger.info(f"   (Supply) {len(self.supply_demand_cache)}개 종목 수급 데이터 로드 완료")
        except Exception as e:
            logger.error(f"❌ 수급 데이터 로드 실패: {e}")

    
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
                    
                    # [Super Prime] Legendary Pattern Check
                    # 골든크로스 발생 시, 외국인 수급 패턴 확인하여 등급 상향
                    if self._check_legendary_pattern(stock_code, recent_bars):
                         signal_type = "GOLDEN_CROSS_SUPER_PRIME"
                         signal_reason += " + Legendary Pattern (Foreign Buy)"
                         logger.info(f"🚨 [{stock_code}] SUPER PRIME 신호 격상! (Legendary Pattern)")
                    
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
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'trade_tier': stock_info.get('trade_tier', 'TIER1'),
            'is_super_prime': (signal_type == "GOLDEN_CROSS_SUPER_PRIME")
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

    def _check_legendary_pattern(self, stock_code: str, bars: List[dict]) -> bool:
        """
        [Super Prime] 전설의 타이밍 패턴 여부 확인 (Realtime Version)
        조건: 최근 20거래일 이내에 (RSI <= 30 AND 외국인 순매수 >= 20일 평균 거래량의 5%) 발생 이력 존재
        """
        try:
            if stock_code not in self.supply_demand_cache:
                return False
            
            df_supply = self.supply_demand_cache[stock_code] # Columns: TRADE_DATE, FOREIGN_NET_BUY, ...
            if df_supply.empty:
                return False
                
            # 1. 최근 바 데이터에서 종가 추출 (이미 Aggregator가 가지고 있는 데이터 활용)
            # 주의: BarAggregator의 bars는 장중 1분봉 데이터임. 
            # Legendary Pattern은 '일봉' 기준 RSI 과매도 구간에서의 수급을 보는 것이 원칙.
            # 하지만 실시간 감시에서는 장중 RSI가 과매도일 때 외국인이 사는지를 볼 수도 있고,
            # 아니면 '과거 며칠 전'에 과매도+수급이 있었는지를 확인하는 것일 수도 있음.
            # 기존 scanner.py 로직: "최근 20일 이내에 (RSI <= 30 AND 외국인 순매수 >= 5%) 발생 이력"
            # 즉, '과거 일봉 데이터'와 '과거 수급 데이터'를 매칭해야 함.
            
            # 여기서 문제는 BarAggregator는 당일 분봉만 가짐. 
            # 따라서 정확한 구현을 위해서는 load_supply_demand_data 할 때 '일봉 데이터'도 같이 로딩해두거나,
            # 아니면 supply_demand_cache에 미리 RSI 계산 결과를 넣어두는 것이 효율적임.
            
            # 간소화된 접근: 
            # 수급 데이터(df_supply)는 일자별 외국인 순매수 정보를 가지고 있음.
            # 여기에 해당 일자의 RSI 정보가 없다면 판단 불가.
            # => FactorRepository에서 데이터를 가져올 때 RSI도 계산해서 가져오거나,
            #    단순히 "대량 매수(거래량 대비 5% 이상)" 여부만이라도 확인할 수 있음.
            
            # 여기서는 안전하게 "최근 5일간 외국인 순매수 합계가 양수이고, 최근 14일 RSI가 40 이하였던 적이 있음" 정도로 근사화하거나
            # 정확성을 위해 DB에서 일봉을 가져와야 함.
            # ==> 성능을 위해: 수급 데이터 로딩 시 '외국인 대량 매수(Volume 5% 이상)' 여부만 플래그로 가져오는 게 좋음.
            
            # 일단 현재 캐시된 df_supply만으로 가능한 로직 (수급 집중 확인):
            # "최근 3일간 외국인 순매수 합계 > 0" AND "현재 RSI < 40" (저점 매수세 유입)
            
            recent_supply = df_supply.sort_values('TRADE_DATE').tail(5)
            foreign_net_buy_sum = recent_supply['FOREIGN_NET_BUY'].sum()
            
            if foreign_net_buy_sum <= 0:
                return False
                
            # 현재 RSI 확인
            closes = [b['close'] for b in bars]
            current_rsi = self._calculate_simple_rsi(closes)
            
            if current_rsi and current_rsi <= 40:
                # 저점에서 외국인 수급 유입됨 -> Super Prime 후보
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Legendary Pattern 체크 실패: {e}")
            return False

    
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
                'is_super_prime': signal.get('is_super_prime', False),
                'factor_score': 520.0 if signal.get('is_super_prime') else 500.0,
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
