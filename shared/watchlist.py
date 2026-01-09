
import json
import logging
from datetime import datetime, timezone
from typing import TypedDict, Dict, Any, List, Optional
import os

from shared.database import get_redis_connection

logger = logging.getLogger(__name__)

class StrategyConfig(TypedDict):
    """
    개별 종목에 적용할 매수 전략 설정
    
    Attributes:
        id: 전략 ID (예: "GOLDEN_CROSS", "RSI_OVERSOLD", "BB_LOWER")
        params: 전략 실행에 필요한 파라미터 (예: {"threshold": 30, "period": 14})
    """
    id: str
    params: Dict[str, Any]

def save_hot_watchlist(
    stocks: list,
    market_regime: str,
    score_threshold: int,
    ttl_seconds: int = 86400
) -> bool:
    """
    Hot Watchlist Redis 저장 (버저닝 + 스왑 패턴)
    
    Price Monitor에서 WebSocket 구독 및 전략 실행 대상으로 사용됨.
    
    Args:
        stocks: 종목 리스트 [{"code": "005930", "name": "삼성전자", "llm_score": 72, "strategies": [...]}, ...]
        market_regime: 현재 시장 국면 (STRONG_BULL, BULL, SIDEWAYS, BEAR)
        score_threshold: 현재 적용된 LLM Score 커트라인
        ttl_seconds: Redis TTL (기본 24시간)
    
    Returns:
        성공 여부
    """
    r = get_redis_connection()
    if not r:
        logger.warning("⚠️ Redis 연결 없음 - Hot Watchlist 저장 실패")
        return False
    
    try:
        # 타임스탬프 기반 버전 키 생성
        timestamp = int(datetime.now(timezone.utc).timestamp())
        version_key = f"hot_watchlist:v{timestamp}"
        
        # Hot Watchlist 데이터 구성 (메타데이터 포함)
        # stocks 리스트 내의 strategies 필드가 포함되어야 함
        clean_stocks = []
        for idx, s in enumerate(stocks):
            if s.get("code") == "0001":  # KOSPI 지수 제외
                continue
                
            stock_entry = {
                "code": s.get("code"),
                "name": s.get("name"),
                "llm_score": s.get("llm_score", 0),
                "rank": idx + 1,
                "is_tradable": s.get("is_tradable", True),
                # Strategy Injection (없으면 빈 리스트)
                "strategies": s.get("strategies", []) 
            }
            # 기타 필요한 메타데이터가 있다면 추가 (호환성 유지)
            if "market_flow" in s:
                stock_entry["market_flow"] = s["market_flow"]
                
            clean_stocks.append(stock_entry)

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "market_regime": market_regime,
            "score_threshold": score_threshold,
            "stocks": clean_stocks
        }
        
        # 1. 새 버전 저장
        r.set(version_key, json.dumps(payload, ensure_ascii=False, default=str))
        r.expire(version_key, ttl_seconds)
        
        # 2. active 포인터 스왑 (원자적 전환)
        old_version = r.get("hot_watchlist:active")
        r.set("hot_watchlist:active", version_key)
        
        # 3. 이전 버전은 TTL에 의해 자연 소멸
        
        stock_count = len(payload["stocks"])
        logger.info(f"   (Redis) ✅ Hot Watchlist 저장: {stock_count}개 종목 (threshold: {score_threshold}점, regime: {market_regime})")
        logger.info(f"   (Redis)    버전: {version_key}")
        
        return True
        
    except Exception as e:
        logger.error(f"   (Redis) ❌ Hot Watchlist 저장 실패: {e}")
        return False


def get_hot_watchlist() -> Optional[dict]:
    """
    Hot Watchlist Redis에서 로드
    
    Returns:
        {
            "generated_at": "2026-01-09T08:30:00+00:00",
            "market_regime": "STRONG_BULL",
            "score_threshold": 58,
            "stocks": [
                {
                    "code": "005930", 
                    "name": "삼성전자", 
                    "llm_score": 72, 
                    "strategies": [{"id": "RSI", "params": {...}}]
                }, 
                ...
            ]
        }
        또는 None
    """
    r = get_redis_connection()
    if not r:
        return None
    
    try:
        # active 포인터에서 현재 버전 키 조회
        version_key = r.get("hot_watchlist:active")
        if not version_key:
            # logger.debug("Hot Watchlist active 버전 없음")
            return None
        
        # 버전 키에서 데이터 조회
        data = r.get(version_key)
        if not data:
            logger.debug(f"Hot Watchlist 데이터 없음: {version_key}")
            return None
        
        return json.loads(data)
        
    except Exception as e:
        logger.warning(f"Hot Watchlist 로드 실패: {e}")
        return None

def refilter_hot_watchlist_by_regime(new_regime: str) -> bool:
    """
    시장 국면 변경 시 Hot Watchlist 경량 재필터링 (LLM 재호출 없음)
    
    Args:
        new_regime: 새 시장 국면 (STRONG_BULL, BULL, SIDEWAYS, BEAR)
    
    Returns:
        성공 여부
    """
    try:
        # 1. 현재 Hot Watchlist 로드
        current = get_hot_watchlist()
        if not current or not current.get('stocks'):
            logger.info("Hot Watchlist가 비어있어 재필터링 불필요")
            return True
        
        old_regime = current.get('market_regime', 'UNKNOWN')
        if old_regime == new_regime:
            logger.info(f"시장 국면 변경 없음 ({new_regime}) - 재필터링 스킵")
            return True
        
        # 2. 새 시장 국면별 score threshold
        recon_score_by_regime = {
            "STRONG_BULL": 58,
            "BULL": 62,
            "SIDEWAYS": 65,
            "BEAR": 70,
        }
        new_threshold = recon_score_by_regime.get(new_regime, 65)
        old_threshold = current.get('score_threshold', 65)
        
        # 3. 새 기준으로 종목 필터링 (llm_score >= new_threshold)
        original_stocks = current.get('stocks', [])
        filtered_stocks = [
            s for s in original_stocks 
            if s.get('llm_score', 0) >= new_threshold
        ]
        
        # 재정렬 (llm_score 내림차순)
        filtered_stocks = sorted(filtered_stocks, key=lambda x: x.get('llm_score', 0), reverse=True)
        
        logger.info(f"🔄 [Regime Change] {old_regime}({old_threshold}점) → {new_regime}({new_threshold}점)")
        logger.info(f"   종목 수: {len(original_stocks)} → {len(filtered_stocks)}개")
        
        # 4. 새 버전으로 저장 (버저닝 패턴)
        # 중요: 기존 strategies 정보 등은 그대로 유지됨
        return save_hot_watchlist(
            stocks=filtered_stocks,
            market_regime=new_regime,
            score_threshold=new_threshold
        )
        
    except Exception as e:
        logger.error(f"Hot Watchlist 재필터링 실패: {e}")
        return False
