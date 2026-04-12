"""
Hybrid Anomaly Detector - Combines Isolation Forest with Z-Score
"""
import joblib
import numpy as np
import os
from backend.core.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

# Load Isolation Forest model
MODEL_PATH = os.path.join(settings.MODEL_PATH, settings.INFRAMIND_MODEL_FILE)
SCALER_PATH = os.path.join(settings.MODEL_PATH, settings.INFRAMIND_SCALER_FILE)

if_model = None
if_scaler = None

try:
    if os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH):
        if_model = joblib.load(MODEL_PATH)
        if_scaler = joblib.load(SCALER_PATH)
        logger.info("✅ Isolation Forest model loaded for hybrid detector")
except Exception as e:
    logger.warning(f"Isolation Forest not available: {e}. Using Z-Score only.")


def calculate_z_score(value: float, mean: float, std: float) -> float:
    """Calculate Z-Score"""
    if std > 0:
        return (value - mean) / std
    return 0.0


def hybrid_predict(
    value: float,
    rolling_mean: float,
    rolling_std: float,
    value_diff: float,
    use_ml: bool = True
) -> dict:
    """
    Hybrid anomaly prediction.
    Combines Isolation Forest (ML) with Z-Score (statistical).
    """
    
    # 1. Z-Score calculation
    z_score = calculate_z_score(value, rolling_mean, rolling_std)
    z_is_anomaly = abs(z_score) > 2.5 or value > 90.0
    
    # Z-Score severity
    if value > 90.0 or abs(z_score) > 4.0:
        z_severity = "critical"
    elif value > 75.0 or abs(z_score) > 2.5:
        z_severity = "warning"
    else:
        z_severity = "normal"
    
    # 2. Isolation Forest prediction (if available)
    if_is_anomaly = False
    if_score = 0.15
    if_severity = "normal"
    
    if if_model is not None and if_scaler is not None and use_ml:
        try:
            features = np.array([[value, rolling_mean, rolling_std, value_diff]])
            X_scaled = if_scaler.transform(features)
            if_score = float(if_model.decision_function(X_scaled)[0])
            if_is_anomaly = if_score < 0.0
            
            # IF severity based on score
            if if_score < -0.10:
                if_severity = "critical"
            elif if_score < 0.0:
                if_severity = "warning"
            else:
                if_severity = "normal"
        except Exception as e:
            logger.warning(f"IF prediction failed: {e}")
    
    # 3. ENSEMBLE DECISION
    # High confidence when both agree
    if z_is_anomaly and if_is_anomaly:
        is_anomaly = True
        severity = "critical" if z_severity == "critical" or if_severity == "critical" else "warning"
        confidence = "HIGH"
        reason = "Both Z-Score and Isolation Forest detected anomaly"
    
    elif z_is_anomaly or if_is_anomaly:
        is_anomaly = True
        severity = "warning"
        confidence = "MEDIUM"
        reason = f"{'Z-Score' if z_is_anomaly else 'Isolation Forest'} detected anomaly"
    
    else:
        is_anomaly = False
        severity = "normal"
        confidence = "HIGH"
        reason = "Both methods agree: normal"
    
    # Combined anomaly score (-1 to 1, lower = more anomalous)
    if is_anomaly:
        combined_score = -min(1.0, (abs(z_score) / 5.0) + max(0, -if_score))
    else:
        combined_score = 0.15
    
    return {
        "is_anomaly": is_anomaly,
        "severity": severity,
        "confidence": confidence,
        "reason": reason,
        "combined_score": round(combined_score, 4),
        "z_score": round(z_score, 2),
        "z_is_anomaly": z_is_anomaly,
        "z_severity": z_severity,
        "if_score": round(if_score, 4),
        "if_is_anomaly": if_is_anomaly,
        "if_severity": if_severity,
        "method": "hybrid"
    }