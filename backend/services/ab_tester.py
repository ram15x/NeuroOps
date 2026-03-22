import joblib
import numpy as np

# model a — random forest (already exists)
MODEL_A_PATH  = "ml_models/saved/failure_rul_model.pkl"
SCALER_A_PATH = "ml_models/saved/failure_rul_scaler.pkl"

# model b — gradient boosting (new)
MODEL_B_PATH  = "ml_models/saved/failure_rul_model_b.pkl"
SCALER_B_PATH = "ml_models/saved/failure_rul_scaler_b.pkl"

# load both models once at import time
model_a  = joblib.load(MODEL_A_PATH)
scaler_a = joblib.load(SCALER_A_PATH)

model_b  = joblib.load(MODEL_B_PATH)
scaler_b = joblib.load(SCALER_B_PATH)

HOURS_PER_CYCLE = 1.0

def run_ab_test(sensor_values: list) -> dict:
    X = np.array(sensor_values).reshape(1, -1)

    # run model a - random forest
    X_a      = scaler_a.transform(X)
    rul_a_raw = float(model_a.predict(X_a)[0])
    rul_a     = max(0.0, round(rul_a_raw, 1))

    # run model b - gradient boosting
    X_b       = scaler_b.transform(X)
    rul_b_raw = float(model_b.predict(X_b)[0])
    rul_b     = max(0.0, round(rul_b_raw, 1))

    # keep raw values for honest reporting
    rul_a_display = rul_a if rul_a_raw >= 0 else f"overdue ({round(rul_a_raw, 1)})"
    rul_b_display = rul_b if rul_b_raw >= 0 else f"overdue ({round(rul_b_raw, 1)})"

    difference = round(abs(rul_a - rul_b), 1)
    max_rul    = max(rul_a, rul_b, 1)
    agreement  = round((1 - difference / max_rul) * 100, 1)
    agreement  = max(0.0, agreement)

    # winner is the more conservative (lower) estimate
    if rul_a <= rul_b:
        winner       = "model_a"
        winner_label = "Random Forest"
        winner_rul   = rul_a
    else:
        winner       = "model_b"
        winner_label = "Gradient Boosting"
        winner_rul   = rul_b

    if winner_rul <= 10:
        urgency = "CRITICAL"
    elif winner_rul <= 30:
        urgency = "HIGH"
    elif winner_rul <= 60:
        urgency = "MEDIUM"
    else:
        urgency = "LOW"

    if agreement >= 90:
        consensus = "STRONG — both models agree"
    elif agreement >= 70:
        consensus = "MODERATE — minor disagreement"
    else:
        consensus = "WEAK — models disagree, model_b predicts failure already overdue"

    return {
        "model_a": {
            "name"            : "Random Forest",
            "cycles_remaining": rul_a_display,
            "hours_remaining" : round(rul_a * HOURS_PER_CYCLE, 1)
        },
        "model_b": {
            "name"            : "Gradient Boosting",
            "cycles_remaining": rul_b_display,
            "hours_remaining" : round(rul_b * HOURS_PER_CYCLE, 1)
        },
        "difference_cycles" : difference,
        "agreement_pct"     : agreement,
        "consensus"         : consensus,
        "winner"            : winner,
        "winner_label"      : winner_label,
        "winner_rul"        : winner_rul,
        "urgency"           : urgency
    }