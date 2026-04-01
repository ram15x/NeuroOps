from fastapi import APIRouter, Request, HTTPException
from backend.services.model_registry import (
    register_model,
    promote_model,
    get_model,
    get_active_model,
    list_all_models
)
from backend.models.schemas import ModelRegistryInput, ModelPromoteInput
from backend.services.rate_limiter import limiter
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/registry/register")
@limiter.limit("20/minute")
def register_new_model(
    request: Request,
    data: ModelRegistryInput
):
    """
    Register a new model version in the model registry.
    
    Required fields:
    - model_name: Name of the model (e.g., "inframind", "failure_classifier")
    - version: Version string (e.g., "v1.0", "v2.1")
    - model_type: Type of model (e.g., "IsolationForest", "RandomForestClassifier")
    - accuracy: Accuracy score (0-100)
    
    Optional fields:
    - dataset: Dataset name/version
    - features: List of features used
    - extra_metrics: Additional metrics like precision, recall, F1
    - description: Model description
    - tags: List of tags for categorization
    """
    try:
        # Validate input
        if not data.model_name or not data.version or not data.model_type:
            raise HTTPException(
                status_code=400, 
                detail="model_name, version, and model_type are required"
            )
        
        # Check if model already exists with same version
        existing = get_model(data.model_name, data.version)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Model {data.model_name} version {data.version} already exists"
            )
        
        # Prepare extra_metrics with sensible defaults if not provided
        extra_metrics = data.extra_metrics or {}
        if data.accuracy:
            extra_metrics["accuracy"] = data.accuracy
        
        # Register the model
        record = register_model(
            model_name    = data.model_name,
            version       = data.version,
            accuracy      = data.accuracy,
            model_type    = data.model_type,
            dataset       = data.dataset,
            features      = data.features,
            extra_metrics = extra_metrics
        )
        
        # Add additional metadata if provided
        if hasattr(data, 'description') and data.description:
            record["description"] = data.description
        if hasattr(data, 'tags') and data.tags:
            record["tags"] = data.tags
        
        logger.info(f"Registered new model: {data.model_name} v{data.version}")
        
        return {
            "status": "success",
            "message": f"✅ Model {data.model_name} version {data.version} registered successfully",
            "model_name": record["model_name"],
            "version": record["version"],
            "model_type": data.model_type,
            "accuracy": data.accuracy,
            "status": record["status"],
            "registered_at": record["registered_at"],
            "description": getattr(data, 'description', None),
            "tags": getattr(data, 'tags', [])
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error registering model: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "message": f"Failed to register model {data.model_name} v{data.version}"
        }


@router.post("/registry/promote")
@limiter.limit("10/minute")
def promote_model_to_active(
    request: Request,
    data: ModelPromoteInput
):
    """
    Promote a specific model version to active status.
    This will demote any previously active version of the same model.
    """
    try:
        # Validate input
        if not data.model_name or not data.version:
            raise HTTPException(
                status_code=400,
                detail="model_name and version are required"
            )
        
        # Check if model exists
        existing = get_model(data.model_name, data.version)
        if not existing:
            raise HTTPException(
                status_code=404,
                detail=f"Model {data.model_name} version {data.version} not found"
            )
        
        # Promote the model
        record = promote_model(data.model_name, data.version)
        
        if "error" in record:
            raise HTTPException(
                status_code=400,
                detail=record["error"]
            )
        
        # Get the previously active model if any
        previous_active = get_active_model(data.model_name)
        
        logger.info(f"Promoted {data.model_name} v{data.version} to active")
        
        return {
            "status": "success",
            "message": f"✅ {data.model_name} v{data.version} promoted to active",
            "model_name": record["model_name"],
            "version": record["version"],
            "status": record["status"],
            "promoted_at": record["promoted_at"],
            "previous_active": previous_active["version"] if previous_active else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error promoting model: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "message": f"Failed to promote {data.model_name} v{data.version}"
        }


@router.get("/registry/list")
def list_models():
    """
    List all registered models with their versions and status.
    """
    try:
        models = list_all_models()
        
        # Group models by name for better organization
        models_by_name = {}
        for model in models:
            name = model["model_name"]
            if name not in models_by_name:
                models_by_name[name] = []
            models_by_name[name].append(model)
        
        # Sort versions for each model
        for name in models_by_name:
            models_by_name[name].sort(key=lambda x: x["version"], reverse=True)
        
        return {
            "status": "success",
            "total": len(models),
            "models": models,
            "by_name": models_by_name,
            "statistics": {
                "total_models": len(set(m["model_name"] for m in models)),
                "active_models": sum(1 for m in models if m.get("status") == "active"),
                "archived_models": sum(1 for m in models if m.get("status") == "archived"),
                "registered_models": sum(1 for m in models if m.get("status") == "registered")
            }
        }
        
    except Exception as e:
        logger.error(f"Error listing models: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "total": 0,
            "models": []
        }


@router.get("/registry/active/{model_name}")
def get_active(model_name: str):
    """
    Get the currently active version of a model.
    """
    try:
        record = get_active_model(model_name)
        if not record:
            return {
                "status": "warning",
                "error": f"No active model found for: {model_name}",
                "message": f"Model {model_name} has no active version. Register and promote one first."
            }
        
        return {
            "status": "success",
            "model_name": model_name,
            "active_version": record["version"],
            "model_type": record.get("model_type"),
            "accuracy": record.get("accuracy"),
            "promoted_at": record.get("promoted_at"),
            "details": record
        }
        
    except Exception as e:
        logger.error(f"Error getting active model: {str(e)}")
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/registry/{model_name}/{version}")
def get_model_version(model_name: str, version: str):
    """
    Get details of a specific model version.
    """
    try:
        record = get_model(model_name, version)
        if not record:
            return {
                "status": "error",
                "error": f"Model {model_name} version {version} not found",
                "message": f"Try listing all models to see available versions"
            }
        
        return {
            "status": "success",
            "model": record
        }
        
    except Exception as e:
        logger.error(f"Error getting model version: {str(e)}")
        return {
            "status": "error",
            "error": str(e)
        }


@router.delete("/registry/{model_name}/{version}")
@limiter.limit("5/minute")
def archive_model(
    request: Request,
    model_name: str, 
    version: str
):
    """
    Archive a model version (soft delete).
    """
    try:
        # Check if model exists
        record = get_model(model_name, version)
        if not record:
            raise HTTPException(
                status_code=404,
                detail=f"Model {model_name} version {version} not found"
            )
        
        # Check if it's active - can't archive active model
        if record.get("status") == "active":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot archive active model. Demote it first by promoting another version."
            )
        
        # Update status to archived
        from backend.services.redis_service import redis_client
        import json
        
        model_key = f"model:{model_name}:{version}"
        record["status"] = "archived"
        record["archived_at"] = __import__('datetime').datetime.utcnow().isoformat()
        
        redis_client.setex(model_key, 86400 * 30, json.dumps(record))  # 30 days expiry
        
        logger.info(f"Archived model: {model_name} v{version}")
        
        return {
            "status": "success",
            "message": f"Model {model_name} version {version} archived successfully",
            "archived_at": record["archived_at"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error archiving model: {str(e)}")
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/registry/search")
def search_models(
    model_type: str = None,
    tag: str = None,
    min_accuracy: float = None,
    status: str = None
):
    """
    Search models with filters.
    """
    try:
        all_models = list_all_models()
        filtered = all_models
        
        if model_type:
            filtered = [m for m in filtered if m.get("model_type", "").lower() == model_type.lower()]
        
        if tag:
            filtered = [m for m in filtered if tag.lower() in [t.lower() for t in m.get("tags", [])]]
        
        if min_accuracy:
            filtered = [m for m in filtered if m.get("accuracy", 0) >= min_accuracy]
        
        if status:
            filtered = [m for m in filtered if m.get("status") == status]
        
        return {
            "status": "success",
            "total": len(filtered),
            "filters_applied": {
                "model_type": model_type,
                "tag": tag,
                "min_accuracy": min_accuracy,
                "status": status
            },
            "models": filtered
        }
        
    except Exception as e:
        logger.error(f"Error searching models: {str(e)}")
        return {
            "status": "error",
            "error": str(e)
        }