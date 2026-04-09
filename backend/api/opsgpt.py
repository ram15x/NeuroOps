from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
import json
from datetime import datetime

from backend.core.config import settings
from backend.models.database import get_db, PredictionHistory
from backend.services.redis_service import redis_client
from backend.services.rate_limiter import limiter
from backend.services.opsgpt_analyzer import analyze_log
from backend.models.schemas import LogInput, ClusterRequest
from backend.services.log_clusterer import run_log_clustering
from backend.services.audit_logger import AuditLogger
from backend.api.auth import get_current_user
from backend.services.priority_ranker import calculate_cluster_priority

router = APIRouter()


@router.post("/opsgpt/analyze")
@limiter.limit(settings.RATE_LIMIT_POST)
def analyze_log_endpoint(
    request: Request,
    data: LogInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Analyze log - synchronous, returns result directly"""
    try:
        log_text = data.log
        
        # Check cache first
        cache_key = f"opsgpt:{hash(log_text)}"
        cached = redis_client.get(cache_key)
        if cached:
            result = json.loads(cached)
            result["from_cache"] = True
            return result

        # Analyze directly (synchronous)
        result = analyze_log(log_text)
        
        # Store prediction history
        prediction_history = PredictionHistory(
            model_name="opsgpt",
            input_features={"log_preview": log_text[:200]},
            prediction={"severity": result.get("severity", "info")},
            created_at=datetime.utcnow()
        )
        db.add(prediction_history)
        db.commit()
        
        # Cache the result
        redis_client.setex(cache_key, settings.OPSGPT_CACHE_TTL, json.dumps(result))
        
        return result
    
    except Exception as e:
        return {"error": str(e)}


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
        
        if result.get("clusters"):
            for cluster_data in result["clusters"]:
                cluster_priority = calculate_cluster_priority(cluster_data, db)
                cluster_data["priority_score"] = cluster_priority["priority_score"]
                cluster_data["priority_rank"] = cluster_priority["priority_rank"]
            
            result["clusters"].sort(key=lambda x: x.get("priority_score", 0), reverse=True)
            for idx, cluster in enumerate(result["clusters"], 1):
                cluster["priority_rank"] = idx

        redis_client.setex(cache_key, settings.LOG_CLUSTER_CACHE_TTL, json.dumps(result))
        result["from_cache"] = False
        return result

    except Exception as e:
        return {"error": str(e)}


@router.get("/opsgpt/result/{job_id}")
def get_result(job_id: str):
    """Legacy endpoint - kept for compatibility"""
    return {"status": "completed", "result": {"message": "Use direct POST for results"}}
