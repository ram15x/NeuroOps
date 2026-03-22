import json
from datetime import datetime
from backend.services.redis_service import redis_client

# how many historical versions to keep per entity
MAX_HISTORY = 5

# key pattern: features:{entity_id}:latest  -> most recent feature set
# key pattern: features:{entity_id}:history -> list of last N versions


def store_features(entity_id: str, features: dict, entity_type: str = "unknown") -> dict:
    timestamp = datetime.utcnow().isoformat()

    record = {
        "entity_id"  : entity_id,
        "entity_type": entity_type,
        "features"   : features,
        "stored_at"  : timestamp,
        "version"    : _get_next_version(entity_id)
    }

    # save latest
    latest_key = f"features:{entity_id}:latest"
    redis_client.set(latest_key, json.dumps(record))

    # append to history list, trim to MAX_HISTORY
    history_key = f"features:{entity_id}:history"
    redis_client.lpush(history_key, json.dumps(record))
    redis_client.ltrim(history_key, 0, MAX_HISTORY - 1)

    return record


def get_latest_features(entity_id: str) -> dict | None:
    key    = f"features:{entity_id}:latest"
    cached = redis_client.get(key)
    if not cached:
        return None
    return json.loads(cached)


def get_feature_history(entity_id: str) -> list:
    key     = f"features:{entity_id}:history"
    entries = redis_client.lrange(key, 0, MAX_HISTORY - 1)
    return [json.loads(e) for e in entries]


def list_all_entities() -> list:
    # scan redis for all feature keys
    keys    = redis_client.keys("features:*:latest")
    results = []
    for key in keys:
        cached = redis_client.get(key)
        if cached:
            data = json.loads(cached)
            results.append({
                "entity_id"  : data["entity_id"],
                "entity_type": data["entity_type"],
                "stored_at"  : data["stored_at"],
                "version"    : data["version"]
            })
    return results


def _get_next_version(entity_id: str) -> int:
    # check if a previous version exists and increment
    key    = f"features:{entity_id}:latest"
    cached = redis_client.get(key)
    if cached:
        data = json.loads(cached)
        return data.get("version", 0) + 1
    return 1