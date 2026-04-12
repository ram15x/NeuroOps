from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.models.database import get_db
from backend.services.redis_service import redis_client
from backend.api.auth import get_current_user

router = APIRouter()

@router.get("/features/list")
def list_features(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List all features in Redis store with real data"""
    try:
        keys = redis_client.keys("feature:*:latest")
        features = []
        
        for key in keys[:50]:
            key_str = key.decode() if isinstance(key, bytes) else key
            data = redis_client.get(key)
            
            if data:
                data_str = data.decode() if isinstance(data, bytes) else data
                try:
                    feature_json = json.loads(data_str)
                    features.append({
                        "key": key_str,
                        "instance_id": key_str.split(":")[1] if ":" in key_str else "unknown",
                        "cpu": feature_json.get("cpu", 0),
                        "memory": feature_json.get("memory", 0),
                        "disk": feature_json.get("disk", 0),
                        "timestamp": feature_json.get("timestamp")
                    })
                except:
                    features.append({"key": key_str, "data": data_str[:100]})
        
        # Also check alert features
        alert_keys = redis_client.keys("feature:alert:*")
        
        return {
            "total": len(features) + len(alert_keys),
            "instance_features": len(features),
            "alert_features": len(alert_keys),
            "features": features,
            "source": "redis"
        }
    except Exception as e:
        logger.error(f"Feature store error: {e}")
        return {"error": str(e), "total": 0, "features": []}