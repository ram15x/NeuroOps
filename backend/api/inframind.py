from fastapi import APIRouter, Depends, Request, BackgroundTasks
from sqlalchemy.orm import Session
import pandas as pd
import joblib
from datetime import datetime
import os

from backend.core.config import settings
from backend.core.logger import get_logger
from backend.models.database import get_db, Alert, PredictionHistory
from backend.models.schemas import MetricInput
from backend.services.redis_service import cache_alert, get_cached_alert
from backend.services.rate_limiter import limiter
from backend.services.explainer import load_explainer, explain_prediction
from backend.services.drift_detector import record_prediction, check_drift, get_drift_status
from backend.services.audit_logger import AuditLogger
from backend.api.auth import get_current_user
from backend.services.root_cause_analyzer import auto_analyze_anomaly

router = APIRouter()
logger = get_logger(__name__)

# build paths from config
MODEL_PATH = os.path.join(settings.MODEL_PATH, settings.INFRAMIND_MODEL_FILE)
SCALER_PATH = os.path.join(settings.MODEL_PATH, settings.INFRAMIND_SCALER_FILE)

model = joblib.load(MODEL_PATH)
scaler = joblib.load(SCALER_PATH)

# load background data for SHAP explainer
DATA_PATH = os.path.join(settings.DATA_PATH, "processed/metrics_clean.csv")
_bg_data = pd.read_csv(DATA_PATH)
_bg_data = _bg_data.sort_values("metric")
_bg_data["rolling_mean"] = _bg_data.groupby("metric")["value"].transform(
    lambda x: x.rolling(window=5, min_periods=1).mean()
)
_bg_data["rolling_std"] = _bg_data.groupby("metric")["value"].transform(
    lambda x: x.rolling(window=5, min_periods=1).std().fillna(0)
)
_bg_data["value_diff"] = _bg_data.groupby("metric")["value"].transform(
    lambda x: x.diff().fillna(0)
)
_bg_sample = _bg_data[["value", "rolling_mean", "rolling_std", "value_diff"]].dropna().sample(
    n=min(settings.SHAP_BACKGROUND_SAMPLES, len(_bg_data)), random_state=42
)
load_explainer(model, scaler, _bg_sample)


def predict_single_metric(
    data: MetricInput,
    db: Session,
    background_tasks: BackgroundTasks,
    current_user: dict,
    request: Request
) -> dict:
    """Core prediction logic reused for single and batch"""
    metric_name = data.metric

    cached = get_cached_alert(metric_name)
    if cached and not data.force:
        cached["from_cache"] = True
        return cached

    input_features = {
        "value": data.value,
        "rolling_mean": data.rolling_mean,
        "rolling_std": data.rolling_std,
        "value_diff": data.value_diff,
    }

    features = pd.DataFrame([input_features])
    X_scaled = scaler.transform(features)
    prediction = model.predict(X_scaled)[0]
    score = float(model.decision_function(X_scaled)[0])
    is_anomaly = bool(prediction == -1)
    record_prediction(is_anomaly)

    # additional rule-based check using config thresholds
    if data.value > settings.ANOMALY_VALUE_THRESHOLD and data.value_diff > settings.ANOMALY_VALUE_DIFF_THRESHOLD:
        is_anomaly = True
        score = settings.ANOMALY_FORCED_SCORE

    severity = get_severity(score)
    message = get_message(is_anomaly, data.value)

    explanation = explain_prediction(model, scaler, input_features)

    result = {
        "metric": metric_name,
        "status": "anomaly" if is_anomaly else "normal",
        "is_anomaly": is_anomaly,
        "anomaly_score": round(score, 4),
        "severity": severity,
        "message": message,
        "explanation": explanation,
        "saved_to_db": True,
        "from_cache": False
    }

    # store alert in database
    alert = Alert(
        metric_value=data.value,
        rolling_mean=data.rolling_mean,
        rolling_std=data.rolling_std,
        value_diff=data.value_diff,
        is_anomaly=is_anomaly,
        severity=severity,
        anomaly_score=score,
        message=message
    )
    db.add(alert)
    db.flush()

    # store prediction history for retraining
    prediction_history = PredictionHistory(
        model_name="inframind",
        input_features=input_features,
        prediction={
            "is_anomaly": is_anomaly,
            "anomaly_score": score,
            "severity": severity
        },
        confidence_score=abs(score) if is_anomaly else None,
        created_at=datetime.utcnow()
    )
    db.add(prediction_history)

    # audit log for anomaly detection
    if is_anomaly:
        AuditLogger.log(
            db=db,
            user_id=current_user.id,
            username=current_user.username,
            action="anomaly_detected",
            resource=metric_name,
            details={
                "value": data.value,
                "anomaly_score": score,
                "severity": severity,
                "explanation": explanation
            },
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent")
        )
        
        # AUTO ROOT CAUSE ANALYSIS - runs in background
        anomaly_data = {
            "metric_name": metric_name,
            "value": data.value,
            "anomaly_score": score,
            "severity": severity,
            "rolling_mean": data.rolling_mean,
            "rolling_std": data.rolling_std,
            "value_diff": data.value_diff
        }
        background_tasks.add_task(auto_analyze_anomaly, db, anomaly_data)
        
    else:
        AuditLogger.log(
            db=db,
            user_id=current_user.id,
            username=current_user.username,
            action="prediction",
            resource=metric_name,
            details={
                "value": data.value,
                "anomaly_score": score,
                "status": "normal"
            },
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent")
        )

    cache_alert(metric_name, result)
    
    return result


@router.post("/inframind/predict")
@limiter.limit(settings.RATE_LIMIT_POST)
def predict_anomaly(
    request: Request,
    data: MetricInput,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        result = predict_single_metric(data, db, background_tasks, current_user, request)
        db.commit()
        return result

    except Exception as e:
        db.rollback()
        return {"error": str(e)}


@router.post("/inframind/batch-predict")
@limiter.limit("10/minute")
def batch_predict_anomaly(
    request: Request,
    metrics: list[MetricInput],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Batch process multiple metrics in one call"""
    try:
        results = []
        success_count = 0
        error_count = 0
        
        for metric in metrics:
            try:
                result = predict_single_metric(metric, db, background_tasks, current_user, request)
                results.append(result)
                success_count += 1
            except Exception as e:
                results.append({
                    "metric": metric.metric,
                    "error": str(e),
                    "status": "failed"
                })
                error_count += 1
        
        db.commit()
        
        return {
            "total": len(metrics),
            "success": success_count,
            "errors": error_count,
            "timestamp": datetime.utcnow().isoformat(),
            "results": results
        }
        
    except Exception as e:
        db.rollback()
        return {
            "error": str(e),
            "total": len(metrics) if metrics else 0,
            "success": 0,
            "errors": len(metrics) if metrics else 0
        }


@router.get("/inframind/root-cause/{metric_name}")
def get_root_cause(metric_name: str, db: Session = Depends(get_db)):
    """Get cached root cause for a metric"""
    from backend.services.root_cause_analyzer import RootCauseAnalyzer
    analyzer = RootCauseAnalyzer(db)
    result = analyzer.get_cached_root_cause(metric_name)
    if result:
        return result
    return {"message": "No root cause analysis available", "metric": metric_name}


@router.get("/inframind/drift")
def get_model_drift():
    """Check if model has drifted"""
    return check_drift()


@router.get("/inframind/drift/status")
def drift_status():
    """Get cached drift status"""
    return get_drift_status()


@router.get("/inframind/history")
def get_prediction_history(
    limit: int = 50,
    db: Session = Depends(get_db),
    _: dict = Depends(get_current_user)
):
    """Get recent prediction history for charts"""
    try:
        history = db.query(Alert).order_by(Alert.created_at.desc()).limit(limit).all()
        return {
            "scores": [
                {
                    "value": h.anomaly_score,
                    "is_anomaly": h.is_anomaly,
                    "timestamp": h.created_at.isoformat()
                }
                for h in history
            ]
        }
    except Exception as e:
        return {"error": str(e)}


def get_severity(score: float) -> str:
    if score < settings.SEVERITY_CRITICAL_THRESHOLD:
        return "critical"
    elif score < settings.SEVERITY_WARNING_THRESHOLD:
        return "warning"
    else:
        return "normal"


def get_message(is_anomaly: bool, value: float) -> str:
    if is_anomaly:
        return f"ANOMALY DETECTED. Metric value {value} is abnormal."
    return f"NORMAL. Metric value {value} is within normal range."