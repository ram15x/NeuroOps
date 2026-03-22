from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from backend.models.database import get_db
from backend.services.redis_service import redis_client
from backend.services.rul_predictor import predict_rul
from backend.services.failure_correlator import correlate_failures
from backend.models.schemas import FailureInput, CorrelationRequest
from backend.services.rate_limiter import limiter
import pandas as pd
import joblib
from backend.services.ab_tester import run_ab_test
import json

router = APIRouter()

# load the binary classifier (will it fail soon yes/no)
model  = joblib.load("ml_models/saved/failure_model.pkl")
scaler = joblib.load("ml_models/saved/failure_scaler.pkl")

SENSOR_COLS = [f"sensor{i}" for i in range(1, 25)]


@router.post("/failure/predict")
def predict_failure(data: FailureInput):
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

        X_scaled    = scaler.transform(X)
        prediction  = model.predict(X_scaled)[0]
        probability = model.predict_proba(X_scaled)[0]

        will_fail   = bool(prediction == 1)
        fail_prob   = round(float(probability[1]) * 100, 2)
        normal_prob = round(float(probability[0]) * 100, 2)

        if fail_prob >= 70:
            risk   = "CRITICAL"
            action = "Immediate maintenance required!"
        elif fail_prob >= 40:
            risk   = "WARNING"
            action = "Schedule maintenance soon."
        else:
            risk   = "NORMAL"
            action = "System operating normally."

        result = {
            "unit_id"       : unit_id,
            "will_fail_soon": will_fail,
            "failure_prob"  : f"{fail_prob}%",
            "normal_prob"   : f"{normal_prob}%",
            "risk_level"    : risk,
            "action"        : action,
            "from_cache"    : False
        }

        redis_client.setex(cache_key, 120, json.dumps(result))
        return result

    except Exception as e:
        return {"error": str(e)}


@router.get("/failure/status")
def failure_status():
    return {
        "module"  : "Failure Prediction",
        "model"   : "Random Forest",
        "accuracy": "96%",
        "status"  : "active"
    }


@router.post("/failure/countdown")
@limiter.limit("20/minute")
def failure_countdown(
    request: Request,
    data: FailureInput
):
    try:
        sensor_values = [
            data.sensor1,  data.sensor2,  data.sensor3,  data.sensor4,
            data.sensor5,  data.sensor6,  data.sensor7,  data.sensor8,
            data.sensor9,  data.sensor10, data.sensor11, data.sensor12,
            data.sensor13, data.sensor14, data.sensor15, data.sensor16,
            data.sensor17, data.sensor18, data.sensor19, data.sensor20,
            data.sensor21, data.sensor22, data.sensor23, data.sensor24
        ]

        result = predict_rul(sensor_values)

        return {
            "unit_id"         : data.unit_id,
            "cycles_remaining": result["cycles_remaining"],
            "hours_remaining" : result["hours_remaining"],
            "urgency"         : result["urgency"],
            "recommendation"  : result["recommendation"],
            "model"           : "RandomForestRegressor (RUL)"
        }

    except Exception as e:
        return {"error": str(e)}


@router.post("/failure/correlate")
@limiter.limit("10/minute")
def correlate_failure_services(
    request: Request,
    data: CorrelationRequest
):
    try:
        services = [
            {
                "service_name": svc.service_name,
                "sensors"     : svc.sensors
            }
            for svc in data.services
        ]

        result = correlate_failures(services)
        return result

    except Exception as e:
        return {"error": str(e)}
    
    
@router.post("/failure/ab-test")
@limiter.limit("10/minute")
def ab_test_models(
    request: Request,
    data: FailureInput
):
    try:
        sensor_values = [
            data.sensor1,  data.sensor2,  data.sensor3,  data.sensor4,
            data.sensor5,  data.sensor6,  data.sensor7,  data.sensor8,
            data.sensor9,  data.sensor10, data.sensor11, data.sensor12,
            data.sensor13, data.sensor14, data.sensor15, data.sensor16,
            data.sensor17, data.sensor18, data.sensor19, data.sensor20,
            data.sensor21, data.sensor22, data.sensor23, data.sensor24
        ]
 
        result = run_ab_test(sensor_values)
 
        return {
            "unit_id": data.unit_id,
            **result
        }
 
    except Exception as e:
        return {"error": str(e)}