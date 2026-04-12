#!/usr/bin/env python
"""
Auto-retrain models weekly with new data from database
Run this every week via Task Scheduler
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import xgboost as xgb
import joblib
from datetime import datetime, timedelta
from backend.models.database import SessionLocal, MetricHistory, Alert
from backend.core.logger import get_logger

logger = get_logger(__name__)

def fetch_training_data_from_db(days: int = 30):
    """Fetch real metrics from database for retraining"""
    db = SessionLocal()
    
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    # Get all metrics from last N days
    metrics = db.query(MetricHistory).filter(
        MetricHistory.timestamp >= cutoff,
        MetricHistory.metric_name.in_(['cpu', 'memory', 'disk'])
    ).all()
    
    if len(metrics) < 100:
        logger.info(f"Not enough data for retraining (need 100, have {len(metrics)})")
        db.close()
        return None
    
    # Convert to DataFrame
    data = []
    for m in metrics:
        data.append({
            'instance_id': m.instance_id,
            'metric_name': m.metric_name,
            'value': m.value,
            'timestamp': m.timestamp
        })
    
    df = pd.DataFrame(data)
    
    # Pivot to get one row per timestamp
    df['timestamp_rounded'] = df['timestamp'].dt.floor('min')
    df_pivot = df.pivot_table(
        index=['instance_id', 'timestamp_rounded'],
        columns='metric_name',
        values='value'
    ).reset_index()
    
    df_pivot.columns.name = None
    df_pivot = df_pivot.rename(columns={'timestamp_rounded': 'timestamp'})
    
    # Check for anomalies in this period - FIXED datetime floor issue
    alerts = db.query(Alert).filter(
        Alert.created_at >= cutoff,
        Alert.severity == "critical"
    ).all()
    
    # Convert alert times to rounded timestamps
    alert_times = set()
    for a in alerts:
        rounded = a.created_at.replace(second=0, microsecond=0)
        alert_times.add(rounded)
    
    # Add labels
    df_pivot['is_anomaly'] = df_pivot['timestamp'].apply(
        lambda x: 1 if x in alert_times else 0
    )
    
    # Add instance_age_days
    if 'timestamp' in df_pivot.columns:
        min_date = df_pivot['timestamp'].min()
        df_pivot['instance_age_days'] = (df_pivot['timestamp'] - min_date).dt.days
    else:
        df_pivot['instance_age_days'] = 0
    
    # Fill missing values
    numeric_cols = ['cpu', 'memory', 'disk', 'instance_age_days']
    for col in numeric_cols:
        if col in df_pivot.columns:
            df_pivot[col] = df_pivot[col].fillna(df_pivot[col].median())
        else:
            df_pivot[col] = 0
    
    db.close()
    
    return df_pivot

def retrain_models():
    """Retrain both models with latest data"""
    print("=" * 60)
    print("AUTO-RETRAINING MODELS")
    print("=" * 60)
    print(f"Started at: {datetime.now()}")
    print("-" * 60)
    
    # Fetch training data
    df = fetch_training_data_from_db(days=30)
    
    if df is None or len(df) < 100:
        print("❌ Not enough data for retraining. Skipping...")
        return
    
    print(f"✅ Retrieved {len(df)} records for retraining")
    
    # Prepare features
    features = ['cpu', 'memory', 'disk', 'instance_age_days']
    
    # Ensure all features exist
    for f in features:
        if f not in df.columns:
            df[f] = 0
    
    X = df[features].fillna(df[features].median()).values
    y = df['is_anomaly'].values
    
    print(f"Features shape: {X.shape}")
    print(f"Class distribution: Normal={sum(y==0)}, Anomaly={sum(y==1)}")
    
    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    
    print(f"\nTraining set: {len(X_train)} records")
    print(f"Test set: {len(X_test)} records")
    
    # ========== RETRAIN RANDOM FOREST ==========
    print("\n🔄 Retraining Random Forest...")
    rf_model = RandomForestClassifier(
        n_estimators=100,
        max_depth=10,
        min_samples_split=5,
        random_state=42,
        n_jobs=-1
    )
    rf_model.fit(X_train, y_train)
    rf_accuracy = accuracy_score(y_test, rf_model.predict(X_test))
    print(f"   Random Forest Accuracy: {rf_accuracy:.4f} ({rf_accuracy*100:.2f}%)")
    
    # ========== RETRAIN XGBOOST ==========
    print("\n🔄 Retraining XGBoost...")
    xgb_model = xgb.XGBClassifier(
        n_estimators=100,
        max_depth=5,
        learning_rate=0.1,
        random_state=42,
        use_label_encoder=False,
        eval_metric='logloss'
    )
    xgb_model.fit(X_train, y_train)
    xgb_accuracy = accuracy_score(y_test, xgb_model.predict(X_test))
    print(f"   XGBoost Accuracy: {xgb_accuracy:.4f} ({xgb_accuracy*100:.2f}%)")
    
    # ========== DETERMINE WINNER ==========
    if xgb_accuracy > rf_accuracy:
        winner = "XGBoost"
        winner_model = xgb_model
        winner_path = 'ml_models/saved/xgb_failure_model.pkl'
        print(f"\n🏆 Winner: XGBoost ({xgb_accuracy*100:.2f}% vs {rf_accuracy*100:.2f}%)")
    elif rf_accuracy > xgb_accuracy:
        winner = "Random Forest"
        winner_model = rf_model
        winner_path = 'ml_models/saved/rf_failure_model.pkl'
        print(f"\n🏆 Winner: Random Forest ({rf_accuracy*100:.2f}% vs {xgb_accuracy*100:.2f}%)")
    else:
        winner = "Tie - Keeping current"
        winner_model = None
        print(f"\n🏆 Tie - Keeping current production model")
    
    # ========== SAVE MODELS ==========
    os.makedirs('ml_models/saved', exist_ok=True)
    
    # Always save both models
    joblib.dump(rf_model, 'ml_models/saved/rf_failure_model.pkl')
    joblib.dump(xgb_model, 'ml_models/saved/xgb_failure_model.pkl')
    print("\n✅ Random Forest model saved")
    print("✅ XGBoost model saved")
    
    # Update production model if winner found
    if winner_model is not None:
        joblib.dump(winner_model, 'ml_models/saved/xgboost_production_model.pkl')
        print(f"✅ Production model updated to {winner}")
    
    # Save metadata
    metadata = {
        'last_retrained': datetime.now().isoformat(),
        'records_used': int(len(df)),
        'rf_accuracy': float(rf_accuracy),
        'xgb_accuracy': float(xgb_accuracy),
        'winner': winner,
        'data_days': 30
    }
    joblib.dump(metadata, 'ml_models/saved/retraining_metadata.pkl')
    print("✅ Retraining metadata saved")
    
    print("\n" + "=" * 60)
    print("AUTO-RETRAINING COMPLETE!")
    print("=" * 60)

if __name__ == "__main__":
    retrain_models()