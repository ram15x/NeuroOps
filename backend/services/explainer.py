import shap
import numpy as np
import pandas as pd
from threading import Lock

# singleton explainer loaded once
_explainer = None
_explainer_lock = Lock()


def load_explainer(model, scaler, background_data: pd.DataFrame):
    """Load SHAP explainer once at startup (singleton)"""
    global _explainer
    
    with _explainer_lock:
        if _explainer is None:
            X_scaled = scaler.transform(background_data)
            _explainer = shap.TreeExplainer(model)
    
    return _explainer


def get_explainer():
    """Get the singleton explainer instance"""
    return _explainer


def explain_prediction(model, scaler, input_features: dict) -> dict:
    """Takes a single prediction input and returns feature contributions"""
    global _explainer

    if _explainer is None:
        return {"error": "Explainer not loaded. Call load_explainer() first."}

    feature_names = ["value", "rolling_mean", "rolling_std", "value_diff"]

    X = pd.DataFrame([input_features])[feature_names]
    X_scaled = scaler.transform(X)

    # get SHAP values for this prediction
    shap_values = _explainer.shap_values(X_scaled)

    # shap_values shape is (1, n_features) for tree explainer
    values = shap_values[0] if isinstance(shap_values, list) else shap_values[0]

    # build contribution dict - positive means pushed toward anomaly
    contributions = {}
    total = sum(abs(v) for v in values)

    for i, feature in enumerate(feature_names):
        raw = float(values[i])
        percentage = round((abs(raw) / total) * 100, 1) if total > 0 else 0
        direction = "toward anomaly" if raw > 0 else "toward normal"
        contributions[feature] = {
            "shap_value": round(raw, 4),
            "contribution": f"{percentage}%",
            "direction": direction
        }

    # sort by contribution size
    sorted_contributions = dict(
        sorted(contributions.items(),
               key=lambda x: abs(x[1]["shap_value"]),
               reverse=True)
    )

    # top reason is the feature with highest contribution
    top_feature = list(sorted_contributions.keys())[0]
    top_contrib = sorted_contributions[top_feature]

    return {
        "feature_contributions": sorted_contributions,
        "top_reason": f"{top_feature} is the main driver ({top_contrib['contribution']} contribution)",
        "explanation": build_explanation(sorted_contributions, input_features)
    }


def build_explanation(contributions: dict, inputs: dict) -> str:
    """Builds a human readable explanation of the prediction"""
    lines = []
    for feature, data in list(contributions.items())[:3]:
        value = inputs.get(feature, 0)
        lines.append(
            f"{feature}={value} contributed {data['contribution']} ({data['direction']})"
        )
    return " | ".join(lines)