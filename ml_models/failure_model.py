import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report
import joblib
import os

# ── Paths ──────────────────────────────────────────────
INPUT_FILE  = "datasets/processed/failure_clean.csv"
MODEL_DIR   = "ml_models/saved"
MODEL_PATH  = f"{MODEL_DIR}/failure_model.pkl"
SCALER_PATH = f"{MODEL_DIR}/failure_scaler.pkl"

os.makedirs(MODEL_DIR, exist_ok=True)

# ── Load Data ──────────────────────────────────────────
print("Loading failure dataset...")
df = pd.read_csv(INPUT_FILE)
print(f"Shape: {df.shape}")

# ── Add RUL (Remaining Useful Life) ───────────────────
print("Calculating RUL...")
max_cycle = df.groupby("unit")["cycle"].max().reset_index()
max_cycle.columns = ["unit", "max_cycle"]
df = df.merge(max_cycle, on="unit")
df["RUL"] = df["max_cycle"] - df["cycle"]

# ── Label: will fail within 30 cycles? ────────────────
df["failure_soon"] = (df["RUL"] <= 30).astype(int)

print(f"Failure cases  : {df['failure_soon'].sum()}")
print(f"Normal cases   : {(df['failure_soon'] == 0).sum()}")

# ── Features ───────────────────────────────────────────
SENSOR_COLS = [col for col in df.columns if col.startswith("sensor")]
X = df[SENSOR_COLS].fillna(0)
y = df["failure_soon"]

# ── Train/Test Split ───────────────────────────────────
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

# ── Scale ──────────────────────────────────────────────
print("Scaling features...")
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled  = scaler.transform(X_test)

# ── Train Random Forest ────────────────────────────────
print("Training Random Forest model...")
model = RandomForestClassifier(
    n_estimators=100,
    max_depth=10,
    random_state=42,
    n_jobs=-1
)
model.fit(X_train_scaled, y_train)

# ── Evaluate ───────────────────────────────────────────
y_pred = model.predict(X_test_scaled)
print(f"\n{'='*40}")
print(f"  Failure Prediction Model Results!")
print(f"{'='*40}")
print(classification_report(y_test, y_pred))

# ── Save ───────────────────────────────────────────────
joblib.dump(model,  MODEL_PATH)
joblib.dump(scaler, SCALER_PATH)
print(f"Model  saved → {MODEL_PATH}")
print(f"Scaler saved → {SCALER_PATH}")