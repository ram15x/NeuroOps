from fastapi import APIRouter, Depends, Request, BackgroundTasks
from sqlalchemy.orm import Session
import pandas as pd
import joblib
from datetime import datetime
import os
import numpy as np
from backend.core.config import settings
from backend.core.logger import get_logger
from backend.models.database import get_db, Alert, PredictionHistory, Service
from backend.models.schemas import MetricInput
from backend.services.redis_service import cache_alert, get_cached_alert
from backend.services.rate_limiter import limiter
from backend.services.explainer import load_explainer, explain_prediction
from backend.services.drift_detector import record_prediction, check_drift, get_drift_status
from backend.services.audit_logger import AuditLogger
from backend.api.auth import get_current_user
from backend.services.root_cause_analyzer import auto_analyze_anomaly
from backend.services.priority_ranker import calculate_alert_priority
from backend.services.aws_service import send_sns_alert_with_timeline
from backend.services.root_cause_timeline import get_timeline_for_alert

# Import hybrid detector
from backend.services.hybrid_anomaly_detector import hybrid_predict

router = APIRouter()
logger = get_logger(__name__)

# Load model for backward compatibility (hybrid detector also loads it)
model = None
scaler = None

model_path = os.path.join(settings.MODEL_PATH, settings.INFRAMIND_MODEL_FILE) if settings.MODEL_PATH else None
scaler_path = os.path.join(settings.MODEL_PATH, settings.INFRAMIND_SCALER_FILE) if settings.MODEL_PATH else None

if model_path and os.path.exists(model_path) and scaler_path and os.path.exists(scaler_path):
    try:
        model = joblib.load(model_path)
        scaler = joblib.load(scaler_path)
        logger.info("inframind_model_loaded")
    except Exception as e:
        logger.warning(f"Could not load InfraMind model: {e}")


def get_severity(score: float) -> str:
    """Legacy severity function - kept for compatibility"""
    if score < settings.SEVERITY_CRITICAL_THRESHOLD:
        return "critical"
    elif score < settings.SEVERITY_WARNING_THRESHOLD:
        return "warning"
    return "normal"


@router.post("/inframind/predict")
@limiter.limit(settings.RATE_LIMIT_POST)
def predict_anomaly(
    request: Request,
    data: MetricInput,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Hybrid Anomaly Detection - Combines Isolation Forest with Z-Score.
    """
    try:
        # Use hybrid detector (falls back to Z-Score if ML model unavailable)
        result = hybrid_predict(
            value=data.value,
            rolling_mean=data.rolling_mean,
            rolling_std=data.rolling_std,
            value_diff=data.value_diff,
            use_ml=True  # Set to False to force Z-Score only
        )
        
        record_prediction(result["is_anomaly"])
        
        # Build message
        if result["is_anomaly"]:
            message = f"Anomaly detected - {result['reason']}"
        else:
            message = "Normal"
        
        alert = Alert(
            metric_value=data.value,
            rolling_mean=data.rolling_mean,
            rolling_std=data.rolling_std,
            value_diff=data.value_diff,
            is_anomaly=result["is_anomaly"],
            severity=result["severity"],
            anomaly_score=result["combined_score"],
            message=f"Metric {data.metric} value {data.value} | {result['reason']}",
            priority_score=50
        )
        db.add(alert)
        db.commit()
        
        return {
            "metric": data.metric,
            "is_anomaly": result["is_anomaly"],
            "anomaly_score": result["combined_score"],
            "severity": result["severity"],
            "confidence": result["confidence"],
            "reason": result["reason"],
            "z_score": result["z_score"],
            "z_is_anomaly": result["z_is_anomaly"],
            "if_score": result["if_score"],
            "if_is_anomaly": result["if_is_anomaly"],
            "method": result["method"],
            "message": message
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Prediction failed: {e}")
        return {"error": str(e)}


@router.get("/inframind/drift")
def get_model_drift():
    return check_drift()


@router.get("/inframind/drift/status")
def drift_status():
    return get_drift_status()


@router.get("/alerts/priority")
def get_alerts_priority(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get alerts sorted by priority"""
    from backend.models.database import Alert
    alerts = db.query(Alert).filter(
        Alert.is_anomaly == True
    ).order_by(Alert.priority_score.desc()).limit(50).all()
    
    return {
        "alerts": [
            {
                "id": a.id,
                "severity": a.severity,
                "message": a.message,
                "priority_score": a.priority_score,
                "created_at": a.created_at.isoformat() if a.created_at else None
            }
            for a in alerts
        ]
    }