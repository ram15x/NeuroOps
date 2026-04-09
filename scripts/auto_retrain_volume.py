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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.models.database import SessionLocal, MetricHistory, Alert
from backend.core.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

STATE_FILE = "/home/ec2-user/NeuroOps/.retrain_state.json"
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
    """Train InfraMind on REAL AWS CPU metrics"""
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
    
    X = df[['value', 'rolling_mean', 'rolling_std', 'value_diff']].fillna(0)
    
    print(f"Training InfraMind on {len(X)} samples...")
    model = IsolationForest(n_estimators=100, contamination=0.08, random_state=42)
    model.fit(X)
    
    scaler = StandardScaler()
    scaler.fit(X)
    
    os.makedirs('ml_models/saved', exist_ok=True)
    joblib.dump(model, 'ml_models/saved/inframind_model.pkl')
    joblib.dump(scaler, 'ml_models/saved/inframind_scaler.pkl')
    
    print(f"✅ InfraMind trained on {len(df)} CPU metrics")
    return True

def train_rul_on_aws_data():
    """Train RUL model on REAL AWS data (3 features: CPU, Memory, Age)"""
    db = SessionLocal()
    
    cutoff = datetime.utcnow() - timedelta(days=30)
    metrics = db.query(MetricHistory).filter(
        MetricHistory.timestamp > cutoff
    ).order_by(MetricHistory.timestamp).all()
    db.close()
    
    if len(metrics) < 100:
        print(f"⚠️ Only {len(metrics)} samples, need at least 100")
        return False
    
    # Process data
    data = {}
    for m in metrics:
        ts = m.timestamp
        if ts not in data:
            data[ts] = {'timestamp': ts}
        data[ts][m.metric_name] = m.value
    
    df = pd.DataFrame(list(data.values()))
    
    if len(df) < 50:
        return False
    
    # Calculate RUL target based on CPU trend
    df['cpu_trend'] = df['cpu'].diff().fillna(0) if 'cpu' in df else 0
    df['rul'] = 100 - (df['cpu'].fillna(50) / 100 * 50) - (df['cpu_trend'].clip(0, 50) / 2)
    df['rul'] = df['rul'].clip(0, 100)
    
    # Use 3 features: CPU, Memory, Age
    X = np.column_stack([
        df['cpu'].fillna(50).values,
        df['memory'].fillna(50).values if 'memory' in df else np.full(len(df), 50),
        np.arange(len(df)) / 30
    ])
    y = df['rul'].values
    
    print(f"Training RUL model on {len(df)} samples...")
    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X, y)
    
    scaler = StandardScaler()
    scaler.fit(X)
    
    joblib.dump(model, 'ml_models/saved/rul_real_model.pkl')
    joblib.dump(scaler, 'ml_models/saved/rul_real_scaler.pkl')
    
    print(f"✅ RUL model trained on {len(df)} samples")
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
        else:
            print("❌ Retraining had issues, check logs")
        
        return success
    else:
        needed = RETRAIN_THRESHOLD - new_records
        print(f"✅ No retrain needed. Need {needed} more records to trigger retrain.")
        return False

if __name__ == "__main__":
    check_and_retrain()
