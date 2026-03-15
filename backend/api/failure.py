from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.models.database import get_db
from backend.services.redis_service import redis_client
import pandas as pd
import joblib
import json

router = APIRouter()

# ── Load Model ─────────────────────────────────────────
model  = joblib.load("ml_models/saved/failure_model.pkl")
scaler = joblib.load("ml_models/saved/failure_scaler.pkl")

SENSOR_COLS = [f"sensor{i}" for i in range(1, 25)]

@router.post("/failure/predict")
def predict_failure(data: dict):
    try:
        unit_id = data.get("unit_id", "unknown")

        # ── Check Cache ────────────────────────────────
        cache_key = f"failure:{unit_id}"
        cached = redis_client.get(cache_key)
        if cached:
            result = json.loads(cached)
            result["from_cache"] = True
            return result

        # ── Build Features ─────────────────────────────
        sensors = {col: data.get(col, 0) for col in SENSOR_COLS}
        X = pd.DataFrame([sensors])

        # ── Scale + Predict ────────────────────────────
        X_scaled     = scaler.transform(X)
        prediction   = model.predict(X_scaled)[0]
        probability  = model.predict_proba(X_scaled)[0]

        will_fail    = bool(prediction == 1)
        fail_prob    = round(float(probability[1]) * 100, 2)
        normal_prob  = round(float(probability[0]) * 100, 2)

        # ── Risk Level ─────────────────────────────────
        if fail_prob >= 70:
            risk = "CRITICAL"
            action = "Immediate maintenance required!"
        elif fail_prob >= 40:
            risk = "WARNING"
            action = "Schedule maintenance soon."
        else:
            risk = "NORMAL"
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

        # ── Cache Result ───────────────────────────────
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