#!/usr/bin/env python
"""
Train XGBoost model for A/B testing (Model B)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
import joblib
from datetime import datetime

print("=" * 60)
print("TRAINING XGBOOST MODEL (MODEL B)")
print("=" * 60)

# Load combined training data
df = pd.read_csv('data/combined_training_data.csv')
print(f"Loaded {len(df)} records")

# Prepare features
features = ['cpu', 'memory', 'disk', 'instance_age_days']
X = df[features].fillna(df[features].median()).values
y = df['is_anomaly'].values

print(f"Features shape: {X.shape}")
print(f"Class distribution: Normal={sum(y==0)}, Anomaly={sum(y==1)}")

# Split data
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

print(f"\nTraining set: {len(X_train)} records")
print(f"Test set: {len(X_test)} records")

# Train XGBoost
model = xgb.XGBClassifier(
    n_estimators=100,
    max_depth=5,
    learning_rate=0.1,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=42,
    use_label_encoder=False,
    eval_metric='logloss'
)

print("\nTraining XGBoost model...")
model.fit(X_train, y_train)

# Evaluate
y_pred = model.predict(X_test)
accuracy = accuracy_score(y_test, y_pred)
print(f"\nModel Accuracy: {accuracy:.4f} ({accuracy*100:.2f}%)")

print("\nClassification Report:")
print(classification_report(y_test, y_pred, target_names=['Normal', 'Anomaly']))

# Feature importance
importance = pd.DataFrame({
    'feature': features,
    'importance': model.feature_importances_
}).sort_values('importance', ascending=False)

print("\nFeature Importance:")
print(importance)

# Save model
os.makedirs('ml_models/saved', exist_ok=True)
joblib.dump(model, 'ml_models/saved/xgb_failure_model.pkl')
print("\n✅ XGBoost model saved to ml_models/saved/xgb_failure_model.pkl")

# Save metadata
metadata = {
    'model_type': 'XGBClassifier',
    'features': features,
    'train_records': len(X_train),
    'test_records': len(X_test),
    'accuracy': accuracy,
    'trained_at': datetime.now().isoformat(),
    'data_source': 'real_ec2_combined'
}
joblib.dump(metadata, 'ml_models/saved/xgb_model_metadata.pkl')
print("✅ Metadata saved")

print("\n" + "=" * 60)
print("XGBOOST MODEL TRAINING COMPLETE!")
print("=" * 60)