import joblib
import numpy as np
import os
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler

from backend.core.config import settings

# Use REAL RUL model trained on EC2 data
MODEL_PATH = os.path.join(settings.MODEL_PATH, settings.RUL_MODEL_FILE)
SCALER_PATH = os.path.join(settings.MODEL_PATH, settings.RUL_SCALER_FILE)

# safe load — no crash if pkl files missing
model = None
scaler = None
_rul_model_ready = False

try:
    if os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH):
        model = joblib.load(MODEL_PATH)
        scaler = joblib.load(SCALER_PATH)
        _rul_model_ready = True
    else:
        import logging as _log
        _log.warning(f"RUL model files missing: {MODEL_PATH}, {SCALER_PATH}")
except Exception as e:
    import logging as _log
    _log.error(f"RUL model load failed: {e}")


def predict_rul(cpu_usage: float, memory_usage: float, disk_usage: float, instance_age_days: int) -> dict:
    """
    Predict RUL using REAL EC2 metrics (CPU, Memory, Disk, Age)
    No more turbofan sensors!
    """
    
    # Prepare features for REAL EC2 data
    features = np.array([[cpu_usage, memory_usage, disk_usage, instance_age_days]])
    X_scaled = scaler.transform(features)

    cycles_left = float(model.predict(X_scaled)[0])
    cycles_left = max(0.0, round(cycles_left, 1))
    hours_left = round(cycles_left * settings.HOURS_PER_CYCLE, 1)

    # Calculate confidence interval using model's internal uncertainty
    if hasattr(model, 'estimators_'):
        tree_predictions = [tree.predict(X_scaled)[0] for tree in model.estimators_]
        lower_bound = max(0.0, round(np.percentile(tree_predictions, 10), 1))
        upper_bound = max(0.0, round(np.percentile(tree_predictions, 90), 1))
        confidence = 80
    else:
        lower_bound = max(0.0, round(cycles_left * 0.85, 1))
        upper_bound = round(cycles_left * 1.15, 1)
        confidence = 70

    # Urgency bands based on cycles remaining
    if cycles_left <= settings.RUL_URGENCY_CRITICAL:
        urgency = "CRITICAL"
        recommendation = f"Shut down immediately. Failure imminent within {settings.RUL_URGENCY_CRITICAL} cycles."
    elif cycles_left <= settings.RUL_URGENCY_HIGH:
        urgency = "HIGH"
        recommendation = f"Schedule maintenance now. Failure expected within {settings.RUL_URGENCY_HIGH} cycles."
    elif cycles_left <= settings.RUL_URGENCY_MEDIUM:
        urgency = "MEDIUM"
        recommendation = "Plan maintenance soon. Instance degrading."
    else:
        urgency = "LOW"
        recommendation = "Instance healthy. Continue monitoring."

    return {
        "cycles_remaining": cycles_left,
        "hours_remaining": hours_left,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "confidence_pct": confidence,
        "urgency": urgency,
        "recommendation": recommendation,
        "model_used": "rul_real_model"
    }


def predict_rul_with_interval(cpu_usage: float, memory_usage: float, disk_usage: float, instance_age_days: int, confidence: float = 95) -> dict:
    """Predict RUL with custom confidence interval using REAL EC2 data"""
    
    features = np.array([[cpu_usage, memory_usage, disk_usage, instance_age_days]])
    X_scaled = scaler.transform(features)

    cycles_left = float(model.predict(X_scaled)[0])
    cycles_left = max(0.0, round(cycles_left, 1))
    
    if hasattr(model, 'estimators_'):
        tree_predictions = [tree.predict(X_scaled)[0] for tree in model.estimators_]
        
        if confidence == 90:
            lower = np.percentile(tree_predictions, 5)
            upper = np.percentile(tree_predictions, 95)
        elif confidence == 95:
            lower = np.percentile(tree_predictions, 2.5)
            upper = np.percentile(tree_predictions, 97.5)
        else:
            lower = np.percentile(tree_predictions, 10)
            upper = np.percentile(tree_predictions, 90)
        
        lower_bound = max(0.0, round(lower, 1))
        upper_bound = max(0.0, round(upper, 1))
    else:
        factor = confidence / 100
        lower_bound = max(0.0, round(cycles_left * (1 - factor * 0.2), 1))
        upper_bound = round(cycles_left * (1 + factor * 0.2), 1)
    
    return {
        "cycles_remaining": cycles_left,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "confidence_pct": confidence
    }


# Keep legacy function for backward compatibility (will be deprecated)
def predict_rul_from_sensors(sensor_values: list) -> dict:
    """Legacy function - extracts REAL metrics from first 4 sensors"""
    cpu = sensor_values[0] if len(sensor_values) > 0 else 0
    memory = sensor_values[4] if len(sensor_values) > 4 else 0
    disk = sensor_values[5] if len(sensor_values) > 5 else 0
    age = int(sensor_values[3]) if len(sensor_values) > 3 else 30
    
    return predict_rul(cpu, memory, disk, age)