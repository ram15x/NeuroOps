from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from backend.models.database import get_db, Alert
from backend.models.schemas import MetricInput
from backend.services.redis_service import cache_alert, get_cached_alert
from backend.services.rate_limiter import limiter
from backend.services.explainer import load_explainer, explain_prediction
import pandas as pd
import joblib
from backend.services.drift_detector import record_prediction, check_drift, get_drift_status
import os

router = APIRouter()

model  = joblib.load("ml_models/saved/inframind_model.pkl")
scaler = joblib.load("ml_models/saved/inframind_scaler.pkl")

# load background data for SHAP explainer
# compute rolling features same way as training
_bg_data = pd.read_csv("datasets/processed/metrics_clean.csv")
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
    n=min(100, len(_bg_data)), random_state=42
)
load_explainer(model, scaler, _bg_sample)


@router.post("/inframind/predict")
@limiter.limit("60/minute")
def predict_anomaly(request: Request, data: MetricInput, db: Session = Depends(get_db)):
    try:
        metric_name = data.metric

        cached = get_cached_alert(metric_name)
        if cached and not data.force:
            cached["from_cache"] = True
            return cached

        input_features = {
            "value"        : data.value,
            "rolling_mean" : data.rolling_mean,
            "rolling_std"  : data.rolling_std,
            "value_diff"   : data.value_diff,
        }

        features = pd.DataFrame([input_features])

        X_scaled   = scaler.transform(features)
        prediction = model.predict(X_scaled)[0]
        score      = float(model.decision_function(X_scaled)[0])
        is_anomaly = bool(prediction == -1)
        record_prediction(is_anomaly)

        if data.value > 90 and data.value_diff > 50:
            is_anomaly = True
            score = -0.20

        severity = get_severity(score)
        message  = get_message(is_anomaly, data.value)

        # get SHAP explanation for why this was flagged
        explanation = explain_prediction(model, scaler, input_features)

        result = {
            "status"        : "anomaly" if is_anomaly else "normal",
            "is_anomaly"    : is_anomaly,
            "anomaly_score" : round(score, 4),
            "severity"      : severity,
            "message"       : message,
            "explanation"   : explanation,
            "saved_to_db"   : True,
            "from_cache"    : False
        }

        alert = Alert(
            metric_value  = data.value,
            rolling_mean  = data.rolling_mean,
            rolling_std   = data.rolling_std,
            value_diff    = data.value_diff,
            is_anomaly    = is_anomaly,
            severity      = severity,
            anomaly_score = score,
            message       = message
        )
        db.add(alert)
        db.commit()

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
        return f"ANOMALY DETECTED. Metric value {value} is abnormal."
    return f"NORMAL. Metric value {value} is within normal range."

@router.get("/inframind/drift")
def get_model_drift():
    # returns current drift status based on recent predictions
    return check_drift()


@router.get("/inframind/drift/status")
def drift_status():
    # returns cached drift status
    return get_drift_status()