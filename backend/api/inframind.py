from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.models.database import get_db, Alert
from backend.services.redis_service import cache_alert, get_cached_alert
import pandas as pd
import joblib

router = APIRouter()

model  = joblib.load("ml_models/saved/inframind_model.pkl")
scaler = joblib.load("ml_models/saved/inframind_scaler.pkl")

@router.post("/inframind/predict")
def predict_anomaly(data: dict, db: Session = Depends(get_db)):
    try:
        metric_name = data.get("metric", "unknown")

        # ── Check Redis Cache First ────────────────────
        cached = get_cached_alert(metric_name)
        if cached and not data.get("force", False):
            cached["from_cache"] = True
            return cached

        features = pd.DataFrame([{
            "value"        : data.get("value", 0),
            "rolling_mean" : data.get("rolling_mean", 0),
            "rolling_std"  : data.get("rolling_std", 0),
            "value_diff"   : data.get("value_diff", 0),
        }])

        X_scaled   = scaler.transform(features)
        prediction = model.predict(X_scaled)[0]
        score      = float(model.decision_function(X_scaled)[0])
        is_anomaly = bool(prediction == -1)

        if data.get("value", 0) > 90 and data.get("value_diff", 0) > 50:
            is_anomaly = True
            score = -0.20

        severity = get_severity(score)
        message  = get_message(is_anomaly, data.get("value", 0))

        result = {
            "status"        : "anomaly" if is_anomaly else "normal",
            "is_anomaly"    : is_anomaly,
            "anomaly_score" : round(score, 4),
            "severity"      : severity,
            "message"       : message,
            "saved_to_db"   : True,
            "from_cache"    : False
        }

        # ── Save to PostgreSQL ─────────────────────────
        alert = Alert(
            metric_value  = data.get("value", 0),
            rolling_mean  = data.get("rolling_mean", 0),
            rolling_std   = data.get("rolling_std", 0),
            value_diff    = data.get("value_diff", 0),
            is_anomaly    = is_anomaly,
            severity      = severity,
            anomaly_score = score,
            message       = message
        )
        db.add(alert)
        db.commit()

        # ── Cache in Redis ─────────────────────────────
        cache_alert(metric_name, result)

        return result

    except Exception as e:
        return {"error": str(e)}


def get_severity(score: float) -> str:
    if score < -0.15:
        return "critical"
    elif score < -0.05:
        return "warning"
    else:
        return "normal"


def get_message(is_anomaly: bool, value: float) -> str:
    if is_anomaly:
        return f"ANOMALY DETECTED! Metric value {value} is abnormal."
    return f"NORMAL. Metric value {value} is within normal range."