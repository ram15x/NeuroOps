from fastapi import APIRouter, Depends, Request, BackgroundTasks
from sqlalchemy.orm import Session
from backend.models.database import get_db
from backend.services.redis_service import redis_client
from backend.services.rate_limiter import limiter
from backend.services.task_manager import create_job, update_job, get_job
import ollama
import json
from backend.models.schemas import LogInput, ClusterRequest
from backend.services.log_clusterer import run_log_clustering

router = APIRouter()


def run_analysis(job_id: str, log_text: str):
    # runs in background after API already returned
    try:
        prompt = f"""You are an expert cloud infrastructure engineer.
Analyze this system log and respond in this exact format:

SEVERITY: [critical/warning/info]
CAUSE: [one line root cause]
IMPACT: [one line business impact]
FIX: [one line recommended fix]

Log: {log_text}"""

        response = ollama.chat(
            model="phi3:mini",
            messages=[{"role": "user", "content": prompt}]
        )

        ai_response = response["message"]["content"]

        result = {
            "log"       : log_text,
            "analysis"  : ai_response,
            "severity"  : extract_field(ai_response, "SEVERITY"),
            "cause"     : extract_field(ai_response, "CAUSE"),
            "impact"    : extract_field(ai_response, "IMPACT"),
            "fix"       : extract_field(ai_response, "FIX"),
            "from_cache": False
        }

        cache_key = f"opsgpt:{hash(log_text)}"
        redis_client.setex(cache_key, 300, json.dumps(result))
        update_job(job_id, "completed", result)

    except Exception as e:
        update_job(job_id, "failed", {"error": str(e)})


@router.post("/opsgpt/analyze")
@limiter.limit("10/minute")
def analyze_log(
    request: Request,
    data: LogInput,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    log_text  = data.log
    cache_key = f"opsgpt:{hash(log_text)}"

    # return cached result immediately if exists
    cached = redis_client.get(cache_key)
    if cached:
        result = json.loads(cached)
        result["from_cache"] = True
        return result

    # start background job and return job id instantly
    job_id = create_job("opsgpt_analyze")
    background_tasks.add_task(run_analysis, job_id, log_text)

    return {
        "job_id" : job_id,
        "status" : "processing",
        "message": "Log analysis started. Poll /opsgpt/result/{job_id} for result."
    }


@router.get("/opsgpt/result/{job_id}")
def get_result(job_id: str):
    return get_job(job_id)


@router.post("/opsgpt/analyze-batch")
@limiter.limit("10/minute")
def analyze_batch(
    request: Request,
    data: dict,
    background_tasks: BackgroundTasks
):
    try:
        logs = data.get("logs", [])
        if not logs:
            return {"error": "No logs provided"}

        job_ids = []
        for log in logs[:5]:
            job_id = create_job("opsgpt_batch")
            background_tasks.add_task(run_analysis, job_id, log)
            job_ids.append(job_id)

        return {
            "message": "Batch analysis started",
            "job_ids": job_ids,
            "total"  : len(job_ids),
            "poll_at": "/api/v1/opsgpt/result/{job_id}"
        }

    except Exception as e:
        return {"error": str(e)}


def extract_field(text: str, field: str) -> str:
    for line in text.split("\n"):
        if line.startswith(f"{field}:"):
            return line.replace(f"{field}:", "").strip()
    return "unknown"

@router.post("/opsgpt/clusters")
@limiter.limit("10/minute")
def get_log_clusters(
    request: Request,
    data: ClusterRequest,
    db: Session = Depends(get_db)
):
    try:
        cache_key = f"opsgpt:clusters:{data.n_clusters}"

        cached = redis_client.get(cache_key)
        if cached:
            result = json.loads(cached)
            result["from_cache"] = True
            return result

        result = run_log_clustering(n_clusters=data.n_clusters)
        redis_client.setex(cache_key, 600, json.dumps(result))

        result["from_cache"] = False
        return result

    except Exception as e:
        return {"error": str(e)}