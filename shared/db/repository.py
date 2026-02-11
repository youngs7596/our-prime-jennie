import json
import logging
import os
from typing import Dict, Iterable, List, Optional, Set

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from . import models

logger = logging.getLogger(__name__)

# =============================================================================
# KIS Gateway 실시간 현재가 조회 (Dashboard V2용)
# =============================================================================

REALTIME_PRICE_KEY = "prices:realtime"


def fetch_current_prices_from_redis(stock_codes: List[str]) -> Dict[str, float]:
    """
    Redis Hash에서 WebSocket 실시간 현재가를 조회합니다.
    kis-gateway가 WebSocket on_price 콜백에서 저장한 데이터를 읽습니다.

    Args:
        stock_codes: 종목 코드 리스트

    Returns:
        {stock_code: current_price} 딕셔너리 (미스 종목은 제외)
    """
    if not stock_codes:
        return {}

    try:
        from shared.redis_cache import get_redis_connection
        r = get_redis_connection()
        if r is None:
            return {}

        values = r.hmget(REALTIME_PRICE_KEY, *stock_codes)
        prices = {}
        for code, val in zip(stock_codes, values):
            if val is not None:
                try:
                    prices[code] = float(val)
                except (ValueError, TypeError):
                    pass
        return prices
    except Exception as e:
        logger.warning(f"Redis 실시간 현재가 조회 실패: {e}")
        return {}


def _fetch_current_prices(stock_codes: List[str]) -> Dict[str, float]:
    """
    Redis 우선 조회 → 미스 종목만 KIS API 폴백.

    Args:
        stock_codes: 종목 코드 리스트

    Returns:
        {stock_code: current_price} 딕셔너리
    """
    if not stock_codes:
        return {}

    # 1단계: Redis에서 조회
    prices = fetch_current_prices_from_redis(stock_codes)

    # 2단계: 미스 종목만 KIS API 폴백
    missing_codes = [c for c in stock_codes if c not in prices]

    if missing_codes:
        logger.info(
            f"Redis 현재가 hit={len(prices)}, miss={len(missing_codes)} -> KIS API 폴백"
        )
        try:
            kis_prices = fetch_current_prices_from_kis(missing_codes)
            prices.update(kis_prices)
        except Exception as e:
            logger.warning(f"KIS API 현재가 폴백 실패: {e}")
    else:
        logger.debug(f"Redis 현재가 전체 hit ({len(prices)}개)")

    return prices


def fetch_current_prices_from_kis(stock_codes: List[str]) -> Dict[str, float]:
    """
    KIS Gateway API를 통해 여러 종목의 실시간 현재가를 조회합니다.
    concurrent.futures를 사용하여 병렬로 요청합니다.

    Args:
        stock_codes: 종목 코드 리스트

    Returns:
        {stock_code: current_price} 딕셔너리
    """
    import httpx
    from concurrent.futures import ThreadPoolExecutor, as_completed

    kis_gateway_url = os.getenv("KIS_GATEWAY_URL", "http://127.0.0.1:8080")
    prices = {}

    if not stock_codes:
        return prices

    def fetch_single_price(code: str) -> tuple:
        """단일 종목 가격 조회"""
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.post(
                    f"{kis_gateway_url}/api/market-data/snapshot",
                    json={"stock_code": code, "is_index": False}
                )
                if response.status_code == 200:
                    result = response.json()
                    if result.get("success") and result.get("data"):
                        data = result["data"]
                        price = data.get("stck_prpr") or data.get("price") or data.get("current_price")
                        if price:
                            return (code, float(price))
        except Exception as e:
            logger.debug(f"종목 {code} 현재가 조회 실패: {e}")
        return (code, None)

    try:
        # 최대 10개 동시 요청 (KIS API 부하 고려)
        max_workers = min(10, len(stock_codes))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_single_price, code): code for code in stock_codes}
            for future in as_completed(futures, timeout=15):
                try:
                    code, price = future.result()
                    if price is not None:
                        prices[code] = price
                except Exception as e:
                    logger.debug(f"현재가 조회 future 에러: {e}")
    except Exception as e:
        logger.warning(f"KIS Gateway 병렬 조회 실패: {e}")

    return prices


def fetch_cash_balance_from_kis() -> float:
    """
    KIS Gateway API를 통해 현금 잔고(주문가능금액)를 조회합니다.
    Connection reset 오류 방지를 위해 최대 3회 재시도합니다.
    
    Returns:
        float: 주문 가능 현금 (원)
    """
    import httpx
    import time
    
    kis_gateway_url = os.getenv("KIS_GATEWAY_URL", "http://127.0.0.1:8080")
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            # Connection: close 헤더로 Keep-Alive 문제 방지
            with httpx.Client(timeout=10.0, headers={"Connection": "close"}) as client:
                response = client.post(f"{kis_gateway_url}/api/account/cash-balance", json={})
                if response.status_code == 200:
                    result = response.json()
                    if result.get("success"):
                        return float(result.get("data", 0.0))
        except Exception as e:
            if attempt < max_retries - 1:
                logger.debug(f"KIS Gateway 현금 잔고 조회 재시도 ({attempt + 1}/{max_retries}): {e}")
                time.sleep(0.5)  # 500ms 대기 후 재시도
                continue
            logger.warning(f"KIS Gateway 현금 잔고 조회 실패 ({max_retries}회 시도): {e}")
    
    return 0.0

LLM_METADATA_MARKER = "[LLM_METADATA]"


def _parse_llm_reason(raw_reason: str):
    """
    WatchList 테이블의 LLM_REASON 컬럼은 `[LLM_METADATA]{...json...}` 형태로
    메타데이터를 함께 저장합니다.
    """
    metadata = {}
    clean_reason = raw_reason or ""
    if raw_reason and LLM_METADATA_MARKER in raw_reason:
        base, metadata_raw = raw_reason.split(LLM_METADATA_MARKER, 1)
        clean_reason = base.strip()
        try:
            metadata = json.loads(metadata_raw.strip())
        except json.JSONDecodeError:
            logger.warning("⚠️ LLM 메타데이터 파싱 실패", exc_info=True)
    return clean_reason, metadata


def get_active_watchlist(session: Session) -> Dict[str, dict]:
    """
    WatchList 전체를 조회하여 서비스 레이어에서 사용하기 좋은 딕셔너리 형태로 반환합니다.
    """
    query = select(models.WatchList)
    rows = session.execute(query).scalars().all()
    watchlist: Dict[str, dict] = {}

    for row in rows:
        reason, metadata = _parse_llm_reason(row.llm_reason or "")
        inferred_tier = "TIER1" if bool(row.is_tradable) else "BLOCKED"
        # Project Recon v1.1: DB 컬럼 우선, 없으면 메타데이터/추론으로 폴백
        trade_tier = getattr(row, "trade_tier", None) or metadata.get("trade_tier") or inferred_tier
        watchlist[row.stock_code] = {
            "name": row.stock_name,
            "is_tradable": bool(row.is_tradable),
            "per": float(row.per) if row.per is not None else None,
            "pbr": float(row.pbr) if row.pbr is not None else None,
            "market_cap": float(row.market_cap) if row.market_cap is not None else None,
            "llm_score": float(row.llm_score) if row.llm_score is not None else 0,
            "llm_reason": reason,
            "llm_metadata": metadata,
            "trade_tier": trade_tier,
            "llm_grade": metadata.get("llm_grade"),
            "bear_strategy": metadata.get("bear_strategy"),
        }

    logger.info("✅ [SQLAlchemy] WatchList %d개 로드 성공!", len(watchlist))
    return watchlist


def get_active_portfolio(session: Session) -> List[dict]:
    """
    현재 보유(ActivePortfolio) 중인 포트폴리오 목록 조회.
    """
    # ActivePortfolio 테이블 조회
    query = (
        select(models.ActivePortfolio)
        .where(models.ActivePortfolio.quantity > 0)
        .order_by(models.ActivePortfolio.stock_code.asc())
    )
    rows = session.execute(query).scalars().all()
    portfolio: List[dict] = []

    for row in rows:
        portfolio.append(
            {
                "id": row.stock_code, # Use stock_code as ID
                "code": row.stock_code,
                "name": row.stock_name,
                "quantity": row.quantity,
                "avg_price": float(row.average_buy_price) if row.average_buy_price is not None else 0.0,
                "high_price": float(row.current_high_price) if row.current_high_price is not None else 0.0,
                # ActivePortfolio doesn't track sell_state explicitly, assume HOLDING
                "sell_state": "HOLDING", 
                "stop_loss_price": float(row.stop_loss_price) if row.stop_loss_price is not None else 0.0,
                "created_at": row.created_at,
            }
        )

    logger.info("✅ [SQLAlchemy] Active Portfolio %d개 로드 성공!", len(portfolio))
    return portfolio


def get_today_total_buy_amount(session: Session) -> float:
    """
    오늘 날짜 기준 총 매수 금액 합계 (price * quantity)
    """
    total_expr = func.coalesce(func.sum(models.TradeLog.price * models.TradeLog.quantity), 0)
    
    # [Hybrid Fix] DB 종속적인 func.trunc(), func.systimestamp() 제거
    # Python 레벨에서 날짜 범위 계산하여 인덱스 친화적인 범위 쿼리 사용
    from datetime import datetime, timedelta, timezone
    
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    today_filter = and_(
        models.TradeLog.trade_timestamp >= today_start,
        models.TradeLog.trade_timestamp < today_end
    )
    
    total = session.execute(
        select(total_expr).where(models.TradeLog.trade_type == "BUY").where(today_filter)
    ).scalar_one()
    logger.debug("ℹ️ [SQLAlchemy] Today buy amount = %s", total)
    return float(total or 0.0)


def get_today_buy_count(session: Session) -> int:
    """
    오늘 매수 건수
    """
    # [Hybrid Fix] 날짜 범위 쿼리 적용
    from datetime import datetime, timedelta, timezone
    
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    today_filter = and_(
        models.TradeLog.trade_timestamp >= today_start,
        models.TradeLog.trade_timestamp < today_end
    )
    
    count_expr = func.coalesce(func.count(), 0)
    count = session.execute(
        select(count_expr)
        .where(models.TradeLog.trade_type == "BUY")
        .where(today_filter)
    ).scalar_one()
    logger.debug("ℹ️ [SQLAlchemy] Today buy count = %s", count)
    return int(count or 0)


def get_trade_logs(session: Session, date_str: str | None = None) -> List[dict]:
    """
    특정 날짜 또는 오늘의 거래 내역.
    """
    query = select(models.TradeLog).order_by(models.TradeLog.trade_timestamp.desc())
    
    # [Hybrid Fix] 날짜 범위 쿼리 적용
    from datetime import datetime, timedelta, timezone
    
    if date_str:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        target_date = datetime.now(timezone.utc)
        
    start_dt = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = start_dt + timedelta(days=1)
    
    query = query.where(
        and_(
            models.TradeLog.trade_timestamp >= start_dt,
            models.TradeLog.trade_timestamp < end_dt
        )
    )

    rows = session.execute(query).scalars().all()
    logs = []
    for row in rows:
        try:
            key_metrics = json.loads(row.key_metrics_json or "{}")
        except json.JSONDecodeError:
            key_metrics = {}
        logs.append(
            {
                "code": row.stock_code,
                "action": row.trade_type,
                "quantity": int(row.quantity or 0),
                "price": float(row.price or 0.0),
                "profit_amount": float(key_metrics.get("profit_amount", 0.0)),
            }
        )
    logger.info("✅ [SQLAlchemy] Trade logs %d건 로드 (date=%s)", len(logs), date_str or "today")
    return logs


def was_traded_recently(session: Session, stock_code: str, hours: int = 24, trade_type: str = None) -> bool:
    """
    최근 N시간 내 거래 여부 확인.
    
    Args:
        session: DB 세션
        stock_code: 종목 코드
        hours: 시간 범위 (기본 24시간)
        trade_type: 거래 유형 필터 (BUY 또는 SELL). None이면 유형 무관하게 확인.
    """
    # [Hybrid Fix] Oracle func.numtodsinterval 제거 -> Python timedelta 사용
    from datetime import datetime, timedelta, timezone
    
    # hours가 float일 수 있음 (10분 = 0.17시간)
    threshold_dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    
    query = select(models.TradeLog.stock_code).where(models.TradeLog.stock_code == stock_code)
    
    if trade_type:
        query = query.where(models.TradeLog.trade_type == trade_type)
        
    query = query.where(models.TradeLog.trade_timestamp >= threshold_dt).limit(1)
    
    result = session.execute(query).first()
    return result is not None


def get_recently_traded_stocks_batch(session: Session, stock_codes: Iterable[str], hours: int = 24, trade_type: str = None) -> Set[str]:
    """
    여러 종목의 최근 거래 여부를 한 번에 조회.
    trade_type: 'BUY' 또는 'SELL' 지정 시 해당 유형만 필터링. None이면 전체.
    """
    stock_codes = list(stock_codes)
    if not stock_codes:
        return set()

    # [Hybrid Fix] Python timedelta 사용
    from datetime import datetime, timedelta, timezone

    threshold_dt = datetime.now(timezone.utc) - timedelta(hours=hours)

    query = (
        select(models.TradeLog.stock_code)
        .where(models.TradeLog.stock_code.in_(stock_codes))
        .where(models.TradeLog.trade_timestamp >= threshold_dt)
    )
    if trade_type:
        query = query.where(models.TradeLog.trade_type == trade_type)
    query = query.distinct()
    rows = session.execute(query).scalars().all()
    return set(rows)


def check_duplicate_order(session: Session, stock_code: str, trade_type: str, time_window_minutes: int = 5) -> bool:
    """
    최근 N분 내 동일 종목/유형의 주문 여부 확인 (Idempotency Check)
    """
    # [Hybrid Fix] Python timedelta 사용
    from datetime import datetime, timedelta, timezone
    
    threshold_dt = datetime.now(timezone.utc) - timedelta(minutes=time_window_minutes)
    
    exists_query = (
        select(models.TradeLog.stock_code)
        .where(models.TradeLog.stock_code == stock_code)
        .where(models.TradeLog.trade_type == trade_type)
        .where(models.TradeLog.trade_timestamp >= threshold_dt)
        .limit(1)
    )
    result = session.execute(exists_query).first()
    return result is not None



# =============================================================================
# Dashboard V2 API용 함수들
# =============================================================================

def get_portfolio_summary(session: Session, use_realtime: bool = True) -> dict:
    """
    포트폴리오 요약 정보 (Dashboard V2용)
    실시간 현재가를 반영한 총 자산 및 수익률 계산
    """
    portfolio = get_active_portfolio(session)
    
    if not portfolio:
        return {
            "total_value": 0,
            "total_invested": 0,
            "total_profit": 0,
            "profit_rate": 0,
            "cash_balance": 0,
            "positions_count": 0,
        }
    
    # 실시간 현재가 조회 (Redis 우선 → KIS API 폴백)
    stock_codes = [p["code"] for p in portfolio]
    current_prices = {}

    if use_realtime:
        try:
            current_prices = _fetch_current_prices(stock_codes)
        except Exception as e:
            logger.warning(f"⚠️ 실시간 현재가 조회 실패: {e}")

    total_invested = sum(p["avg_price"] * p["quantity"] for p in portfolio)
    
    # 실시간 현재가로 총 평가금액 계산
    total_value = 0
    for p in portfolio:
        current_price = current_prices.get(p["code"], p["avg_price"])
        total_value += current_price * p["quantity"]
    
    total_profit = total_value - total_invested
    profit_rate = (total_profit / total_invested * 100) if total_invested > 0 else 0
    
    # KIS Gateway에서 실시간 현금 잔고 조회
    cash_balance = 0.0
    if use_realtime:
        try:
            cash_balance = fetch_cash_balance_from_kis()
            logger.info(f"✅ 현금 잔고 조회 완료: {cash_balance:,.0f}원")
        except Exception as e:
            logger.warning(f"⚠️ 현금 잔고 조회 실패: {e}")
    
    return {
        "total_value": total_value + cash_balance,
        "total_invested": total_invested,
        "total_profit": total_profit,
        "profit_rate": profit_rate,
        "cash_balance": cash_balance,
        "positions_count": len(portfolio),
    }


def get_portfolio_with_current_prices(session: Session, use_realtime: bool = True) -> List[dict]:
    """
    보유 종목 목록 (현재가 포함, Dashboard V2용)
    
    Args:
        session: SQLAlchemy 세션
        use_realtime: True면 KIS Gateway에서 실시간 현재가 조회
    """
    portfolio = get_active_portfolio(session)
    
    if not portfolio:
        return []
    
    # 실시간 현재가 조회 (Redis 우선 → KIS API 폴백)
    stock_codes = [p["code"] for p in portfolio]
    current_prices = {}

    if use_realtime:
        try:
            current_prices = _fetch_current_prices(stock_codes)
            if current_prices:
                logger.info(f"✅ 실시간 현재가 {len(current_prices)}개 조회 성공")
        except Exception as e:
            logger.warning(f"⚠️ 실시간 현재가 조회 실패 (평균가 사용): {e}")
    
    result = []
    total_current_value = 0
    # 먼저 총 평가금액을 계산합니다.
    for p_orig in portfolio:
        current_price = current_prices.get(p_orig["code"], p_orig["avg_price"])
        total_current_value += current_price * p_orig["quantity"]

    for p_orig in portfolio:
        p = p_orig.copy() # 원본 수정을 방지하기 위해 복사본 사용
        invested = p["avg_price"] * p["quantity"]
        # 실시간 현재가 사용, 없으면 평균가 사용
        current_price = current_prices.get(p["code"], p["avg_price"])
        current_value = current_price * p["quantity"]
        profit = current_value - invested
        profit_rate = (profit / invested * 100) if invested > 0 else 0
        weight = (current_value / total_current_value * 100) if total_current_value > 0 else 0
        
        result.append({
            "stock_code": p["code"],
            "stock_name": p["name"],
            "quantity": p["quantity"],
            "avg_price": p["avg_price"],
            "current_price": current_price, # 조회된 실시간 현재가 반영
            "profit": profit,
            "profit_rate": profit_rate,
            "weight": weight,
        })
    
    return result


def get_watchlist_all(session: Session, limit: int = 50) -> List[models.WatchList]:
    """
    Watchlist 전체 조회 (Dashboard V2용)
    """
    # MariaDB는 NULLS LAST를 지원하지 않으므로 COALESCE 사용
    query = (
        select(models.WatchList)
        .order_by(func.coalesce(models.WatchList.llm_score, 0).desc())
        .limit(limit)
    )
    return list(session.execute(query).scalars().all())


def get_recent_trades(session: Session, limit: int = 50, offset: int = 0) -> List[models.TradeLog]:
    """
    최근 거래 내역 조회 (Dashboard V2용)
    """
    query = (
        select(models.TradeLog)
        .order_by(models.TradeLog.trade_timestamp.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.execute(query).scalars().all())


def get_scheduler_jobs(session: Session) -> List[dict]:
    """
    스케줄러 Job 목록 조회 (Dashboard V2용)
    Scheduler Service의 jobs 테이블에서 직접 조회
    """
    from sqlalchemy import text
    try:
        result = session.execute(text("SELECT job_id, queue, enabled, last_run_at, next_due_at FROM jobs ORDER BY job_id"))
        jobs = []
        for row in result:
            jobs.append({
                "job_id": row[0],
                "queue": row[1],
                "enabled": row[2],
                "last_run_at": row[3],
                "next_due_at": row[4],
            })
        return jobs
    except Exception as e:
        logger.warning(f"Scheduler jobs 조회 실패: {e}")
        return []


# ============================================================================
# CONFIG 테이블 CRUD (SQLAlchemy ORM)
# ============================================================================

def get_config(session: Session, config_key: str, silent: bool = False) -> str | None:
    """
    CONFIG 테이블에서 설정값 조회 (SQLAlchemy ORM)
    
    Args:
        session: SQLAlchemy Session
        config_key: 설정 키
        silent: True이면 설정값이 없을 때 경고 로그를 남기지 않음
    
    Returns:
        설정값 (문자열) 또는 None
    """
    try:
        # SQLAlchemy 2.0 style
        stmt = select(models.Config).where(models.Config.config_key == config_key)
        config = session.scalars(stmt).first()

        if config:
            logger.info(f"✅ DB: CONFIG '{config_key}' 값 로드 성공.")
            return config.config_value
        else:
            if not silent:
                logger.debug(f"ℹ️ DB: CONFIG '{config_key}' 값이 존재하지 않습니다.")
            return None
    except Exception as e:
        logger.error(f"❌ DB: get_config ('{config_key}') 실패! (에러: {e})")
        return None


def set_config(session: Session, config_key: str, config_value: str, description: str = None) -> bool:
    """
    CONFIG 테이블에 설정값 저장 (SQLAlchemy ORM, UPSERT)
    
    Args:
        session: SQLAlchemy Session
        config_key: 설정 키
        config_value: 설정 값
        description: 설명 (선택)
    
    Returns:
        성공 여부
    """
    try:
        # SQLAlchemy 2.0 style
        stmt = select(models.Config).where(models.Config.config_key == config_key)
        config = session.scalars(stmt).first()

        if config:
            # UPDATE
            config.config_value = config_value
            if description:
                config.description = description
            config.last_updated = datetime.now(timezone.utc)
        else:
            # INSERT
            config = models.Config(
                config_key=config_key,
                config_value=config_value,
                description=description,
                last_updated=datetime.now(timezone.utc)
            )
            session.add(config)

        session.commit()
        logger.info(f"✅ DB: CONFIG '{config_key}' 값 '{config_value[:50]}...'로 저장 성공." if len(config_value) > 50 else f"✅ DB: CONFIG '{config_key}' 값 '{config_value}'로 저장 성공.")
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"❌ DB: set_config ('{config_key}') 실패! (에러: {e})")
        return False


def delete_config(session: Session, config_key: str) -> bool:
    """
    CONFIG 테이블에서 설정값 삭제 (SQLAlchemy 2.0 style)
    """
    try:
        stmt = delete(models.Config).where(models.Config.config_key == config_key)
        result = session.execute(stmt)
        session.commit()
        if result.rowcount:
            logger.info(f"✅ DB: CONFIG '{config_key}' 삭제 성공.")
        return result.rowcount > 0
    except Exception as e:
        session.rollback()
        logger.error(f"❌ DB: delete_config ('{config_key}') 실패! (에러: {e})")
        return False


def get_daily_prices(session: Session, stock_code: str, limit: int = 60) -> List[models.StockDailyPrice]:
    """
    Get daily prices for a stock.
    Returns List of StockDailyPrice objects ordered by date desc.
    """
    stmt = (
        select(models.StockDailyPrice)
        .where(models.StockDailyPrice.stock_code == stock_code)
        .order_by(models.StockDailyPrice.price_date.desc())
        .limit(limit)
    )
    return session.execute(stmt).scalars().all()


def get_minute_prices(session: Session, stock_code: str, days: int = 3, aggregate: str = "1m") -> List[dict]:
    """
    Get minute-level prices for a stock.

    Args:
        session: SQLAlchemy session
        stock_code: Stock code
        days: Number of days to fetch (default 3)
        aggregate: Aggregation level - "1m" (1-minute), "5m" (5-minute), "1d" (daily)

    Returns:
        List of OHLCV dict with time, open, high, low, close, volume
    """
    from datetime import datetime, timedelta, timezone

    # Calculate date range
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)

    if aggregate == "1d":
        # Return daily prices instead
        daily_prices = get_daily_prices(session, stock_code, limit=days)
        return [
            {
                "time": p.price_date.strftime("%Y-%m-%d"),
                "open": float(p.open_price) if p.open_price else 0.0,
                "high": float(p.high_price) if p.high_price else 0.0,
                "low": float(p.low_price) if p.low_price else 0.0,
                "close": float(p.close_price) if p.close_price else 0.0,
                "volume": float(p.volume) if p.volume else 0.0
            }
            for p in daily_prices
            if p.open_price and p.high_price and p.low_price and p.close_price
        ]

    # Fetch minute prices
    stmt = (
        select(models.StockMinutePrice)
        .where(models.StockMinutePrice.stock_code == stock_code)
        .where(models.StockMinutePrice.price_time >= start_date)
        .order_by(models.StockMinutePrice.price_time.asc())
    )
    minute_prices = list(session.execute(stmt).scalars().all())

    if not minute_prices:
        return []

    if aggregate == "1m":
        # Return raw 1-minute data
        return [
            {
                "time": p.price_time.strftime("%Y-%m-%d %H:%M"),
                "open": float(p.open_price) if p.open_price else 0.0,
                "high": float(p.high_price) if p.high_price else 0.0,
                "low": float(p.low_price) if p.low_price else 0.0,
                "close": float(p.close_price) if p.close_price else 0.0,
                "volume": float(p.volume) if p.volume else 0.0
            }
            for p in minute_prices
            if p.open_price and p.high_price and p.low_price and p.close_price
        ]

    elif aggregate == "5m":
        # Aggregate to 5-minute candles
        result = []
        bucket = None

        for p in minute_prices:
            if not (p.open_price and p.high_price and p.low_price and p.close_price):
                continue

            # Calculate 5-minute bucket
            minute = p.price_time.minute
            bucket_minute = (minute // 5) * 5
            bucket_time = p.price_time.replace(minute=bucket_minute, second=0, microsecond=0)
            bucket_key = bucket_time.strftime("%Y-%m-%d %H:%M")

            if bucket is None or bucket["time"] != bucket_key:
                # Start new bucket
                if bucket:
                    result.append(bucket)
                bucket = {
                    "time": bucket_key,
                    "open": float(p.open_price),
                    "high": float(p.high_price),
                    "low": float(p.low_price),
                    "close": float(p.close_price),
                    "volume": float(p.volume) if p.volume else 0.0
                }
            else:
                # Update existing bucket
                bucket["high"] = max(bucket["high"], float(p.high_price))
                bucket["low"] = min(bucket["low"], float(p.low_price))
                bucket["close"] = float(p.close_price)
                bucket["volume"] += float(p.volume) if p.volume else 0.0

        if bucket:
            result.append(bucket)

        return result

    return []

