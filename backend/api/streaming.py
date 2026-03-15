from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from backend.services.ws_manager import manager
from backend.services.redis_service import redis_client
import joblib
import pandas as pd
import numpy as np
import asyncio
import json
import random
from datetime import datetime

router = APIRouter()

# ── Load InfraMind Model ───────────────────────────────
model  = joblib.load("ml_models/saved/inframind_model.pkl")
scaler = joblib.load("ml_models/saved/inframind_scaler.pkl")

# ── Simulated Services ─────────────────────────────────
SERVICES = [
    "payment-service",
    "auth-service",
    "api-gateway",
    "database-proxy",
    "notification-service"
]

def generate_metric(service: str) -> dict:
    """Generate realistic metric with occasional spikes"""
    is_spike = random.random() < 0.1  # 10% chance of spike

    if is_spike:
        value        = random.uniform(85, 99)
        rolling_mean = random.uniform(40, 60)
        rolling_std  = random.uniform(20, 40)
        value_diff   = random.uniform(30, 60)
    else:
        value        = random.uniform(10, 65)
        rolling_mean = random.uniform(20, 50)
        rolling_std  = random.uniform(2, 10)
        value_diff   = random.uniform(-5, 10)

    return {
        "service"     : service,
        "value"       : round(value, 2),
        "rolling_mean": round(rolling_mean, 2),
        "rolling_std" : round(rolling_std, 2),
        "value_diff"  : round(value_diff, 2),
        "timestamp"   : datetime.utcnow().isoformat()
    }

def run_prediction(metric: dict) -> dict:
    """Run InfraMind prediction on metric"""
    features = pd.DataFrame([{
        "value"        : metric["value"],
        "rolling_mean" : metric["rolling_mean"],
        "rolling_std"  : metric["rolling_std"],
        "value_diff"   : metric["value_diff"],
    }])

    X_scaled   = scaler.transform(features)
    prediction = model.predict(X_scaled)[0]
    score      = float(model.decision_function(X_scaled)[0])
    is_anomaly = bool(prediction == -1)

    if metric["value"] > 90 and metric["value_diff"] > 50:
        is_anomaly = True
        score = -0.20

    severity = "critical" if score < -0.15 else "warning" if score < -0.05 else "normal"

    return {
        **metric,
        "is_anomaly"    : is_anomaly,
        "anomaly_score" : round(score, 4),
        "severity"      : severity,
        "type"          : "metric_stream"
    }

# ── Main WebSocket Endpoint ────────────────────────────
@router.websocket("/ws/stream")
async def metric_stream(websocket: WebSocket):
    await manager.connect(websocket)

    # Send welcome message
    await manager.send_personal({
        "type"   : "connected",
        "message": "NeuroOps stream connected",
        "time"   : datetime.utcnow().isoformat()
    }, websocket)

    try:
        while True:
            # ── Generate + Predict for all services ───
            stream_data = []
            for service in SERVICES:
                metric     = generate_metric(service)
                prediction = run_prediction(metric)
                stream_data.append(prediction)

                # Cache in Redis
                redis_client.setex(
                    f"live:{service}",
                    10,
                    json.dumps(prediction)
                )

            # ── Broadcast to all connected clients ────
            payload = {
                "type"     : "metric_stream",
                "timestamp": datetime.utcnow().isoformat(),
                "services" : stream_data,
                "summary"  : {
                    "total"    : len(stream_data),
                    "anomalies": sum(1 for s in stream_data if s["is_anomaly"]),
                    "critical" : sum(1 for s in stream_data if s["severity"] == "critical"),
                    "healthy"  : sum(1 for s in stream_data if s["severity"] == "normal")
                }
            }

            await manager.send_personal(payload, websocket)
            await asyncio.sleep(3)  # stream every 3 seconds

    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ── Get Live Status from Redis ─────────────────────────
@router.get("/stream/status")
def get_live_status():
    status = {}
    for service in SERVICES:
        cached = redis_client.get(f"live:{service}")
        if cached:
            status[service] = json.loads(cached)
        else:
            status[service] = {"status": "no data yet"}
    return status