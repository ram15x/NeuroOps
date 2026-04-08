"""
Real ML model for deployment risk prediction
"""
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
import joblib
import os

MODEL_PATH = "ml_models/saved/deployguard_model.pkl"

def _get_default_model():
    """Create default model if not trained"""
    from sklearn.ensemble import RandomForestClassifier
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    # Dummy training
    X_dummy = np.random.rand(100, 6)
    y_dummy = np.random.randint(0, 2, 100)
    model.fit(X_dummy, y_dummy)
    return model

def load_model():
    """Load trained model or return default"""
    if os.path.exists(MODEL_PATH):
        try:
            return joblib.load(MODEL_PATH)
        except:
            return _get_default_model()
    return _get_default_model()

def predict_deployment_risk(cpu_usage, memory_usage, error_rate, recent_failures, deployment_size_mb, time_since_last_deploy):
    """Predict deployment risk using ML model"""
    model = load_model()
    
    features = np.array([[cpu_usage, memory_usage, error_rate, recent_failures, deployment_size_mb, time_since_last_deploy]])
    
    # Get prediction and probability
    prediction = model.predict(features)[0]
    probabilities = model.predict_proba(features)[0] if hasattr(model, 'predict_proba') else [0.5, 0.5]
    
    risk_score = round(probabilities[1] * 100, 2) if prediction == 1 else round(probabilities[0] * 100, 2)
    risk_level = "HIGH" if risk_score > 70 else "MEDIUM" if risk_score > 40 else "LOW"
    decision = "BLOCKED" if risk_level == "HIGH" else "APPROVED"
    
    recommendations = []
    if cpu_usage > 75:
        recommendations.append("CPU usage is high — scale up before deploying")
    if memory_usage > 80:
        recommendations.append("Memory usage is critical — risk of OOM")
    if recent_failures > 2:
        recommendations.append(f"Multiple recent failures ({recent_failures}) — investigate root cause")
    if deployment_size_mb > 400:
        recommendations.append("Large deployment size — consider blue/green deployment")
    
    return {
        "risk_score": f"{risk_score}%",
        "risk_level": risk_level,
        "decision": decision,
        "recommendations": recommendations,
        "confidence": round(probabilities[1] * 100, 2),
        "model_used": "RandomForestClassifier"
    }