import pandas as pd
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, r2_score
import joblib
import os

TRAIN_PATH = "datasets/processed/failure_clean.csv"
MODEL_OUT  = "ml_models/saved/failure_rul_model_b.pkl"
SCALER_OUT = "ml_models/saved/failure_rul_scaler_b.pkl"

print("loading data...")
df = pd.read_csv(TRAIN_PATH)

max_cycle = df.groupby("unit")["cycle"].max().reset_index()
max_cycle.columns = ["unit", "max_cycle"]
df = df.merge(max_cycle, on="unit")
df["RUL"] = df["max_cycle"] - df["cycle"]
df["RUL"] = df["RUL"].clip(upper=125)

sensor_cols = [f"sensor{i}" for i in range(1, 25)]
sensor_cols = [c for c in sensor_cols if c in df.columns]

X = df[sensor_cols].values
y = df["RUL"].values

# model b gets its own scaler so its independent from model a
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

print(f"training gradient boosting on {len(X)} samples...")
model = GradientBoostingRegressor(
    n_estimators=200,
    max_depth=5,
    learning_rate=0.05,
    random_state=42
)
model.fit(X_scaled, y)

preds = model.predict(X_scaled)
mae   = mean_absolute_error(y, preds)
r2    = r2_score(y, preds)
print(f"train MAE: {mae:.2f} cycles")
print(f"train R2 : {r2:.4f}")

os.makedirs("ml_models/saved", exist_ok=True)
joblib.dump(model,  MODEL_OUT)
joblib.dump(scaler, SCALER_OUT)

print(f"saved model  -> {MODEL_OUT}")
print(f"saved scaler -> {SCALER_OUT}")
print("done. now add the ab_tester service and endpoint.")