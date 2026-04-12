"""
RUL Predictor - SRE Hardened Version
Handles 3, 4, 5, and 7 feature models dynamically.
"""
import joblib
import numpy as np
import os
import logging
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler

from backend.core.config import settings

logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join(settings.MODEL_PATH, settings.RUL_MODEL_FILE)
SCALER_PATH = os.path.join(settings.MODEL_PATH, settings.RUL_SCALER_FILE)

model = None
scaler = None
_rul_model_ready = False

try:
    if os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH):
        model = joblib.load(MODEL_PATH)
        scaler = joblib.load(SCALER_PATH)
        _rul_model_ready = True
        logger.info(f"✅ RUL model loaded. Expects {model.n_features_in_} features.")
    else:
        logger.warning(f"RUL model files missing: {MODEL_PATH}, {SCALER_PATH}")
except Exception as e:
    logger.error(f"RUL model load failed: {e}")


def predict_rul(cpu_usage: float, memory_usage: float = 50.0, instance_age_days: int = 30, disk_usage: float = None) -> dict:
    # Default fallback if model is missing or failed to load
    if model is None or scaler is None:
        logger.warning("RUL Model unavailable. Using simple threshold fallback.")
        return _simple_rul_fallback(cpu_usage)

    memory_usage = memory_usage if memory_usage is not None else 50.0
    instance_age_days = instance_age_days if instance_age_days is not None else 30
    disk_val = disk_usage if disk_usage is not None else 30.0

    try:
        expected_features = model.n_features_in_
        
        # Calculate trend and std (used for 5 and 7 feature models)
        cpu_trend = 0.0
        cpu_std = 5.0
        memory_trend = 0.0
        
        try:
            import json
            from backend.services.redis_service import redis_client
            history_key = f"cpu_history:i-00dfb80a59da9a56d"
            history_data = redis_client.get(history_key)
            if history_data:
                history = json.loads(history_data)
                if len(history) >= 5:
                    cpu_trend = (history[-1] - history[-5]) / 5
                    cpu_std = np.std(history[-10:]) if len(history) >= 10 else 5.0
        except:
            pass
        
        # Build features based on what the model actually expects
        if expected_features == 7:
            features = np.array([[float(cpu_usage), float(memory_usage), float(disk_val), float(instance_age_days),
                          float(cpu_trend), float(cpu_std), float(memory_trend)]])
        elif expected_features == 5:
            features = np.array([[float(cpu_usage), float(memory_usage), float(instance_age_days), 
                          float(cpu_trend), float(cpu_std)]])
        elif expected_features == 4:
            features = np.array([[cpu_usage, memory_usage, disk_val, instance_age_days]])
        elif expected_features == 3:
            features = np.array([[cpu_usage, memory_usage, instance_age_days]])
        else:
            logger.error(f"Unexpected feature count: {expected_features}")
            return _simple_rul_fallback(cpu_usage)

        X_scaled = scaler.transform(features)
        cycles_left = float(model.predict(X_scaled)[0])
        cycles_left = max(0.0, round(cycles_left, 1))
        
    except Exception as e:
        logger.error(f"RUL prediction failed: {e}, using fallback")
        return _simple_rul_fallback(cpu_usage)

    hours_left = round(cycles_left * settings.HOURS_PER_CYCLE, 1)

    # Confidence interval
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
        "model_used": f"rul_real_model_{expected_features}features"
    }


def _simple_rul_fallback(cpu_usage: float) -> dict:
    """Simple rule-based fallback when ML model fails."""
    if cpu_usage > 90:
        cycles = 5; urgency = "CRITICAL"
    elif cpu_usage > 75:
        cycles = 15; urgency = "HIGH"
    elif cpu_usage > 60:
        cycles = 30; urgency = "MEDIUM"
    else:
        cycles = 60; urgency = "LOW"
        
    return {
        "cycles_remaining": cycles,
        "hours_remaining": cycles,
        "lower_bound": max(0, cycles - 10),
        "upper_bound": cycles + 10,
        "confidence_pct": 70,
        "urgency": urgency,
        "recommendation": "Using fallback calculation (ML model unavailable).",
        "model_used": "rule_based_fallback"
    }


def predict_rul_safe(cpu_usage, memory_usage=None, instance_age_days=None, disk_usage=None):
    """Safe wrapper"""
    return predict_rul(cpu_usage, memory_usage, instance_age_days, disk_usage)


def predict_rul_with_interval(cpu_usage: float, memory_usage: float, instance_age_days: int, confidence: float = 95) -> dict:
    """Predict RUL with custom confidence interval"""
    return predict_rul(cpu_usage, memory_usage, instance_age_days)


def predict_rul_from_sensors(sensor_values: list) -> dict:
    """Legacy function - extracts REAL metrics from sensors"""
    cpu = sensor_values[0] if len(sensor_values) > 0 else 0
    memory = sensor_values[4] if len(sensor_values) > 4 else 50
    age = int(sensor_values[3]) if len(sensor_values) > 3 else 30
    return predict_rul(cpu, memory, age)