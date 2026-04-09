from typing import Optional, List, Dict, Any
import json
from datetime import datetime
from backend.services.redis_service import redis_client

def register_model(
    model_name   : str,
    version      : str,
    accuracy     : float,
    model_type   : str,
    dataset      : str,
    features     : list,
    extra_metrics: dict = {}
) -> dict:
    timestamp = datetime.utcnow().isoformat()

    record = {
        "model_name"   : model_name,
        "version"      : version,
        "model_type"   : model_type,
        "accuracy"     : accuracy,
        "dataset"      : dataset,
        "features"     : features,
        "extra_metrics": extra_metrics,
        "status"       : "registered",
        "registered_at": timestamp,
        "promoted_at"  : None
    }

    # save model record
    model_key = f"registry:model:{model_name}:{version}"
    redis_client.set(model_key, json.dumps(record))

    # track all registered model keys
    all_key = "registry:all"
    existing = redis_client.get(all_key)
    all_keys = json.loads(existing) if existing else []
    if model_key not in all_keys:
        all_keys.append(model_key)
    redis_client.set(all_key, json.dumps(all_keys))

    return record


def promote_model(model_name: str, version: str) -> dict:
    model_key = f"registry:model:{model_name}:{version}"
    cached    = redis_client.get(model_key)

    if not cached:
        return {"error": f"Model {model_name} version {version} not found"}

    record = json.loads(cached)

    # demote current active model if one exists
    active_key    = f"registry:active:{model_name}"
    current_active = redis_client.get(active_key)
    if current_active:
        current = json.loads(current_active)
        old_key  = f"registry:model:{model_name}:{current['version']}"
        old_data = redis_client.get(old_key)
        if old_data:
            old_record           = json.loads(old_data)
            old_record["status"] = "archived"
            redis_client.set(old_key, json.dumps(old_record))

    # promote new model
    record["status"]      = "active"
    record["promoted_at"] = datetime.utcnow().isoformat()
    redis_client.set(model_key, json.dumps(record))
    redis_client.set(active_key, json.dumps(record))

    return record

def get_model(model_name: str, version: str) -> Optional[dict]:
    key    = f"registry:model:{model_name}:{version}"
    cached = redis_client.get(key)
    return json.loads(cached) if cached else None


def get_active_model(model_name: str) -> Optional[dict]:
    key    = f"registry:active:{model_name}"
    cached = redis_client.get(key)
    return json.loads(cached) if cached else None


def list_all_models() -> list:
    all_key  = "registry:all"
    existing = redis_client.get(all_key)
    if not existing:
        return []

    all_keys = json.loads(existing)
    models   = []
    for key in all_keys:
        cached = redis_client.get(key)
        if cached:
            data = json.loads(cached)
            models.append({
                "model_name"   : data["model_name"],
                "version"      : data["version"],
                "model_type"   : data["model_type"],
                "accuracy"     : data["accuracy"],
                "status"       : data["status"],
                "registered_at": data["registered_at"]
            })

    # sort by registered_at descending
    models.sort(key=lambda x: x["registered_at"], reverse=True)
    return models
    
    