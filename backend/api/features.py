from fastapi import APIRouter, Request
from backend.services.feature_store import (
    store_features,
    get_latest_features,
    get_feature_history,
    list_all_entities
)
from backend.models.schemas import FeatureStoreInput
from backend.services.rate_limiter import limiter
 
router = APIRouter()
@router.post("/features/store")
@limiter.limit("30/minute")
def store_entity_features(
    request: Request,
    data: FeatureStoreInput
):
    try:
        record = store_features(
            entity_id   = data.entity_id,
            features    = data.features,
            entity_type = data.entity_type
        )
        return {
            "message"   : "Features stored successfully",
            "entity_id" : record["entity_id"],
            "version"   : record["version"],
            "stored_at" : record["stored_at"]
        }
    except Exception as e:
        return {"error": str(e)}
 

@router.get("/features/list")
def list_features():
    try:
        entities = list_all_entities()
        return {
            "total"   : len(entities),
            "entities": entities
        }
    except Exception as e:
        return {"error": str(e)}
 
@router.get("/features/{entity_id}")
def get_features(entity_id: str):
    try:
        record = get_latest_features(entity_id)
        if not record:
            return {"error": f"No features found for entity: {entity_id}"}
        return record
    except Exception as e:
        return {"error": str(e)}

 
@router.get("/features/{entity_id}/history")
def get_features_history(entity_id: str):
    try:
        history = get_feature_history(entity_id)
        if not history:
            return {"error": f"No feature history found for entity: {entity_id}"}
        return {
            "entity_id": entity_id,
            "versions" : len(history),
            "history"  : history
        }
    except Exception as e:
        return {"error": str(e)}
 