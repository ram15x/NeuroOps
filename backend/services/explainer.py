import shap
import numpy as np
import pandas as pd
from threading import Lock

_explainer = None
_explainer_lock = Lock()


def load_explainer(model, scaler, background_data: pd.DataFrame):
    global _explainer
    
    with _explainer_lock:
        if _explainer is None:
            n_features = scaler.n_features_in_ if hasattr(scaler, 'n_features_in_') else background_data.shape[1]
            print(f"Explainer: scaler expects {n_features} features")
            
            if background_data.shape[1] > n_features:
                background_data = background_data.iloc[:, :n_features]
            
            X_scaled = scaler.transform(background_data)
            _explainer = shap.TreeExplainer(model)
    
    return _explainer


def get_explainer():
    return _explainer


def explain_prediction(model, scaler, input_features: dict) -> dict:
    global _explainer

    if _explainer is None:
        return {"error": "Explainer not loaded. Call load_explainer() first."}

    n_features = scaler.n_features_in_ if hasattr(scaler, 'n_features_in_') else 4
    
    if n_features == 2:
        feature_names = ["cpu", "memory"]
        input_mapped = {
            "cpu": input_features.get("value", input_features.get("cpu", 0)),
            "memory": input_features.get("memory", input_features.get("rolling_mean", 0))
        }
    else:
        feature_names = ["value", "rolling_mean", "rolling_std", "value_diff"]
        input_mapped = input_features
    
    X = pd.DataFrame([input_mapped])[feature_names]
    X_scaled = scaler.transform(X)
    shap_values = _explainer.shap_values(X_scaled)
    values = shap_values[0] if isinstance(shap_values, list) else shap_values[0]

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

    sorted_contributions = dict(
        sorted(contributions.items(),
               key=lambda x: abs(x[1]["shap_value"]),
               reverse=True)
    )

    if sorted_contributions:
        top_feature = list(sorted_contributions.keys())[0]
        top_contrib = sorted_contributions[top_feature]
        top_reason = f"{top_feature} is the main driver ({top_contrib['contribution']} contribution)"
    else:
        top_reason = "No significant contributors"

    return {
        "feature_contributions": sorted_contributions,
        "top_reason": top_reason,
        "explanation": build_explanation(sorted_contributions, input_mapped)
    }


def build_explanation(contributions: dict, inputs: dict) -> str:
    lines = []
    for feature, data in list(contributions.items())[:3]:
        value = inputs.get(feature, 0)
        lines.append(
            f"{feature}={value} contributed {data['contribution']} ({data['direction']})"
        )
    return " | ".join(lines)
