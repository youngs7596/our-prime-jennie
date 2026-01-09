# services/scout-job/scout_cache.py
# Version: v1.0
# Scout Job Cache Management - Redis 상태 관리 및 LLM 캐시 함수들
#
# scout.py에서 분리된 캐시/상태 관리 함수들

import os
import json
import hashlib
import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, Tuple, List, Optional

import redis

import shared.database as database

logger = logging.getLogger(__name__)

# 상수
STATE_PREFIX = "SCOUT"
CANDIDATE_DIGEST_SUFFIX = "CANDIDATE_DIGEST"
CANDIDATE_HASHES_SUFFIX = "CANDIDATE_HASHES"
LLM_CACHE_SUFFIX = "LLM_DECISIONS"
LLM_LAST_RUN_SUFFIX = "LAST_LLM_RUN_AT"
ISO_FORMAT_Z = "%Y-%m-%dT%H:%M:%S.%f%z"

# Redis 연결 (Dashboard 실시간 상태 표시용)
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
_redis_client = None


# =============================================================================
# Redis 클라이언트 및 상태 업데이트
# =============================================================================

def _get_redis():
    """Redis 클라이언트 싱글톤"""
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            _redis_client.ping()
            logger.info("✅ Redis 연결 성공 (Dashboard 상태 업데이트용)")
        except Exception as e:
            logger.warning(f"⚠️ Redis 연결 실패 (Dashboard 상태 업데이트 비활성화): {e}")
            _redis_client = None
    return _redis_client


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def update_pipeline_status(
    phase: int,
    phase_name: str,
    status: str = "running",
    progress: float = 0,
    current_stock: str = None,
    total_candidates: int = 0,
    passed_phase1: int = 0,
    passed_phase2: int = 0,
    final_selected: int = 0
):
    """
    Dashboard용 Redis 상태 업데이트
    Dashboard의 Scout Pipeline 페이지에서 실시간으로 진행 상황을 표시
    """
    r = _get_redis()
    if not r:
        return
    
    try:
        r.hset("scout:pipeline:status", mapping={
            "phase": phase,
            "phase_name": phase_name,
            "status": status,
            "progress": progress,
            "current_stock": current_stock or "",
            "total_candidates": total_candidates,
            "passed_phase1": passed_phase1,
            "passed_phase2": passed_phase2,
            "final_selected": final_selected,
            "last_updated": _utcnow().isoformat(),
        })
    except Exception as e:
        logger.debug(f"Redis 상태 업데이트 실패: {e}")


def save_pipeline_results(results: list):
    """
    Dashboard용 최종 결과 저장
    """
    r = _get_redis()
    if not r:
        return
    
    try:
        r.set("scout:pipeline:results", json.dumps(results, ensure_ascii=False, default=str))
        r.expire("scout:pipeline:results", 86400)  # 24시간 유지
    except Exception as e:
        logger.debug(f"Redis 결과 저장 실패: {e}")


def save_hot_watchlist(
    stocks: list,
    market_regime: str,
    score_threshold: int,
    ttl_seconds: int = 86400
) -> bool:
    """
    Hot Watchlist Redis 저장 (버저닝 + 스왑 패턴)
    
    Price Monitor에서 WebSocket 구독 대상으로 사용됨.
    
    Args:
        stocks: 종목 리스트 [{"code": "005930", "name": "삼성전자", "llm_score": 72, ...}, ...]
        market_regime: 현재 시장 국면 (STRONG_BULL, BULL, SIDEWAYS, BEAR)
        score_threshold: 현재 적용된 LLM Score 커트라인
        ttl_seconds: Redis TTL (기본 24시간)
    
    Returns:
        성공 여부
    """
    r = _get_redis()
    if not r:
        logger.warning("⚠️ Redis 연결 없음 - Hot Watchlist 저장 실패")
        return False
    
    try:
        from datetime import datetime, timezone
        
        # 타임스탬프 기반 버전 키 생성
        timestamp = int(datetime.now(timezone.utc).timestamp())
        version_key = f"hot_watchlist:v{timestamp}"
        
        # Hot Watchlist 데이터 구성 (메타데이터 포함)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "market_regime": market_regime,
            "score_threshold": score_threshold,
            "stocks": [
                {
                    "code": s.get("code"),
                    "name": s.get("name"),
                    "llm_score": s.get("llm_score", 0),
                    "rank": idx + 1,
                    "is_tradable": s.get("is_tradable", True),
                }
                for idx, s in enumerate(stocks)
                if s.get("code") != "0001"  # KOSPI 지수 제외
            ]
        }
        
        # 1. 새 버전 저장
        r.set(version_key, json.dumps(payload, ensure_ascii=False, default=str))
        r.expire(version_key, ttl_seconds)
        
        # 2. active 포인터 스왑 (원자적 전환)
        old_version = r.get("hot_watchlist:active")
        r.set("hot_watchlist:active", version_key)
        
        # 3. 이전 버전 삭제 (즉시 삭제 대신 TTL로 자연 만료 - 롤백 가능)
        # 이전 버전은 TTL이 설정되어 있으므로 자동 삭제됨
        
        stock_count = len(payload["stocks"])
        logger.info(f"   (Redis) ✅ Hot Watchlist 저장: {stock_count}개 종목 (threshold: {score_threshold}점, regime: {market_regime})")
        logger.info(f"   (Redis)    버전: {version_key}")
        
        return True
        
    except Exception as e:
        logger.error(f"   (Redis) ❌ Hot Watchlist 저장 실패: {e}")
        return False


def get_hot_watchlist() -> dict:
    """
    Hot Watchlist Redis에서 로드
    
    Returns:
        {
            "generated_at": "2026-01-09T08:30:00+00:00",
            "market_regime": "STRONG_BULL",
            "score_threshold": 58,
            "stocks": [{"code": "005930", "name": "삼성전자", "llm_score": 72, "rank": 1}, ...]
        }
        또는 None
    """
    r = _get_redis()
    if not r:
        return None
    
    try:
        # active 포인터에서 현재 버전 키 조회
        version_key = r.get("hot_watchlist:active")
        if not version_key:
            logger.debug("Hot Watchlist active 버전 없음")
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
    
    (준호/민지 제안: 기존 llm_score를 재활용해서 새 기준으로 필터만 다시 적용)
    
    Args:
        new_regime: 새 시장 국면 (STRONG_BULL, BULL, SIDEWAYS, BEAR)
    
    Returns:
        성공 여부
    """
    r = _get_redis()
    if not r:
        logger.warning("⚠️ Redis 연결 없음 - 재필터링 실패")
        return False
    
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
        return save_hot_watchlist(
            stocks=[
                {
                    'code': s['code'],
                    'name': s.get('name', s['code']),
                    'llm_score': s.get('llm_score', 0),
                    'is_tradable': s.get('is_tradable', True),
                }
                for s in filtered_stocks
            ],
            market_regime=new_regime,
            score_threshold=new_threshold
        )
        
    except Exception as e:
        logger.error(f"Hot Watchlist 재필터링 실패: {e}")
        return False


# =============================================================================
# CONFIG 테이블 기반 상태 관리
# =============================================================================

def _get_scope() -> str:
    return os.getenv("SCHEDULER_SCOPE", "real")


def _make_state_key(suffix: str) -> str:
    scope = _get_scope()
    return f"{STATE_PREFIX}::{scope}::{suffix}"


def _load_json_config(connection, suffix: str, default=None):
    raw = database.get_config(connection, _make_state_key(suffix), silent=True)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception as exc:
        logger.warning(f"⚠️ CONFIG '{suffix}' JSON 파싱 실패: {exc}")
        return default


def _save_json_config(connection, suffix: str, payload) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    database.set_config(connection, _make_state_key(suffix), serialized)


def _get_last_llm_run_at(connection) -> Optional[datetime]:
    raw = database.get_config(connection, _make_state_key(LLM_LAST_RUN_SUFFIX), silent=True)
    if not raw:
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except Exception as exc:
        logger.warning(f"⚠️ LAST_LLM_RUN_AT 파싱 실패: {exc}")
        return None


def _save_last_llm_run_at(connection, dt: datetime) -> None:
    database.set_config(connection, _make_state_key(LLM_LAST_RUN_SUFFIX), dt.astimezone(timezone.utc).isoformat())


def _load_candidate_state(connection) -> Tuple[str | None, Dict[str, str]]:
    digest = database.get_config(connection, _make_state_key(CANDIDATE_DIGEST_SUFFIX), silent=True)
    hashes = _load_json_config(connection, CANDIDATE_HASHES_SUFFIX, default={})
    return digest, hashes or {}


def _save_candidate_state(connection, digest: str, hashes: Dict[str, str]) -> None:
    database.set_config(connection, _make_state_key(CANDIDATE_DIGEST_SUFFIX), digest)
    _save_json_config(connection, CANDIDATE_HASHES_SUFFIX, hashes)


# =============================================================================
# 캐시 시스템 - LLM_EVAL_CACHE 테이블 기반
# =============================================================================

def _load_llm_cache_from_db(connection) -> Dict[str, Dict]:
    """
    LLM_EVAL_CACHE 테이블에서 모든 캐시 로드
    
    Returns:
        Dict[stock_code, cache_entry]
    """
    cache = {}
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT STOCK_CODE, STOCK_NAME, PRICE_BUCKET, VOLUME_BUCKET, NEWS_HASH,
                   EVAL_DATE, HUNTER_SCORE, JUDGE_SCORE, LLM_GRADE, LLM_REASON,
                   NEWS_USED, IS_APPROVED, IS_TRADABLE, UPDATED_AT
            FROM LLM_EVAL_CACHE
        """)
        rows = cursor.fetchall()
        
        for row in rows:
            if isinstance(row, dict):
                code = row['STOCK_CODE']
                cache[code] = {
                    'stock_code': code,
                    'stock_name': row['STOCK_NAME'],
                    'price_bucket': row['PRICE_BUCKET'],
                    'volume_bucket': row['VOLUME_BUCKET'],
                    'news_hash': row['NEWS_HASH'],
                    'eval_date': str(row['EVAL_DATE']) if row['EVAL_DATE'] else None,
                    'hunter_score': row['HUNTER_SCORE'],
                    'judge_score': row['JUDGE_SCORE'],
                    'llm_grade': row['LLM_GRADE'],
                    'llm_reason': row['LLM_REASON'],
                    'news_used': row['NEWS_USED'],
                    'is_approved': bool(row['IS_APPROVED']),
                    'is_tradable': bool(row['IS_TRADABLE']),
                    'updated_at': row['UPDATED_AT'],
                }
            else:
                code = row[0]
                cache[code] = {
                    'stock_code': code,
                    'stock_name': row[1],
                    'price_bucket': row[2],
                    'volume_bucket': row[3],
                    'news_hash': row[4],
                    'eval_date': str(row[5]) if row[5] else None,
                    'hunter_score': row[6],
                    'judge_score': row[7],
                    'llm_grade': row[8],
                    'llm_reason': row[9],
                    'news_used': row[10],
                    'is_approved': bool(row[11]),
                    'is_tradable': bool(row[12]),
                    'updated_at': row[13],
                }
        cursor.close()
        logger.info(f"   (Cache) ✅ LLM_EVAL_CACHE에서 {len(cache)}개 로드")
    except Exception as e:
        logger.warning(f"   (Cache) ⚠️ LLM_EVAL_CACHE 로드 실패: {e}")
    return cache


def _save_llm_cache_to_db(connection, stock_code: str, cache_entry: Dict) -> None:
    """
    LLM_EVAL_CACHE 테이블에 단일 종목 캐시 저장 (UPSERT)
    """
    try:
        cursor = connection.cursor()
        sql = """
            INSERT INTO LLM_EVAL_CACHE (
                STOCK_CODE, STOCK_NAME, PRICE_BUCKET, VOLUME_BUCKET, NEWS_HASH,
                EVAL_DATE, HUNTER_SCORE, JUDGE_SCORE, LLM_GRADE, LLM_REASON,
                NEWS_USED, IS_APPROVED, IS_TRADABLE, CREATED_AT, UPDATED_AT
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
            ) ON DUPLICATE KEY UPDATE
                STOCK_NAME = VALUES(STOCK_NAME),
                PRICE_BUCKET = VALUES(PRICE_BUCKET),
                VOLUME_BUCKET = VALUES(VOLUME_BUCKET),
                NEWS_HASH = VALUES(NEWS_HASH),
                EVAL_DATE = VALUES(EVAL_DATE),
                HUNTER_SCORE = VALUES(HUNTER_SCORE),
                JUDGE_SCORE = VALUES(JUDGE_SCORE),
                LLM_GRADE = VALUES(LLM_GRADE),
                LLM_REASON = VALUES(LLM_REASON),
                NEWS_USED = VALUES(NEWS_USED),
                IS_APPROVED = VALUES(IS_APPROVED),
                IS_TRADABLE = VALUES(IS_TRADABLE),
                UPDATED_AT = NOW()
        """
        cursor.execute(sql, (
            stock_code,
            cache_entry.get('stock_name', ''),
            cache_entry.get('price_bucket', 0),
            cache_entry.get('volume_bucket', 0),
            cache_entry.get('news_hash'),
            cache_entry.get('eval_date'),
            cache_entry.get('hunter_score', 0),
            cache_entry.get('judge_score', 0),
            cache_entry.get('llm_grade'),
            cache_entry.get('llm_reason', '')[:60000] if cache_entry.get('llm_reason') else None,
            cache_entry.get('news_used', '')[:60000] if cache_entry.get('news_used') else None,
            1 if cache_entry.get('is_approved') else 0,
            1 if cache_entry.get('is_tradable') else 0,
        ))
        connection.commit()
        cursor.close()
    except Exception as e:
        logger.warning(f"   (Cache) ⚠️ {stock_code} 캐시 저장 실패: {e}")


def _save_llm_cache_batch(connection, cache_entries: Dict[str, Dict]) -> None:
    """
    LLM_EVAL_CACHE 테이블에 배치 저장
    """
    if not cache_entries:
        return
    
    try:
        cursor = connection.cursor()
        sql = """
            INSERT INTO LLM_EVAL_CACHE (
                STOCK_CODE, STOCK_NAME, PRICE_BUCKET, VOLUME_BUCKET, NEWS_HASH,
                EVAL_DATE, HUNTER_SCORE, JUDGE_SCORE, LLM_GRADE, LLM_REASON,
                NEWS_USED, IS_APPROVED, IS_TRADABLE, CREATED_AT, UPDATED_AT
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
            ) ON DUPLICATE KEY UPDATE
                STOCK_NAME = VALUES(STOCK_NAME),
                PRICE_BUCKET = VALUES(PRICE_BUCKET),
                VOLUME_BUCKET = VALUES(VOLUME_BUCKET),
                NEWS_HASH = VALUES(NEWS_HASH),
                EVAL_DATE = VALUES(EVAL_DATE),
                HUNTER_SCORE = VALUES(HUNTER_SCORE),
                JUDGE_SCORE = VALUES(JUDGE_SCORE),
                LLM_GRADE = VALUES(LLM_GRADE),
                LLM_REASON = VALUES(LLM_REASON),
                NEWS_USED = VALUES(NEWS_USED),
                IS_APPROVED = VALUES(IS_APPROVED),
                IS_TRADABLE = VALUES(IS_TRADABLE),
                UPDATED_AT = NOW()
        """
        
        data = []
        for code, entry in cache_entries.items():
            data.append((
                code,
                entry.get('stock_name', ''),
                entry.get('price_bucket', 0),
                entry.get('volume_bucket', 0),
                entry.get('news_hash'),
                entry.get('eval_date'),
                entry.get('hunter_score', 0),
                entry.get('judge_score', 0),
                entry.get('llm_grade'),
                entry.get('llm_reason', '')[:60000] if entry.get('llm_reason') else None,
                entry.get('news_used', '')[:60000] if entry.get('news_used') else None,
                1 if entry.get('is_approved') else 0,
                1 if entry.get('is_tradable') else 0,
            ))
        
        cursor.executemany(sql, data)
        connection.commit()
        cursor.close()
        logger.info(f"   (Cache) ✅ LLM_EVAL_CACHE에 {len(data)}개 저장")
    except Exception as e:
        logger.warning(f"   (Cache) ⚠️ 배치 캐시 저장 실패: {e}")


# =============================================================================
# 캐시 유효성 검사 및 해시 계산
# =============================================================================

def _is_cache_valid_direct(cached: Optional[Dict], current_data: Dict, today_str: str) -> bool:
    """
    직접 비교로 캐시 유효성 검증 (해시 불필요!)
    
    Args:
        cached: DB에서 로드한 캐시 데이터
        current_data: 현재 종목 데이터 (price_bucket, volume_bucket, news_hash)
        today_str: 오늘 날짜 (YYYY-MM-DD)
    
    Returns:
        True면 캐시 사용, False면 LLM 재호출
    """
    if not cached:
        return False
    
    # 1. 날짜가 다르면 재평가
    if cached.get('eval_date') != today_str:
        return False
    
    # 2. 가격 버킷이 다르면 재평가 (5% 이상 변동)
    if cached.get('price_bucket') != current_data.get('price_bucket'):
        return False
    
    # 3. 뉴스가 바뀌면 재평가
    cached_news = cached.get('news_hash') or ''
    current_news = current_data.get('news_hash') or ''
    if cached_news != current_news:
        return False
    
    return True


def _get_price_bucket(price: float) -> int:
    """가격을 5% 버킷으로 변환 (가격 변동 감지용)"""
    if price <= 0:
        return 0
    # log 스케일로 5% 버킷 생성
    bucket = int(math.log(price) / math.log(1.05))  # 5% 간격
    return bucket


def _get_volume_bucket(volume: int) -> int:
    """거래량을 버킷으로 변환 (거래량 급변 감지용)"""
    if volume <= 0:
        return 0
    # 거래량을 10만주 단위 버킷으로 (예: 500만주 → 50)
    return volume // 100000


def _get_foreign_direction(foreign_net: int) -> str:
    """외국인 순매수 방향 (매수/매도/중립)"""
    if foreign_net > 10000:  # 1만주 이상 순매수
        return "buy"
    elif foreign_net < -10000:  # 1만주 이상 순매도
        return "sell"
    return "neutral"


def _hash_candidate_payload(code: str, info: Dict) -> str:
    """
    종목별 해시 생성 (v4.1 - 시장 데이터 포함)
    
    해시에 포함되는 데이터:
    - 종목코드, 종목명, 선정이유 (기본)
    - 오늘 날짜 (매일 재평가 보장)
    - 가격 버킷 (5% 이상 변동 시 재평가)
    - 거래량 버킷 (급변 감지)
    - 외국인 순매수 방향 (수급 변화 감지)
    - 최신 뉴스 날짜 (뉴스 변경 시 재평가)
    """
    # 오늘 날짜 (KST 기준)
    kst = timezone(timedelta(hours=9))
    today_kst = datetime.now(kst).strftime("%Y-%m-%d")
    
    normalized = {
        "code": code,
        "name": info.get("name"),
        "reasons": sorted(info.get("reasons", [])),
        "date": today_kst,  # 매일 재평가 보장
    }
    
    # 시장 데이터가 있으면 버킷화하여 포함
    if "price" in info:
        normalized["price_bucket"] = _get_price_bucket(info["price"])
    if "volume" in info:
        normalized["volume_bucket"] = _get_volume_bucket(info["volume"])
    if "foreign_net" in info:
        normalized["foreign_direction"] = _get_foreign_direction(info["foreign_net"])
    
    # 뉴스 해시 (내용 기반 - 시간 정보 포함)
    if "news_hash" in info:
        normalized["news_hash"] = info["news_hash"]
    
    # 나머지 키들도 포함 (기존 호환성)
    for key in sorted(k for k in info.keys() if k not in ("name", "reasons", "price", "volume", "foreign_net", "news_date")):
        value = info.get(key)
        if isinstance(value, list):
            normalized[key] = sorted(value)
        else:
            normalized[key] = value
    
    serialized = json.dumps(normalized, ensure_ascii=True, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _compute_candidate_hashes(candidate_stocks: Dict[str, Dict]) -> Tuple[Dict[str, str], str]:
    per_stock = {}
    for code in candidate_stocks:
        per_stock[code] = _hash_candidate_payload(code, candidate_stocks[code])
    digest_source = "".join(per_stock[code] for code in sorted(per_stock))
    overall_digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    return per_stock, overall_digest


def _minutes_since(timestamp: Optional[datetime]) -> float:
    if not timestamp:
        return float("inf")
    delta = _utcnow() - timestamp.astimezone(timezone.utc)
    return delta.total_seconds() / 60.0


def _parse_int_env(value: Optional[str], default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _is_cache_entry_valid(entry: Optional[Dict], decision_hash: str, ttl_minutes: int) -> bool:
    if not entry:
        return False
    if entry.get("decision_hash") != decision_hash:
        return False
    if ttl_minutes <= 0:
        return True
    updated_at = entry.get("llm_updated_at")
    if not updated_at:
        return False
    try:
        ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except Exception:
        return False
    return _minutes_since(ts) < ttl_minutes


def _record_to_watchlist_entry(record: Dict) -> Dict:
    return {
        "code": record["code"],
        "name": record["name"],
        "is_tradable": record.get("is_tradable", True),
        "llm_score": record.get("llm_score", 0),
        "llm_reason": record.get("llm_reason", ""),
        "llm_metadata": record.get("llm_metadata", {}),
        # 재무 데이터 추가 (scout 파이프라인에서 전달됨)
        "per": record.get("per"),
        "pbr": record.get("pbr"),
        "roe": record.get("roe"),
        "market_cap": record.get("market_cap"),
        "sales_growth": record.get("sales_growth"),
        "eps_growth": record.get("eps_growth"),
        "financial_updated_at": _utcnow().isoformat(),
    }


def _record_to_cache_payload(record: Dict) -> Dict:
    metadata = record.get("llm_metadata", {})
    return {
        "code": record["code"],
        "name": record["name"],
        "llm_score": record.get("llm_score", 0),
        "llm_reason": record.get("llm_reason", ""),
        "llm_grade": metadata.get("llm_grade"),
        "decision_hash": metadata.get("decision_hash"),
        "llm_updated_at": metadata.get("llm_updated_at"),
        "is_tradable": record.get("is_tradable", True),
        "approved": record.get("approved", False),
    }


def _cache_payload_to_record(entry: Dict, decision_hash: str) -> Dict:
    updated_at = entry.get("llm_updated_at")
    metadata = {
        "llm_grade": entry.get("llm_grade"),
        "decision_hash": decision_hash,
        "llm_updated_at": updated_at,
        "source": "cache",
    }
    return {
        "code": entry["code"],
        "name": entry.get("name", entry["code"]),
        "llm_score": entry.get("llm_score", 0),
        "llm_reason": entry.get("llm_reason", ""),
        "is_tradable": entry.get("is_tradable", True),
        "approved": entry.get("approved", False),
        "llm_metadata": metadata,
    }
