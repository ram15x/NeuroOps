import pandas as pd
import joblib
import os
import numpy as np
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
        print(f"Model loaded. Scaler expects {_scaler.n_features_in_} features")
    return _model, _scaler


def analyze_metric(metric_name: str, value: float, rolling_mean: float, rolling_std: float, value_diff: float) -> dict:
    """Run InfraMind prediction on a metric"""
    model, scaler = load_model()
    
    # Check how many features the scaler expects
    n_features = scaler.n_features_in_ if hasattr(scaler, 'n_features_in_') else 4
    
    if n_features == 2:
        # Use only CPU and Memory (2 features)
        # For now, use value as CPU and rolling_mean as Memory
        cpu_value = value
        memory_value = rolling_mean if rolling_mean else 50
        
        input_features = {
            "cpu": cpu_value,
            "memory": memory_value
        }
        feature_names = ["cpu", "memory"]
    else:
        # Use all 4 features
        input_features = {
            "value": value,
            "rolling_mean": rolling_mean,
            "rolling_std": rolling_std,
            "value_diff": value_diff
        }
        feature_names = ["value", "rolling_mean", "rolling_std", "value_diff"]
    
    features = pd.DataFrame([input_features])[feature_names]
    X_scaled = scaler.transform(features)
    prediction = model.predict(X_scaled)[0]
    score = float(model.decision_function(X_scaled)[0])
    is_anomaly = bool(prediction == -1)
    
    # Force anomaly for high CPU (override model)
    if value > 80:
        is_anomaly = True
        score = -0.5  # Force critical score
        print(f"Forced anomaly for CPU {value}%")
    
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