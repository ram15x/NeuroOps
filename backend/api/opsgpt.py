from fastapi import APIRouter, Depends, Request, BackgroundTasks
from sqlalchemy.orm import Session
import json
from datetime import datetime
import uuid

from backend.core.config import settings
from backend.models.database import get_db, PredictionHistory, AlertCluster
from backend.services.redis_service import redis_client
from backend.services.rate_limiter import limiter
from backend.services.task_manager import create_job, update_job, get_job
from backend.services.opsgpt_analyzer import analyze_log  # NEW: use two-tier analyzer
from backend.models.schemas import LogInput, ClusterRequest
from backend.services.log_clusterer import run_log_clustering
from backend.services.audit_logger import AuditLogger
from backend.api.auth import get_current_user
from backend.services.priority_ranker import calculate_cluster_priority

router = APIRouter()

# Simple in-memory job store (replace with Redis in production)
jobs = {}


def run_analysis_task(job_id: str, log_text: str, user_id=None, username=None):
    """Background task using two-tier analyzer"""
    try:
        # Use the new two-tier analyzer
        result = analyze_log(log_text)
        
        # Cache the result
        cache_key = f"opsgpt:{hash(log_text)}"
        redis_client.setex(cache_key, settings.OPSGPT_CACHE_TTL, json.dumps(result))
        
        update_job(job_id, "completed", result)
        
    except Exception as e:
        update_job(job_id, "failed", {"error": str(e)})


@router.post("/opsgpt/analyze")
@limiter.limit(settings.RATE_LIMIT_POST)
def analyze_log_endpoint(
    request: Request,
    data: LogInput,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        log_text = data.log
        
        # Check cache first
        cache_key = f"opsgpt:{hash(log_text)}"
        cached = redis_client.get(cache_key)
        if cached:
            result = json.loads(cached)
            result["from_cache"] = True
            return result

        # Create job
        job_id = str(uuid.uuid4())
        jobs[job_id] = {"status": "processing", "result": None}
        
        # Store prediction history
        prediction_history = PredictionHistory(
            model_name="opsgpt",
            input_features={"log_preview": log_text[:200]},
            prediction={},
            confidence_score=None,
            created_at=datetime.utcnow()
        )
        db.add(prediction_history)
        db.flush()
        
        # Audit log
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
        
        # Run background task
        background_tasks.add_task(run_analysis_task, job_id, log_text, current_user.id, current_user.username)

        return {
            "job_id": job_id,
            "status": "processing",
            "message": "Log analysis started. Poll /opsgpt/result/{job_id} for result."
        }
    
    except Exception as e:
        return {"error": str(e)}


@router.get("/opsgpt/result/{job_id}")
def get_result(job_id: str):
    """Get analysis result"""
    job = jobs.get(job_id, {"status": "not_found", "result": None})
    return job


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
            job_id = str(uuid.uuid4())
            jobs[job_id] = {"status": "processing", "result": None}
            background_tasks.add_task(run_analysis_task, job_id, log, current_user.id, current_user.username)
            job_ids.append(job_id)

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
                cluster_priority = calculate_cluster_priority(
                    cluster_data=cluster_data,
                    db=db
                )
                cluster_data["priority_score"] = cluster_priority["priority_score"]
                cluster_data["priority_rank"] = cluster_priority["priority_rank"]
                
                cluster_id = f"cluster_{cluster_data['cluster_id']}"
                existing_cluster = db.query(AlertCluster).filter(
                    AlertCluster.cluster_id == cluster_id
                ).first()
                
                if existing_cluster:
                    existing_cluster.total_alerts = cluster_data["count"]
                    existing_cluster.priority_score = cluster_priority["priority_score"]
                    existing_cluster.priority_rank = cluster_priority["priority_rank"]
                    existing_cluster.last_seen = datetime.utcnow()
                    existing_cluster.occurrence_count_7d += 1
                else:
                    new_cluster = AlertCluster(
                        cluster_id=cluster_id,
                        root_cause_pattern=cluster_data.get("representative", ""),
                        total_alerts=cluster_data["count"],
                        severity_distribution={"critical": 0, "warning": 0, "normal": 0},
                        affected_services=cluster_data.get("services", []),
                        priority_score=cluster_priority["priority_score"],
                        priority_rank=cluster_priority["priority_rank"],
                        occurrence_count_7d=1,
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow()
                    )
                    db.add(new_cluster)
            
            result["clusters"].sort(key=lambda x: x.get("priority_score", 0), reverse=True)
            
            for idx, cluster in enumerate(result["clusters"], 1):
                cluster["priority_rank"] = idx
            
            db.commit()

        redis_client.setex(cache_key, settings.LOG_CLUSTER_CACHE_TTL, json.dumps(result))

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
        db.rollback()
        return {"error": str(e)}


@router.get("/opsgpt/clusters/ranked")
def get_ranked_clusters_endpoint(
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user)
):
    """Get all clusters sorted by priority"""
    try:
        clusters = db.query(AlertCluster).filter(
            AlertCluster.status == "active"
        ).order_by(AlertCluster.priority_score.desc()).all()
        
        return {
            "clusters": [
                {
                    "cluster_id": c.cluster_id,
                    "root_cause_pattern": c.root_cause_pattern,
                    "total_alerts": c.total_alerts,
                    "priority_score": c.priority_score,
                    "priority_rank": idx + 1,
                    "occurrence_count_7d": c.occurrence_count_7d,
                    "status": c.status,
                    "first_seen": c.first_seen.isoformat() if c.first_seen else None,
                    "last_seen": c.last_seen.isoformat() if c.last_seen else None
                }
                for idx, c in enumerate(clusters)
            ]
        }
    except Exception as e:
        return {"error": str(e)}