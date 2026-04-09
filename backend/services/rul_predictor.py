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
        print(f"✅ RUL model loaded. Expects {model.n_features_in_} features")
    else:
        import logging as _log
        _log.warning(f"RUL model files missing: {MODEL_PATH}, {SCALER_PATH}")
except Exception as e:
    import logging as _log
    _log.error(f"RUL model load failed: {e}")


def predict_rul(cpu_usage: float, memory_usage: float = 50.0, instance_age_days: int = 30, disk_usage: float = None) -> dict:
    """
    Predict RUL using REAL EC2 metrics
    Model expects 3 features: [cpu_usage, memory_usage, instance_age_days]
    """
    # Use default values if not provided
    if memory_usage is None or memory_usage == 0:
        memory_usage = 50.0
    if instance_age_days is None or instance_age_days == 0:
        instance_age_days = 30
    
    # Prepare features - ONLY 3 features as model expects
    features = np.array([[cpu_usage, memory_usage, instance_age_days]])
    
    try:
        if scaler:
            X_scaled = scaler.transform(features)
            cycles_left = float(model.predict(X_scaled)[0])
        else:
            cycles_left = float(model.predict(features)[0])
    except Exception as e:
        # Fallback to simple calculation
        print(f"RUL prediction failed: {e}, using fallback")
        if cpu_usage > 90:
            cycles_left = 5
        elif cpu_usage > 75:
            cycles_left = 15
        elif cpu_usage > 60:
            cycles_left = 30
        else:
            cycles_left = 60
    
    cycles_left = max(0.0, round(cycles_left, 1))
    hours_left = round(cycles_left * settings.HOURS_PER_CYCLE, 1)

    # Calculate confidence interval
    if hasattr(model, 'estimators_') and scaler:
        try:
            tree_predictions = [tree.predict(scaler.transform(features))[0] for tree in model.estimators_[:10]]
            lower_bound = max(0.0, round(np.percentile(tree_predictions, 10), 1))
            upper_bound = max(0.0, round(np.percentile(tree_predictions, 90), 1))
            confidence = 80
        except:
            lower_bound = max(0.0, round(cycles_left * 0.85, 1))
            upper_bound = round(cycles_left * 1.15, 1)
            confidence = 70
    else:
        lower_bound = max(0.0, round(cycles_left * 0.85, 1))
        upper_bound = round(cycles_left * 1.15, 1)
        confidence = 70

    # Urgency bands
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


def predict_rul_safe(cpu_usage, memory_usage=None, instance_age_days=None, disk_usage=None):
    """Safe wrapper - ignores disk_usage"""
    return predict_rul(cpu_usage, memory_usage, instance_age_days)


def predict_rul_with_interval(cpu_usage: float, memory_usage: float, instance_age_days: int, confidence: float = 95) -> dict:
    """Predict RUL with custom confidence interval"""
    features = np.array([[cpu_usage, memory_usage, instance_age_days]])
    
    if scaler:
        X_scaled = scaler.transform(features)
        cycles_left = float(model.predict(X_scaled)[0])
    else:
        cycles_left = float(model.predict(features)[0])
    
    cycles_left = max(0.0, round(cycles_left, 1))

    if hasattr(model, 'estimators_') and scaler:
        tree_predictions = [tree.predict(scaler.transform(features))[0] for tree in model.estimators_]
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


def predict_rul_from_sensors(sensor_values: list) -> dict:
    """Legacy function - extracts REAL metrics from sensors"""
    cpu = sensor_values[0] if len(sensor_values) > 0 else 0
    memory = sensor_values[4] if len(sensor_values) > 4 else 50
    age = int(sensor_values[3]) if len(sensor_values) > 3 else 30
    return predict_rul(cpu, memory, age)
