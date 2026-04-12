#!/usr/bin/env python
"""
Train RUL (Remaining Useful Life) model on REAL EC2 data
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
import joblib
from datetime import datetime

print("=" * 60)
print("TRAINING RUL MODEL ON REAL EC2 DATA")
print("=" * 60)

# Load combined training data
combined_file = 'data/combined_training_data.csv'
if not os.path.exists(combined_file):
    print(f"ERROR: {combined_file} not found!")
    sys.exit(1)

df = pd.read_csv(combined_file)
print(f"Loaded {len(df)} records")

# Parse timestamp
df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
df = df.dropna(subset=['timestamp'])
print(f"After timestamp cleaning: {len(df)} records")

# Sort by instance and timestamp
df = df.sort_values(['instance_id', 'timestamp'])

# Calculate simulated RUL based on CPU patterns
def calculate_simulated_rul(group):
    n = len(group)
    rul_values = []
    for i in range(n):
        cpu = group.iloc[i]['cpu']
        if cpu > 90:
            base_rul = max(5, 30 - (cpu - 90) * 2)
        elif cpu > 80:
            base_rul = max(15, 50 - (cpu - 80) * 3)
        elif cpu > 70:
            base_rul = max(30, 80 - (cpu - 70) * 4)
        else:
            base_rul = max(50, 100 - cpu)
        position_factor = 1 - (i / n) * 0.3
        rul_value = base_rul * position_factor
        rul_values.append(max(1, min(200, rul_value)))
    return rul_values

# Apply RUL calculation - using transform instead of apply
print("\nCalculating RUL values...")
df['rul'] = df.groupby('instance_id')['cpu'].transform(
    lambda x: calculate_simulated_rul(df.loc[x.index])
)

print(f"\nRUL statistics:")
print(f"  Min: {df['rul'].min():.1f}")
print(f"  Max: {df['rul'].max():.1f}")
print(f"  Mean: {df['rul'].mean():.1f}")
print(f"  Std: {df['rul'].std():.1f}")

# Prepare features
features = ['cpu', 'memory', 'disk', 'instance_age_days']
X = df[features].values
y = df['rul'].values

# Check for NaN values
print(f"\nNaN check:")
print(f"  X has NaN: {np.isnan(X).any()}")
print(f"  y has NaN: {np.isnan(y).any()}")

# Fill NaN values if any
if np.isnan(X).any():
    print("Filling NaN values in X with column means...")
    for i in range(X.shape[1]):
        col_mean = np.nanmean(X[:, i])
        X[np.isnan(X[:, i]), i] = col_mean

if np.isnan(y).any():
    print("Filling NaN values in y with median...")
    y_median = np.nanmedian(y)
    y = np.nan_to_num(y, nan=y_median)

# Verify no NaN left
print(f"\nAfter filling:")
print(f"  X has NaN: {np.isnan(X).any()}")
print(f"  y has NaN: {np.isnan(y).any()}")

# Train/test split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

print(f"\nTraining set: {len(X_train)} records")
print(f"Test set: {len(X_test)} records")

# Scale features
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

# Train Random Forest
model = RandomForestRegressor(
    n_estimators=100,
    max_depth=10,
    min_samples_split=5,
    random_state=42,
    n_jobs=-1
)

print("\nTraining Random Forest model...")
model.fit(X_train_scaled, y_train)

# Evaluate
train_score = model.score(X_train_scaled, y_train)
test_score = model.score(X_test_scaled, y_test)

print(f"\nModel Performance:")
print(f"  Train R²: {train_score:.4f}")
print(f"  Test R²: {test_score:.4f}")

# Feature importance
importance = pd.DataFrame({
    'feature': features,
    'importance': model.feature_importances_
}).sort_values('importance', ascending=False)

print("\nFeature Importance:")
print(importance.to_string(index=False))

# Save model
os.makedirs('ml_models/saved', exist_ok=True)
joblib.dump(model, 'ml_models/saved/rul_real_model.pkl')
joblib.dump(scaler, 'ml_models/saved/rul_real_scaler.pkl')

print("\n✅ RUL model saved to ml_models/saved/rul_real_model.pkl")
print("✅ RUL scaler saved to ml_models/saved/rul_real_scaler.pkl")

# Save metadata
metadata = {
    'model_type': 'RandomForestRegressor',
    'features': features,
    'train_records': int(len(X_train)),
    'test_records': int(len(X_test)),
    'train_r2': float(train_score),
    'test_r2': float(test_score),
    'trained_at': datetime.now().isoformat(),
    'data_source': 'real_ec2_combined'
}
joblib.dump(metadata, 'ml_models/saved/rul_model_metadata.pkl')
print("✅ Metadata saved")

print("\n" + "=" * 60)
print("RUL MODEL TRAINING COMPLETE!")
print("=" * 60)