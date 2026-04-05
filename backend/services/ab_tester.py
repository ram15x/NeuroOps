import joblib
import os
import numpy as np
from datetime import datetime, timedelta
from backend.core.config import settings
from backend.services.redis_service import redis_client
from backend.core.logger import get_logger

logger = get_logger(__name__)

# Model paths - TWO DIFFERENT MODELS for true A/B testing
MODEL_A_PATH = os.path.join(settings.MODEL_PATH, "rf_failure_model.pkl")    # Random Forest
MODEL_B_PATH = os.path.join(settings.MODEL_PATH, "xgb_failure_model.pkl")   # XGBoost
PRODUCTION_MODEL_PATH = os.path.join(settings.MODEL_PATH, "xgboost_production_model.pkl")

# Track model performance
MODEL_PERFORMANCE_KEY = "model_performance"


def run_ab_test(features):
    """Run A/B test between Random Forest and XGBoost"""
    try:
        # Load both models
        model_a = joblib.load(MODEL_A_PATH)
        model_b = joblib.load(MODEL_B_PATH)
        
        # Get predictions (probability of failure)
        prob_a = model_a.predict_proba(features)[0][1] * 100
        prob_b = model_b.predict_proba(features)[0][1] * 100
        
        # Choose more conservative (higher probability of failure)
        if prob_a > prob_b:
            winner = "Model A (Random Forest)"
            probability = prob_a
            winner_model = "rf"
        elif prob_b > prob_a:
            winner = "Model B (XGBoost)"
            probability = prob_b
            winner_model = "xgb"
        else:
            winner = "Both models agree"
            probability = prob_a
            winner_model = "both"
        
        # Log the comparison
        logger.info(f"A/B Test - RF: {prob_a:.2f}%, XGB: {prob_b:.2f}%, Winner: {winner}")
        
        return {
            "model_a_name": "Random Forest",
            "model_a_probability": round(prob_a, 2),
            "model_b_name": "XGBoost",
            "model_b_probability": round(prob_b, 2),
            "winner": winner,
            "winner_model": winner_model,
            "failure_probability": round(probability, 2),
            "agreement_pct": round(100 - abs(prob_a - prob_b), 2),
            "difference": round(abs(prob_a - prob_b), 2)
        }
    except FileNotFoundError as e:
        logger.error(f"Model file not found: {e}")
        return {"error": "Models not trained yet. Run training scripts first.", "note": str(e)}
    except Exception as e:
        logger.error(f"A/B test failed: {e}")
        return {"error": str(e)}


def evaluate_and_swap_models():
    """
    Evaluate both models on recent data and swap production model if needed.
    Runs automatically every 24 hours.
    """
    try:
        from backend.models.database import SessionLocal, PredictionHistory, Alert
        
        db = SessionLocal()
        
        # Get predictions from last 7 days
        cutoff = datetime.utcnow() - timedelta(days=7)
        predictions = db.query(PredictionHistory).filter(
            PredictionHistory.created_at >= cutoff,
            PredictionHistory.model_name.in_(['rf_failure_model', 'xgb_failure_model'])
        ).all()
        
        if len(predictions) < 50:
            logger.info(f"Not enough data for evaluation (need 50, have {len(predictions)})")
            db.close()
            return
        
        # Calculate accuracy for each model
        rf_correct = 0
        xgb_correct = 0
        rf_total = 0
        xgb_total = 0
        
        for pred in predictions:
            # Get actual outcome from alerts
            actual_failure = db.query(Alert).filter(
                Alert.created_at >= pred.created_at - timedelta(minutes=5),
                Alert.created_at <= pred.created_at + timedelta(minutes=5),
                Alert.severity == "critical"
            ).first()
            
            predicted_failure = pred.prediction.get("will_fail", False)
            actual = actual_failure is not None
            
            if pred.model_name == 'rf_failure_model':
                rf_total += 1
                if predicted_failure == actual:
                    rf_correct += 1
            elif pred.model_name == 'xgb_failure_model':
                xgb_total += 1
                if predicted_failure == actual:
                    xgb_correct += 1
        
        rf_accuracy = (rf_correct / rf_total * 100) if rf_total > 0 else 0
        xgb_accuracy = (xgb_correct / xgb_total * 100) if xgb_total > 0 else 0
        
        logger.info(f"Model Performance - RF: {rf_accuracy:.2f}% ({rf_correct}/{rf_total}), XGB: {xgb_accuracy:.2f}% ({xgb_correct}/{xgb_total})")
        
        # Determine winner
        if xgb_accuracy > rf_accuracy:
            winner = "XGBoost"
            winner_path = MODEL_B_PATH
            logger.info(f"XGBoost performs better! Swapping production model...")
        elif rf_accuracy > xgb_accuracy:
            winner = "Random Forest"
            winner_path = MODEL_A_PATH
            logger.info(f"Random Forest performs better! Swapping production model...")
        else:
            winner = "Tie"
            winner_path = None
            logger.info("Both models perform equally. No change.")
        
        # Update production model if winner found
        if winner_path and os.path.exists(winner_path):
            import shutil
            shutil.copy(winner_path, PRODUCTION_MODEL_PATH)
            logger.info(f"Production model updated to {winner}")
            
            # Store performance metrics
            performance_data = {
                "last_evaluated": datetime.utcnow().isoformat(),
                "rf_accuracy": rf_accuracy,
                "xgb_accuracy": xgb_accuracy,
                "winner": winner,
                "rf_correct": rf_correct,
                "rf_total": rf_total,
                "xgb_correct": xgb_correct,
                "xgb_total": xgb_total
            }
            redis_client.setex(MODEL_PERFORMANCE_KEY, 86400, json.dumps(performance_data))
        
        db.close()
        return {"winner": winner, "rf_accuracy": rf_accuracy, "xgb_accuracy": xgb_accuracy}
        
    except Exception as e:
        logger.error(f"Model evaluation failed: {e}")
        return {"error": str(e)}


def get_model_performance():
    """Get cached model performance metrics"""
    try:
        cached = redis_client.get(MODEL_PERFORMANCE_KEY)
        if cached:
            return json.loads(cached)
        return {"message": "No performance data available yet"}
    except Exception as e:
        return {"error": str(e)}