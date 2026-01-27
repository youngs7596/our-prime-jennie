from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Dict, Any, List, Optional
import json
import logging
from datetime import datetime

from shared.db.connection import get_session
from shared.db import repository as repo
import shared.redis_cache as redis_cache

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/logic",
    tags=["logic"],
    responses={404: {"description": "Not found"}},
)

@router.get("/status/{stock_code}")
async def get_logic_status(
    stock_code: str,
    timeframe: str = Query("1d", description="Timeframe: 1m, 5m, or 1d")
):
    """
    Get the real-time logic snapshot and historical chart data for a specific stock.
    Used for Logic Observability Visualization.

    Args:
        stock_code: Stock code to fetch
        timeframe: Chart timeframe - "1m" (1-minute), "5m" (5-minute), "1d" (daily)
    """
    try:
        # 1. Fetch Sell Logic Snapshot from Redis (Price Monitor)
        snapshot_key = f"logic:snapshot:{stock_code}"
        snapshot = redis_cache.get_redis_data(snapshot_key)

        # 2. Fetch Buy Logic Snapshot from Redis (Buy Scanner)
        buy_snapshot_key = f"buy_logic:snapshot:{stock_code}"
        buy_snapshot = redis_cache.get_redis_data(buy_snapshot_key)

        # 3. Fetch Signal History from Redis (최근 50개)
        signal_history = []
        try:
            signals_key = f"logic:signals:{stock_code}"
            raw_signals = redis_cache.get_redis_data(signals_key)
            if raw_signals and isinstance(raw_signals, list):
                signal_history = raw_signals
        except Exception:
            pass

        # 4. Fetch Chart Data based on timeframe
        chart_data = []
        with get_session() as session:
            if timeframe in ["1m", "5m"]:
                # Fetch minute prices
                chart_data = repo.get_minute_prices(session, stock_code, days=3, aggregate=timeframe)
            else:
                # Default: Daily prices (60 days)
                prices = repo.get_daily_prices(session, stock_code, limit=60)
                if prices:
                    for p in prices:
                        # [Backend Sanitization] OHLC 유효성 검사 - None/0 값 필터링
                        o = float(p.open_price) if p.open_price else 0.0
                        h = float(p.high_price) if p.high_price else 0.0
                        l = float(p.low_price) if p.low_price else 0.0
                        c = float(p.close_price) if p.close_price else 0.0

                        # OHLC 중 하나라도 0이면 비정상 캔들로 간주하여 제외
                        if o <= 0 or h <= 0 or l <= 0 or c <= 0:
                            logger.debug(f"[Sanitize] Invalid candle dropped: {stock_code} {p.price_date} (O={o}, H={h}, L={l}, C={c})")
                            continue

                        chart_data.append({
                            "time": p.price_date.strftime("%Y-%m-%d"),
                            "open": o,
                            "high": h,
                            "low": l,
                            "close": c,
                            "volume": float(p.volume) if p.volume else 0.0
                        })

        # 5. Deduplicate and Sort
        # [Backend Sanitization] 동일 타임스탬프 중복 제거 (최신 데이터 우선)
        seen_times = {}
        for candle in chart_data:
            seen_times[candle['time']] = candle  # 동일 시간이면 마지막 값으로 덮어씀
        chart_data = list(seen_times.values())

        # Lightweight Charts requires data in ascending order
        chart_data.sort(key=lambda x: x['time'])

        return {
            "stock_code": stock_code,
            "snapshot": snapshot,
            "buy_snapshot": buy_snapshot,
            "signal_history": signal_history,
            "chart_data": chart_data,
            "timeframe": timeframe
        }

    except Exception as e:
        logger.error(f"Logic status fetch failed for {stock_code}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
