#!/usr/bin/env python
"""
Auto-retrain models based on data volume (every 1500 new records)
Retrains InfraMind, Failure Predictor, and RUL models on REAL AWS data
"""
import sys
import os
import json
import pickle
import joblib
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sklearn.ensemble import IsolationForest, RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, mean_absolute_error
import xgboost as xgb
from sklearn.preprocessing import StandardScaler
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.models.database import SessionLocal, MetricHistory, Alert
from backend.core.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

# SRE FIX: Platform-independent state file path
PROJECT_ROOT = str(Path(__file__).parent.parent)
STATE_FILE = os.path.join(PROJECT_ROOT, ".retrain_state.json")
RETRAIN_THRESHOLD = 1500  # Retrain after 1500 new records

def get_current_metrics_count():
    """Get current number of metrics from database"""
    db = SessionLocal()
    count = db.query(MetricHistory).count()
    db.close()
    return count

def get_last_retrain_count():
    """Get count at last retrain"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
                return state.get('last_count', 0)
        except:
            return 0
    return 0

def save_retrain_state(count, metadata):
    """Save current count after retrain"""
    with open(STATE_FILE, 'w') as f:
        json.dump({
            'last_count': count,
            'last_retrain': datetime.utcnow().isoformat(),
            'metadata': metadata
        }, f)

def train_inframind_on_aws_data():
    """Train InfraMind on REAL AWS CPU metrics with SYNTHETIC ANOMALIES"""
    db = SessionLocal()
    
    # Get CPU metrics from last 30 days
    cutoff = datetime.utcnow() - timedelta(days=30)
    metrics = db.query(MetricHistory).filter(
        MetricHistory.metric_name == 'cpu',
        MetricHistory.timestamp > cutoff
    ).order_by(MetricHistory.timestamp).all()
    db.close()
    
    if len(metrics) < 100:
        print(f"⚠️ Only {len(metrics)} CPU samples, need at least 100")
        return False
    
    df = pd.DataFrame([(m.timestamp, m.value) for m in metrics], columns=['timestamp', 'value'])
    
    # Feature engineering
    df['rolling_mean'] = df['value'].rolling(5, min_periods=1).mean()
    df['rolling_std'] = df['value'].rolling(5, min_periods=1).std().fillna(0)
    df['value_diff'] = df['value'].diff().fillna(0)
    
    # SRE FIX: Create synthetic anomalies to teach the model what "bad" looks like
    synthetic_anomalies = []
    
    # High CPU spikes (95-100%)
    for _ in range(50):
        base = np.random.uniform(95, 100)
        synthetic_anomalies.append({
            'value': base,
            'rolling_mean': base - np.random.uniform(20, 40),
            'rolling_std': np.random.uniform(15, 30),
            'value_diff': np.random.uniform(20, 50)
        })
    
    # Volatile CPU (rapid changes)
    for _ in range(50):
        synthetic_anomalies.append({
            'value': np.random.uniform(80, 95),
            'rolling_mean': np.random.uniform(40, 60),
            'rolling_std': np.random.uniform(25, 40),
            'value_diff': np.random.uniform(-30, 30)
        })
    
    # Memory-like CPU (sustained high)
    for _ in range(50):
        val = np.random.uniform(85, 95)
        synthetic_anomalies.append({
            'value': val,
            'rolling_mean': val - np.random.uniform(5, 15),
            'rolling_std': np.random.uniform(5, 15),
            'value_diff': np.random.uniform(-5, 5)
        })
    
    synthetic_df = pd.DataFrame(synthetic_anomalies)
    
    # Combine real and synthetic data
    X_real = df[['value', 'rolling_mean', 'rolling_std', 'value_diff']].fillna(0)
    X = pd.concat([X_real, synthetic_df], ignore_index=True)
    
    print(f"Training InfraMind on {len(X)} samples (including {len(synthetic_df)} synthetic anomalies)...")
    model = IsolationForest(n_estimators=200, contamination=0.05, random_state=42)
    model.fit(X)
    
    scaler = StandardScaler()
    scaler.fit(X)
    
    os.makedirs('ml_models/saved', exist_ok=True)
    joblib.dump(model, 'ml_models/saved/inframind_model.pkl')
    joblib.dump(scaler, 'ml_models/saved/inframind_scaler.pkl')
    
    # Verify the model works on a test anomaly
    test_anomaly = np.array([[95.0, 60.0, 15.0, 35.0]])
    test_normal = np.array([[30.0, 28.0, 2.0, 1.0]])
    
    pred_anomaly = model.predict(test_anomaly)[0]
    pred_normal = model.predict(test_normal)[0]
    score_anomaly = model.decision_function(test_anomaly)[0]
    score_normal = model.decision_function(test_normal)[0]
    
    print(f"   Verification:")
    print(f"   - Normal CPU (30%): prediction={pred_normal}, score={score_normal:.4f}")
    print(f"   - High CPU (95%):   prediction={pred_anomaly}, score={score_anomaly:.4f}")
    print(f"   - Model detects anomalies: {pred_anomaly == -1}")
    
    print(f"✅ InfraMind trained on {len(X_real)} real + {len(synthetic_df)} synthetic samples")
    return True

def train_rul_on_aws_data():
    """Train RUL model on REAL AWS data with 7 ENHANCED FEATURES"""
    db = SessionLocal()
    
    cutoff = datetime.utcnow() - timedelta(days=30)
    metrics = db.query(MetricHistory).filter(
        MetricHistory.timestamp > cutoff
    ).order_by(MetricHistory.timestamp).all()
    db.close()
    
    if len(metrics) < 100:
        print(f"⚠️ Only {len(metrics)} samples, need at least 100")
        return False
    
    # Pivot to align by timestamp
    data = {}
    for m in metrics:
        ts = m.timestamp
        if ts not in data:
            data[ts] = {'timestamp': ts}
        data[ts][m.metric_name] = m.value
    
    df = pd.DataFrame(list(data.values()))
    
    if len(df) < 50:
        return False
    
    # Fill missing values
    df['cpu'] = df['cpu'].fillna(50)
    df['memory'] = df['memory'].fillna(50) if 'memory' in df else 50
    df['disk'] = df['disk'].fillna(30) if 'disk' in df else 30
    
    # Enhanced feature engineering (7 features)
    df['cpu_trend'] = df['cpu'].diff().fillna(0)
    df['cpu_rolling_std'] = df['cpu'].rolling(10, min_periods=1).std().fillna(5)
    df['memory_trend'] = df['memory'].diff().fillna(0)
    df['memory_rolling_std'] = df['memory'].rolling(10, min_periods=1).std().fillna(5)
    df['disk_trend'] = df['disk'].diff().fillna(0)
    df['age_days'] = np.arange(len(df)) / 30
    
    # Synthetic RUL target with enhanced degradation
    cpu_factor = df['cpu'] / 100
    memory_factor = df['memory'] / 100
    trend_factor = (df['cpu_trend'].clip(0, 10) + df['memory_trend'].clip(0, 10)) / 20
    variance_factor = (df['cpu_rolling_std'] + df['memory_rolling_std']) / 100
    
    df['rul'] = 100 - (cpu_factor * 40) - (memory_factor * 20) - (trend_factor * 20) - (variance_factor * 20)
    df['rul'] = df['rul'].clip(5, 100)
    
    # 7 Features: CPU, Memory, Disk, Age, CPU_Trend, CPU_Std, Memory_Trend
    X = np.column_stack([
        df['cpu'].values,
        df['memory'].values,
        df['disk'].values,
        df['age_days'].values,
        df['cpu_trend'].values,
        df['cpu_rolling_std'].values,
        df['memory_trend'].values
    ])
    y = df['rul'].values
    
    print(f"Training enhanced RUL model on {len(df)} samples with 7 features...")
    print(f"   RUL range: {y.min():.1f} to {y.max():.1f} cycles")
    
    model = RandomForestRegressor(n_estimators=200, max_depth=12, random_state=42)
    model.fit(X, y)
    
    scaler = StandardScaler()
    scaler.fit(X)
    
    joblib.dump(model, 'ml_models/saved/rul_real_model.pkl')
    joblib.dump(scaler, 'ml_models/saved/rul_real_scaler.pkl')
    
    with open('ml_models/saved/rul_feature_count.txt', 'w') as f:
        f.write(str(model.n_features_in_))
    
    print(f"✅ Enhanced RUL model trained with {model.n_features_in_} features")
    return True

def check_and_retrain():
    """Main function - check if retrain needed based on volume"""
    current_count = get_current_metrics_count()
    last_count = get_last_retrain_count()
    new_records = current_count - last_count
    
    print(f"📊 Current metrics: {current_count}, Last retrain: {last_count}, New: {new_records}")
    
    if new_records >= RETRAIN_THRESHOLD:
        print(f"🔄 RETRAINING TRIGGERED! ({new_records} new records)")
        
        success = True
        if not train_inframind_on_aws_data():
            success = False
        if not train_rul_on_aws_data():
            success = False
        
        metadata = {
            'records_used': current_count,
            'retrain_trigger': f"{new_records}_new_records",
            'timestamp': datetime.utcnow().isoformat()
        }
        
        if success:
            save_retrain_state(current_count, metadata)
            print(f"✅ Retraining complete at {datetime.utcnow().isoformat()}")
            
            # Also update the original metadata file
            with open('ml_models/saved/retraining_metadata.pkl', 'wb') as f:
                pickle.dump(metadata, f)
            
            # SRE FIX: Run auto-deploy after successful retraining
            try:
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from backend.services.auto_model_deploy import check_and_deploy
                check_and_deploy()
            except Exception as e:
                print(f"Auto-deploy check failed: {e}")
        else:
            print("❌ Retraining had issues, check logs")
        
        return success
    else:
        needed = RETRAIN_THRESHOLD - new_records
        print(f"✅ No retrain needed. Need {needed} more records to trigger retrain.")
        return False

if __name__ == "__main__":
    check_and_retrain()