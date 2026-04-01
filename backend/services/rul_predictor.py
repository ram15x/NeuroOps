import joblib
import numpy as np
import os
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler

from backend.core.config import settings

MODEL_PATH = os.path.join(settings.MODEL_PATH, settings.RUL_MODEL_A_FILE)
SCALER_PATH = os.path.join(settings.MODEL_PATH, settings.RUL_SCALER_A_FILE)

model = joblib.load(MODEL_PATH)
scaler = joblib.load(SCALER_PATH)


def predict_rul(sensor_values: list) -> dict:
    """Predict RUL with confidence interval"""
    
    X = np.array(sensor_values).reshape(1, -1)
    X_scaled = scaler.transform(X)

    cycles_left = float(model.predict(X_scaled)[0])
    cycles_left = max(0.0, round(cycles_left, 1))
    hours_left = round(cycles_left * settings.HOURS_PER_CYCLE, 1)

    # Calculate confidence interval using model's internal uncertainty
    # For Random Forest, use predictions from individual trees
    if hasattr(model, 'estimators_'):
        tree_predictions = [tree.predict(X_scaled)[0] for tree in model.estimators_]
        lower_bound = max(0.0, round(np.percentile(tree_predictions, 10), 1))
        upper_bound = max(0.0, round(np.percentile(tree_predictions, 90), 1))
        confidence = 80  # 80% confidence interval
    else:
        # Fallback: ±15% interval
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
        recommendation = "Plan maintenance soon. Engine degrading."
    else:
        urgency = "LOW"
        recommendation = "Engine healthy. Continue monitoring."

    return {
        "cycles_remaining": cycles_left,
        "hours_remaining": hours_left,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "confidence_pct": confidence,
        "urgency": urgency,
        "recommendation": recommendation
    }


def predict_rul_with_interval(sensor_values: list, confidence: float = 95) -> dict:
    """Predict RUL with custom confidence interval"""
    
    X = np.array(sensor_values).reshape(1, -1)
    X_scaled = scaler.transform(X)

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
        else:  # default 80%
            lower = np.percentile(tree_predictions, 10)
            upper = np.percentile(tree_predictions, 90)
        
        lower_bound = max(0.0, round(lower, 1))
        upper_bound = max(0.0, round(upper, 1))
    else:
        # Fallback
        factor = confidence / 100
        lower_bound = max(0.0, round(cycles_left * (1 - factor * 0.2), 1))
        upper_bound = round(cycles_left * (1 + factor * 0.2), 1)
    
    return {
        "cycles_remaining": cycles_left,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "confidence_pct": confidence
    }