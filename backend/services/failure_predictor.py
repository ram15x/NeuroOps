import joblib
import numpy as np
import os
from datetime import datetime
from backend.core.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

MODEL_PATH = os.path.join(settings.MODEL_PATH, settings.FAILURE_MODEL_FILE)
SCALER_PATH = os.path.join(settings.MODEL_PATH, settings.FAILURE_SCALER_FILE)

_model = None
_scaler = None


def load_model():
    global _model, _scaler
    if _model is None:
        _model = joblib.load(MODEL_PATH)
        _scaler = joblib.load(SCALER_PATH)
    return _model, _scaler


def predict_failure_from_status(
    cpu_usage: float,
    status_check_ok: bool,
    recent_reboots: int = 0,
    instance_age_days: int = 30
) -> dict:
    """
    Predict failure probability using real AWS data
    Only triggers meaningful predictions if CPU > 45%
    """
    
    # Only trigger predictions if CPU is meaningful (>30%)
    if cpu_usage < 45:
        return {
            "will_fail_soon": False,
            "failure_probability": 0.0,
            "risk_level": "NORMAL",
            "action": "System operating normally",
            "input_metrics": {
                "cpu_usage": cpu_usage,
                "status_check_ok": status_check_ok,
                "recent_reboots": recent_reboots,
                "instance_age_days": instance_age_days
            },
            "reason": f"CPU normal: {cpu_usage:.1f}%"
        }
    
    # Check status check first (most critical)
    if not status_check_ok:
        return {
            "will_fail_soon": True,
            "failure_probability": 95.0,
            "risk_level": "CRITICAL",
            "action": "Immediate instance reboot required!",
            "input_metrics": {
                "cpu_usage": cpu_usage,
                "status_check_ok": status_check_ok,
                "recent_reboots": recent_reboots,
                "instance_age_days": instance_age_days
            },
            "reason": "EC2 status check failing"
        }
    
    # High CPU with multiple reboots
    if cpu_usage > 85 and recent_reboots >= 2:
        return {
            "will_fail_soon": True,
            "failure_probability": 85.0,
            "risk_level": "CRITICAL",
            "action": "Scale up or investigate root cause",
            "input_metrics": {
                "cpu_usage": cpu_usage,
                "status_check_ok": status_check_ok,
                "recent_reboots": recent_reboots,
                "instance_age_days": instance_age_days
            },
            "reason": f"High CPU ({cpu_usage:.1f}%) with {recent_reboots} recent reboots"
        }
    
    # Very high CPU
    if cpu_usage > 90:
        return {
            "will_fail_soon": True,
            "failure_probability": 75.0,
            "risk_level": "CRITICAL",
            "action": "Scale up or optimize application",
            "input_metrics": {
                "cpu_usage": cpu_usage,
                "status_check_ok": status_check_ok,
                "recent_reboots": recent_reboots,
                "instance_age_days": instance_age_days
            },
            "reason": f"Very high CPU: {cpu_usage:.1f}%"
        }
    
    # High CPU (warning)
    if cpu_usage > 80:
        return {
            "will_fail_soon": False,
            "failure_probability": 50.0,
            "risk_level": "WARNING",
            "action": "Monitor closely",
            "input_metrics": {
                "cpu_usage": cpu_usage,
                "status_check_ok": status_check_ok,
                "recent_reboots": recent_reboots,
                "instance_age_days": instance_age_days
            },
            "reason": f"High CPU: {cpu_usage:.1f}%"
        }
    
    # Normal range (30-80% CPU) - use ML model
    model, scaler = load_model()
    
    # Build feature vector for the model
    sensor_values = [
        cpu_usage,                      # sensor1
        1.0 if status_check_ok else 0.0, # sensor2
        recent_reboots,                 # sensor3
        instance_age_days,              # sensor4
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    ][:settings.NUM_SENSORS]
    
    X = np.array(sensor_values).reshape(1, -1)
    X_scaled = scaler.transform(X)
    
    prediction = model.predict(X_scaled)[0]
    probability = model.predict_proba(X_scaled)[0]
    
    will_fail = bool(prediction == 1)
    fail_prob = round(float(probability[1]) * 100, 2)
    
    # Determine risk level
    if fail_prob >= settings.FAILURE_PROB_CRITICAL:
        risk = "CRITICAL"
        action = "Immediate pre-healing required!"
    elif fail_prob >= settings.FAILURE_PROB_WARNING:
        risk = "WARNING"
        action = "Schedule pre-healing soon."
    else:
        risk = "NORMAL"
        action = "System operating normally."
    
    result = {
        "will_fail_soon": will_fail,
        "failure_probability": fail_prob,
        "risk_level": risk,
        "action": action,
        "input_metrics": {
            "cpu_usage": cpu_usage,
            "status_check_ok": status_check_ok,
            "recent_reboots": recent_reboots,
            "instance_age_days": instance_age_days
        },
        "reason": f"ML prediction: {fail_prob}% failure probability"
    }
    
    logger.info(
        "failure_prediction",
        will_fail=will_fail,
        probability=fail_prob,
        risk=risk,
        cpu=cpu_usage
    )
    
    return result