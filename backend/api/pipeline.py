"""
NeuroOps Data Pipeline - Production Version
Processes real metrics, triggers retraining check, and updates feature store.
"""
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from backend.models.database import get_db, MetricHistory, Alert
from backend.services.redis_service import redis_client
from backend.api.auth import get_current_user
from backend.core.logger import get_logger
import uuid
import json
from datetime import datetime, timedelta

router = APIRouter()
logger = get_logger(__name__)

jobs = {}


def run_real_pipeline(job_id: str, db: Session):
    """Execute real data pipeline stages"""
    stages = []
    errors = []
    
    try:
        # STAGE 1: Metrics Pipeline - Aggregate recent metrics
        logger.info(f"[Pipeline {job_id}] Stage 1: Metrics aggregation")
        cutoff = datetime.utcnow() - timedelta(hours=1)
        
        cpu_metrics = db.query(MetricHistory).filter(
            MetricHistory.metric_name == 'cpu',
            MetricHistory.timestamp > cutoff
        ).all()
        
        memory_metrics = db.query(MetricHistory).filter(
            MetricHistory.metric_name == 'memory',
            MetricHistory.timestamp > cutoff
        ).all()
        
        # Calculate aggregates
        cpu_avg = sum(m.value for m in cpu_metrics) / len(cpu_metrics) if cpu_metrics else 0
        memory_avg = sum(m.value for m in memory_metrics) / len(memory_metrics) if memory_metrics else 0
        
        # Store in Redis
        redis_client.setex("pipeline:metrics:last_run", 3600, datetime.utcnow().isoformat())
        redis_client.setex("pipeline:metrics:cpu_avg", 3600, cpu_avg)
        redis_client.setex("pipeline:metrics:memory_avg", 3600, memory_avg)
        
        stages.append({
            "stage": "metrics_pipeline",
            "status": "completed",
            "records_processed": len(cpu_metrics) + len(memory_metrics),
            "cpu_avg": round(cpu_avg, 2),
            "memory_avg": round(memory_avg, 2)
        })
        
    except Exception as e:
        logger.error(f"[Pipeline {job_id}] Stage 1 failed: {e}")
        errors.append(str(e))
        stages.append({"stage": "metrics_pipeline", "status": "failed", "error": str(e)})
    
    try:
        # STAGE 2: Failure Pipeline - Check for anomalies and update feature store
        logger.info(f"[Pipeline {job_id}] Stage 2: Failure prediction data prep")
        
        # Get recent alerts
        cutoff = datetime.utcnow() - timedelta(hours=24)
        alerts = db.query(Alert).filter(
            Alert.is_anomaly == True,
            Alert.created_at > cutoff
        ).all()
        
        # Update feature store with alert patterns
        for alert in alerts[:10]:
            feature_key = f"feature:alert:{alert.id}"
            redis_client.setex(
                feature_key,
                86400,  # 24 hours
                json.dumps({
                    "severity": alert.severity,
                    "anomaly_score": alert.anomaly_score,
                    "message": alert.message,
                    "created_at": alert.created_at.isoformat()
                })
            )
        
        stages.append({
            "stage": "failure_pipeline",
            "status": "completed",
            "alerts_processed": len(alerts),
            "features_updated": min(len(alerts), 10)
        })
        
    except Exception as e:
        logger.error(f"[Pipeline {job_id}] Stage 2 failed: {e}")
        errors.append(str(e))
        stages.append({"stage": "failure_pipeline", "status": "failed", "error": str(e)})
    
    try:
        # STAGE 3: Drift Check - Verify model performance
        logger.info(f"[Pipeline {job_id}] Stage 3: Drift check")
        
        from backend.services.drift_detector import check_drift
        drift_result = check_drift()
        
        # Store drift status
        redis_client.setex("pipeline:drift:last_check", 3600, datetime.utcnow().isoformat())
        redis_client.setex("pipeline:drift:status", 3600, json.dumps(drift_result))
        
        stages.append({
            "stage": "drift_check",
            "status": "completed",
            "drift_detected": drift_result.get("drift_detected", False),
            "drift_amount": drift_result.get("drift_amount", "0%")
        })
        
    except Exception as e:
        logger.error(f"[Pipeline {job_id}] Stage 3 failed: {e}")
        errors.append(str(e))
        stages.append({"stage": "drift_check", "status": "failed", "error": str(e)})
    
    # STAGE 4: Trigger retraining check (if needed)
    try:
        from scripts.auto_retrain_volume import check_and_retrain
        retrain_result = check_and_retrain()
        stages.append({
            "stage": "retrain_check",
            "status": "completed",
            "retrain_triggered": retrain_result
        })
    except Exception as e:
        logger.warning(f"[Pipeline {job_id}] Retrain check skipped: {e}")
        stages.append({"stage": "retrain_check", "status": "skipped", "reason": str(e)})
    
    # Final result
    result = {
        "pipeline": "NeuroOps Data Pipeline",
        "job_id": job_id,
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": datetime.utcnow().isoformat(),
        "stages_run": len(stages),
        "errors": errors,
        "status": "completed" if not errors else "completed_with_errors",
        "stages": stages
    }
    
    jobs[job_id] = {"status": "completed", "result": result}
    logger.info(f"[Pipeline {job_id}] Completed with {len(errors)} errors")


@router.post("/pipeline/run")
def run_data_pipeline(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Run the NeuroOps data pipeline"""
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "processing", "result": None}
    
    # Run in background
    background_tasks.add_task(run_real_pipeline, job_id, db)
    
    logger.info(f"Pipeline started: {job_id}")
    return {
        "job_id": job_id,
        "status": "processing",
        "message": "Pipeline started. Poll /pipeline/result/{job_id} for status."
    }


@router.get("/pipeline/result/{job_id}")
def get_pipeline_result(
    job_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get pipeline execution result"""
    if job_id not in jobs:
        return {"status": "not_found", "message": "Job ID not found"}
    return jobs[job_id]


@router.get("/pipeline/status")
def get_pipeline_status(
    current_user: dict = Depends(get_current_user)
):
    """Get last pipeline run status from Redis"""
    last_run = redis_client.get("pipeline:metrics:last_run")
    cpu_avg = redis_client.get("pipeline:metrics:cpu_avg")
    memory_avg = redis_client.get("pipeline:metrics:memory_avg")
    drift_status = redis_client.get("pipeline:drift:status")
    
    return {
        "last_run": last_run.decode() if isinstance(last_run, bytes) else last_run,
        "cpu_avg_1h": float(cpu_avg) if cpu_avg else None,
        "memory_avg_1h": float(memory_avg) if memory_avg else None,
        "drift": json.loads(drift_status) if drift_status else None
    }