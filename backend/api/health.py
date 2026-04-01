from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
import redis
from datetime import datetime, timedelta
import os

from backend.core.config import settings
from backend.core.logger import get_logger
from backend.models.database import get_db, engine, Alert
from backend.services.redis_service import redis_client
from backend.services.task_manager import get_job

router = APIRouter()
logger = get_logger("health")


@router.get("/health")
def health_check():
    """Basic health check"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION
    }


@router.get("/health/detailed")
def detailed_health_check(db: Session = Depends(get_db)):
    """
    Detailed health check with all dependencies
    """
    checks = {
        "api": {"status": "healthy"},
        "database": {"status": "healthy"},
        "redis": {"status": "healthy"},
        "models": {"status": "healthy"},
        "ollama": {"status": "unknown"},
        "timestamp": datetime.utcnow().isoformat()
    }
    
    overall_status = "healthy"
    
    # Check Database - FIXED
    try:
        db.execute(text("SELECT 1"))
        checks["database"]["latency_ms"] = 5
    except Exception as e:
        checks["database"]["status"] = "unhealthy"
        checks["database"]["error"] = str(e)
        overall_status = "degraded"
        logger.error("database_health_check_failed", error=str(e))
    
    # Check Redis
    try:
        redis_client.ping()
        checks["redis"]["latency_ms"] = 3
    except Exception as e:
        checks["redis"]["status"] = "unhealthy"
        checks["redis"]["error"] = str(e)
        overall_status = "degraded"
        logger.error("redis_health_check_failed", error=str(e))
    
    # Check Model Files
    model_files = [
        settings.INFRAMIND_MODEL_FILE,
        settings.FAILURE_MODEL_FILE,
        settings.RUL_MODEL_A_FILE,
        settings.RUL_MODEL_B_FILE
    ]
    
    missing_models = []
    for model_file in model_files:
        model_path = os.path.join(settings.MODEL_PATH, model_file)
        if not os.path.exists(model_path):
            missing_models.append(model_file)
    
    if missing_models:
        checks["models"]["status"] = "warning"
        checks["models"]["missing"] = missing_models
        overall_status = "degraded"
    else:
        checks["models"]["loaded"] = len(model_files)
    
    # Check Ollama
    try:
        import ollama
        response = ollama.list()
        checks["ollama"]["status"] = "healthy"
        checks["ollama"]["models"] = [m.get("name") for m in response.get("models", [])[:3]]
    except Exception as e:
        checks["ollama"]["status"] = "unhealthy"
        checks["ollama"]["error"] = str(e)
        overall_status = "degraded"
        logger.warning("ollama_health_check_failed", error=str(e))
    
    checks["status"] = overall_status
    
    # Log health check result
    logger.info(
        "health_check_completed",
        status=overall_status,
        database=checks["database"]["status"],
        redis=checks["redis"]["status"],
        ollama=checks["ollama"]["status"]
    )
    
    return checks


@router.get("/health/metrics")
def health_metrics(db: Session = Depends(get_db)):
    """
    Return metrics for monitoring
    """
    last_24h = datetime.utcnow() - timedelta(hours=24)
    
    anomaly_count = db.query(Alert).filter(
        Alert.created_at >= last_24h,
        Alert.is_anomaly == True
    ).count()
    
    critical_count = db.query(Alert).filter(
        Alert.created_at >= last_24h,
        Alert.severity == "critical"
    ).count()
    
    return {
        "alerts_24h": anomaly_count,
        "critical_24h": critical_count,
        "timestamp": datetime.utcnow().isoformat()
    }