import redis
import json
from dotenv import load_dotenv
import os

load_dotenv("backend/.env")

# ── Connect to Redis ───────────────────────────────────
redis_client = redis.Redis(
    host="localhost",
    port=6379,
    decode_responses=True
)

def cache_alert(metric_name: str, alert_data: dict, expiry_seconds: int = 300):
    """
    Cache latest alert for a metric.
    Expires after 5 minutes by default.
    """
    key = f"alert:{metric_name}"
    redis_client.setex(key, expiry_seconds, json.dumps(alert_data))
    print(f"Cached alert for {metric_name}")

def get_cached_alert(metric_name: str):
    """
    Get cached alert for a metric.
    Returns None if not cached.
    """
    key = f"alert:{metric_name}"
    data = redis_client.get(key)
    if data:
        return json.loads(data)
    return None

def cache_system_status(status: dict):
    """
    Cache overall system health status.
    """
    redis_client.setex("system:status", 60, json.dumps(status))

def get_system_status():
    """
    Get cached system status.
    """
    data = redis_client.get("system:status")
    if data:
        return json.loads(data)
    return None