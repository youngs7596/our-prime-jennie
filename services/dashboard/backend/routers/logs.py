from fastapi import APIRouter, HTTPException, Query
import httpx
import os
import time
from typing import List, Optional

router = APIRouter(prefix="/api/logs", tags=["logs"])

LOKI_URL = os.getenv("LOKI_URL", "http://localhost:3400")

@router.get("/stream")
async def get_logs(
    service: str = Query(..., description="Container name or service label"),
    limit: int = Query(100, description="Number of log lines to return"),
    start: Optional[int] = Query(None, description="Start timestamp in ns"),
    end: Optional[int] = Query(None, description="End timestamp in ns")
):
    """
    Fetch logs from Loki for a specific service.
    Uses query: {container_name="<service>"} first, defaults to {app="<service>"} if needed.
    """
    
    # Default lookback 1 hour if not specified
    if not start:
        start = int((time.time() - 3600) * 1e9)
    if not end:
        end = int(time.time() * 1e9)
        
    query = f'{{app="{service}"}}'
    
    async with httpx.AsyncClient() as client:
        try:
            # Query Loki
            response = await client.get(
                f"{LOKI_URL}/loki/api/v1/query_range",
                params={
                    "query": query,
                    "limit": limit,
                    "start": start,
                    "end": end,
                    "direction": "BACKWARD"
                }
            )
            response.raise_for_status()
            data = response.json()
            
            # Simple parsing to return clean list of messages
            logs = []
            if "data" in data and "result" in data["data"]:
                for result in data["data"]["result"]:
                    # result['values'] is list of [ts, log_line]
                    for val in result["values"]:
                        logs.append({
                            "timestamp": val[0],
                            "message": val[1]
                        })
            
            # Sort by timestamp (Loki returns based on direction, but ensuring correct order for UI)
            # BACKWARD means newest first. UI usually wants oldest at top or newest at bottom.
            # Let's return as is (newest first) and let UI reverse if needed.
            return {"logs": logs}
            
        except httpx.RequestError as exc:
            print(f"Loki connection error: {exc}")
            raise HTTPException(status_code=502, detail="Could not connect to logging service")
        except Exception as e:
            print(f"Error fetching logs: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@router.get("/services")
async def list_services():
    """
    Return list of available services for logging.
    Hardcoded for now based on docker-compose, or could query Loki for label values.
    """
    return {
        "services": [
            "scout-job",
            "scout-worker",
            "buy-scanner",
            "buy-executor", 
            "sell-executor",
            "price-monitor",
            "news-collector",
            "news-analyzer", 
            "news-archiver",
            "kis-gateway",
            "dashboard-backend"
        ]
    }
