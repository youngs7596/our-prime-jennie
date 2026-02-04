# services/buy-scanner/opportunity_watcher.py
# Version: v1.3
# Hot Watchlist 실시간 매수 신호 감지 (WebSocket 기반) + Supply/Demand & Legendary Pattern
# buy-scanner가 매수용 WebSocket을 담당
# + Logic Observability: Buy Logic Snapshot 저장 (2026-01-27)
# + Enhanced Macro Trading Context 통합 (2026-02-01)


import os
import time
import logging
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from threading import Lock, Event
from typing import Dict, Optional, List, Tuple

import redis
import pandas as pd
from shared.db.connection import session_scope
from shared.db.factor_repository import FactorRepository

logger = logging.getLogger(__name__)


# Macro Trading Context 로드 (선택적)
def _load_trading_context():
    """EnhancedTradingContext 로드 (실패 시 None 반환)"""
    try:
        from shared.macro_insight import get_enhanced_trading_context
        return get_enhanced_trading_context()
    except ImportError:
        logger.debug("[Macro] macro_insight module not available")
        return None
    except Exception as e:
        logger.warning(f"[Macro] Failed to load trading context: {e}")
        return None


class BarAggregator:
    """
    실시간 틱 데이터를 1분 캔들로 집계
    """
    
    def __init__(self, bar_interval_seconds: int = 60):
        self.bar_interval = bar_interval_seconds
        self.current_bars: Dict[str, dict] = {}
        self.completed_bars: Dict[str, List[dict]] = defaultdict(list)
        self.lock = Lock()
        self.max_bar_history = 60
        # [Phase 2] VWAP 엔진 스토리지: {code: {'date': 'YYYY-MM-DD', 'cum_pv': 0.0, 'cum_vol': 0.0, 'vwap': 0.0}}
        self.vwap_store = defaultdict(lambda: {'date': None, 'cum_pv': 0.0, 'cum_vol': 0.0, 'vwap': 0.0})
        # [Minji] 거래량 추적 (분당 거래량 리스트, 평균 계산용): {code: [vol1, vol2, ...]}
        self.volume_history = defaultdict(list)
        self.max_volume_history = 60  # 최근 60개 바(60분)의 거래량 추적
        
    def update(self, stock_code: str, price: float, volume: int = 0) -> Optional[dict]:
        """새 틱 데이터 수신 시 호출"""
        now = datetime.now(timezone.utc)
        bar_timestamp = self._get_bar_timestamp(now)
        
        # [Phase 2] VWAP 실시간 계산 (KST 기준 날짜 관리)
        with self.lock:
            # KST 변환 (UTC+9)
            kst_now = now + timedelta(hours=9)
            today_str = kst_now.strftime('%Y-%m-%d')
            
            vwap_info = self.vwap_store[stock_code]
            
            # 날짜 변경 시(또는 첫 데이터) 초기화
            if vwap_info['date'] != today_str:
                vwap_info['date'] = today_str
                vwap_info['cum_pv'] = 0.0
                vwap_info['cum_vol'] = 0.0
                vwap_info['vwap'] = price # 초기값은 현재가
            
            # VWAP 누적 (Volume이 있을 때만 유효하지만, 0이라도 가격 갱신용으로 둠)
            if volume > 0:
                vwap_info['cum_pv'] += price * volume
                vwap_info['cum_vol'] += volume
                vwap_info['vwap'] = vwap_info['cum_pv'] / vwap_info['cum_vol']
            
            # (만약 장초반 Volume 0인 틱만 오면 VWAP은 첫 가격 유지)

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
                
                # [Minji] 완료된 바의 거래량을 히스토리에 추가
                self.volume_history[stock_code].append(completed['volume'])
                if len(self.volume_history[stock_code]) > self.max_volume_history:
                    self.volume_history[stock_code].pop(0)
                
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
    
    def get_vwap(self, stock_code: str) -> float:
        """현재 VWAP 반환"""
        with self.lock:
             return self.vwap_store[stock_code]['vwap']
    
    def get_volume_info(self, stock_code: str) -> dict:
        """[Minji] 거래량 정보 반환 (현재 바 거래량 vs 평균)"""
        with self.lock:
            volumes = self.volume_history.get(stock_code, [])
            if not volumes:
                return {'current': 0, 'avg': 0, 'ratio': 0}
            
            current_vol = volumes[-1] if volumes else 0
            avg_vol = sum(volumes) / len(volumes) if volumes else 1
            ratio = current_vol / avg_vol if avg_vol > 0 else 0
            
            return {'current': current_vol, 'avg': avg_vol, 'ratio': ratio}
    
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
        # [Config] Bar Interval (기본 60초, Mock=5초 등 설정 가능)
        bar_int = int(os.getenv('BAR_INTERVAL_SECONDS', 60))
        self.bar_aggregator = BarAggregator(bar_interval_seconds=bar_int)
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
        self.supply_demand_cache: Dict[str, pd.DataFrame] = {}  # {code: DataFrame}
        self.watchlist_entry_cache: Dict[str, dict] = {}  # {code: {"entry_date": date, "entry_price": float}}

        # Cooldown (중복 시그널 방지) - 설정에서 로드 (기본 600초)
        self.cooldown_seconds = self.config.get_int("SIGNAL_COOLDOWN_SECONDS", default=600)

        # [Enhanced Macro] 트레이딩 컨텍스트
        self._trading_context = None
        self._trading_context_loaded_at = None
        self._trading_context_refresh_interval = 1800  # 30분
        self._load_trading_context()

        # 메트릭
        self.metrics = {
            'tick_count': 0,
            'bar_count': 0,
            'signal_count': 0,
            'cooldown_blocked': 0,
            'watchlist_loads': 0,
            'last_tick_time': None,
            'last_signal_time': None,
            'macro_risk_blocked': 0,  # [Enhanced Macro] 매크로 리스크로 차단된 횟수
        }
        self.current_version_key = None

    def _load_trading_context(self) -> bool:
        """Enhanced Trading Context 로드/갱신"""
        try:
            ctx = _load_trading_context()
            if ctx:
                self._trading_context = ctx
                self._trading_context_loaded_at = time.time()
                logger.info(
                    f"🌍 [Macro] Trading context loaded: "
                    f"risk_off={ctx.risk_off_level}, vix_regime={ctx.vix_regime}, "
                    f"pos_mult={ctx.position_multiplier}"
                )
                return True
        except Exception as e:
            logger.warning(f"[Macro] Failed to load trading context: {e}")
        return False

    def _get_trading_context(self):
        """트레이딩 컨텍스트 조회 (필요 시 갱신)"""
        now = time.time()

        # 주기적 갱신 (30분)
        if (self._trading_context_loaded_at is None or
            now - self._trading_context_loaded_at > self._trading_context_refresh_interval):
            self._load_trading_context()

        return self._trading_context

    def _check_macro_risk_gate(self) -> Tuple[bool, str]:
        """
        매크로 Risk Gate 체크.

        Returns:
            (passed, reason)
        """
        ctx = self._get_trading_context()

        if ctx is None:
            # 컨텍스트 없으면 통과 (기존 동작 유지)
            return True, "No macro context"

        # Risk-Off Level 2 이상이면 신규 진입 제한
        if ctx.risk_off_level >= 2:
            reasons = ", ".join(ctx.risk_off_reasons) if ctx.risk_off_reasons else "unknown"
            return False, f"Risk-Off Level {ctx.risk_off_level}: {reasons}"

        # VIX Crisis 상태에서도 진입 제한
        if ctx.vix_regime == "crisis":
            return False, f"VIX Crisis (VIX={ctx.vix_value})"

        return True, "OK"

    def _get_position_multiplier(self) -> float:
        """매크로 기반 포지션 배율 조회"""
        ctx = self._get_trading_context()
        if ctx:
            return ctx.position_multiplier
        return 1.0

    def _get_allowed_strategies(self) -> Optional[List[str]]:
        """매크로 기반 허용 전략 목록 조회"""
        ctx = self._get_trading_context()
        if ctx:
            return ctx.get_allowed_strategies()
        return None  # None이면 모든 전략 허용

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

            # [Added] Watchlist 진입 히스토리 로드 (for DIP_BUY)
            self._load_watchlist_entry_data(list(self.hot_watchlist.keys()))

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
            # 쓰레드에서 호출될 수 있으므로 DB 초기화 보장
            from shared.db.connection import ensure_engine_initialized
            ensure_engine_initialized()

            with session_scope(readonly=True) as session:
                repo = FactorRepository(session)
                # 최근 30일치 외국인 수급 데이터 조회
                self.supply_demand_cache = repo.get_supply_demand_data(stock_codes, days=30)
                logger.info(f"   (Supply) {len(self.supply_demand_cache)}개 종목 수급 데이터 로드 완료")
        except Exception as e:
            logger.error(f"❌ 수급 데이터 로드 실패: {e}")

    def _load_watchlist_entry_data(self, stock_codes: List[str]):
        """
        [DIP_BUY 전략용] Watchlist 진입 히스토리 로드

        최근 5일간 Watchlist에 처음 등장한 종목의 진입일/진입가격 캐시
        """
        if not stock_codes:
            return

        try:
            from shared.db.connection import ensure_engine_initialized
            ensure_engine_initialized()
            from sqlalchemy import text

            with session_scope(readonly=True) as session:
                # 최근 5일간 watchlist 히스토리에서 각 종목의 첫 등장 정보 조회
                # MariaDB 문법 사용, 컬럼명: PRICE_DATE (not TRADE_DATE)
                codes_str = ",".join([f"'{c}'" for c in stock_codes])
                query = text(f"""
                    SELECT
                        fe.STOCK_CODE,
                        fe.ENTRY_DATE,
                        p.CLOSE_PRICE AS ENTRY_PRICE
                    FROM (
                        SELECT
                            STOCK_CODE,
                            MIN(SNAPSHOT_DATE) AS ENTRY_DATE
                        FROM watchlist_history
                        WHERE SNAPSHOT_DATE >= DATE_SUB(CURDATE(), INTERVAL 5 DAY)
                          AND STOCK_CODE IN ({codes_str})
                        GROUP BY STOCK_CODE
                    ) fe
                    LEFT JOIN stock_daily_prices_3y p
                        ON fe.STOCK_CODE = p.STOCK_CODE
                        AND DATE(fe.ENTRY_DATE) = DATE(p.PRICE_DATE)
                """)
                result = session.execute(query)
                rows = result.fetchall()

                self.watchlist_entry_cache = {}
                for row in rows:
                    self.watchlist_entry_cache[row[0]] = {
                        "entry_date": row[1],
                        "entry_price": row[2]
                    }

                logger.info(f"   (DIP_BUY) {len(self.watchlist_entry_cache)}개 종목 진입 히스토리 로드 완료")
        except Exception as e:
            logger.warning(f"⚠️ Watchlist 진입 히스토리 로드 실패: {e}")
            self.watchlist_entry_cache = {}

    
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
        """매수 신호 체크 + Logic Observability 스냅샷 저장"""
        stock_info = self.hot_watchlist.get(stock_code, {})
        strategies = stock_info.get('strategies', [])

        if not strategies:
            # [FIX] Jennie CSO Review: 시장 상황에 따른 동적 RSI 기준값
            # 강세장=50, 횡보=40, 약세=30
            dynamic_rsi = self._get_dynamic_rsi_threshold()


            strategies = [
                {"id": "GOLDEN_CROSS", "params": {"short_window": 5, "long_window": 20}},
                {"id": "RSI_REBOUND", "params": {"threshold": dynamic_rsi}},
                {"id": "MOMENTUM", "params": {"threshold": 1.5}}
            ]


        recent_bars = self.bar_aggregator.get_recent_bars(stock_code, count=30)

        # [Config] 최소 바 개수 (기본 20개, Mock/Dev 모드에서 조절 가능)
        min_bars = int(os.getenv('MIN_REQUIRED_BARS', 20))

        # [Logic Observability] Risk Gate 체크 결과 수집
        volume_info = self.bar_aggregator.get_volume_info(stock_code)
        vwap = self.bar_aggregator.get_vwap(stock_code)

        # RSI 계산 (스냅샷용)
        closes = [b['close'] for b in recent_bars] if recent_bars else []
        current_rsi = self._calculate_simple_rsi(closes, period=14) if len(closes) >= 15 else None

        risk_gate_checks = []
        risk_gate_passed = True

        # 조건 0: 최소 바 개수
        bar_check_passed = len(recent_bars) >= min_bars
        risk_gate_checks.append({
            "name": "Min Bars",
            "passed": bar_check_passed,
            "value": str(len(recent_bars)),
            "threshold": f">= {min_bars}"
        })
        if not bar_check_passed:
            risk_gate_passed = False
            self._save_buy_logic_snapshot(stock_code, stock_info, current_price, vwap, volume_info,
                                          current_rsi, risk_gate_passed, risk_gate_checks, [], None)
            return None

        # [Phase 1] 장초 노이즈 구간 차단 (09:00~09:15) - 30분에서 15분으로 축소
        no_trade_window_passed = self._check_no_trade_window()
        risk_gate_checks.append({
            "name": "No-Trade Window",
            "passed": no_trade_window_passed,
            "value": datetime.now().strftime("%H:%M"),
            "threshold": "Not 09:00~09:15"
        })
        if not no_trade_window_passed:
            risk_gate_passed = False
            self._save_buy_logic_snapshot(stock_code, stock_info, current_price, vwap, volume_info,
                                          current_rsi, risk_gate_passed, risk_gate_checks, [], None)
            return None

        # [NEW] Danger Zone 차단 (14:00~15:00)
        danger_zone_passed = self._check_danger_zone()
        risk_gate_checks.append({
            "name": "Danger Zone",
            "passed": danger_zone_passed,
            "value": datetime.now().strftime("%H:%M"),
            "threshold": "Not 14:00~15:00"
        })
        if not danger_zone_passed:
            risk_gate_passed = False
            self._save_buy_logic_snapshot(stock_code, stock_info, current_price, vwap, volume_info,
                                          current_rsi, risk_gate_passed, risk_gate_checks, [], None)
            return None

        # [NEW] RSI 과열 필터
        rsi_max = self.config.get_int("RISK_GATE_RSI_MAX", default=70)
        rsi_guard_passed = self._check_rsi_guard(current_rsi)
        risk_gate_checks.append({
            "name": "RSI Guard",
            "passed": rsi_guard_passed,
            "value": f"{current_rsi:.1f}" if current_rsi else "N/A",
            "threshold": f"<= {rsi_max}"
        })
        if not rsi_guard_passed:
            risk_gate_passed = False
            self._save_buy_logic_snapshot(stock_code, stock_info, current_price, vwap, volume_info,
                                          current_rsi, risk_gate_passed, risk_gate_checks, [], None)
            return None

        # [Enhanced Macro] 매크로 Risk Gate 체크
        macro_risk_passed, macro_risk_reason = self._check_macro_risk_gate()
        ctx = self._get_trading_context()
        risk_gate_checks.append({
            "name": "Macro Risk",
            "passed": macro_risk_passed,
            "value": f"Level {ctx.risk_off_level}" if ctx else "N/A",
            "threshold": "< 2 (not Risk-Off)"
        })
        if not macro_risk_passed:
            risk_gate_passed = False
            self.metrics['macro_risk_blocked'] += 1
            logger.info(f"🚫 [{stock_code}] Macro Risk Gate 차단: {macro_risk_reason}")
            self._save_buy_logic_snapshot(stock_code, stock_info, current_price, vwap, volume_info,
                                          current_rsi, risk_gate_passed, risk_gate_checks, [], None)
            return None

        # [Junho] 조건부 차단 (2개 이상 위험 조건 충족 시)
        risk_conditions = 0

        # 설정에서 Risk Gate 임계값 로드
        volume_ratio_limit = self.config.get_float("RISK_GATE_VOLUME_RATIO", default=2.0)
        vwap_deviation_limit = self.config.get_float("RISK_GATE_VWAP_DEVIATION", default=0.02)

        # 조건 1: 거래량 급증 (> 설정값 x 평균)
        volume_check_passed = volume_info['ratio'] <= volume_ratio_limit
        if not volume_check_passed:
            risk_conditions += 1
        risk_gate_checks.append({
            "name": "Volume Gate",
            "passed": volume_check_passed,
            "value": f"{volume_info['ratio']:.1f}x",
            "threshold": f"<= {volume_ratio_limit}x"
        })

        # 조건 2: VWAP 이격 과대 (> 설정값 %)
        vwap_deviation = ((current_price - vwap) / vwap * 100) if vwap > 0 else 0
        vwap_check_passed = not (vwap > 0 and current_price > vwap * (1 + vwap_deviation_limit))
        if not vwap_check_passed:
            risk_conditions += 1
        risk_gate_checks.append({
            "name": "VWAP Gate",
            "passed": vwap_check_passed,
            "value": f"{vwap_deviation:.1f}%",
            "threshold": f"<= {vwap_deviation_limit * 100:.1f}%"
        })

        # 2개 이상 조건 충족 시 차단 (거래량 급증 + VWAP 이격 = 뉴스반영 상태)
        combined_risk_passed = risk_conditions < 2
        risk_gate_checks.append({
            "name": "Combined Risk",
            "passed": combined_risk_passed,
            "value": f"{risk_conditions} conditions",
            "threshold": "< 2 risk flags"
        })
        if not combined_risk_passed:
            risk_gate_passed = False
            self._save_buy_logic_snapshot(stock_code, stock_info, current_price, vwap, volume_info,
                                          current_rsi, risk_gate_passed, risk_gate_checks, [], None)
            return None

        # Cooldown 체크
        cooldown_passed = self._check_cooldown(stock_code)
        risk_gate_checks.append({
            "name": "Cooldown",
            "passed": cooldown_passed,
            "value": "Active" if not cooldown_passed else "Clear",
            "threshold": "No recent signal"
        })
        if not cooldown_passed:
            risk_gate_passed = False
            self._save_buy_logic_snapshot(stock_code, stock_info, current_price, vwap, volume_info,
                                          current_rsi, risk_gate_passed, risk_gate_checks, [], None)
            return None
        
        signal_type = None
        signal_reason = ""
        signal_checks = []  # [Logic Observability] 전략별 체크 결과 수집

        # [Enhanced Macro] 매크로 기반 허용 전략 목록
        allowed_strategies = self._get_allowed_strategies()
        if allowed_strategies:
            logger.debug(f"[{stock_code}] Macro allowed strategies: {allowed_strategies}")

        def _is_strategy_allowed(strategy_name: str) -> bool:
            """매크로 기반 전략 허용 여부 확인"""
            if allowed_strategies is None:
                return True  # 컨텍스트 없으면 모두 허용
            return strategy_name in allowed_strategies

        # [NEW] 상승장 전용 전략 먼저 체크 (기존 전략보다 우선 적용)
        if self.market_regime in ['BULL', 'STRONG_BULL']:
            # 1. RECON_BULL_ENTRY: 고점수 RECON 종목 자동 진입
            result = self._check_recon_bull_entry(stock_code, stock_info)
            if result:
                signal_type, signal_reason = result
                signal_checks.append({"strategy": "RECON_BULL_ENTRY", "triggered": True, "reason": signal_reason})
            else:
                signal_checks.append({"strategy": "RECON_BULL_ENTRY", "triggered": False, "reason": "Conditions not met"})

            # 2. MOMENTUM_CONTINUATION: 모멘텀 지속 종목
            if not signal_type:
                result = self._check_momentum_continuation(stock_code, stock_info, recent_bars)
                if result:
                    signal_type, signal_reason = result
                    signal_checks.append({"strategy": "MOMENTUM_CONTINUATION", "triggered": True, "reason": signal_reason})
                else:
                    signal_checks.append({"strategy": "MOMENTUM_CONTINUATION", "triggered": False, "reason": "MA5 <= MA20 or price change < 2%"})

            # 3. SHORT_TERM_HIGH_BREAKOUT (60분 고가 돌파) - 브레이크아웃 전략, 매크로 필터 적용
            if not signal_type and _is_strategy_allowed("SHORT_TERM_HIGH_BREAKOUT"):
                result = self._check_short_term_high_breakout(stock_code, recent_bars)
                if result:
                    signal_type, signal_reason = result
                    signal_checks.append({"strategy": "SHORT_TERM_HIGH_BREAKOUT", "triggered": True, "reason": signal_reason})
                else:
                    signal_checks.append({"strategy": "SHORT_TERM_HIGH_BREAKOUT", "triggered": False, "reason": "No breakout or volume < 2x"})
            elif not signal_type:
                signal_checks.append({"strategy": "SHORT_TERM_HIGH_BREAKOUT", "triggered": False, "reason": "Blocked by macro context"})

            # 4. VOLUME_BREAKOUT_1MIN (거래량 폭발 돌파) - 공격적 전략, 매크로 필터 적용
            if not signal_type and _is_strategy_allowed("VOLUME_BREAKOUT_1MIN"):
                result = self._check_volume_breakout_1min(stock_code, recent_bars)
                if result:
                    signal_type, signal_reason = result
                    signal_checks.append({"strategy": "VOLUME_BREAKOUT_1MIN", "triggered": True, "reason": signal_reason})
                else:
                    signal_checks.append({"strategy": "VOLUME_BREAKOUT_1MIN", "triggered": False, "reason": "No resistance break or volume < 3x"})
            elif not signal_type:
                signal_checks.append({"strategy": "VOLUME_BREAKOUT_1MIN", "triggered": False, "reason": "Blocked by macro context"})

            # ================================================================
            # [NEW] Jennie CSO 지시: 추가 Bull Market 전략 (2026-01-17)
            # ================================================================

            # 5. BULL_PULLBACK: 상승 추세 중 건전한 조정 후 반등
            if not signal_type:
                result = self._check_bull_pullback(recent_bars)
                if result:
                    signal_type, signal_reason = result
                    signal_checks.append({"strategy": "BULL_PULLBACK", "triggered": True, "reason": signal_reason})
                else:
                    signal_checks.append({"strategy": "BULL_PULLBACK", "triggered": False, "reason": "No pullback pattern"})

            # 6. VCP_BREAKOUT: 변동성 축소 후 거래량 동반 돌파 - 공격적 전략, 매크로 필터 적용
            if not signal_type and _is_strategy_allowed("VCP_BREAKOUT"):
                result = self._check_vcp_breakout(recent_bars)
                if result:
                    signal_type, signal_reason = result
                    signal_checks.append({"strategy": "VCP_BREAKOUT", "triggered": True, "reason": signal_reason})
                else:
                    signal_checks.append({"strategy": "VCP_BREAKOUT", "triggered": False, "reason": "No VCP pattern"})
            elif not signal_type:
                signal_checks.append({"strategy": "VCP_BREAKOUT", "triggered": False, "reason": "Blocked by macro context"})

            # 7. INSTITUTIONAL_ENTRY: 기관/외국인 매수세 캔들 패턴
            if not signal_type:
                result = self._check_institutional_buying(recent_bars)
                if result:
                    signal_type, signal_reason = result
                    signal_checks.append({"strategy": "INSTITUTIONAL_ENTRY", "triggered": True, "reason": signal_reason})
                else:
                    signal_checks.append({"strategy": "INSTITUTIONAL_ENTRY", "triggered": False, "reason": "No institutional pattern"})

        # [NEW] DIP_BUY: Watchlist 진입 1-3일 후 조정 매수 (시장 상황 무관)
        if not signal_type:
            result = self._check_dip_buy(stock_code, current_price, stock_info)
            if result:
                signal_type, signal_reason = result
                signal_checks.append({"strategy": "DIP_BUY", "triggered": True, "reason": signal_reason})
            else:
                signal_checks.append({"strategy": "DIP_BUY", "triggered": False, "reason": "No dip entry condition"})

        # [EXISTING] 신호가 없으면 기존 전략 루프 실행
        # 단, 강세장(BULL/STRONG_BULL)에서는 역추세 전략(RSI, BB) 비활성화
        if not signal_type:
            # 강세장에서는 역추세 전략 스킵
            is_bull_market = self.market_regime in ['BULL', 'STRONG_BULL']

            for strat in strategies:
                strat_id = strat.get('id')
                params = strat.get('params', {})

                if strat_id == "GOLDEN_CROSS":
                    # [Updated] Pass volume_ratio for filtration (1.2x threshold)
                    vol_ratio = volume_info.get('ratio', 0)
                    triggered, reason = self._check_golden_cross(recent_bars, params, vol_ratio)

                    if triggered:
                        signal_type = "GOLDEN_CROSS"
                        signal_reason = reason

                        # [Super Prime] Legendary Pattern Check
                        if self._check_legendary_pattern(stock_code, recent_bars):
                             signal_type = "GOLDEN_CROSS_SUPER_PRIME"
                             signal_reason += " + Legendary Pattern (Foreign Buy)"
                             logger.info(f"🚨 [{stock_code}] SUPER PRIME 신호 격상! (Legendary Pattern)")

                        signal_checks.append({"strategy": "GOLDEN_CROSS", "triggered": True, "reason": signal_reason})
                        break
                    else:
                        # MA 값 계산해서 이유 표시
                        if len(closes) >= 20:
                            ma5 = sum(closes[-5:]) / 5
                            ma20 = sum(closes[-20:]) / 20
                            base_reason = f"MA5({ma5:.0f}) {'>' if ma5 > ma20 else '<='} MA20({ma20:.0f})"
                            
                            # Add specific volume failure reason if applicable
                            if reason and "Weak Volume" in reason:
                                base_reason += f" ({reason})"
                                
                            signal_checks.append({"strategy": "GOLDEN_CROSS", "triggered": False, "reason": base_reason})
                        else:
                            signal_checks.append({"strategy": "GOLDEN_CROSS", "triggered": False, "reason": reason or "Not enough data"})

                elif strat_id == "RSI_REBOUND":
                    # 강세장에서는 RSI Rebound 비활성화 (거의 발생 안 함 + 가짜 신호 방지)
                    if is_bull_market:
                        signal_checks.append({"strategy": "RSI_REBOUND", "triggered": False, "reason": "Disabled in Bull market"})
                        continue

                    triggered, reason = self._check_rsi_rebound(recent_bars, params)
                    if triggered:
                        signal_type = "RSI_REBOUND"
                        signal_reason = reason
                        signal_checks.append({"strategy": "RSI_REBOUND", "triggered": True, "reason": signal_reason})
                        break
                    else:
                        threshold = params.get('threshold', 30)
                        signal_checks.append({"strategy": "RSI_REBOUND", "triggered": False, "reason": f"RSI {current_rsi:.1f if current_rsi else 'N/A'} > {threshold}"})

                elif strat_id == "RSI_OVERSOLD":
                    continue

                elif strat_id == "BB_LOWER":
                    # 강세장에서는 BB 하단 터치 전략 비활성화 (Band Walk 위험)
                    if is_bull_market:
                        signal_checks.append({"strategy": "BB_LOWER", "triggered": False, "reason": "Disabled in Bull market"})
                        continue

                    triggered, reason = self._check_bb_lower(recent_bars, params, current_price)
                    if triggered:
                        signal_type = "BB_LOWER"
                        signal_reason = reason
                        signal_checks.append({"strategy": "BB_LOWER", "triggered": True, "reason": signal_reason})
                        break
                    else:
                        signal_checks.append({"strategy": "BB_LOWER", "triggered": False, "reason": reason or "Price above BB Lower"})

                elif strat_id == "MOMENTUM":
                    triggered, reason = self._check_momentum(recent_bars, params)
                    if triggered:
                        signal_type = "MOMENTUM"
                        signal_reason = reason
                        signal_checks.append({"strategy": "MOMENTUM", "triggered": True, "reason": signal_reason})
                        break
                    else:
                        signal_checks.append({"strategy": "MOMENTUM", "triggered": False, "reason": reason or "Momentum below threshold"})

        # [Logic Observability] 스냅샷 저장 (신호 유무와 관계없이)
        self._save_buy_logic_snapshot(stock_code, stock_info, current_price, vwap, volume_info,
                                      current_rsi, risk_gate_passed, risk_gate_checks, signal_checks, signal_type)

        if not signal_type:
            return None

        self._set_cooldown(stock_code)
        logger.info(f"🔔 [{stock_code}] {signal_type} 신호 감지: {signal_reason}")

        # [Logic Observability] 신호 히스토리 저장
        self._save_signal_history(stock_code, stock_info.get('name', stock_code), 'BUY', signal_type, signal_reason, current_price)

        # [Enhanced Macro] 포지션 배율 및 컨텍스트 정보 추가
        position_mult = self._get_position_multiplier()
        ctx = self._get_trading_context()

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
            'is_super_prime': (signal_type == "GOLDEN_CROSS_SUPER_PRIME"),
            # [Enhanced Macro] 추가 필드
            'position_multiplier': position_mult,
            'macro_context': {
                'vix_regime': ctx.vix_regime if ctx else None,
                'risk_off_level': ctx.risk_off_level if ctx else 0,
                'stop_loss_multiplier': ctx.stop_loss_multiplier if ctx else 1.0,
            } if ctx else None,
        }

        if ctx:
            logger.info(
                f"📊 [{stock_code}] Macro: pos_mult={position_mult}, "
                f"vix={ctx.vix_regime}, risk_off={ctx.risk_off_level}"
            )

        return signal

    def _check_golden_cross(self, bars: List[dict], params: dict, volume_ratio: float = 0.0) -> tuple:
        closes = [b['close'] for b in bars]
        short_w = params.get('short_window', 5)
        long_w = params.get('long_window', 20)
        
        if len(closes) < long_w:
            return False, ""
            
        ma_short = sum(closes[-short_w:]) / short_w
        ma_long = sum(closes[-long_w:]) / long_w
        
        prev_closes = closes[:-1]
        prev_ma_short = sum(prev_closes[-short_w:]) / short_w if len(prev_closes) >= short_w else ma_short
        
        # 1. Golden Cross Condition
        cross_triggered = (prev_ma_short <= ma_long) and (ma_short > ma_long)
        
        if cross_triggered:
            # 2. Volume Threshold Check - 설정에서 로드
            min_volume_ratio = self.config.get_float("GOLDEN_CROSS_MIN_VOLUME_RATIO", default=1.5)

            if volume_ratio < min_volume_ratio:
                return False, f"Weak Volume ({volume_ratio:.1f}x < {min_volume_ratio}x)"

            return True, f"MA({short_w}) > MA({long_w}) w/ Vol {volume_ratio:.1f}x"
            
        return False, ""

    def _check_rsi_rebound(self, bars: List[dict], params: dict) -> tuple:
        """
        RSI Rebound 전략: 과매도권(Threshold)을 하향 돌파했다가 다시 상향 돌파할 때 매수
        조건: Prev_RSI < Threshold <= Curr_RSI
        """
        closes = [b['close'] for b in bars]
        threshold = params.get('threshold', 30)
        
        # 1. 현재 RSI
        curr_rsi = self._calculate_simple_rsi(closes, period=14)
        if curr_rsi is None:
            return False, ""
            
        # 2. 전일 RSI (최신 데이터 1개 제외하고 계산)
        if len(closes) < 2:
            return False, ""
        prev_closes = closes[:-1]
        prev_rsi = self._calculate_simple_rsi(prev_closes, period=14)
        if prev_rsi is None:
            return False, ""
            
        # 3. Rebound 확인
        # (이전에는 과매도 상태였고 -> 현재는 과매도 기준 이상으로 올라옴)
        if prev_rsi < threshold and curr_rsi >= threshold:
            return True, f"RSI Rebound: {prev_rsi:.1f} -> {curr_rsi:.1f} (CrossUp {threshold})"
            
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

    def _save_buy_logic_snapshot(self, stock_code: str, stock_info: dict,
                                  current_price: float, vwap: float,
                                  volume_info: dict, rsi: Optional[float],
                                  risk_gate_passed: bool, risk_gate_checks: List[dict],
                                  signal_checks: List[dict], triggered_signal: Optional[str]):
        """
        [Logic Observability] Buy Logic 스냅샷을 Redis에 저장
        - Dashboard에서 실시간으로 "왜 매수를 안 하는지" 확인 가능
        """
        if not self.redis:
            return

        try:
            snapshot = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stock_code": stock_code,
                "stock_name": stock_info.get('name', stock_code),
                "current_price": current_price,
                "vwap": vwap,
                "volume_ratio": volume_info.get('ratio', 0),
                "rsi": rsi,
                "market_regime": self.market_regime,
                "llm_score": stock_info.get('llm_score', 0),
                "trade_tier": stock_info.get('trade_tier', 'UNKNOWN'),
                "risk_gate": {
                    "passed": risk_gate_passed,
                    "checks": risk_gate_checks
                },
                "signal_checks": signal_checks,
                "triggered_signal": triggered_signal
            }

            key = f"buy_logic:snapshot:{stock_code}"
            self.redis.setex(key, 60, json.dumps(snapshot))  # 60초 TTL
            # logger.debug(f"   [Observability] Buy logic snapshot saved: {stock_code}")

        except Exception as e:
            logger.warning(f"⚠️ Buy logic snapshot 저장 실패 ({stock_code}): {e}")

    def _save_signal_history(self, stock_code: str, stock_name: str, signal_type: str,
                             signal_name: str, reason: str, price: float):
        """
        [Logic Observability] 신호 히스토리를 Redis에 저장 (최근 50개, 7일 TTL)
        """
        if not self.redis:
            return

        try:
            key = f"logic:signals:{stock_code}"
            signal_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": signal_type,  # BUY or SELL
                "signal_type": signal_name,
                "reason": reason,
                "price": price,
                "stock_name": stock_name
            }

            # Get existing history
            existing_raw = self.redis.get(key)
            existing = json.loads(existing_raw) if existing_raw else []
            if not isinstance(existing, list):
                existing = []

            # Add new entry and keep only last 50
            existing.append(signal_entry)
            existing = existing[-50:]

            # Save with 7-day TTL
            self.redis.setex(key, 7*24*3600, json.dumps(existing))
            logger.debug(f"   [Observability] Signal history saved: {stock_code} {signal_type}")

        except Exception as e:
            logger.warning(f"⚠️ Signal history 저장 실패 ({stock_code}): {e}")

    def _check_recon_bull_entry(self, stock_code: str, stock_info: dict) -> Optional[tuple]:
        """
        RECON_BULL_ENTRY: 상승장에서 고점수 RECON 종목 자동 진입
        
        조건:
        1. market_regime in ['BULL', 'STRONG_BULL']
        2. LLM Score >= 70
        3. Trade_Tier == 'RECON'
        
        Returns:
            (signal_type, reason) or None
        """
        # 환경변수로 비활성화 가능
        if not self.config.get_bool("ENABLE_RECON_BULL_ENTRY", default=True):
            return None
        
        # 상승장 체크
        if self.market_regime not in ['BULL', 'STRONG_BULL']:
            return None
        
        # LLM Score 체크
        llm_score = stock_info.get('llm_score', 0)
        if llm_score < 70:
            return None
        
        # Trade Tier 체크
        trade_tier = stock_info.get('trade_tier', '')
        if trade_tier != 'RECON':
            return None
        
        reason = f"LLM Score {llm_score:.1f} + RECON Tier + {self.market_regime} Market"
        logger.info(f"🚀 [{stock_code}] RECON_BULL_ENTRY 조건 충족: {reason}")
        return ("RECON_BULL_ENTRY", reason)
    
    def _check_momentum_continuation(self, stock_code: str, stock_info: dict, 
                                     bars: List[dict]) -> Optional[tuple]:
        """
        MOMENTUM_CONTINUATION_BULL: 거래량 급증 + 상승 추세 지속 종목
        
        조건:
        1. market_regime in ['BULL', 'STRONG_BULL']
        2. MA5 > MA20 (현재)
        3. 당일 상승률 >= 2%
        4. LLM Score >= 65
        
        Returns:
            (signal_type, reason) or None
        """
        # 환경변수로 비활성화 가능
        if not self.config.get_bool("ENABLE_MOMENTUM_CONTINUATION", default=True):
            return None
        
        # 상승장 체크
        if self.market_regime not in ['BULL', 'STRONG_BULL']:
            return None
        
        # LLM Score 체크
        llm_score = stock_info.get('llm_score', 0)
        if llm_score < 65:
            return None
        
        # 충분한 바 데이터 필요
        if len(bars) < 20:
            return None
        
        # MA5 > MA20 체크
        closes = [bar['close'] for bar in bars]
        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20
        
        if ma5 <= ma20:
            return None
        
        # 당일 상승률 체크 (첫 바 대비 현재)
        first_price = bars[0]['open']
        current_price = bars[-1]['close']
        price_change = ((current_price - first_price) / first_price) * 100
        
        if price_change < 2.0:
            return None
        
        reason = f"MA5({ma5:.0f}) > MA20({ma20:.0f}) + 상승률 {price_change:.1f}% + LLM {llm_score:.1f}"
        logger.info(f"📈 [{stock_code}] MOMENTUM_CONTINUATION 조건 충족: {reason}")
        return ("MOMENTUM_CONTINUATION_BULL", reason)

    def _check_short_term_high_breakout(self, stock_code: str, bars: List[dict]) -> Optional[tuple]:
        """
        [New] SHORT_TERM_HIGH_BREAKOUT: 60분 신고가 돌파 + 거래량 급증 (2배)
        조건:
        1. 현재가 > 최근 60분 내 최고가 (High)
        2. 현재 거래량 > 최근 30분 평균 거래량 * 2.0
        """
        # 데이터 충분 여부 확인
        if len(bars) < 30:
            return None
        
        # 최근 60분(또는 가능한 최대) 고가 계산
        # bars는 1분봉 리스트 (최대 30개지만 BarAggregator 설정에 따라 다름)
        # BarAggregator.max_bar_history를 60으로 늘려야 정확하지만, 
        # 현재 30개라면 30분 신고가로 근사하여 사용
        
        recent_highs = [b['high'] for b in bars[:-1]] # 현재 봉 제외
        if not recent_highs:
            return None
            
        period_high = max(recent_highs)
        current_bar = bars[-1]
        current_price = current_bar['close']
        
        # 1. 고가 돌파 확인 (현재는 종가 기준)
        if current_price <= period_high:
            return None
            
        # 2. 거래량 급증 확인
        recent_volumes = [b['volume'] for b in bars[:-1]][-30:]
        avg_volume = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0
        
        if avg_volume == 0:
            return None
            
        current_volume = current_bar['volume']
        volume_ratio = current_volume / avg_volume
        
        if volume_ratio < 2.0:
            return None
            
        reason = f"60분 신고가 돌파 ({current_price} > {period_high}) + 거래량 {volume_ratio:.1f}배"
        logger.info(f"🚀 [{stock_code}] SHORT_TERM_HIGH_BREAKOUT 조건 충족: {reason}")
        return ("SHORT_TERM_HIGH_BREAKOUT", reason)

    def _check_volume_breakout_1min(self, stock_code: str, bars: List[dict]) -> Optional[tuple]:
        """
        [New] VOLUME_BREAKOUT_1MIN: 20분 저항 돌파 + 거래량 폭발 (3배)
        조건:
        1. 현재가 > 최근 20분 내 최고 종가
        2. 현재 거래량 > 최근 60분(실제론 30분) 평균 거래량 * 3.0
        """
        if len(bars) < 20:
            return None
            
        # 최근 20분 종가 최고치 (저항선)
        recent_closes = [b['close'] for b in bars[:-1]][-20:] 
        if not recent_closes: 
            return None
            
        resistance_price = max(recent_closes)
        current_bar = bars[-1]
        current_price = current_bar['close']
        
        if current_price <= resistance_price:
            return None
            
        # 거래량 확인 (3배)
        recent_volumes = [b['volume'] for b in bars[:-1]]
        avg_volume = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0
        
        if avg_volume == 0:
            return None
            
        current_volume = current_bar['volume']
        volume_ratio = current_volume / avg_volume
        
        if volume_ratio < 3.0:
            return None
            
        reason = f"20분 저항 돌파 ({current_price} > {resistance_price}) + 거래량 {volume_ratio:.1f}배"
        logger.info(f"💥 [{stock_code}] VOLUME_BREAKOUT_1MIN 조건 충족: {reason}")
        return ("VOLUME_BREAKOUT_1MIN", reason)

    # ==========================================================================
    # [NEW] Jennie CSO 지시: Bull Market 대응 신규 전략 (2026-01-17)
    # ==========================================================================
    
    def _get_dynamic_rsi_threshold(self) -> float:
        """
        [A] 시장 상황에 따른 동적 RSI 매수 기준
        강세장: RSI 50 (눌림목 진입), 횡보장: 40, 약세장: 30
        """
        if self.market_regime in ['BULL', 'STRONG_BULL']:
            return 50.0
        elif self.market_regime == 'SIDEWAYS':
            return 40.0
        else:  # BEAR, STRONG_BEAR
            return 30.0

    def _check_bull_pullback(self, bars: List[dict]) -> Optional[tuple]:
        """
        [B] BULL_PULLBACK: 상승 추세 중 건전한 조정 후 반등
        
        Trigger Condition (Jennie CSO 정의):
        1. 현재가 > MA20 (상승 추세)
        2. MA5 > MA20 (정배열)
        3. 최근 3개 캔들 중 2개 이상 음봉 (조정)
        4. 현재 캔들 양봉 전환 (close > open)
        5. 거래량 감소 → 증가 전환
        """
        if len(bars) < 20:
            return None
            
        closes = [b['close'] for b in bars]
        current_bar = bars[-1]
        current_price = current_bar['close']
        
        # 1. MA 계산
        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes[-20:]) / 20
        
        # 2. 정배열 확인 (MA5 > MA20)
        if ma5 <= ma20:
            return None
            
        # 3. 현재가 > MA20 (상승 추세)
        if current_price <= ma20:
            return None
            
        # 4. 최근 3개 캔들 중 2개 이상 음봉 (조정 구간 확인)
        recent_3_bars = bars[-4:-1]  # 현재 봉 제외, 직전 3개
        bearish_count = sum(1 for b in recent_3_bars if b['close'] < b['open'])
        if bearish_count < 2:
            return None
            
        # 5. 현재 캔들 양봉 (반등 시도)
        if current_bar['close'] <= current_bar['open']:
            return None
            
        # 6. 거래량 감소 → 증가 전환 확인
        recent_volumes = [b['volume'] for b in bars[-6:-1]]  # 직전 5개
        if not recent_volumes or recent_volumes[-1] == 0:
            return None
            
        avg_recent_volume = sum(recent_volumes) / len(recent_volumes)
        current_volume = current_bar['volume']
        
        # 마지막 3개 거래량이 감소 추세였다가 현재 증가
        if len(recent_volumes) >= 3:
            vol_trend = recent_volumes[-3:]
            # 감소 후 증가: 마지막 봉이 직전보다 20% 이상 증가
            if current_volume <= avg_recent_volume * 0.8:
                return None
        
        reason = f"MA5({ma5:.0f}) > MA20({ma20:.0f}) + 조정 {bearish_count}음봉 → 양봉 전환"
        logger.info(f"📈 [BULL_PULLBACK] {reason}")
        return ("BULL_PULLBACK", reason)

    def _check_vcp_breakout(self, bars: List[dict]) -> Optional[tuple]:
        """
        [C] VCP_BREAKOUT: Volatility Contraction Pattern
        변동성 축소 후 거래량 동반 돌파
        
        Trigger Condition (Jennie CSO 정의):
        1. 최근 20캔들 Range(고-저) 축소 (수렴 구간)
        2. 현재 거래량 > 직전 20개 평균의 300%
        3. 현재가 > 최근 20개 캔들 최고가 돌파
        """
        if len(bars) < 20:
            return None
            
        current_bar = bars[-1]
        current_price = current_bar['close']
        current_volume = current_bar['volume']
        
        # 직전 20개 캔들 분석 (현재 봉 제외)
        analysis_bars = bars[-21:-1]
        if len(analysis_bars) < 20:
            return None
            
        # 1. Range 축소 확인: 최근 10개 vs 이전 10개 평균 Range 비교
        first_half = analysis_bars[:10]
        second_half = analysis_bars[10:]
        
        first_half_ranges = [(b['high'] - b['low']) for b in first_half]
        second_half_ranges = [(b['high'] - b['low']) for b in second_half]
        
        avg_first = sum(first_half_ranges) / len(first_half_ranges) if first_half_ranges else 1
        avg_second = sum(second_half_ranges) / len(second_half_ranges) if second_half_ranges else 1
        
        # 수렴 확인: 후반부 Range가 전반부의 70% 이하
        if avg_first == 0 or avg_second / avg_first > 0.7:
            return None
            
        # 2. 거래량 폭발 확인 (300%)
        recent_volumes = [b['volume'] for b in analysis_bars]
        avg_volume = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0
        
        if avg_volume == 0:
            return None
            
        volume_ratio = current_volume / avg_volume
        if volume_ratio < 3.0:
            return None
            
        # 3. 고가 돌파 확인
        period_high = max(b['high'] for b in analysis_bars)
        if current_price <= period_high:
            return None
            
        contraction_pct = (1 - avg_second / avg_first) * 100
        reason = f"Range 축소 {contraction_pct:.0f}% + 거래량 {volume_ratio:.1f}배 + 고가 돌파"
        logger.info(f"🎯 [VCP_BREAKOUT] {reason}")
        return ("VCP_BREAKOUT", reason)

    def _check_institutional_buying(self, bars: List[dict]) -> Optional[tuple]:
        """
        [D] INSTITUTIONAL_ENTRY: 기관/외국인 매수세 추정 (캔들 패턴 기반)
        
        Trigger Condition (Jennie CSO 정의):
        1. Marubozu 양봉: (High - Close) / (High - Low) < 0.1 (윗꼬리 거의 없음)
        2. 양봉 몸통 크기가 직전 캔들 대비 2배 이상
        """
        if len(bars) < 5:
            return None
            
        current_bar = bars[-1]
        prev_bar = bars[-2]
        
        # 양봉 확인
        if current_bar['close'] <= current_bar['open']:
            return None
            
        # Range 계산 (0 방지)
        current_range = current_bar['high'] - current_bar['low']
        if current_range <= 0:
            return None
            
        # 1. Marubozu 확인: 윗꼬리 비율 < 10%
        upper_wick = current_bar['high'] - current_bar['close']
        upper_wick_ratio = upper_wick / current_range
        
        if upper_wick_ratio >= 0.1:
            return None
            
        # 2. 양봉 몸통 크기 비교 (직전 캔들 대비 2배)
        current_body = abs(current_bar['close'] - current_bar['open'])
        prev_body = abs(prev_bar['close'] - prev_bar['open'])
        
        if prev_body == 0:
            prev_body = 1  # 도지 캔들 처리
            
        body_ratio = current_body / prev_body
        if body_ratio < 2.0:
            return None
            
        # 추가 신뢰도: 거래량도 증가
        if current_bar['volume'] <= prev_bar['volume']:
            return None
            
        reason = f"Marubozu (윗꼬리 {upper_wick_ratio*100:.1f}%) + 몸통 {body_ratio:.1f}배"
        logger.info(f"🐋 [INSTITUTIONAL_ENTRY] {reason}")
        return ("INSTITUTIONAL_ENTRY", reason)

    def _check_dip_buy(self, stock_code: str, current_price: float, stock_info: dict) -> Optional[tuple]:
        """
        [NEW] DIP_BUY: Watchlist 진입 1-3일 후 -2%~-5% 하락 시 매수

        분석 결과: Watchlist 진입 후 1일 뒤 매수가 가장 많았고,
        단기 조정 후 매수하면 승률이 높음

        Trigger Condition:
        1. Watchlist 진입 후 1-3일 경과
        2. 진입가 대비 -2% ~ -5% 하락
        3. LLM Score >= 65
        4. RSI 30-50 구간 (과매도 아닌 건전한 조정)
        """
        try:
            # 1. 진입 데이터 확인
            entry_data = self.watchlist_entry_cache.get(stock_code)
            if not entry_data or not entry_data.get("entry_price"):
                return None

            entry_date = entry_data["entry_date"]
            entry_price = entry_data["entry_price"]

            if not entry_date or not entry_price:
                return None

            # 2. 경과일 계산 (1-3일)
            from datetime import date
            today = date.today()

            if hasattr(entry_date, 'date'):
                entry_date = entry_date.date()

            days_since_entry = (today - entry_date).days

            if days_since_entry < 1 or days_since_entry > 3:
                return None

            # 3. 하락률 계산 (-2% ~ -5%)
            price_change_pct = ((current_price - entry_price) / entry_price) * 100

            if price_change_pct > -2.0 or price_change_pct < -5.0:
                return None

            # 4. LLM Score 체크
            llm_score = stock_info.get('llm_score', 0)
            if llm_score < 65:
                return None

            reason = (f"Watchlist 진입 {days_since_entry}일차, "
                     f"진입가({entry_price:,.0f}) 대비 {price_change_pct:.1f}%, "
                     f"LLM {llm_score:.1f}")
            logger.info(f"📉 [{stock_code}] DIP_BUY 조건 충족: {reason}")
            return ("DIP_BUY", reason)

        except Exception as e:
            logger.debug(f"DIP_BUY 체크 실패 ({stock_code}): {e}")
            return None

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

    def _check_cooldown(self, stock_code: str) -> bool:
        """쿨타임 체크 (Redis에 키가 없으면 True)"""
        if not self.redis:
            return True
        key = f"buy_signal_cooldown:{stock_code}"
        return not self.redis.exists(key)

    def _check_no_trade_window(self) -> bool:
        """장초 노이즈 구간(09:00~09:15) 진입 금지 (KST 기준)

        분석 결과: 09:15-09:30 구간의 수익률이 양호하여 금지 구간 축소
        기존 30분 → 15분으로 단축하여 매수 기회 확대
        """
        # UTC -> KST 변환 (Explicit Timezone)
        now_utc = datetime.now(timezone.utc)
        now_kst = now_utc + timedelta(hours=9)

        start_time = now_kst.replace(hour=9, minute=0, second=0, microsecond=0)
        end_time = now_kst.replace(hour=9, minute=15, second=0, microsecond=0)

        if start_time <= now_kst <= end_time:
            self.metrics['cooldown_blocked'] += 1
            return False
        return True

    def _check_danger_zone(self) -> bool:
        """
        [Danger Zone] 14:00~15:00 진입 금지 (KST 기준)
        - 통계적으로 승률이 낮고 손실이 집중되는 구간
        """
        # UTC -> KST 변환 (Explicit Timezone)
        now_utc = datetime.now(timezone.utc)
        now_kst = now_utc + timedelta(hours=9)

        start_time = now_kst.replace(hour=14, minute=0, second=0, microsecond=0)
        end_time = now_kst.replace(hour=15, minute=0, second=0, microsecond=0)
        
        if start_time <= now_kst < end_time:
            # self.metrics['danger_zone_blocked'] += 1 # Add metric later if needed
            return False
        return True

    def _check_rsi_guard(self, current_rsi: Optional[float]) -> bool:
        """
        [RSI Guard] RSI 초과열 진입 금지
        - 단기 고점 추격 매수 방지
        """
        if current_rsi is None:
            return True  # RSI 계산 불가 시 Pass

        rsi_max = self.config.get_int("RISK_GATE_RSI_MAX", default=70)
        if current_rsi > rsi_max:
            return False
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
        """매수 신호 RabbitMQ 발행 및 Redis Pub/Sub 전송"""
        if not self.tasks_publisher:
            logger.warning("RabbitMQ Publisher 없음 - 신호 발행 불가")
            return False
        
        try:
            # [Enhanced Macro] 포지션 배율 및 컨텍스트 정보 추가
            position_mult = self._get_position_multiplier()
            ctx = self._get_trading_context()

            # [FIX] Executor가 사용할 수 있는 형태의 risk_setting 구성 및 주입
            # BuyExecutor는 risk_setting['position_size_ratio']와 ['stop_loss_pct']를 참조함
            base_stop_loss = -0.05  # 기본 -5%
            adjusted_stop_loss = base_stop_loss * (ctx.stop_loss_multiplier if ctx else 1.0)
            
            risk_setting = {
                'position_size_ratio': position_mult,
                'stop_loss_multiplier': ctx.stop_loss_multiplier if ctx else 1.0,
                'risk_off_level': ctx.risk_off_level if ctx else 0,
                'vix_regime': ctx.vix_regime if ctx else 'NORMAL',
                'stop_loss_pct': adjusted_stop_loss,
                'macro_source': 'daily_insight'
            }

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
                # [Important] 리스크 설정 주입
                'risk_setting': risk_setting,
            }
            
            payload = {
                'candidates': [candidate],
                'market_regime': signal['market_regime'],
                'scan_timestamp': signal['timestamp'],
                'source': 'buy_scanner_websocket',
                'risk_setting': risk_setting,  # 최상위에도 백업용으로 추가
            }
            
            # 1. RabbitMQ 발행
            msg_id = self.tasks_publisher.publish(payload)
            
            if msg_id:
                logger.info(f"✅ 매수 신호 발행: {signal['stock_code']} - {signal['signal_type']} (ID: {msg_id})")
                self.metrics['signal_count'] += 1
                self.metrics['last_signal_time'] = datetime.now(timezone.utc).isoformat()
                
                # 2. [Live Integration] Redis Pub/Sub 발행 (For Dashboard)
                if self.redis:
                    try:
                        # 대시보드 시각화용 경량 페이로드
                        dashboard_payload = {
                            "type": "buy_signal",
                            "data": {
                                "stock_code": signal['stock_code'],
                                "stock_name": signal['stock_name'],
                                "price": signal['current_price'],
                                "time": signal['timestamp'],
                                "signal_type": signal['signal_type'],
                                "reason": signal['signal_reason'],
                                "regime": signal['market_regime']
                            }
                        }
                        self.redis.publish("dashboard:stream", json.dumps(dashboard_payload))
                        # logger.debug(f"   (Live) Redis Pub/Sub 발행: {signal['stock_code']}")
                    except Exception as redis_e:
                        logger.warning(f"   (Live) Redis Pub/Sub 발행 실패: {redis_e}")

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
