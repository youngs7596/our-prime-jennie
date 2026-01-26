from fastapi import APIRouter, HTTPException, Depends
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
async def get_logic_status(stock_code: str):
    """
    Get the real-time logic snapshot and historical chart data for a specific stock.
    Used for Logic Observability Visualization.
    """
    try:
        # 1. Fetch Logic Snapshot from Redis
        snapshot_key = f"logic:snapshot:{stock_code}"
        snapshot = redis_cache.get_redis_data(snapshot_key)
        
        # If no snapshot exists (maybe monitoring not active for this stock), return empty/partial
        if not snapshot:
            # Fallback: Try to get current price at least?
            # For now, just indicate it's not being monitored or no data yet
            pass 

        # 2. Fetch Historical Data (30-60 days) for Chart
        chart_data = []
        with get_session() as session:
            # Fetch daily prices
            df = repo.get_daily_prices(session, stock_code, limit=60)
            if not df.empty:
                # Convert DataFrame to list of dicts compatible with frontend
                # Expected: time, open, high, low, close, volume
                # df columns: PRICE_DATE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, TRADE_VOLUME
                for _, row in df.iterrows():
                    chart_data.append({
                        "time": row['PRICE_DATE'].strftime("%Y-%m-%d"),
                        "open": float(row['OPEN_PRICE']),
                        "high": float(row['HIGH_PRICE']),
                        "low": float(row['LOW_PRICE']),
                        "close": float(row['CLOSE_PRICE']),
                        "volume": float(row['TRADE_VOLUME'])
                    })
        
        # 3. Combine and Return
        return {
            "stock_code": stock_code,
            "snapshot": snapshot,
            "chart_data": chart_data
        }

    except Exception as e:
        logger.error(f"Logic status fetch failed for {stock_code}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
