import joblib
import numpy as np
import os

from backend.core.config import settings

# build paths from config
MODEL_A_PATH = os.path.join(settings.MODEL_PATH, settings.RUL_MODEL_A_FILE)
SCALER_A_PATH = os.path.join(settings.MODEL_PATH, settings.RUL_SCALER_A_FILE)
MODEL_B_PATH = os.path.join(settings.MODEL_PATH, settings.RUL_MODEL_B_FILE)
SCALER_B_PATH = os.path.join(settings.MODEL_PATH, settings.RUL_SCALER_B_FILE)

model_a = joblib.load(MODEL_A_PATH)
scaler_a = joblib.load(SCALER_A_PATH)
model_b = joblib.load(MODEL_B_PATH)
scaler_b = joblib.load(SCALER_B_PATH)

def run_ab_test(sensor_values: list) -> dict:
    X = np.array(sensor_values).reshape(1, -1)

    # model a
    X_a = scaler_a.transform(X)
    rul_a_raw = float(model_a.predict(X_a)[0])
    rul_a = max(0.0, round(rul_a_raw, 1))

    # model b
    X_b = scaler_b.transform(X)
    rul_b_raw = float(model_b.predict(X_b)[0])
    rul_b = max(0.0, round(rul_b_raw, 1))

    rul_a_display = rul_a if rul_a_raw >= 0 else f"overdue ({round(rul_a_raw, 1)})"
    rul_b_display = rul_b if rul_b_raw >= 0 else f"overdue ({round(rul_b_raw, 1)})"

    difference = round(abs(rul_a - rul_b), 1)
    max_rul = max(rul_a, rul_b, 1)
    agreement = round((1 - difference / max_rul) * 100, 1)
    agreement = max(0.0, agreement)

    # winner is more conservative (lower RUL)
    if rul_a <= rul_b:
        winner = "model_a"
        winner_label = "Random Forest"
        winner_rul = rul_a
    else:
        winner = "model_b"
        winner_label = "Gradient Boosting"
        winner_rul = rul_b

    # urgency from config thresholds
    if winner_rul <= settings.RUL_URGENCY_CRITICAL:
        urgency = "CRITICAL"
    elif winner_rul <= settings.RUL_URGENCY_HIGH:
        urgency = "HIGH"
    elif winner_rul <= settings.RUL_URGENCY_MEDIUM:
        urgency = "MEDIUM"
    else:
        urgency = "LOW"

    if agreement >= settings.AB_AGREEMENT_STRONG:
        consensus = "STRONG — both models agree"
    elif agreement >= settings.AB_AGREEMENT_MODERATE:
        consensus = "MODERATE — minor disagreement"
    else:
        consensus = "WEAK — models disagree, investigate manually"

    return {
        "model_a": {
            "name": "Random Forest",
            "cycles_remaining": rul_a_display,
            "hours_remaining": round(rul_a * settings.HOURS_PER_CYCLE, 1)
        },
        "model_b": {
            "name": "Gradient Boosting",
            "cycles_remaining": rul_b_display,
            "hours_remaining": round(rul_b * settings.HOURS_PER_CYCLE, 1)
        },
        "difference_cycles": difference,
        "agreement_pct": agreement,
        "consensus": consensus,
        "winner": winner,
        "winner_label": winner_label,
        "winner_rul": winner_rul,
        "urgency": urgency
    }