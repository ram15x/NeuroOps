import json
import redis
from backend.core.config import settings

redis_client = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=settings.REDIS_DB,
    decode_responses=True
)

def get_redis():
    return redis_client

def cache_alert(metric_name: str, alert_data: dict, expiry_seconds: int = None):
    """
    Cache latest alert for a metric.
    """
    if expiry_seconds is None:
        expiry_seconds = settings.ALERT_CACHE_TTL
    
    key = f"alert:{metric_name}"
    redis_client.setex(key, expiry_seconds, json.dumps(alert_data))

def get_cached_alert(metric_name: str):
    """
    Get cached alert for a metric.
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
    redis_client.setex("system:status", settings.SYSTEM_STATUS_TTL, json.dumps(status))

def get_system_status():
    """
    Get cached system status.
    """
    data = redis_client.get("system:status")
    if data:
        return json.loads(data)
    return None