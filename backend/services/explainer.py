import shap
import numpy as np
import pandas as pd

# global explainer loaded once at startup
explainer = None

def load_explainer(model, scaler, background_data: pd.DataFrame):
    # creates SHAP explainer using iso forest
    # background_data is a sample from training data used as reference
    global explainer
    X_scaled   = scaler.transform(background_data)
    explainer  = shap.TreeExplainer(model)
    return explainer

def explain_prediction(model, scaler, input_features: dict) -> dict:
    # takes a single prediction input and returns feature contributions
    global explainer

    if explainer is None:
        return {"error": "Explainer not loaded"}

    feature_names = ["value", "rolling_mean", "rolling_std", "value_diff"]

    X = pd.DataFrame([input_features])[feature_names]
    X_scaled = scaler.transform(X)

    # get SHAP values for this prediction
    shap_values = explainer.shap_values(X_scaled)

    # shap_values shape is (1, n_features) for tree explainer
    values = shap_values[0] if isinstance(shap_values, list) else shap_values[0]

    # build contribution dict - positive means pushed toward anomaly
    contributions = {}
    total = sum(abs(v) for v in values)

    for i, feature in enumerate(feature_names):
        raw        = float(values[i])
        percentage = round((abs(raw) / total) * 100, 1) if total > 0 else 0
        direction  = "toward anomaly" if raw > 0 else "toward normal"
        contributions[feature] = {
            "shap_value"  : round(raw, 4),
            "contribution": f"{percentage}%",
            "direction"   : direction
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
        "top_reason"           : f"{top_feature} is the main driver ({top_contrib['contribution']} contribution)",
        "explanation"          : build_explanation(sorted_contributions, input_features)
    }


def build_explanation(contributions: dict, inputs: dict) -> str:
    # builds a human readable explanation of the prediction
    lines = []
    for feature, data in list(contributions.items())[:3]:
        value  = inputs.get(feature, 0)
        lines.append(
            f"{feature}={value} contributed {data['contribution']} ({data['direction']})"
        )
    return " | ".join(lines)