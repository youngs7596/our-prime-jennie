"""
Dashboard Backend - Scheduler Proxy API

대시보드에서 스케줄러 서비스를 제어하기 위한 프록시 API입니다.
"""

import os
import httpx
import logging
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/scheduler",
    tags=["scheduler"],
    responses={404: {"description": "Not found"}},
)

# 스케줄러 서비스 URL
SCHEDULER_SERVICE_URL = os.getenv("SCHEDULER_SERVICE_URL", "http://scheduler-service:8000")
TIMEOUT = 10.0  # seconds


# === Pydantic Models ===

class JobInfo(BaseModel):
    job_id: str
    description: Optional[str] = None
    queue: str
    cron_expr: str
    enabled: bool
    reschedule_mode: str
    interval_seconds: Optional[int] = None
    timeout_sec: int
    next_due_at: Optional[str] = None
    last_run_at: Optional[str] = None
    last_status: Optional[str] = None


class JobUpdateRequest(BaseModel):
    cron_expr: Optional[str] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None
    timeout_sec: Optional[int] = None


class ManualRunRequest(BaseModel):
    params: Optional[Dict[str, Any]] = None
    trigger_source: str = "dashboard"


# === Helper Functions ===

async def _proxy_request(method: str, path: str, json_data: dict = None) -> dict:
    """스케줄러 서비스로 요청을 프록시합니다."""
    url = f"{SCHEDULER_SERVICE_URL}{path}"
    
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            if method == "GET":
                response = await client.get(url)
            elif method == "POST":
                response = await client.post(url, json=json_data or {})
            elif method == "PUT":
                response = await client.put(url, json=json_data or {})
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            if response.status_code >= 400:
                detail = response.json().get("detail", response.text) if response.text else "Unknown error"
                raise HTTPException(status_code=response.status_code, detail=detail)
            
            return response.json()
    
    except httpx.ConnectError as e:
        logger.error(f"스케줄러 서비스 연결 실패: {e}")
        raise HTTPException(status_code=503, detail="스케줄러 서비스에 연결할 수 없습니다")
    except httpx.TimeoutException:
        logger.error("스케줄러 서비스 타임아웃")
        raise HTTPException(status_code=504, detail="스케줄러 서비스 응답 시간 초과")


# === API Endpoints ===

@router.get("/jobs", response_model=List[Dict])
async def list_jobs():
    """
    스케줄러 작업 목록을 조회합니다.
    """
    return await _proxy_request("GET", "/jobs")


@router.get("/jobs/{job_id}", response_model=Dict)
async def get_job(job_id: str):
    """
    특정 스케줄러 작업 정보를 조회합니다.
    """
    jobs = await _proxy_request("GET", "/jobs")
    for job in jobs:
        if job.get("job_id") == job_id:
            return job
    raise HTTPException(status_code=404, detail=f"Job '{job_id}'를 찾을 수 없습니다")


@router.put("/jobs/{job_id}", response_model=Dict)
async def update_job(job_id: str, payload: JobUpdateRequest):
    """
    스케줄러 작업을 수정합니다.
    - cron_expr: 스케줄 표현식
    - enabled: 활성화 여부
    - description: 설명
    - timeout_sec: 타임아웃 (초)
    """
    update_data = payload.dict(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="수정할 내용이 없습니다")
    
    return await _proxy_request("PUT", f"/jobs/{job_id}", update_data)


@router.post("/jobs/{job_id}/run", response_model=Dict)
async def run_job(job_id: str, payload: ManualRunRequest = None):
    """
    스케줄러 작업을 즉시 실행합니다.
    """
    run_data = payload.dict() if payload else {"trigger_source": "dashboard"}
    return await _proxy_request("POST", f"/jobs/{job_id}/run", run_data)


@router.post("/jobs/{job_id}/pause", response_model=Dict)
async def pause_job(job_id: str):
    """
    스케줄러 작업을 일시정지합니다.
    """
    return await _proxy_request("POST", f"/jobs/{job_id}/pause")


@router.post("/jobs/{job_id}/resume", response_model=Dict)
async def resume_job(job_id: str):
    """
    스케줄러 작업을 재개합니다.
    """
    return await _proxy_request("POST", f"/jobs/{job_id}/resume")


@router.get("/health")
async def scheduler_health():
    """
    스케줄러 서비스 상태를 확인합니다.
    """
    try:
        return await _proxy_request("GET", "/health")
    except HTTPException as e:
        return {"status": "error", "detail": e.detail}
