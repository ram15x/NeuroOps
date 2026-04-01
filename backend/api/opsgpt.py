from fastapi import APIRouter, Depends, Request, BackgroundTasks
from sqlalchemy.orm import Session
import ollama
import json
from datetime import datetime

from backend.core.config import settings
from backend.models.database import get_db, PredictionHistory
from backend.services.redis_service import redis_client
from backend.services.rate_limiter import limiter
from backend.services.task_manager import create_job, update_job, get_job
from backend.models.schemas import LogInput, ClusterRequest
from backend.services.log_clusterer import run_log_clustering
from backend.services.audit_logger import AuditLogger
from backend.api.auth import get_current_user

router = APIRouter()


def run_analysis(job_id: str, log_text: str, user_id=None, username=None):
    try:
        prompt = f"""You are an expert cloud infrastructure engineer.
Analyze this system log and respond in this exact format:

SEVERITY: [critical/warning/info]
CAUSE: [one line root cause]
IMPACT: [one line business impact]
FIX: [one line recommended fix]

Log: {log_text}"""

        response = ollama.chat(
            model=settings.OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"timeout": settings.OLLAMA_TIMEOUT}
        )

        ai_response = response["message"]["content"]
        severity = extract_field(ai_response, "SEVERITY")

        result = {
            "log": log_text,
            "analysis": ai_response,
            "severity": severity,
            "cause": extract_field(ai_response, "CAUSE"),
            "impact": extract_field(ai_response, "IMPACT"),
            "fix": extract_field(ai_response, "FIX"),
            "from_cache": False
        }

        cache_key = f"opsgpt:{hash(log_text)}"
        redis_client.setex(cache_key, settings.OPSGPT_CACHE_TTL, json.dumps(result))
        update_job(job_id, "completed", result)

    except Exception as e:
        update_job(job_id, "failed", {"error": str(e)})


@router.post("/opsgpt/analyze")
@limiter.limit(settings.RATE_LIMIT_POST)
def analyze_log(
    request: Request,
    data: LogInput,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        log_text = data.log
        cache_key = f"opsgpt:{hash(log_text)}"
        cached = redis_client.get(cache_key)
        if cached:
            result = json.loads(cached)
            result["from_cache"] = True
            return result

        job_id = create_job("opsgpt_analyze", {"log": log_text[:500]})
        
        # store prediction history
        prediction_history = PredictionHistory(
            model_name="opsgpt",
            input_features={"log_preview": log_text[:200]},
            prediction={},
            confidence_score=None,
            created_at=datetime.utcnow()
        )
        db.add(prediction_history)
        db.flush()
        
        # audit log
        AuditLogger.log(
            db=db,
            user_id=current_user.id,
            username=current_user.username,
            action="llm_analysis",
            resource="opsgpt",
            details={"log_preview": log_text[:100], "job_id": job_id},
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent")
        )
        db.commit()
        
        background_tasks.add_task(run_analysis, job_id, log_text, current_user.id, current_user.username)

        return {
            "job_id": job_id,
            "status": "processing",
            "message": "Log analysis started. Poll /opsgpt/result/{job_id} for result."
        }
    
    except Exception as e:
        return {"error": str(e)}


@router.get("/opsgpt/result/{job_id}")
def get_result(job_id: str):
    return get_job(job_id)


@router.post("/opsgpt/analyze-batch")
@limiter.limit(settings.RATE_LIMIT_POST)
def analyze_batch(
    request: Request,
    data: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        logs = data.get("logs", [])
        if not logs:
            return {"error": "No logs provided"}

        job_ids = []
        for log in logs[:settings.OPSGPT_BATCH_MAX]:
            job_id = create_job("opsgpt_batch", {"log": log[:500]})
            background_tasks.add_task(run_analysis, job_id, log, current_user.id, current_user.username)
            job_ids.append(job_id)

        # audit log for batch
        AuditLogger.log(
            db=db,
            user_id=current_user.id,
            username=current_user.username, 
            action="llm_batch_analysis",
            resource="opsgpt",
            details={"batch_size": len(job_ids), "job_ids": job_ids},
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent")
        )
        db.commit()

        return {
            "message": "Batch analysis started",
            "job_ids": job_ids,
            "total": len(job_ids),
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
@limiter.limit(settings.RATE_LIMIT_POST)
def get_log_clusters(
    request: Request,
    data: ClusterRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        cache_key = f"opsgpt:clusters:{data.n_clusters}"

        cached = redis_client.get(cache_key)
        if cached:
            result = json.loads(cached)
            result["from_cache"] = True
            return result

        result = run_log_clustering(n_clusters=data.n_clusters)
        redis_client.setex(cache_key, settings.LOG_CLUSTER_CACHE_TTL, json.dumps(result))

        # audit log for clustering
        AuditLogger.log(
            db=db,
            user_id=current_user.id,
            username=current_user.username,
            action="log_clustering",
            resource="opsgpt",
            details={"n_clusters": data.n_clusters, "total_logs": result.get("total_logs_analyzed")},
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent")
        )
        db.commit()

        result["from_cache"] = False
        return result

    except Exception as e:
        return {"error": str(e)}