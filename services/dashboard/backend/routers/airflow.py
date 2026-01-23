from fastapi import APIRouter, HTTPException, BackgroundTasks
import httpx
import os
from typing import List, Optional
from pydantic import BaseModel

router = APIRouter(prefix="/api/airflow", tags=["airflow"])

AIRFLOW_URL = os.getenv("AIRFLOW_URL", "http://localhost:8085")
# Airflow Default Auth (if configured) - Basic Auth usually required
# Ideally pass via env vars, but defaulting to admin:admin for internal MVP if auth on
AIRFLOW_AUTH = ("admin", "admin") 

class DagRun(BaseModel):
    dag_id: str
    run_id: str
    state: str
    execution_date: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class DagHelper:
    @staticmethod
    async def get_dags():
        async with httpx.AsyncClient() as client:
            try:
                # Limit to 100 for performance
                response = await client.get(
                    f"{AIRFLOW_URL}/api/v1/dags?limit=100", 
                    auth=AIRFLOW_AUTH
                )
                response.raise_for_status()
                return response.json()
            except httpx.RequestError as exc:
                print(f"An error occurred while requesting {exc.request.url!r}.")
                return {"dags": []}
            except httpx.HTTPStatusError as exc:
                print(f"Error response {exc.response.status_code} while requesting {exc.request.url!r}.")
                return {"dags": []}

    @staticmethod
    async def get_dag_runs(dag_id: str, limit: int = 5):
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{AIRFLOW_URL}/api/v1/dags/{dag_id}/dagRuns?limit={limit}&order_by=-execution_date",
                    auth=AIRFLOW_AUTH
                )
                response.raise_for_status()
                return response.json()
            except Exception as e:
                print(f"Error fetching runs for {dag_id}: {e}")
                return {"dag_runs": []}

    @staticmethod
    async def trigger_dag(dag_id: str, conf: dict = {}):
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{AIRFLOW_URL}/api/v1/dags/{dag_id}/dagRuns",
                    auth=AIRFLOW_AUTH,
                    json={"conf": conf}
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                raise HTTPException(status_code=exc.response.status_code, detail=str(exc.response.text))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

@router.get("/dags")
async def list_dags():
    """List all DAGs and their latest status summary"""
    dags_data = await DagHelper.get_dags()
    results = []
    
    # Filter for relevant DAGs to reduce noise? 
    # For now, return all active ones or user specific
    for dag in dags_data.get("dags", []):
        if dag.get("is_paused"):
            continue
            
        dag_id = dag["dag_id"]
        # Get latest run
        runs = await DagHelper.get_dag_runs(dag_id, limit=1)
        last_run = runs.get("dag_runs", [{}])[0]
        
        results.append({
            "dag_id": dag_id,
            "description": dag.get("description"),
            "schedule_interval": dag.get("schedule_interval"),
            "next_dagrun": dag.get("next_dagrun"),
            "last_run_state": last_run.get("state", "unknown"),
            "last_run_date": last_run.get("execution_date")
        })
    
    return results

@router.post("/dags/{dag_id}/trigger")
async def trigger_dag(dag_id: str):
    """Trigger a specific DAG"""
    return await DagHelper.trigger_dag(dag_id)
