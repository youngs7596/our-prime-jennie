
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
import json
import logging
import redis
import os

from shared.db.connection import get_session

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/market",
    tags=["market"],
    responses={404: {"description": "Not found"}},
)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

def get_redis_client():
    try:
        return redis.from_url(REDIS_URL, decode_responses=True)
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
        return None

@router.get("/regime")
async def get_market_regime_api():
    """Market Regime (Bull/Bear/Sideways) API"""
    try:
        r = get_redis_client()
        if r:
            data = r.get("market:regime:data")
            if data:
                return json.loads(data)
        
        # Fallback if Redis is empty (e.g. before first Scout run)
        return {
            "regime": "SIDEWAYS",
            "confidence": 0.0,
            "description": "Waiting for Scout analysis...",
            "updated_at": None
        }
            
    except Exception as e:
        logger.error(f"Market Regime 조회 실패: {e}")
        return {"error": str(e)}
