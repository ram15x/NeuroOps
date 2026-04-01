from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
import pandas as pd
import joblib
import json
import random
import hashlib
import os
from datetime import datetime

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

router = APIRouter()

# build paths from config
FAILURE_MODEL_PATH = os.path.join(settings.MODEL_PATH, settings.FAILURE_MODEL_FILE)
FAILURE_SCALER_PATH = os.path.join(settings.MODEL_PATH, settings.FAILURE_SCALER_FILE)

model = joblib.load(FAILURE_MODEL_PATH)
scaler = joblib.load(FAILURE_SCALER_PATH)

SENSOR_COLS = [f"sensor{i}" for i in range(1, settings.NUM_SENSORS + 1)]


def generate_varied_sensors(service_name: str, variation_strength: float = None) -> dict:
    """Generate realistic sensor variations for a service"""
    if variation_strength is None:
        variation_strength = settings.SENSOR_VARIATION_STRENGTH
    
    baseline = settings.SERVICE_BASELINES.get(
        service_name,
        settings.SERVICE_BASELINES["default"]
    )
    
    degradation_rate = settings.SERVICE_DEGRADATION_RATES.get(
        service_name,
        settings.SERVICE_DEGRADATION_RATES["default"]
    )
    
    seed = int(hashlib.md5(service_name.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    
    degradation_factor = 1.0 + (degradation_rate - 1.0) * rng.uniform(
        settings.DEGRADATION_FACTOR_MIN,
        settings.DEGRADATION_FACTOR_MAX
    )
    
    varied_sensors = {}
    for sensor_name, baseline_value in baseline.items():
        sensor_idx = int(sensor_name.replace("sensor", ""))
        
        if sensor_idx in settings.CRITICAL_SENSORS:
            sensor_degradation = degradation_factor * rng.uniform(
                settings.CRITICAL_SENSOR_DEGRADATION_MIN,
                settings.CRITICAL_SENSOR_DEGRADATION_MAX
            )
        elif sensor_idx in settings.MODERATE_SENSORS:
            sensor_degradation = degradation_factor * rng.uniform(
                settings.MODERATE_SENSOR_DEGRADATION_MIN,
                settings.MODERATE_SENSOR_DEGRADATION_MAX
            )
        else:
            sensor_degradation = rng.uniform(
                settings.STABLE_SENSOR_DEGRADATION_MIN,
                settings.STABLE_SENSOR_DEGRADATION_MAX
            )
        
        variation = rng.uniform(-variation_strength, variation_strength)
        varied_value = baseline_value * sensor_degradation * (1 + variation)
        
        if sensor_name in settings.SENSOR_VALUE_CAPS:
            max_val = settings.SENSOR_VALUE_CAPS[sensor_name]
            if varied_value > max_val:
                varied_value = baseline_value * settings.SENSOR_CAP_MULTIPLIER
        
        varied_sensors[sensor_name] = round(varied_value, 2)
    
    return varied_sensors


@router.post("/failure/predict")
def predict_failure(
    request: Request,
    data: FailureInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        unit_id = data.unit_id

        cache_key = f"failure:{unit_id}"
        cached = redis_client.get(cache_key)
        if cached:
            result = json.loads(cached)
            result["from_cache"] = True
            return result

        sensors = {col: getattr(data, col, 0) for col in SENSOR_COLS}
        X = pd.DataFrame([sensors])

        X_scaled = scaler.transform(X)
        prediction = model.predict(X_scaled)[0]
        probability = model.predict_proba(X_scaled)[0]

        will_fail = bool(prediction == 1)
        fail_prob = round(float(probability[1]) * 100, 2)

        if fail_prob >= settings.FAILURE_PROB_CRITICAL:
            risk = "CRITICAL"
            action = "Immediate maintenance required!"
        elif fail_prob >= settings.FAILURE_PROB_WARNING:
            risk = "WARNING"
            action = "Schedule maintenance soon."
        else:
            risk = "NORMAL"
            action = "System operating normally."

        result = {
            "unit_id": unit_id,
            "will_fail_soon": will_fail,
            "failure_prob": f"{fail_prob}%",
            "risk_level": risk,
            "action": action,
            "from_cache": False
        }

        # store prediction history
        prediction_history = PredictionHistory(
            model_name="failure_classifier",
            input_features=sensors,
            prediction={
                "will_fail_soon": will_fail,
                "failure_prob": fail_prob,
                "risk_level": risk
            },
            confidence_score=fail_prob / 100,
            created_at=datetime.utcnow()
        )
        db.add(prediction_history)

        # audit log for critical failures
        if risk == "CRITICAL":
            AuditLogger.log(
                db=db,
                user_id=current_user.id,
                username=current_user.username,
                action="critical_failure_prediction",
                resource=unit_id,
                details={
                    "failure_prob": fail_prob,
                    "action": action
                },
                ip_address=request.client.host,
                user_agent=request.headers.get("user-agent")
            )
        else:
            AuditLogger.log(
                db=db,
                user_id=current_user.id,
                username=current_user.username,
                action="failure_prediction",
                resource=unit_id,
                details={
                    "will_fail_soon": will_fail,
                    "failure_prob": fail_prob,
                    "risk_level": risk
                },
                ip_address=request.client.host,
                user_agent=request.headers.get("user-agent")
            )

        db.commit()
        redis_client.setex(cache_key, settings.FAILURE_CACHE_TTL, json.dumps(result))
        return result

    except Exception as e:
        return {"error": str(e)}


@router.get("/failure/status")
def failure_status():
    return {
        "module": "Failure Prediction",
        "model": "Random Forest",
        "accuracy": settings.FAILURE_MODEL_ACCURACY,
        "status": "active"
    }


@router.post("/failure/countdown")
@limiter.limit(settings.RATE_LIMIT_POST)
def failure_countdown(
    request: Request,
    data: FailureInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        sensor_values = [getattr(data, f"sensor{i}", 0) for i in range(1, settings.NUM_SENSORS + 1)]
        result = predict_rul(sensor_values)

        # Store prediction history
        prediction_history = PredictionHistory(
            model_name="rul_predictor",
            input_features={f"sensor{i}": sensor_values[i-1] for i in range(1, settings.NUM_SENSORS + 1)},
            prediction={
                "cycles_remaining": result["cycles_remaining"],
                "hours_remaining": result["hours_remaining"],
                "lower_bound": result.get("lower_bound"),
                "upper_bound": result.get("upper_bound"),
                "confidence_pct": result.get("confidence_pct"),
                "urgency": result["urgency"]
            },
            confidence_score=result.get("confidence_pct", 70) / 100,
            created_at=datetime.utcnow()
        )
        db.add(prediction_history)
        
        if result["urgency"] == "CRITICAL":
            AuditLogger.log(
                db=db,
                user_id=current_user.id,
                username=current_user.username,
                action="critical_rul_prediction",
                resource=data.unit_id,
                details={
                    "cycles_remaining": result["cycles_remaining"],
                    "hours_remaining": result["hours_remaining"],
                    "confidence_range": f"{result.get('lower_bound')}-{result.get('upper_bound')}"
                },
                ip_address=request.client.host,
                user_agent=request.headers.get("user-agent")
            )
        
        db.commit()

        return {
            "unit_id": data.unit_id,
            "cycles_remaining": result["cycles_remaining"],
            "hours_remaining": result["hours_remaining"],
            "confidence_interval": {
                "lower": result.get("lower_bound"),
                "upper": result.get("upper_bound"),
                "confidence": result.get("confidence_pct", 80)
            },
            "urgency": result["urgency"],
            "recommendation": result["recommendation"],
            "model": settings.RUL_MODEL_A_NAME
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
    try:
        results = []
        
        for service in data.services:
            service_name = service.service_name
            input_sensors = service.sensors
            
            if input_sensors and len(input_sensors) == settings.NUM_SENSORS:
                rng = random.Random(hash(service_name) % 1000)
                varied_sensors = {}
                for i, val in enumerate(input_sensors, 1):
                    sensor_name = f"sensor{i}"
                    variation = rng.uniform(
                        settings.SENSOR_VARIATION_MIN,
                        settings.SENSOR_VARIATION_MAX
                    )
                    varied_sensors[sensor_name] = round(val * variation, 2)
            else:
                varied_sensors = generate_varied_sensors(service_name)
            
            failure_kwargs = {"unit_id": service_name}
            for i in range(1, settings.NUM_SENSORS + 1):
                failure_kwargs[f"sensor{i}"] = varied_sensors.get(f"sensor{i}", 0)
            
            failure_input = FailureInput(**failure_kwargs)
            
            try:
                sensor_values = [getattr(failure_input, f"sensor{i}", 0) for i in range(1, settings.NUM_SENSORS + 1)]
                rul_result = predict_rul(sensor_values)
                
                results.append({
                    "service_name": service_name,
                    "rul_cycles": rul_result["cycles_remaining"],
                    "rul_hours": rul_result["hours_remaining"],
                    "urgency": rul_result["urgency"],
                    "recommendation": rul_result["recommendation"],
                    "sensor_variation_applied": not (input_sensors and len(input_sensors) == settings.NUM_SENSORS)
                })
            except Exception as e:
                results.append({
                    "service_name": service_name,
                    "error": str(e),
                    "rul_cycles": "N/A"
                })
        
        is_correlated = False
        correlation_analysis = {}
        
        if len(results) >= settings.CORRELATION_MIN_SERVICES:
            rul_values = [r["rul_cycles"] for r in results if "rul_cycles" in r and r["rul_cycles"] != "N/A"]
            
            if len(rul_values) >= settings.CORRELATION_MIN_SERVICES:
                max_rul = max(rul_values)
                min_rul = min(rul_values)
                range_rul = max_rul - min_rul
                
                is_correlated = range_rul < settings.CORRELATION_RUL_THRESHOLD
                
                correlation_analysis = {
                    "max_rul": max_rul,
                    "min_rul": min_rul,
                    "range": range_rul,
                    "avg_rul": sum(rul_values) / len(rul_values),
                    "correlation_threshold": settings.CORRELATION_RUL_THRESHOLD,
                    "is_correlated": is_correlated
                }
                
                if is_correlated:
                    correlation_analysis["message"] = settings.CORRELATION_MESSAGE_CORRELATED
                else:
                    correlation_analysis["message"] = settings.CORRELATION_MESSAGE_INDEPENDENT
        
        # audit log for correlation
        if is_correlated:
            AuditLogger.log(
                db=db,
                user_id=current_user.id,
                username=current_user.username,
                action="failure_correlation",
                resource="multi_service",
                details={
                    "services": [s["service_name"] for s in results],
                    "is_correlated": is_correlated,
                    "avg_rul": correlation_analysis.get("avg_rul")
                },
                ip_address=request.client.host,
                user_agent=request.headers.get("user-agent")
            )
        db.commit()
        
        return {
            "services": results,
            "is_correlated_failure": is_correlated,
            "correlation_analysis": correlation_analysis,
            "total_services": len(results),
            "services_at_risk": len([r for r in results if r.get("urgency") in settings.URGENCY_RISK_LEVELS])
        }

    except Exception as e:
        return {"error": str(e)}


@router.post("/failure/ab-test")
@limiter.limit(settings.RATE_LIMIT_POST)
def ab_test_models(
    request: Request,
    data: FailureInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    try:
        sensor_values = [getattr(data, f"sensor{i}", 0) for i in range(1, settings.NUM_SENSORS + 1)]
        result = run_ab_test(sensor_values)
        
        # audit log for A/B test
        AuditLogger.log(
            db=db,
            user_id=current_user.id,
            username=current_user.username,
            action="ab_test",
            resource=data.unit_id,
            details={
                "winner": result["winner"],
                "agreement_pct": result["agreement_pct"],
                "difference": result["difference_cycles"]
            },
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent")
        )
        db.commit()
        
        return {
            "unit_id": data.unit_id,
            **result
        }
 
    except Exception as e:
        return {"error": str(e)}


@router.get("/failure/health")
def failure_health():
    return {
        "status": "healthy",
        "models_loaded": {
            "binary_classifier": model is not None,
            "scaler": scaler is not None,
            "rul_predictor": True
        },
        "service_baselines_loaded": len(settings.SERVICE_BASELINES) - 1,
        "sensor_count": len(SENSOR_COLS)
    }
    
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
        from backend.services.redis_service import redis_client
        import json
        cached = redis_client.get(f"rul_prediction:{instance_id}")
        if cached:
            return json.loads(cached)
        return {"message": "No RUL prediction available", "instance_id": instance_id}
    except Exception as e:
        return {"error": str(e)}