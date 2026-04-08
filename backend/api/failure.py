from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
import pandas as pd
import joblib
import json
import os
from datetime import datetime
# Add this with other imports at the top
from backend.services.service_correlation import get_real_service_correlation
from backend.core.config import settings
from backend.models.database import get_db, PredictionHistory
from backend.services.redis_service import redis_client
from backend.services.rul_predictor import predict_rul
from backend.services.failure_correlator import correlate_failures
from backend.models.schemas import FailureInput, CorrelationRequest
from backend.services.rate_limiter import limiter
from backend.services.ab_tester import run_ab_test
from backend.services.audit_logger import AuditLogger
from backend.api.auth import get_current_user
from backend.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# load XGBoost failure model — safe load, no crash if file missing
FAILURE_MODEL_PATH = os.path.join(settings.MODEL_PATH, settings.FAILURE_MODEL_FILE)
model = None
_failure_model_ready = False

try:
    if os.path.exists(FAILURE_MODEL_PATH):
        model = joblib.load(FAILURE_MODEL_PATH)
        _failure_model_ready = True
        logger.info("failure_model_loaded", extra={"path": FAILURE_MODEL_PATH})
    else:
        logger.warning("failure_model_missing_degraded_mode", extra={"path": FAILURE_MODEL_PATH})
except Exception as e:
    logger.error("failure_model_load_failed", extra={"error": str(e)})

# XGBoost doesn't need scaler
scaler = None

# Define REAL EC2 feature columns (not 24 sensors)
REAL_FEATURES = ['cpu_usage', 'memory_usage', 'disk_usage', 'instance_age_days']


@router.post("/failure/predict")
def predict_failure(
    request: Request,
    data: dict,  # Accept JSON with real EC2 metrics
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Predict failure using REAL EC2 metrics (cpu, memory, disk, age)
    """
    try:
        # Extract REAL metrics from request
        cpu_usage = data.get("cpu_usage", 0)
        memory_usage = data.get("memory_usage", 0)
        disk_usage = data.get("disk_usage", 0)
        instance_age_days = data.get("instance_age_days", 30)
        unit_id = data.get("unit_id", "unknown")
        
        cache_key = f"failure:{unit_id}"
        cached = redis_client.get(cache_key)
        if cached:
            result = json.loads(cached)
            result["from_cache"] = True
            return result
        
        # Prepare features for XGBoost
        features = pd.DataFrame([[
            cpu_usage,
            memory_usage,
            disk_usage,
            instance_age_days
        ]], columns=REAL_FEATURES)
        
        # Predict
        prediction = model.predict(features)[0]
        probability = model.predict_proba(features)[0]
        
        will_fail = bool(prediction == 1)
        fail_prob = round(float(probability[1]) * 100, 2)
        
        if fail_prob >= 70:
            risk = "CRITICAL"
            action = "Immediate maintenance required! Scale up or investigate."
        elif fail_prob >= 40:
            risk = "WARNING"
            action = "Schedule maintenance soon. Monitor closely."
        else:
            risk = "NORMAL"
            action = "System operating normally."
        
        result = {
            "unit_id": unit_id,
            "will_fail_soon": will_fail,
            "failure_probability": fail_prob,
            "risk_level": risk,
            "action": action,
            "input_metrics": {
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage,
                "disk_usage": disk_usage,
                "instance_age_days": instance_age_days
            },
            "from_cache": False,
            "model_used": "xgboost_production"
        }
        
        # Store prediction history
        prediction_history = PredictionHistory(
            model_name="failure_predictor_xgboost",
            input_features={
                "cpu": cpu_usage,
                "memory": memory_usage,
                "disk": disk_usage,
                "age": instance_age_days
            },
            prediction={
                "will_fail_soon": will_fail,
                "failure_probability": fail_prob,
                "risk_level": risk
            },
            confidence_score=fail_prob / 100,
            created_at=datetime.utcnow()
        )
        db.add(prediction_history)
        
        # Audit log for critical failures
        if risk == "CRITICAL":
            AuditLogger.log(
                db=db,
                user_id=current_user.id,
                username=current_user.username,
                action="critical_failure_prediction",
                resource=unit_id,
                details={
                    "failure_probability": fail_prob,
                    "action": action,
                    "cpu": cpu_usage,
                    "memory": memory_usage,
                    "disk": disk_usage
                },
                ip_address=request.client.host,
                user_agent=request.headers.get("user-agent")
            )
        
        db.commit()
        redis_client.setex(cache_key, settings.FAILURE_CACHE_TTL, json.dumps(result))
        return result
        
    except Exception as e:
        logger.error(f"Failure prediction failed: {e}")
        return {"error": str(e)}


@router.post("/failure/countdown")
@limiter.limit(settings.RATE_LIMIT_POST)
def failure_countdown(
    request: Request,
    data: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """RUL countdown using REAL EC2 metrics"""
    try:
        cpu_usage = data.get("cpu_usage", 0)
        memory_usage = data.get("memory_usage", 0)
        disk_usage = data.get("disk_usage", 0)
        instance_age_days = data.get("instance_age_days", 30)
        unit_id = data.get("unit_id", "unknown")
        
        # Call RUL predictor with REAL metrics
        result = predict_rul(
            cpu_usage=cpu_usage,
            memory_usage=memory_usage,
            disk_usage=disk_usage,
            instance_age_days=instance_age_days
        )
        
        # Store prediction history
        prediction_history = PredictionHistory(
            model_name="rul_predictor_real",
            input_features={
                "cpu": cpu_usage,
                "memory": memory_usage,
                "disk": disk_usage,
                "age": instance_age_days
            },
            prediction={
                "cycles_remaining": result["cycles_remaining"],
                "hours_remaining": result["hours_remaining"],
                "urgency": result["urgency"]
            },
            confidence_score=result.get("confidence_pct", 80) / 100,
            created_at=datetime.utcnow()
        )
        db.add(prediction_history)
        
        if result["urgency"] == "CRITICAL":
            AuditLogger.log(
                db=db,
                user_id=current_user.id,
                username=current_user.username,
                action="critical_rul_prediction",
                resource=unit_id,
                details={
                    "cycles_remaining": result["cycles_remaining"],
                    "hours_remaining": result["hours_remaining"]
                },
                ip_address=request.client.host,
                user_agent=request.headers.get("user-agent")
            )
        
        db.commit()
        
        return {
            "unit_id": unit_id,
            "cycles_remaining": result["cycles_remaining"],
            "hours_remaining": result["hours_remaining"],
            "confidence_interval": {
                "lower": result.get("lower_bound"),
                "upper": result.get("upper_bound"),
                "confidence": result.get("confidence_pct", 80)
            },
            "urgency": result["urgency"],
            "recommendation": result["recommendation"],
            "model_used": "rul_real_model"
        }
        
    except Exception as e:
        logger.error(f"RUL prediction failed: {e}")
        return {"error": str(e)}


@router.get("/failure/latest/{instance_id}")
def get_latest_failure_prediction(
    instance_id: str,
    _: dict = Depends(get_current_user)
):
    """Get the latest cached failure prediction for an instance"""
    try:
        cached = redis_client.get(f"failure_prediction:{instance_id}")
        if cached:
            return json.loads(cached)
        return {"message": "No prediction available", "instance_id": instance_id}
    except Exception as e:
        return {"error": str(e)}


@router.get("/failure/rul-latest/{instance_id}")
def get_latest_rul_prediction(
    instance_id: str,
    _: dict = Depends(get_current_user)
):
    """Get the latest cached RUL prediction for an instance"""
    try:
        cached = redis_client.get(f"rul_prediction:{instance_id}")
        if cached:
            return json.loads(cached)
        return {"message": "No RUL prediction available", "instance_id": instance_id}
    except Exception as e:
        return {"error": str(e)}


@router.get("/failure/health")
def failure_health():
    return {
        "status": "healthy",
        "model_loaded": model is not None,
        "model_type": "xgboost_production",
        "features": REAL_FEATURES,
        "scaler_required": False
    }


# Keep legacy endpoints for backward compatibility (deprecated)
@router.post("/failure/ab-test")
@limiter.limit(settings.RATE_LIMIT_POST)
def ab_test_models(
    request: Request,
    data: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """A/B test using REAL metrics"""
    try:
        cpu_usage = data.get("cpu_usage", 0)
        memory_usage = data.get("memory_usage", 0)
        disk_usage = data.get("disk_usage", 0)
        instance_age_days = data.get("instance_age_days", 30)
        
        features = [[cpu_usage, memory_usage, disk_usage, instance_age_days]]
        result = run_ab_test(features)
        
        return {
            "unit_id": data.get("unit_id", "unknown"),
            **result
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/failure/correlate")
@limiter.limit(settings.RATE_LIMIT_POST)
def correlate_failure_services(
    request: Request,
    data: CorrelationRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Multi-service correlation using REAL metrics from database
    Now uses actual service metrics instead of synthetic data
    """
    try:
        from backend.services.service_correlation import get_real_service_correlation
        from backend.models.database import Service, MetricHistory
        from datetime import datetime, timedelta
        
        # Get service names from request or fetch all from DB
        service_names = [s.service_name for s in data.services] if data.services else None
        
        # Use the real correlation service
        result = get_real_service_correlation(db, service_names)
        
        # Enhance with RUL predictions for each service
        services_with_rul = []
        for service_name in result.get("correlated_services", []):
            # Get service metrics
            service = db.query(Service).filter(Service.service_name == service_name.get("service1")).first()
            if service:
                # Get latest metrics for this service
                latest_cpu = db.query(MetricHistory).filter(
                    MetricHistory.metric_name == 'cpu',
                    MetricHistory.instance_id.like(f'%{service_name.get("service1")}%')
                ).order_by(MetricHistory.timestamp.desc()).first()
                
                if latest_cpu:
                    rul_result = predict_rul(
                        cpu_usage=latest_cpu.value,
                        memory_usage=70,  # Default, will be replaced with real memory data
                        disk_usage=30,    # Default
                        instance_age_days=service.age_days if hasattr(service, 'age_days') else 30
                    )
                    services_with_rul.append({
                        "service_name": service_name.get("service1"),
                        "correlation_with": service_name.get("service2"),
                        "correlation_strength": service_name.get("correlation"),
                        "rul_cycles": rul_result.get("cycles_remaining", 0),
                        "urgency": rul_result.get("urgency", "UNKNOWN")
                    })
        
        return {
            "services": services_with_rul,
            "is_correlated_failure": result.get("is_correlated_failure", False),
            "total_services": result.get("total_services", 0),
            "correlation_analysis": {
                "correlated_pairs": result.get("correlated_services", []),
                "correlation_threshold": 0.5,
                "is_correlated": result.get("is_correlated_failure", False),
                "message": result.get("message", "No correlation detected")
            },
            "services_at_risk": len([s for s in services_with_rul if s.get("urgency") in ["CRITICAL", "HIGH"]]),
            "timestamp": datetime.utcnow().isoformat(),
            "data_source": "real_metrics"
        }
        
    except Exception as e:
        logger.error(f"Correlation failed: {e}")
        # Fallback to basic correlation using available data
        return _fallback_correlation(data, db)


def _fallback_correlation(data: CorrelationRequest, db: Session):
    """Fallback correlation using available metrics"""
    try:
        from backend.services.rul_predictor import predict_rul
        
        results = []
        for service in data.services:
            service_name = service.service_name
            sensors = service.sensors
            
            # Try to get real metrics for this service
            latest_metric = db.query(MetricHistory).filter(
                MetricHistory.metric_name == 'cpu',
                MetricHistory.instance_id.like(f'%{service_name}%')
            ).order_by(MetricHistory.timestamp.desc()).first()
            
            if latest_metric:
                cpu = latest_metric.value
                memory = 65  # Default until we have memory per service
                disk = 25    # Default
                age = 30     # Default
            else:
                # Use provided sensors or defaults
                cpu = sensors[0] if len(sensors) > 0 else 50
                memory = sensors[1] if len(sensors) > 1 else 40
                disk = sensors[2] if len(sensors) > 2 else 30
                age = sensors[3] if len(sensors) > 3 else 30
            
            rul_result = predict_rul(
                cpu_usage=cpu,
                memory_usage=memory,
                disk_usage=disk,
                instance_age_days=age
            )
            
            results.append({
                "service_name": service_name,
                "rul_cycles": rul_result["cycles_remaining"],
                "rul_hours": rul_result["hours_remaining"],
                "urgency": rul_result["urgency"],
                "recommendation": rul_result["recommendation"],
                "data_source": "real_metric" if latest_metric else "fallback"
            })
        
        # Determine correlation based on RUL values
        rul_values = [r["rul_cycles"] for r in results if isinstance(r["rul_cycles"], (int, float))]
        is_correlated = False
        if len(rul_values) >= 2:
            range_rul = max(rul_values) - min(rul_values)
            is_correlated = range_rul < 20
        
        return {
            "services": results,
            "is_correlated_failure": is_correlated,
            "total_services": len(results),
            "services_at_risk": len([r for r in results if r.get("urgency") in ["CRITICAL", "HIGH"]]),
            "data_source": "mixed"
        }
        
    except Exception as e:
        return {"error": str(e)}