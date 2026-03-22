from fastapi import APIRouter, Request
from backend.services.model_registry import (
    register_model,
    promote_model,
    get_model,
    get_active_model,
    list_all_models
)
from backend.models.schemas import ModelRegistryInput, ModelPromoteInput
from backend.services.rate_limiter import limiter

router = APIRouter()


@router.post("/registry/register")
@limiter.limit("20/minute")
def register_new_model(
    request: Request,
    data: ModelRegistryInput
):
    try:
        record = register_model(
            model_name    = data.model_name,
            version       = data.version,
            accuracy      = data.accuracy,
            model_type    = data.model_type,
            dataset       = data.dataset,
            features      = data.features,
            extra_metrics = data.extra_metrics
        )
        return {
            "message"      : "Model registered successfully",
            "model_name"   : record["model_name"],
            "version"      : record["version"],
            "status"       : record["status"],
            "registered_at": record["registered_at"]
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/registry/promote")
@limiter.limit("10/minute")
def promote_model_to_active(
    request: Request,
    data: ModelPromoteInput
):
    try:
        record = promote_model(data.model_name, data.version)
        if "error" in record:
            return record
        return {
            "message"    : f"{data.model_name} v{data.version} promoted to active",
            "model_name" : record["model_name"],
            "version"    : record["version"],
            "status"     : record["status"],
            "promoted_at": record["promoted_at"]
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/registry/list")
def list_models():
    try:
        models = list_all_models()
        return {
            "total" : len(models),
            "models": models
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/registry/active/{model_name}")
def get_active(model_name: str):
    try:
        record = get_active_model(model_name)
        if not record:
            return {"error": f"No active model found for: {model_name}"}
        return record
    except Exception as e:
        return {"error": str(e)}


@router.get("/registry/{model_name}/{version}")
def get_model_version(model_name: str, version: str):
    try:
        record = get_model(model_name, version)
        if not record:
            return {"error": f"Model {model_name} version {version} not found"}
        return record
    except Exception as e:
        return {"error": str(e)}