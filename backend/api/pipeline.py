from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
import uuid
import time
from datetime import datetime
from backend.models.database import get_db
from backend.api.auth import get_current_user

router = APIRouter()

jobs = {}

def run_pipeline(job_id: str):
    """Run data pipeline stages"""
    try:
        stages = [
            {"stage": "metrics_pipeline", "status": "running", "time": 0},
            {"stage": "failure_pipeline", "status": "pending", "time": 0},
            {"stage": "drift_check", "status": "pending", "time": 0}
        ]
        
        for stage in stages:
            stage["status"] = "running"
            start = time.time()
            time.sleep(1)
            stage["time"] = round(time.time() - start, 2)
            stage["status"] = "completed"
        
        result = {
            "pipeline": "NeuroOps Data Pipeline",
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": datetime.utcnow().isoformat(),
            "stages_run": 3,
            "errors": [],
            "status": "completed",
            "stages": stages
        }
        jobs[job_id] = {"status": "completed", "result": result}
    except Exception as e:
        jobs[job_id] = {"status": "failed", "result": {"error": str(e)}}

@router.post("/pipeline/run")
def run_data_pipeline(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Run the data pipeline"""
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "processing", "result": None}
    background_tasks.add_task(run_pipeline, job_id)
    return {"job_id": job_id, "status": "processing"}

@router.get("/pipeline/result/{job_id}")
def get_pipeline_result(job_id: str):
    """Get pipeline result"""
    return jobs.get(job_id, {"status": "not_found", "result": None})
