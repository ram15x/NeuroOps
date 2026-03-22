import numpy as np
from datetime import datetime
from backend.services.redis_service import redis_client
import json

# baseline anomaly rate from training - 5% contamination we set
BASELINE_ANOMALY_RATE = 0.05
# alert if current rate drifts more than 15% from baseline
DRIFT_THRESHOLD       = 0.15
# check based on last 100 predictions
WINDOW_SIZE           = 100

def record_prediction(is_anomaly: bool):
    # push prediction result into redis list for tracking
    redis_client.lpush("drift:predictions", int(is_anomaly))
    # keep only last WINDOW_SIZE predictions in the list
    redis_client.ltrim("drift:predictions", 0, WINDOW_SIZE - 1)

def check_drift() -> dict:
    # get last N predictions from redis
    raw = redis_client.lrange("drift:predictions", 0, WINDOW_SIZE - 1)

    if len(raw) < 20:
        return {
            "status" : "insufficient_data",
            "message": f"Need at least 20 predictions, have {len(raw)}",
            "count"  : len(raw)
        }

    predictions    = [int(x) for x in raw]
    current_rate   = sum(predictions) / len(predictions)
    drift_amount   = abs(current_rate - BASELINE_ANOMALY_RATE)
    drift_detected = drift_amount > DRIFT_THRESHOLD

    if drift_amount > 0.30:
        severity = "critical"
        message  = "Model severely drifted - immediate retraining required"
    elif drift_amount > 0.15:
        severity = "warning"
        message  = "Model drift detected - schedule retraining soon"
    else:
        severity = "normal"
        message  = "Model performing within expected range"

    result = {
        "drift_detected"     : drift_detected,
        "severity"           : severity,
        "baseline_rate"      : f"{BASELINE_ANOMALY_RATE * 100}%",
        "current_rate"       : f"{round(current_rate * 100, 2)}%",
        "drift_amount"       : f"{round(drift_amount * 100, 2)}%",
        "predictions_checked": len(predictions),
        "message"            : message,
        "checked_at"         : datetime.utcnow().isoformat()
    }

    # cache drift status for 5 minutes
    redis_client.setex("drift:status", 300, json.dumps(result))

    return result

def get_drift_status() -> dict:
    # return cached status if available
    cached = redis_client.get("drift:status")
    if cached:
        return json.loads(cached)
    return check_drift()