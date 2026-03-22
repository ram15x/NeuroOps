from fastapi import APIRouter, Request, BackgroundTasks
from backend.services.data_pipeline import run_full_pipeline
from backend.services.rate_limiter import limiter
from backend.services.task_manager import create_job, update_job
import json

router = APIRouter()


def run_pipeline_task(job_id: str):
    try:
        result = run_full_pipeline()
        update_job(job_id, "completed", result)
    except Exception as e:
        update_job(job_id, "failed", {"error": str(e)})


@router.post("/pipeline/run")
@limiter.limit("5/minute")
def trigger_pipeline(
    request: Request,
    background_tasks: BackgroundTasks
):
    try:
        from backend.services.task_manager import create_job
        job_id = create_job("data_pipeline")
        background_tasks.add_task(run_pipeline_task, job_id)

        return {
            "job_id" : job_id,
            "status" : "processing",
            "message": "Pipeline started. Poll /pipeline/result/{job_id} for result."
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/pipeline/result/{job_id}")
def get_pipeline_result(job_id: str):
    from backend.services.task_manager import get_job
    return get_job(job_id)


@router.get("/pipeline/status")
def pipeline_status():
    return {
        "pipeline" : "NeuroOps Data Pipeline",
        "stages"   : [
            "metrics_pipeline  — computes stats from NAB CloudWatch data",
            "failure_pipeline  — computes sensor averages from NASA Turbofan data",
            "drift_check       — checks InfraMind model drift status"
        ],
        "status"   : "ready"
    }