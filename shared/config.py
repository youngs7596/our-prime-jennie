
"""
shared/config.py - Carbon Silicons Council 설정 관리 모듈
=============================================

이 모듈은 중앙화된 설정 관리를 담당합니다.

설정값 우선순위:
--------------
1. 메모리 캐시 (런타임 변경값)
2. DB CONFIG 테이블 (동적 설정)
3. 환경 변수
4. 기본값 (하드코딩)

주요 설정 카테고리:
-----------------
1. 매수 관련: RSI 기준, 볼린저밴드, 골든크로스 등
2. 매도 관련: 익절/손절 비율, RSI 과매수 구간
3. 포지션 관리: 최대 보유 종목, 섹터/종목별 비중 제한
4. 시장 국면: Bull/Bear/Sideways별 전략 파라미터

사용 예시:
---------
>>> from shared.config import ConfigManager
>>>
>>> config = ConfigManager()
>>> scan_interval = config.get('SCAN_INTERVAL_SEC', default=600)
>>> rsi_threshold = config.get('BUY_RSI_OVERSOLD_THRESHOLD', default=30)

주요 설정 키:
-----------
- SCAN_INTERVAL_SEC: 스캔 간격 (초)
- BUY_RSI_OVERSOLD_THRESHOLD: 과매도 RSI 기준 (기본: 30)
- MAX_HOLDING_STOCKS: 최대 보유 종목 수
- PROFIT_TARGET_FULL: 전량 익절 목표 (%)
- SELL_STOP_LOSS_PCT: 손절 기준 (%)
- MAX_SECTOR_PCT: 섹터별 최대 비중 (%)
- MAX_STOCK_PCT: 종목별 최대 비중 (%)
"""

import os
import logging
from typing import Any, Optional, Dict
from functools import lru_cache

from .db.connection import session_scope

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    중앙화된 설정 관리 클래스
    
    설정값 우선순위:
    1. 메모리 캐시 (런타임 변경값)
    2. DB CONFIG 테이블 (동적 설정)
    3. 환경 변수
    4. 기본값 (하드코딩)
    
    사용 예시:
        config = ConfigManager(db_conn=connection)
        scan_interval = config.get('SCAN_INTERVAL_SEC', default=600)
        daily_limit = config.get('DAILY_BUY_LIMIT_AMOUNT', default=10000000)
    """
    
    def __init__(self, db_conn=None, cache_ttl: int = 300):
        """
        Args:
            db_conn: DB 연결 (더 이상 사용되지 않음, 하위 호환성을 위해 유지)
            cache_ttl: 캐시 TTL (초, 기본값 5분)
        
        Note:
            db_conn 파라미터는 하위 호환성을 위해 유지되지만 실제로는 사용되지 않습니다.
            ConfigManager는 연결 풀을 직접 사용하여 DB에 접근합니다.
        """
        # db_conn은 더 이상 사용하지 않음 (연결 풀을 직접 사용)
        self.db_conn = None
        self.cache_ttl = cache_ttl
        self._memory_cache: Dict[str, tuple] = {}  # {key: (value, timestamp)}
        self._db_cache: Dict[str, tuple] = {}  # {key: (value, timestamp)}
        
        # 기본값 정의 (AgentConfig에서 가져온 값들)
        # 딕셔너리 구조 변경: 값 -> {"value": 값, "desc": "설명", "category": "카테고리"}
        # 하위 호환성을 위해 get() 메서드에서 처리 로직 추가 필요
        self._defaults = {
            # 매수 관련 (Buying)
            'SCAN_INTERVAL_SEC': {
                "value": 600,
                "desc": "종목 스캔 및 분석 주기 (초 단위)",
                "category": "Buying"
            },
            'MARKET_INDEX_MA_PERIOD': {
                "value": 20,
                "desc": "시장 지수 이동평균 산출 기간 (일)",
                "category": "Buying"
            },
            'BUY_BOLLINGER_PERIOD': {
                "value": 20,
                "desc": "볼린저 밴드 계산 기간",
                "category": "Buying"
            },
            'BUY_RSI_OVERSOLD_THRESHOLD': {
                "value": 30,
                "desc": "매수 시그널 발생을 위한 RSI 과매도 기준값",
                "category": "Buying"
            },
            'BUY_GOLDEN_CROSS_SHORT': {
                "value": 5,
                "desc": "골든크로스 판단용 단기 이동평균일",
                "category": "Buying"
            },
            'BUY_GOLDEN_CROSS_LONG': {
                "value": 20,
                "desc": "골든크로스 판단용 장기 이동평균일",
                "category": "Buying"
            },
            'MAX_HOLDING_STOCKS': {
                "value": 50,
                "desc": "포트폴리오 최대 보유 종목 수",
                "category": "Risk"
            },
            'DEFAULT_DAILY_BUY_LIMIT_AMOUNT': {
                "value": 10000000,
                "desc": "일일 최대 매수 한도 금액 (원)",
                "category": "Risk"
            },
            'BUY_QUANTITY_PER_TRADE': {
                "value": 1,
                "desc": "1회 주문 시 기본 매수 수량",
                "category": "Buying"
            },
            'ALLOW_BEAR_TRADING': {
                "value": False,
                "desc": "하락장(Bear Market) 매매 허용 여부",
                "category": "Strategy"
            },
            'MIN_LLM_CONFIDENCE_BEAR': {
                "value": 85,
                "desc": "하락장 진입을 위한 최소 LLM 확신도",
                "category": "Strategy"
            },
            
            # 매도 관련 (Selling)
            'ATR_PERIOD': {
                "value": 14,
                "desc": "ATR(평균진폭범위) 계산 기간",
                "category": "Selling"
            },
            'ATR_MULTIPLIER_INITIAL_STOP': {
                "value": 2.0,
                "desc": "초기 손절가 설정을 위한 ATR 승수",
                "category": "Selling"
            },
            'ATR_MULTIPLIER_TRAILING_STOP': {
                "value": 1.5,
                "desc": "트레일링 스탑을 위한 ATR 승수",
                "category": "Selling"
            },
            'SELL_RSI_THRESHOLD': {
                "value": 70,
                "desc": "매도 검토를 시작하는 RSI 기준값",
                "category": "Selling"
            },
            'PROFIT_TARGET_FULL': {
                "value": 8.0,
                "desc": "전량 익절 목표 수익률 (%)",
                "category": "Selling"
            },
            'SELL_STOP_LOSS_PCT': {
                "value": 5.0, # 누락된 키 복구
                "desc": "기본 손절매 기준 (%)",
                "category": "Buying"
            },
            'TIME_BASED_BULL': {
                "value": 20,
                "desc": "상승장에서의 최대 보유 기간 (거래일)",
                "category": "Selling"
            },
            'TIME_BASED_SIDEWAYS': {
                "value": 35,
                "desc": "횡보장에서의 최대 보유 기간 (거래일)",
                "category": "Selling"
            },
            
            # 포지션/리스크 (Risk)
            'MAX_POSITION_PCT': {
                "value": 15,
                "desc": "단일 종목 최대 비중 (%) (백테스트용)",
                "category": "Risk"
            },
            'MAX_POSITION_VALUE_PCT': {
                "value": 15.0,
                "desc": "단일 종목 최대 평가금액 비중 (%)",
                "category": "Risk"
            },
            'CASH_KEEP_PCT': {
                "value": 10,
                "desc": "최소 현금 보유 비중 (%)",
                "category": "Risk"
            },
            'RISK_PER_TRADE_PCT': {
                "value": 2.0,
                "desc": "트레이드 당 리스크 허용치 (%)",
                "category": "Risk"
            },
        }
    
    def get(self, key: str, default: Any = None, use_cache: bool = True) -> Any:
        """
        설정값 조회 (우선순위: 메모리 캐시 > DB > 환경 변수 > 기본값)
        
        Args:
            key: 설정 키
            default: 기본값 (없으면 _defaults에서 조회)
            use_cache: 캐시 사용 여부
        
        Returns:
            설정값 (타입 자동 변환 시도)
        """
        import time
        current_time = time.time()
        
        # 1. 메모리 캐시 확인
        if use_cache and key in self._memory_cache:
            value, timestamp = self._memory_cache[key]
            if current_time - timestamp < self.cache_ttl:
                logger.debug(f"[Config] 메모리 캐시에서 '{key}' 조회: {value}")
                return value
        
        # 2. DB CONFIG 테이블 확인
        # 컨텍스트 매니저가 Pool 또는 Stateless 연결을 자동으로 처리
        try:
            # DB 캐시 확인
            if use_cache and key in self._db_cache:
                value, timestamp = self._db_cache[key]
                if current_time - timestamp < self.cache_ttl:
                    logger.debug(f"[Config] DB 캐시에서 '{key}' 조회: {value}")
                    return value
            
            # DB 조회 (Pool 또는 Stateless 모드 자동 처리)
            from . import database
            with session_scope(readonly=True) as session:
                db_value = database.get_config(session, key, silent=True)
                if db_value is not None:
                    # DB 캐시 업데이트
                    self._db_cache[key] = (db_value, current_time)
                    logger.debug(f"[Config] DB에서 '{key}' 조회: {db_value}")
                    return self._convert_type(key, db_value)
        except Exception as e:
            logger.warning(f"[Config] DB에서 '{key}' 조회 실패 (환경변수/기본값으로 대체): {e}")
        
        # 3. 환경 변수 확인
        env_value = os.getenv(key)
        if env_value is not None:
            logger.debug(f"[Config] 환경 변수에서 '{key}' 조회: {env_value}")
            return self._convert_type(key, env_value)
        
        # 4. 기본값 반환
        if default is not None:
            logger.debug(f"[Config] 기본값 사용 '{key}': {default}")
            return default
        
        if key in self._defaults:
            default_entry = self._defaults[key]
            # 딕셔너리 구조(값+설명)인 경우 값만 추출
            if isinstance(default_entry, dict) and "value" in default_entry:
                default_value = default_entry["value"]
            else:
                default_value = default_entry
                
            # 초기화 시에는 INFO 레벨로 로그 (설정값이 제대로 적용되는지 확인)
            logger.info(f"[Config] 내장 기본값 사용 '{key}': {default_value}")
            return default_value
        
        logger.warning(f"[Config] 설정값 '{key}'를 찾을 수 없습니다. None 반환.")
        return None
    
    def set(self, key: str, value: Any, persist_to_db: bool = False) -> bool:
        """
        설정값 설정 (메모리 캐시에 저장, 선택적으로 DB에도 저장)
        
        Args:
            key: 설정 키
            value: 설정값
            persist_to_db: DB에도 저장할지 여부
        
        Returns:
            성공 여부
        """
        import time
        current_time = time.time()
        
        # 메모리 캐시 업데이트
        self._memory_cache[key] = (value, current_time)
        logger.info(f"[Config] 메모리 캐시에 '{key}' 설정: {value}")
        
        # DB에도 저장 (컨텍스트 매니저가 자동으로 Pool/Stateless 처리)
        if persist_to_db:
            try:
                from . import database
                with session_scope() as session:
                    database.set_config(session, key, str(value))
                # DB 캐시도 업데이트
                self._db_cache[key] = (str(value), current_time)
                logger.info(f"[Config] DB에도 '{key}' 저장: {value}")
                return True
            except Exception as e:
                logger.error(f"[Config] DB에 '{key}' 저장 실패: {e}")
                return False
        
        return True
    
    def get_int(self, key: str, default: int = None) -> int:
        """정수형 설정값 조회"""
        value = self.get(key, default=default)
        if value is None:
            return default if default is not None else 0
        try:
            return int(value)
        except (ValueError, TypeError):
            logger.warning(f"[Config] '{key}'를 정수로 변환 실패: {value}, 기본값 사용")
            return default if default is not None else 0
    
    def get_float(self, key: str, default: float = None) -> float:
        """실수형 설정값 조회"""
        value = self.get(key, default=default)
        if value is None:
            return default if default is not None else 0.0
        try:
            return float(value)
        except (ValueError, TypeError):
            logger.warning(f"[Config] '{key}'를 실수로 변환 실패: {value}, 기본값 사용")
            return default if default is not None else 0.0
    
    def get_bool(self, key: str, default: bool = None) -> bool:
        """불린형 설정값 조회"""
        value = self.get(key, default=default)
        if value is None:
            return default if default is not None else False
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on')
        return bool(value)
    
    def clear_cache(self, key: Optional[str] = None):
        """
        캐시 초기화
        
        Args:
            key: 특정 키만 초기화 (None이면 전체 초기화)
        """
        if key:
            self._memory_cache.pop(key, None)
            self._db_cache.pop(key, None)
            logger.debug(f"[Config] 캐시 초기화: '{key}'")
        else:
            self._memory_cache.clear()
            self._db_cache.clear()
            logger.debug("[Config] 전체 캐시 초기화")
    
    def _convert_type(self, key: str, value: Any) -> Any:
        """
        설정값 타입 자동 변환
        
        기본값의 타입을 참고하여 변환 시도
        """
        if value is None:
            return None
        
        # 기본값이 있는 경우 타입 참고
        if key in self._defaults:
            default_entry = self._defaults[key]
            # 딕셔너리 구조(값+설명)인 경우 값만 추출
            if isinstance(default_entry, dict) and "value" in default_entry:
                default_value = default_entry["value"]
            else:
                default_value = default_entry
                
            if isinstance(default_value, int):
                try:
                    return int(value)
                except (ValueError, TypeError):
                    pass
            elif isinstance(default_value, float):
                try:
                    return float(value)
                except (ValueError, TypeError):
                    pass
            elif isinstance(default_value, bool):
                if isinstance(value, str):
                    return value.lower() in ('true', '1', 'yes', 'on')
                return bool(value)
        
        return value
    
    def get_all(self) -> Dict[str, Any]:
        """
        모든 설정값 조회 (디버깅/모니터링용)
        
        Returns:
            모든 설정값 딕셔너리
        """
        all_config = {}
        
        # 기본값
        for key in self._defaults:
            all_config[key] = self.get(key)
        
        return all_config


# 전역 ConfigManager 인스턴스 (선택적 사용)
_global_config: Optional[ConfigManager] = None


def get_global_config(db_conn=None) -> ConfigManager:
    """
    전역 ConfigManager 인스턴스 반환 (싱글톤 패턴)
    
    Args:
        db_conn: DB 연결 (더 이상 사용되지 않음, 하위 호환성을 위해 유지)
    
    Returns:
        전역 ConfigManager 인스턴스
    
    Note:
        db_conn 파라미터는 하위 호환성을 위해 유지되지만 실제로는 사용되지 않습니다.
        ConfigManager는 연결 풀을 직접 사용합니다.
    """
    global _global_config
    if _global_config is None:
        _global_config = ConfigManager(db_conn=None)  # 연결 풀을 직접 사용하므로 None
    return _global_config


def reset_global_config():
    """전역 ConfigManager 인스턴스 초기화 (테스트용)"""
    global _global_config
    _global_config = None
