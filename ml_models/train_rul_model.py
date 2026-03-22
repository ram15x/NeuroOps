import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, r2_score
import joblib
import os
 
TRAIN_PATH = "datasets/processed/failure_clean.csv"
MODEL_OUT   = "ml_models/saved/failure_rul_model.pkl"
SCALER_OUT  = "ml_models/saved/failure_rul_scaler.pkl"
 
print("loading data...")
df = pd.read_csv(TRAIN_PATH)
 
# calculate max cycle per unit so we can compute RUL
max_cycle = df.groupby("unit")["cycle"].max().reset_index()
max_cycle.columns = ["unit", "max_cycle"]
df = df.merge(max_cycle, on="unit")
 
# RUL = how many cycles are left for this engine at this point
df["RUL"] = df["max_cycle"] - df["cycle"]
 
# cap RUL at 125 so the model focuses on the useful range
# engines with 300 cycles left are "fine" — we care about the last 125
df["RUL"] = df["RUL"].clip(upper=125)
 
# sensor columns only — same ones used in failure_model.pkl
sensor_cols = [f"sensor{i}" for i in range(1, 25)]
# only keep sensor columns that exist in the dataset
sensor_cols = [c for c in sensor_cols if c in df.columns]
 
X = df[sensor_cols].values
y = df["RUL"].values
 
# scale features
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)
 
print(f"training on {len(X)} samples, {len(sensor_cols)} sensors...")
model = RandomForestRegressor(
    n_estimators=100,
    max_depth=15,
    random_state=42,
    n_jobs=-1  # use all cores
)
model.fit(X_scaled, y)
 
# quick eval on training data
preds = model.predict(X_scaled)
mae   = mean_absolute_error(y, preds)
r2    = r2_score(y, preds)
print(f"train MAE: {mae:.2f} cycles")
print(f"train R2 : {r2:.4f}")
 
# save model and scaler
os.makedirs("ml_models/saved", exist_ok=True)
joblib.dump(model,  MODEL_OUT)
joblib.dump(scaler, SCALER_OUT)
 
print(f"saved model  -> {MODEL_OUT}")
print(f"saved scaler -> {SCALER_OUT}")
print("done. run the server and hit /api/v1/failure/countdown")
 