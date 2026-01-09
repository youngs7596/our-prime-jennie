# services/price-monitor/opportunity_watcher.py
# Version: v1.0
# Hot Watchlist 실시간 매수 신호 감지 (WebSocket 기반)

import time
import logging
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from threading import Lock
from typing import Dict, Optional, List

import redis

logger = logging.getLogger(__name__)


class BarAggregator:
    """
    실시간 틱 데이터를 1분 캔들로 집계
    (준호 제안: Tick → micro-bar aggregation → 1분 캔들 확정 시 지표 계산)
    """
    
    def __init__(self, bar_interval_seconds: int = 60):
        """
        Args:
            bar_interval_seconds: 캔들 간격 (기본 60초 = 1분)
        """
        self.bar_interval = bar_interval_seconds
        self.current_bars: Dict[str, dict] = {}  # stock_code -> current bar
        self.completed_bars: Dict[str, List[dict]] = defaultdict(list)  # stock_code -> bar history
        self.lock = Lock()
        self.max_bar_history = 30  # 30분치 보관
        
    def update(self, stock_code: str, price: float, volume: int = 0) -> Optional[dict]:
        """
        새 틱 데이터 수신 시 호출
        
        Returns:
            완료된 캔들 (bar가 닫히면 반환, 아니면 None)
        """
        now = datetime.now(timezone.utc)
        bar_timestamp = self._get_bar_timestamp(now)
        
        with self.lock:
            if stock_code not in self.current_bars:
                # 새 캔들 시작
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
            
            # 새 캔들 시간이면 이전 캔들 완료 처리
            if bar_timestamp > bar['timestamp']:
                completed = bar.copy()
                
                # 완료된 캔들 히스토리에 추가
                self.completed_bars[stock_code].append(completed)
                if len(self.completed_bars[stock_code]) > self.max_bar_history:
                    self.completed_bars[stock_code].pop(0)
                
                # 새 캔들 시작
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
            
            # 현재 캔들 업데이트
            bar['high'] = max(bar['high'], price)
            bar['low'] = min(bar['low'], price)
            bar['close'] = price
            bar['volume'] += volume
            bar['tick_count'] += 1
            
            return None
    
    def _get_bar_timestamp(self, dt: datetime) -> datetime:
        """주어진 시간을 캔들 시작 시간으로 정규화"""
        seconds = dt.second + (dt.minute * 60)
        bar_seconds = (seconds // self.bar_interval) * self.bar_interval
        return dt.replace(
            minute=bar_seconds // 60,
            second=bar_seconds % 60,
            microsecond=0
        )
    
    def get_recent_bars(self, stock_code: str, count: int = 20) -> List[dict]:
        """최근 N개 완료된 캔들 조회"""
        with self.lock:
            return list(self.completed_bars.get(stock_code, []))[-count:]


class OpportunityWatcher:
    """
    Hot Watchlist 매수 기회 감지
    (제니 제안: PortfolioWatcher와 분리된 SRP 구조)
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
        
        # Redis 연결
        redis_url = redis_url or "redis://127.0.0.1:6379/0"
        try:
            self.redis = redis.from_url(redis_url, decode_responses=True)
            self.redis.ping()
            logger.info("✅ OpportunityWatcher Redis 연결 성공")
        except Exception as e:
            logger.warning(f"⚠️ OpportunityWatcher Redis 연결 실패: {e}")
            self.redis = None
        
        self.hot_watchlist: Dict[str, dict] = {}
        self.last_watchlist_load = 0
        self.watchlist_refresh_interval = 60  # 60초마다 갱신 체크
        
        # Cooldown 관리 (준호 제안: 중복 시그널 방지)
        self.cooldown_seconds = 180  # 3분
        
        # [Phase 6] 관측성 메트릭
        self.metrics = {
            'tick_count': 0,          # 수신한 틱 수
            'bar_count': 0,           # 완료된 캔들 수
            'signal_count': 0,        # 발행된 신호 수
            'cooldown_blocked': 0,    # Cooldown으로 차단된 수
            'watchlist_loads': 0,     # Watchlist 로드 횟수
            'last_tick_time': None,   # 마지막 틱 수신 시간
            'last_signal_time': None, # 마지막 신호 발행 시간
        }
        
    def load_hot_watchlist(self) -> bool:
        """
        Redis에서 Hot Watchlist 로드
        (준호 제안: 버저닝/스왑 패턴)
        """
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
        # 주기적 갱신
        if time.time() - self.last_watchlist_load > self.watchlist_refresh_interval:
            self.load_hot_watchlist()
        
        return list(self.hot_watchlist.keys())
    
    def on_price_update(self, stock_code: str, price: float, volume: int = 0) -> Optional[dict]:
        """
        실시간 가격 업데이트 수신
        
        Returns:
            매수 신호 발생 시 signal dict, 아니면 None
        """
        # 메트릭 업데이트
        self.metrics['tick_count'] += 1
        self.metrics['last_tick_time'] = datetime.now(timezone.utc).isoformat()
        
        # Hot Watchlist에 없는 종목은 무시
        if stock_code not in self.hot_watchlist:
            return None
        
        # 캔들 집계
        completed_bar = self.bar_aggregator.update(stock_code, price, volume)
        
        # 캔들이 완료되면 신호 체크 (준호 제안: 1분 캔들 확정 시에만)
        if completed_bar:
            self.metrics['bar_count'] += 1
            return self._check_buy_signal(stock_code, price, completed_bar)
        
        return None
    
    def _check_buy_signal(self, stock_code: str, current_price: float, 
                          completed_bar: dict) -> Optional[dict]:
        """
        매수 신호 체크 (1분 캔들 완료 시)
        
        간소화된 신호 로직:
        - 5분/20분 이동평균 골든크로스
        - RSI 30 이하
        """
        recent_bars = self.bar_aggregator.get_recent_bars(stock_code, count=25)
        
        if len(recent_bars) < 20:
            # 데이터 부족 - 20개 이상 캔들 필요
            return None
        
        # Cooldown 체크 (준호 제안: 중복 시그널 방지)
        if not self._check_cooldown(stock_code):
            logger.debug(f"[{stock_code}] Cooldown 중 - 신호 무시")
            return None
        
        # 이동평균 계산
        closes = [b['close'] for b in recent_bars]
        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20
        
        # 골든크로스 체크 (5MA > 20MA 상향 돌파)
        prev_ma5 = sum(closes[-6:-1]) / 5 if len(closes) >= 6 else ma5
        is_golden_cross = (prev_ma5 <= ma20) and (ma5 > ma20)
        
        # RSI 계산 (간소화)
        rsi = self._calculate_simple_rsi(closes, period=14)
        
        signal_type = None
        signal_reason = ""
        
        if is_golden_cross:
            signal_type = "GOLDEN_CROSS"
            signal_reason = f"5MA({ma5:.0f}) crossed above 20MA({ma20:.0f})"
            logger.info(f"🔔 [{stock_code}] 골든크로스 감지: {signal_reason}")
        elif rsi and rsi <= 30:
            signal_type = "RSI_OVERSOLD"
            signal_reason = f"RSI={rsi:.1f} (oversold)"
            logger.info(f"🔔 [{stock_code}] RSI 과매도 감지: {signal_reason}")
        
        if not signal_type:
            return None
        
        # Cooldown 설정
        self._set_cooldown(stock_code)
        
        # 매수 신호 발행
        stock_info = self.hot_watchlist.get(stock_code, {})
        signal = {
            'stock_code': stock_code,
            'stock_name': stock_info.get('name', stock_code),
            'signal_type': signal_type,
            'signal_reason': signal_reason,
            'current_price': current_price,
            'llm_score': stock_info.get('llm_score', 0),
            'market_regime': self.market_regime,
            'source': 'opportunity_watcher',
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
        
        return signal
    
    def _calculate_simple_rsi(self, prices: List[float], period: int = 14) -> Optional[float]:
        """간소화된 RSI 계산"""
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
        """
        Cooldown 체크 (준호 제안: Redis SETNX + TTL)
        
        Returns:
            True면 신호 발행 가능, False면 Cooldown 중
        """
        if not self.redis:
            return True  # Redis 없으면 항상 허용
        
        try:
            cooldown_key = f"buy_signal_cooldown:{stock_code}"
            if self.redis.exists(cooldown_key):
                self.metrics['cooldown_blocked'] += 1
                return False
            return True
        except Exception:
            return True
    
    def _set_cooldown(self, stock_code: str) -> None:
        """Cooldown 설정"""
        if not self.redis:
            return
        
        try:
            cooldown_key = f"buy_signal_cooldown:{stock_code}"
            self.redis.setex(cooldown_key, self.cooldown_seconds, "1")
            logger.debug(f"[{stock_code}] Cooldown 설정: {self.cooldown_seconds}초")
        except Exception as e:
            logger.warning(f"Cooldown 설정 실패: {e}")
    
    def publish_signal(self, signal: dict) -> bool:
        """
        매수 신호 RabbitMQ 발행
        """
        if not self.tasks_publisher:
            logger.warning("RabbitMQ Publisher 없음 - 신호 발행 불가")
            return False
        
        try:
            # Buy Executor가 기대하는 형식으로 변환
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
                'trade_tier': 'TIER1',  # Hot Watchlist는 이미 LLM Score 필터 통과
                'factor_score': 500.0,  # 기본값 (실시간이라 Factor 계산 생략)
            }
            
            payload = {
                'candidates': [candidate],
                'market_regime': signal['market_regime'],
                'scan_timestamp': signal['timestamp'],
                'source': 'opportunity_watcher',
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
        """
        관측성 메트릭 조회
        
        Returns:
            {
                'tick_count': int,
                'bar_count': int,
                'signal_count': int,
                'cooldown_blocked': int,
                'watchlist_loads': int,
                'last_tick_time': str or None,
                'last_signal_time': str or None,
                'hot_watchlist_size': int,
                'market_regime': str,
            }
        """
        return {
            **self.metrics,
            'hot_watchlist_size': len(self.hot_watchlist),
            'market_regime': getattr(self, 'market_regime', 'UNKNOWN'),
        }
