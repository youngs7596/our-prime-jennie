"""
Dashboard Backend - System Router
시스템 상태(Docker, RabbitMQ, Scheduler, Logs)를 조회하는 API 라우터입니다.
성능 최적화를 위해 Redis 캐싱이 적용되어 있습니다.
"""

import os
import json
import logging
import httpx
import functools
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import redis

from shared.db.connection import get_session
from shared.db.repository import get_scheduler_jobs
from shared.db.models import WatchList  # 필요시 import

# 순환 참조 방지를 위해 main.py가 아닌 곳에서 Redis 클라이언트를 가져오거나 
# 의존성 주입을 사용하는 것이 좋지만, 여기서는 main.py와 동일한 환경변수를 사용하여
# 독립적인 연결을 맺거나, redis_utils 같은 공통 모듈을 사용하는 패턴 권장.
# 일단 기존 패턴대로 REDIS_URL 사용.

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/system",
    tags=["system"],
    responses={404: {"description": "Not found"}},
)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# --- Redis Helper ---
_redis_client = None

def get_redis_client():
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        except Exception as e:
            logger.warning(f"Router Redis 연결 실패: {e}")
            return None
    return _redis_client

# --- Pydantic Models (from main.py) ---
class SystemStatus(BaseModel):
    service_name: str
    status: str
    last_run: Optional[datetime]
    next_run: Optional[datetime]
    message: Optional[str]

# --- Helper: Cache Decorator ---
def cache_response(ttl_seconds: int = 5):
    """
    간단한 Redis 캐싱 데코레이터
    * 주의: async 함수에만 적용 가능
    * 키 생성: router_system:{func_name}:{args}
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            r = get_redis_client()
            if not r:
                return await func(*args, **kwargs)
            
            # 캐시 키 생성 (함수 이름 + 인자 기반)
            # kwargs에서 간단히 중요한 파라미터만 추출하거나 전체 사용
            # 여기서는 편의상 함수 이름 + kwargs 문자열
            key = f"cache:system:{func.__name__}:{str(kwargs)}"
            
            cached = r.get(key)
            if cached:
                try:
                    return json.loads(cached)
                except (json.JSONDecodeError, TypeError, ValueError):
                    # 손상된 캐시 데이터는 무시하고 새로 조회
                    pass
            
            # 캐시 미스 -> 함수 실행
            result = await func(*args, **kwargs)
            
            # 결과 저장 (Pydantic 모델 등은 dict로 변환 필요하지만, 
            # 이 라우터의 반환값은 대부분 dict/list임)
            try:
                # Pydantic 모델 리스트인 경우 model_dump/dict 처리 필요할 수 있음
                # 여기서는 API가 dict/list를 반환한다고 가정
                r.setex(key, ttl_seconds, json.dumps(result, default=str))
            except Exception as e:
                logger.warning(f"캐시 저장 실패 ({key}): {e}")
                
            return result
        return wrapper
    return decorator


# =============================================================================
# API Endpoints
# =============================================================================

@router.get("/status", response_model=List[SystemStatus])
async def get_system_status():
    """시스템 서비스 상태 (Scheduler Jobs 기반) - 캐시 없음 (실시간성 중요)"""
    try:
        with get_session() as session:
            jobs = get_scheduler_jobs(session)
            return [
                SystemStatus(
                    service_name=job.get("job_id", "unknown"),
                    status="active" if job.get("enabled") else "inactive",
                    last_run=job.get("last_run_at"),
                    next_run=job.get("next_due_at"),
                    message=f"Queue: {job.get('queue', 'N/A')}",
                )
                for job in jobs
            ]
    except Exception as e:
        logger.error(f"시스템 상태 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/docker")
@cache_response(ttl_seconds=5)
async def get_docker_status():
    """Docker 컨테이너 상태 (WSL2 환경) - 5초 캐싱"""
    try:
        transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
        # 3초 타임아웃
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost", timeout=3.0) as client:
            response = await client.get("/containers/json")
            containers_raw = response.json()
            
            containers = []
            for c in containers_raw:
                containers.append({
                    "ID": c.get("Id", "")[:12],
                    "Names": c.get("Names", [""])[0].lstrip("/"),
                    "Image": c.get("Image", ""),
                    "Status": c.get("Status", ""),
                    "State": c.get("State", ""),
                })
            return {"containers": containers, "count": len(containers)}
        
    except Exception as e:
        logger.error(f"Docker 상태 조회 실패: {e}")
        return {"containers": [], "count": 0, "error": str(e)}


@router.get("/rabbitmq")
@cache_response(ttl_seconds=5)
async def get_rabbitmq_status():
    """RabbitMQ 큐 상태 - 5초 캐싱"""
    try:
        rabbitmq_url = os.getenv("RABBITMQ_MANAGEMENT_URL", "http://127.0.0.1:15672")
        rabbitmq_user = os.getenv("RABBITMQ_USER", "guest")
        rabbitmq_pass = os.getenv("RABBITMQ_PASS", "guest")
        
        import base64
        auth = base64.b64encode(f"{rabbitmq_user}:{rabbitmq_pass}".encode()).decode()
        
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                f"{rabbitmq_url}/api/queues",
                headers={"Authorization": f"Basic {auth}"}
            )
            
            if response.status_code == 200:
                queues_raw = response.json()
                queues = []
                for q in queues_raw:
                    queues.append({
                        "name": q.get("name", ""),
                        "messages": q.get("messages", 0),
                        "messages_ready": q.get("messages_ready", 0),
                        "messages_unacknowledged": q.get("messages_unacknowledged", 0),
                        "consumers": q.get("consumers", 0),
                        "state": q.get("state", "unknown")
                    })
                return {"queues": queues, "count": len(queues)}
            else:
                return {"queues": [], "error": f"HTTP {response.status_code}"}
                
    except Exception as e:
        logger.error(f"RabbitMQ 상태 조회 실패: {e}")
        return {"queues": [], "error": str(e)}


@router.get("/scheduler")
async def get_scheduler_jobs_api():
    """Scheduler Jobs 상세 상태 - DB 직접 조회 (캐시 없음)"""
    try:
        from sqlalchemy import text
        with get_session() as session:
            result = session.execute(text("""
                SELECT 
                    job_id,
                    queue,
                    cron_expr,
                    interval_seconds,
                    enabled,
                    last_run_at,
                    last_status,
                    description,
                    created_at
                FROM jobs
                ORDER BY job_id
            """))
            
            jobs = []
            for row in result:
                interval = row.interval_seconds or 0
                if interval >= 3600:
                    interval_str = f"{interval // 3600}시간"
                elif interval >= 60:
                    interval_str = f"{interval // 60}분"
                elif interval > 0:
                    interval_str = f"{interval}초"
                else:
                    interval_str = row.cron_expr or "N/A"
                
                jobs.append({
                    "name": row.job_id,
                    "queue": row.queue,
                    "interval": interval_str,
                    "interval_seconds": interval,
                    "cron": row.cron_expr,
                    "is_active": row.enabled,
                    "last_run": row.last_run_at.isoformat() if row.last_run_at else None,
                    "last_status": row.last_status or "unknown",
                    "description": row.description,
                    "created_at": row.created_at.isoformat() if row.created_at else None
                })
            
            return {"jobs": jobs, "count": len(jobs)}
            
    except Exception as e:
        logger.error(f"Scheduler Jobs 조회 실패: {e}")
        return {"jobs": [], "error": str(e)}


@router.get("/logs/{container_name}")
@cache_response(ttl_seconds=2)
async def get_container_logs(
    container_name: str,
    limit: int = 100,
    since: str = "1h",
):
    """Loki 컨테이너 로그 조회 - 2초 캐싱"""
    try:
        loki_url = os.getenv("LOKI_URL", "http://127.0.0.1:3100")
        query = f'{{container="{container_name}"}}'
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{loki_url}/loki/api/v1/query_range",
                params={
                    "query": query,
                    "limit": limit,
                    "since": since,
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                logs = []
                
                results = data.get("data", {}).get("result", [])
                for stream in results:
                    for value in stream.get("values", []):
                        timestamp, log_line = value
                        from datetime import datetime
                        ts = datetime.fromtimestamp(int(timestamp) / 1e9)
                        logs.append({
                            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                            "message": log_line
                        })
                
                logs.sort(key=lambda x: x["timestamp"])
                
                return {
                    "container": container_name,
                    "logs": logs[-limit:],
                    "count": len(logs)
                }
            else:
                return {
                    "container": container_name,
                    "logs": [],
                    "error": f"Loki HTTP {response.status_code}"
                }
                
    except Exception as e:
        logger.error(f"로그 조회 실패 ({container_name}): {e}")
        return {
            "container": container_name,
            "logs": [],
            "error": str(e)
        }
@router.get("/realtime-monitor")
@cache_response(ttl_seconds=1)
async def get_realtime_monitor_status():
    """PriceMonitor 실시간 상태 조회 (Redis)"""
    try:
        r = get_redis_client()
        if not r:
            return {"status": "offline", "error": "Redis unavailable"}
        
        # 키 변경: monitoring:opportunity_watcher -> monitoring:price_monitor
        data = r.get("monitoring:price_monitor")
        if not data:
            return {"status": "offline", "message": "No heartbeat data"}
            
        hb_data = json.loads(data)
        # hb_data 구조: {"status": "online", "service": "price-monitor", "metrics": {...}}
        # 프론트엔드는 "metrics" 필드를 기대함
        return {
            "status": hb_data.get("status", "online"), 
            "metrics": hb_data.get("metrics", {})
        }
    except Exception as e:
        logger.error(f"Realtime Monitor 상태 조회 실패: {e}")
        return {"status": "error", "error": str(e)}
