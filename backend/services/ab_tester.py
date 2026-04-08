import joblib
import os
import json
import shutil
import numpy as np
from datetime import datetime, timedelta
from backend.core.config import settings
from backend.services.redis_service import redis_client
from backend.core.logger import get_logger

logger = get_logger(__name__)

# Model paths
MODEL_A_PATH = os.path.join(settings.MODEL_PATH, "rf_failure_model.pkl")
MODEL_B_PATH = os.path.join(settings.MODEL_PATH, "xgb_failure_model.pkl")
PRODUCTION_MODEL_PATH = os.path.join(settings.MODEL_PATH, "xgboost_production_model.pkl")

# Redis keys
AB_TEST_STATS_KEY = "ab_test_stats"
AUTO_SWAP_CONFIG_KEY = "auto_swap_config"


def run_ab_test(features):
    """Run A/B test and track results for auto-swap"""
    try:
        model_a = joblib.load(MODEL_A_PATH)
        model_b = joblib.load(MODEL_B_PATH)
        
        prob_a = model_a.predict_proba(features)[0][1] * 100
        prob_b = model_b.predict_proba(features)[0][1] * 100
        
        # Determine winner
        if prob_a > prob_b:
            winner = "rf"
            probability = prob_a
        elif prob_b > prob_a:
            winner = "xgb"
            probability = prob_b
        else:
            winner = "tie"
            probability = prob_a
        
        # Track stats for auto-swap
        _track_prediction(winner, prob_a, prob_b)
        
        # Check if auto-swap needed
        _check_and_swap_models()
        
        logger.info(f"A/B Test - RF: {prob_a:.2f}%, XGB: {prob_b:.2f}%, Winner: {winner}")
        
        return {
            "model_a_name": "Random Forest",
            "model_a_probability": round(prob_a, 2),
            "model_b_name": "XGBoost",
            "model_b_probability": round(prob_b, 2),
            "winner": "Model A (RF)" if winner == "rf" else "Model B (XGB)" if winner == "xgb" else "Tie",
            "winner_model": winner,
            "failure_probability": round(probability, 2)
        }
    except Exception as e:
        logger.error(f"A/B test failed: {e}")
        return {"error": str(e)}


def _track_prediction(winner, prob_a, prob_b):
    """Track prediction results for auto-swap evaluation"""
    try:
        stats = redis_client.get(AB_TEST_STATS_KEY)
        if stats:
            stats = json.loads(stats)
        else:
            stats = {
                "rf_wins": 0,
                "xgb_wins": 0,
                "ties": 0,
                "total": 0,
                "rf_sum_prob": 0,
                "xgb_sum_prob": 0,
                "last_reset": datetime.utcnow().isoformat()
            }
        
        if winner == "rf":
            stats["rf_wins"] += 1
        elif winner == "xgb":
            stats["xgb_wins"] += 1
        else:
            stats["ties"] += 1
        
        stats["total"] += 1
        stats["rf_sum_prob"] += prob_a
        stats["xgb_sum_prob"] += prob_b
        
        # Keep last 7 days only
        last_reset = datetime.fromisoformat(stats["last_reset"])
        if datetime.utcnow() - last_reset > timedelta(days=7):
            stats = {
                "rf_wins": 0,
                "xgb_wins": 0,
                "ties": 0,
                "total": 0,
                "rf_sum_prob": 0,
                "xgb_sum_prob": 0,
                "last_reset": datetime.utcnow().isoformat()
            }
        
        redis_client.setex(AB_TEST_STATS_KEY, 604800, json.dumps(stats))  # 7 days TTL
    except Exception as e:
        logger.error(f"Failed to track prediction: {e}")


def _check_and_swap_models():
    """Check if auto-swap condition met and swap if needed"""
    try:
        stats = redis_client.get(AB_TEST_STATS_KEY)
        if not stats:
            return
        
        stats = json.loads(stats)
        total = stats["total"]
        
        if total < settings.AUTO_SWAP_MIN_PREDICTIONS:
            logger.info(f"Auto-swap: Need {settings.AUTO_SWAP_MIN_PREDICTIONS} predictions, have {total}")
            return
        
        rf_win_rate = (stats["rf_wins"] / total) * 100
        xgb_win_rate = (stats["xgb_wins"] / total) * 100
        
        # Check if XGB significantly outperforms RF
        if xgb_win_rate > rf_win_rate + settings.AUTO_SWAP_THRESHOLD_PERCENT:
            logger.info(f"Auto-swap: XGB win rate {xgb_win_rate:.1f}% > RF {rf_win_rate:.1f}%")
            _perform_swap("xgb")
        
        # Check if RF significantly outperforms XGB
        elif rf_win_rate > xgb_win_rate + settings.AUTO_SWAP_THRESHOLD_PERCENT:
            logger.info(f"Auto-swap: RF win rate {rf_win_rate:.1f}% > XGB {xgb_win_rate:.1f}%")
            _perform_swap("rf")
        
        else:
            logger.info(f"Auto-swap: No clear winner (RF: {rf_win_rate:.1f}%, XGB: {xgb_win_rate:.1f}%)")
            
    except Exception as e:
        logger.error(f"Auto-swap check failed: {e}")


def _perform_swap(winner):
    """Execute model swap"""
    try:
        source_path = MODEL_A_PATH if winner == "rf" else MODEL_B_PATH
        source_name = "Random Forest" if winner == "rf" else "XGBoost"
        
        # Backup current production model
        if os.path.exists(PRODUCTION_MODEL_PATH):
            backup_path = PRODUCTION_MODEL_PATH + ".backup"
            shutil.copy(PRODUCTION_MODEL_PATH, backup_path)
            logger.info(f"Backed up production model to {backup_path}")
        
        # Swap
        shutil.copy(source_path, PRODUCTION_MODEL_PATH)
        logger.info(f"Auto-swap completed: {source_name} is now production model")
        
        # Record swap event
        swap_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "winner": winner,
            "source_model": source_name
        }
        
        redis_client.lpush("model_swap_history", json.dumps(swap_record))
        redis_client.ltrim("model_swap_history", 0, 9)  # Keep last 10 swaps
        
        # Reset stats after swap
        redis_client.delete(AB_TEST_STATS_KEY)
        
    except Exception as e:
        logger.error(f"Swap failed: {e}")


def get_swap_history():
    """Get last 10 model swaps"""
    try:
        history = redis_client.lrange("model_swap_history", 0, -1)
        return [json.loads(h) for h in history]
    except Exception as e:
        return {"error": str(e)}


def get_ab_test_stats():
    """Get current A/B test statistics"""
    try:
        stats = redis_client.get(AB_TEST_STATS_KEY)
        if stats:
            return json.loads(stats)
        return {"message": "No A/B test data yet"}
    except Exception as e:
        return {"error": str(e)}