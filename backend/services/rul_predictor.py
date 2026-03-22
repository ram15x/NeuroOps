import joblib
import numpy as np

MODEL_PATH  = "ml_models/saved/failure_rul_model.pkl"
SCALER_PATH = "ml_models/saved/failure_rul_scaler.pkl"

# load once at import time so endpoint calls are fast
model  = joblib.load(MODEL_PATH)
scaler = joblib.load(SCALER_PATH)

# assume each cycle is 1 hour (standard turbofan dataset convention)
HOURS_PER_CYCLE = 1.0

def predict_rul(sensor_values: list) -> dict:
    X = np.array(sensor_values).reshape(1, -1)
    X_scaled = scaler.transform(X)

    cycles_left = float(model.predict(X_scaled)[0])
    cycles_left = max(0.0, round(cycles_left, 1))
    hours_left  = round(cycles_left * HOURS_PER_CYCLE, 1)

    # urgency bands — easy to explain in interview
    if cycles_left <= 10:
        urgency        = "CRITICAL"
        recommendation = "Shut down immediately. Failure imminent within 10 cycles."
    elif cycles_left <= 30:
        urgency        = "HIGH"
        recommendation = "Schedule maintenance now. Failure expected within 30 cycles."
    elif cycles_left <= 60:
        urgency        = "MEDIUM"
        recommendation = "Plan maintenance soon. Engine degrading."
    else:
        urgency        = "LOW"
        recommendation = "Engine healthy. Continue monitoring."

    return {
        "cycles_remaining"  : cycles_left,
        "hours_remaining"   : hours_left,
        "urgency"           : urgency,
        "recommendation"    : recommendation
    }