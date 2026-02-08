"""
job-worker: Airflow job 실행 전용 워커 서비스

Airflow DAG에서 curl로 호출하면, 등록된 스크립트를 subprocess로 실행.
- 동기 응답: job 완료까지 대기 후 200/500 반환
- subprocess 방식: 기존 스크립트 코드 수정 없이 그대로 실행
"""

import logging
import os
import subprocess
import time
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("job-worker")

app = FastAPI(title="Job Worker", version="1.0.0")

# ==============================================================================
# Job Registry
# ==============================================================================
# cmd: 실행 명령어 리스트 (또는 "dynamic" → 별도 핸들러)
# timeout: 최대 실행 시간 (초)

JOB_REGISTRY = {
    # utility_jobs_dag.py
    "analyst-feedback": {
        "cmd": ["python", "scripts/update_analyst_feedback.py"],
        "timeout": 120,
    },
    "collect-minute-chart": {
        "cmd": ["python", "scripts/collect_minute_chart.py"],
        "timeout": 300,
    },
    "collect-investor-trading": {
        "cmd": ["python", "scripts/collect_investor_trading.py"],
        "timeout": 600,
    },
    "collect-dart-filings": {
        "cmd": ["python", "scripts/collect_dart_filings.py"],
        "timeout": 300,
    },
    "collect-foreign-holding": {
        "cmd": ["python", "scripts/collect_foreign_holding_ratio.py", "--days", "1"],
        "timeout": 300,
    },
    "cleanup-old-data": {
        "cmd": ["python", "scripts/cleanup_old_data.py"],
        "timeout": 600,
    },
    "update-naver-sectors": {
        "cmd": ["python", "utilities/update_naver_sectors.py"],
        "timeout": 900,
    },
    # enhanced_macro_collection_dag.py
    "macro-collect-global": {
        "cmd": ["python", "scripts/collect_enhanced_macro.py", "--sources", "finnhub,fred"],
        "timeout": 300,
    },
    "macro-collect-korea": {
        "cmd": "dynamic",
        "timeout": 300,
    },
    "macro-validate-store": {
        "cmd": ["python", "scripts/collect_enhanced_macro.py"],
        "timeout": 180,
    },
    "macro-quick": {
        "cmd": ["python", "scripts/collect_enhanced_macro.py", "--quick"],
        "timeout": 120,
    },
    # macro_council_dag.py
    "macro-council": {
        "cmd": ["python", "scripts/run_macro_council.py"],
        "timeout": 600,
    },
    # host_consolidated_dag.py
    "weekly-factor-analysis": {
        "cmd": ["python", "scripts/weekly_factor_analysis_batch.py", "--analysis-only"],
        "timeout": 1800,
    },
    "collect-full-market-data": {
        "cmd": ["python", "scripts/collect_full_market_data_parallel.py"],
        "timeout": 600,
    },
    "analyze-ai-performance": {
        "cmd": ["python", "scripts/analyze_ai_performance.py"],
        "timeout": 300,
    },
    # daily_asset_snapshot_dag.py
    "daily-asset-snapshot": {
        "cmd": "dynamic",
        "timeout": 300,
    },
}


# ==============================================================================
# Dynamic command builders
# ==============================================================================

def _build_macro_collect_korea_cmd() -> list[str]:
    """한국 매크로 데이터 수집 - 시간대별 소스 분기."""
    hour = datetime.now(KST).hour
    # 11시대 실행 시 pykrx 스킵 (장중 enhanced_macro_quick이 이미 수집)
    sources = "bok_ecos,rss" if hour == 11 else "bok_ecos,pykrx,rss"
    return ["python", "scripts/collect_enhanced_macro.py", "--sources", sources]


def _build_daily_asset_snapshot_cmd(request: Request) -> list[str]:
    """일일 자산 스냅샷 - 날짜 파라미터 수신."""
    date_str = request.query_params.get("date", datetime.now(KST).strftime("%Y-%m-%d"))
    return ["python", "scripts/daily_asset_snapshot.py", "--date", date_str]


DYNAMIC_BUILDERS = {
    "macro-collect-korea": lambda req: _build_macro_collect_korea_cmd(),
    "daily-asset-snapshot": lambda req: _build_daily_asset_snapshot_cmd(req),
}


# ==============================================================================
# Endpoints
# ==============================================================================

@app.get("/health")
def health():
    return {"status": "ok", "service": "job-worker", "jobs": len(JOB_REGISTRY)}


@app.post("/jobs/{job_name}")
def run_job(job_name: str, request: Request):
    """범용 job 실행 엔드포인트."""
    if job_name not in JOB_REGISTRY:
        return JSONResponse(
            status_code=404,
            content={"error": f"Unknown job: {job_name}", "available": list(JOB_REGISTRY.keys())},
        )

    job = JOB_REGISTRY[job_name]
    timeout = job["timeout"]

    # Resolve command
    if job["cmd"] == "dynamic":
        builder = DYNAMIC_BUILDERS.get(job_name)
        if not builder:
            return JSONResponse(
                status_code=500,
                content={"error": f"No dynamic builder for job: {job_name}"},
            )
        cmd = builder(request)
    else:
        cmd = job["cmd"]

    logger.info(f"[{job_name}] Starting: {' '.join(cmd)} (timeout={timeout}s)")
    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd="/app",
            env={**os.environ, "PYTHONPATH": "/app"},
        )
        elapsed = time.time() - start_time

        if result.returncode == 0:
            logger.info(f"[{job_name}] Completed in {elapsed:.1f}s")
            # Truncate stdout to avoid huge responses
            stdout_tail = result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout
            return {
                "job": job_name,
                "status": "success",
                "returncode": 0,
                "elapsed_seconds": round(elapsed, 1),
                "stdout_tail": stdout_tail,
            }
        else:
            logger.error(f"[{job_name}] Failed (exit={result.returncode}) in {elapsed:.1f}s")
            logger.error(f"[{job_name}] stderr: {result.stderr[-1000:]}")
            return JSONResponse(
                status_code=500,
                content={
                    "job": job_name,
                    "status": "failed",
                    "returncode": result.returncode,
                    "elapsed_seconds": round(elapsed, 1),
                    "stderr_tail": result.stderr[-2000:] if result.stderr else "",
                    "stdout_tail": result.stdout[-1000:] if result.stdout else "",
                },
            )

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        logger.error(f"[{job_name}] Timeout after {elapsed:.1f}s (limit={timeout}s)")
        return JSONResponse(
            status_code=500,
            content={
                "job": job_name,
                "status": "timeout",
                "elapsed_seconds": round(elapsed, 1),
                "timeout_limit": timeout,
            },
        )
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[{job_name}] Exception: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "job": job_name,
                "status": "error",
                "elapsed_seconds": round(elapsed, 1),
                "error": str(e),
            },
        )


# ==============================================================================
# Entry point
# ==============================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8095))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
