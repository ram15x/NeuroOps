import pandas as pd
import joblib
import os
from backend.core.config import settings
from backend.services.drift_detector import record_prediction

MODEL_PATH = os.path.join(settings.MODEL_PATH, settings.INFRAMIND_MODEL_FILE)
SCALER_PATH = os.path.join(settings.MODEL_PATH, settings.INFRAMIND_SCALER_FILE)

_model = None
_scaler = None


def load_model():
    global _model, _scaler
    if _model is None:
        _model = joblib.load(MODEL_PATH)
        _scaler = joblib.load(SCALER_PATH)
    return _model, _scaler


def analyze_metric(metric_name: str, value: float, rolling_mean: float, rolling_std: float, value_diff: float) -> dict:
    """Run InfraMind prediction on a metric"""
    model, scaler = load_model()
    
    input_features = {
        "value": value,
        "rolling_mean": rolling_mean,
        "rolling_std": rolling_std,
        "value_diff": value_diff
    }
    
    features = pd.DataFrame([input_features])
    X_scaled = scaler.transform(features)
    prediction = model.predict(X_scaled)[0]
    score = float(model.decision_function(X_scaled)[0])
    is_anomaly = bool(prediction == -1)
    
    record_prediction(is_anomaly)
    
    # Determine severity
    if score < settings.SEVERITY_CRITICAL_THRESHOLD:
        severity = "critical"
    elif score < settings.SEVERITY_WARNING_THRESHOLD:
        severity = "warning"
    else:
        severity = "normal"
    
    return {
        "metric": metric_name,
        "value": value,
        "is_anomaly": is_anomaly,
        "anomaly_score": round(score, 4),
        "severity": severity,
        "timestamp": pd.Timestamp.now().isoformat()
    }
    
def analyze_metric(metric_name: str, value: float, rolling_mean: float, rolling_std: float, value_diff: float) -> dict:
    """Run InfraMind prediction on a metric"""
    model, scaler = load_model()
    
    input_features = {
        "value": value,
        "rolling_mean": rolling_mean,
        "rolling_std": rolling_std,
        "value_diff": value_diff
    }
    
    features = pd.DataFrame([input_features])
    X_scaled = scaler.transform(features)
    prediction = model.predict(X_scaled)[0]
    score = float(model.decision_function(X_scaled)[0])
    is_anomaly = bool(prediction == -1)
    
    # ADD THIS: Force anomaly for high CPU
    if value > 80:
        is_anomaly = True
        score = -0.5  # Force critical score
    
    record_prediction(is_anomaly)
    
    # Determine severity
    if score < settings.SEVERITY_CRITICAL_THRESHOLD:
        severity = "critical"
    elif score < settings.SEVERITY_WARNING_THRESHOLD:
        severity = "warning"
    else:
        severity = "normal"
    
    return {
        "metric": metric_name,
        "value": value,
        "is_anomaly": is_anomaly,
        "anomaly_score": round(score, 4),
        "severity": severity,
        "timestamp": pd.Timestamp.now().isoformat()
    }