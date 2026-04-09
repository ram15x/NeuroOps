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
    """List all features in Redis store"""
    try:
        keys = redis_client.keys("feature:*")
        features = []
        for key in keys[:50]:
            data = redis_client.get(key)
            features.append({
                "key": key,
                "data": data[:200] if data else "null"
            })
        return {
            "total": len(keys),
            "features": features,
            "source": "redis"
        }
    except Exception as e:
        return {"error": str(e)}
