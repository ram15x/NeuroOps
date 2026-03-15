import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import joblib
import os

# ── Paths ──────────────────────────────────────────────
INPUT_FILE  = "datasets/processed/metrics_clean.csv"
MODEL_DIR   = "ml_models/saved"
MODEL_PATH  = f"{MODEL_DIR}/inframind_model.pkl"
SCALER_PATH = f"{MODEL_DIR}/inframind_scaler.pkl"

os.makedirs(MODEL_DIR, exist_ok=True)

# ── Load Data ──────────────────────────────────────────
print("Loading metrics dataset...")
df = pd.read_csv(INPUT_FILE, parse_dates=["timestamp"])

# ── Feature Engineering ────────────────────────────────
print("Engineering features...")
df = df.sort_values(["metric", "timestamp"])

df["rolling_mean"] = (
    df.groupby("metric")["value"]
    .transform(lambda x: x.rolling(window=5, min_periods=1).mean())
)

df["rolling_std"] = (
    df.groupby("metric")["value"]
    .transform(lambda x: x.rolling(window=5, min_periods=1).std().fillna(0))
)

df["value_diff"] = (
    df.groupby("metric")["value"]
    .transform(lambda x: x.diff().fillna(0))
)

# ── Prepare Features ───────────────────────────────────
FEATURES = ["value", "rolling_mean", "rolling_std", "value_diff"]
X = df[FEATURES].fillna(0)

# ── Scale ──────────────────────────────────────────────
print("Scaling features...")
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# ── Train Isolation Forest ─────────────────────────────
print("Training Isolation Forest model...")
model = IsolationForest(
    n_estimators=100,
    contamination=0.08,   # expect ~5% anomalies
    random_state=42
)
model.fit(X_scaled)

# ── Predict & Label ────────────────────────────────────
df["anomaly_score"] = model.decision_function(X_scaled)
df["predicted_anomaly"] = model.predict(X_scaled)
df["predicted_anomaly"] = df["predicted_anomaly"].map({1: 0, -1: 1})



# ── Results Summary ────────────────────────────────────
total     = len(df)
anomalies = df["predicted_anomaly"].sum()

print(f"\n{'='*40}")
print(f"  InfraMind Model Training Complete!")
print(f"{'='*40}")
print(f"  Total datapoints : {total}")
print(f"  Anomalies found  : {int(anomalies)}")
print(f"  Anomaly rate     : {anomalies/total*100:.2f}%")
print(f"{'='*40}\n")

# ── Save Model ─────────────────────────────────────────
joblib.dump(model,  MODEL_PATH)
joblib.dump(scaler, SCALER_PATH)
print(f"Model  saved → {MODEL_PATH}")
print(f"Scaler saved → {SCALER_PATH}")