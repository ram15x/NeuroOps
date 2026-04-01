import numpy as np
from datetime import datetime
import json

from backend.core.config import settings
from backend.services.redis_service import redis_client


def record_prediction(is_anomaly: bool):
    """Store prediction result in Redis for drift tracking"""
    redis_client.lpush("drift:predictions", int(is_anomaly))
    redis_client.ltrim("drift:predictions", 0, settings.WINDOW_SIZE - 1)


def get_current_anomaly_rate() -> float:
    """Get current anomaly rate from recent predictions"""
    raw = redis_client.lrange("drift:predictions", 0, settings.WINDOW_SIZE - 1)
    if len(raw) < settings.MIN_PREDICTIONS_FOR_DRIFT:
        return None
    
    predictions = [int(x) for x in raw]
    return sum(predictions) / len(predictions)


def auto_tune_contamination() -> float:
    """
    Automatically adjust contamination rate based on actual anomaly rate
    Returns new contamination value
    """
    current_rate = get_current_anomaly_rate()
    if current_rate is None:
        return settings.INITIAL_CONTAMINATION
    
    # Get current contamination from Redis or use default
    current_contamination = redis_client.get("model:contamination")
    if current_contamination:
        current_contamination = float(current_contamination)
    else:
        current_contamination = settings.INITIAL_CONTAMINATION
    
    # Adjust based on drift
    if current_rate > settings.BASELINE_ANOMALY_RATE * 1.5:
        # Too many anomalies — increase threshold
        new_contamination = min(0.12, current_contamination + 0.01)
    elif current_rate < settings.BASELINE_ANOMALY_RATE * 0.5:
        # Too few anomalies — decrease threshold
        new_contamination = max(0.01, current_contamination - 0.01)
    else:
        new_contamination = current_contamination
    
    # Store new value
    redis_client.setex("model:contamination", 86400, str(new_contamination))
    
    return new_contamination


def check_drift() -> dict:
    """Check if model has drifted from baseline"""
    raw = redis_client.lrange("drift:predictions", 0, settings.WINDOW_SIZE - 1)

    if len(raw) < settings.MIN_PREDICTIONS_FOR_DRIFT:
        return {
            "status": "insufficient_data",
            "message": f"Need at least {settings.MIN_PREDICTIONS_FOR_DRIFT} predictions, have {len(raw)}",
            "count": len(raw)
        }
    
    predictions = [int(x) for x in raw]
    current_rate = sum(predictions) / len(predictions)
    drift_amount = abs(current_rate - settings.BASELINE_ANOMALY_RATE)
    drift_detected = drift_amount > settings.DRIFT_THRESHOLD
    
    # Auto-tune contamination if drift detected
    new_contamination = None
    if drift_detected:
        new_contamination = auto_tune_contamination()

    if drift_amount > settings.DRIFT_CRITICAL_THRESHOLD:
        severity = "critical"
        message = "Model severely drifted - immediate retraining required"
    elif drift_amount > settings.DRIFT_WARNING_THRESHOLD:
        severity = "warning"
        message = "Model drift detected - schedule retraining soon"
    else:
        severity = "normal"
        message = "Model performing within expected range"

    result = {
        "drift_detected": drift_detected,
        "severity": severity,
        "baseline_rate": f"{settings.BASELINE_ANOMALY_RATE * 100}%",
        "current_rate": f"{round(current_rate * 100, 2)}%",
        "drift_amount": f"{round(drift_amount * 100, 2)}%",
        "predictions_checked": len(predictions),
        "message": message,
        "checked_at": datetime.utcnow().isoformat()
    }
    
    if new_contamination:
        result["auto_tuned_contamination"] = f"{new_contamination * 100}%"
        result["message"] += f" | Contamination auto-tuned to {new_contamination * 100}%"

    redis_client.setex("drift:status", settings.DRIFT_STATUS_CACHE_TTL, json.dumps(result))
    return result


def get_drift_status() -> dict:
    """Return cached drift status"""
    cached = redis_client.get("drift:status")
    if cached:
        return json.loads(cached)
    return check_drift()


def get_contamination() -> float:
    """Get current contamination rate"""
    cont = redis_client.get("model:contamination")
    if cont:
        return float(cont)
    return settings.INITIAL_CONTAMINATION