import joblib
import numpy as np
import os
from datetime import datetime
from backend.core.config import settings
from backend.core.logger import get_logger
import pandas as pd
import time

logger = get_logger(__name__)

# Paths for new XGBoost production model
XGB_MODEL_PATH = os.path.join(settings.MODEL_PATH, "xgboost_production_model.pkl")
XGB_MODEL_METADATA = os.path.join(settings.MODEL_PATH, "model_metadata.pkl")
ORIGINAL_MODEL_PATH = os.path.join(settings.MODEL_PATH, settings.FAILURE_MODEL_FILE)
SCALER_PATH = os.path.join(settings.MODEL_PATH, settings.FAILURE_SCALER_FILE)

_model = None
_scaler = None
_xgb_model = None
_model_metadata = None
_last_loaded = 0


def load_xgboost_model():
    """Load the latest XGBoost production model"""
    global _xgb_model, _model_metadata, _last_loaded
    
    if os.path.exists(XGB_MODEL_PATH):
        mod_time = os.path.getmtime(XGB_MODEL_PATH)
        if _xgb_model is None or mod_time > _last_loaded:
            _xgb_model = joblib.load(XGB_MODEL_PATH)
            if os.path.exists(XGB_MODEL_METADATA):
                _model_metadata = joblib.load(XGB_MODEL_METADATA)
            _last_loaded = mod_time
            logger.info("xgboost_model_loaded", records=_model_metadata.get('records_used', 0) if _model_metadata else 0)
    return _xgb_model


def load_original_model():
    """Load original Random Forest model (fallback)"""
    global _model, _scaler
    if _model is None:
        _model = joblib.load(ORIGINAL_MODEL_PATH)
        _scaler = joblib.load(SCALER_PATH)
    return _model, _scaler


def predict_failure_from_status(
    cpu_usage: float,
    status_check_ok: bool,
    recent_reboots: int = 0,
    instance_age_days: int = 30,
    memory_usage: float = None,
    disk_usage: float = None
) -> dict:
    """
    Predict failure probability using XGBoost model (trained on REAL data)
    Falls back to rule-based if model not available
    """
    
    # Use REAL memory/disk if available, otherwise estimate
    if memory_usage is None:
        memory_usage = min(95, max(5, cpu_usage * 0.7 + 15))
    
    if disk_usage is None:
        disk_usage = min(85, 20 + instance_age_days * 0.5)
    
    # Rule-based for extreme cases
    if not status_check_ok:
        return {
            "will_fail_soon": True,
            "failure_probability": 95.0,
            "risk_level": "CRITICAL",
            "action": "Immediate instance reboot required!",
            "input_metrics": {
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage,
                "disk_usage": disk_usage,
                "status_check_ok": status_check_ok,
                "recent_reboots": recent_reboots,
                "instance_age_days": instance_age_days
            },
            "reason": "EC2 status check failing",
            "model_used": "rule_based"
        }
    
    if cpu_usage > 95:
        return {
            "will_fail_soon": True,
            "failure_probability": 85.0,
            "risk_level": "CRITICAL",
            "action": "Scale up or optimize application immediately!",
            "input_metrics": {
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage,
                "disk_usage": disk_usage,
                "status_check_ok": status_check_ok,
                "recent_reboots": recent_reboots,
                "instance_age_days": instance_age_days
            },
            "reason": f"Critical CPU: {cpu_usage:.1f}%",
            "model_used": "rule_based"
        }
    
    # Try XGBoost model first (trained on 5000+ REAL records)
    xgb_model = load_xgboost_model()
    
    if xgb_model is not None:
        try:
            # Prepare features for XGBoost
            features = np.array([[
                cpu_usage,
                memory_usage,
                disk_usage,
                instance_age_days
            ]])
            
            # Get prediction and probability
            prediction = xgb_model.predict(features)[0]
            probabilities = xgb_model.predict_proba(features)[0]
            
            will_fail = bool(prediction == 1)
            fail_prob = round(float(probabilities[1]) * 100, 2)
            
            # Get model metadata for confidence
            model_info = ""
            if _model_metadata:
                model_info = f" (trained on {_model_metadata.get('records_used', 0)} records)"
            
            # Determine risk level based on probability
            if fail_prob >= 70:
                risk = "CRITICAL"
                action = "Immediate action required! Scale up or investigate."
            elif fail_prob >= 40:
                risk = "WARNING"
                action = "Schedule maintenance soon. Monitor closely."
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
                    "memory_usage": memory_usage,
                    "disk_usage": disk_usage,
                    "status_check_ok": status_check_ok,
                    "recent_reboots": recent_reboots,
                    "instance_age_days": instance_age_days
                },
                "reason": f"XGBoost prediction: {fail_prob}% failure probability{model_info}",
                "model_used": "xgboost_production"
            }
            
            logger.info(
                "failure_prediction_xgboost",
                will_fail=will_fail,
                probability=fail_prob,
                risk=risk,
                cpu=cpu_usage,
                memory=memory_usage,
                disk=disk_usage,
                model_records=_model_metadata.get('records_used', 0) if _model_metadata else 0
            )
            
            return result
            
        except Exception as e:
            logger.error("xgboost_prediction_failed", error=str(e))
            # Fall through to rule-based
    
    # Fallback to rule-based for normal range
    if cpu_usage > 80:
        return {
            "will_fail_soon": False,
            "failure_probability": 50.0,
            "risk_level": "WARNING",
            "action": "Monitor closely",
            "input_metrics": {
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage,
                "disk_usage": disk_usage,
                "status_check_ok": status_check_ok,
                "recent_reboots": recent_reboots,
                "instance_age_days": instance_age_days
            },
            "reason": f"High CPU: {cpu_usage:.1f}%",
            "model_used": "rule_based"
        }
    
    # Normal CPU
    return {
        "will_fail_soon": False,
        "failure_probability": 0.0,
        "risk_level": "NORMAL",
        "action": "System operating normally",
        "input_metrics": {
            "cpu_usage": cpu_usage,
            "memory_usage": memory_usage,
            "disk_usage": disk_usage,
            "status_check_ok": status_check_ok,
            "recent_reboots": recent_reboots,
            "instance_age_days": instance_age_days
        },
        "reason": f"CPU normal: {cpu_usage:.1f}%, Memory: {memory_usage:.1f}%, Disk: {disk_usage:.1f}%",
        "model_used": "rule_based"
    }


# Keep original function for backward compatibility
def predict_failure_from_sensors(sensor_values: list) -> dict:
    """Legacy function for 24-sensor input"""
    # Extract first 4 sensors as CPU, status, reboots, age
    cpu = sensor_values[0] if len(sensor_values) > 0 else 0
    status_ok = sensor_values[1] > 0.5 if len(sensor_values) > 1 else True
    reboots = int(sensor_values[2]) if len(sensor_values) > 2 else 0
    age = int(sensor_values[3]) if len(sensor_values) > 3 else 30
    
    return predict_failure_from_status(
        cpu_usage=cpu,
        status_check_ok=status_ok,
        recent_reboots=reboots,
        instance_age_days=age
    )