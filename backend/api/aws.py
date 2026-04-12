from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel, Field
from typing import Optional
import json
from backend.core.config import settings
from backend.services.redis_service import redis_client
from datetime import datetime
from backend.services.aws_service import get_ec2_status_checks
from backend.services.aws_service import (
    check_aws_connection,
    fetch_cloudwatch_metrics,
    list_ec2_instances,
    upload_model_to_s3,
    list_s3_models,
    send_sns_alert,
)
from backend.services.redis_service import cache_alert, get_cached_alert
from backend.services.rate_limiter import limiter
from backend.api.auth import get_current_user

router = APIRouter()


# schemas

class FetchMetricsInput(BaseModel):
    instance_id : str           = Field(..., min_length=10)
    minutes     : Optional[int] = Field(default=60, ge=5, le=1440)

class UploadModelInput(BaseModel):
    local_path : str = Field(..., min_length=1)
    s3_key     : str = Field(..., min_length=1)

class SNSAlertInput(BaseModel):
    subject : str = Field(..., min_length=1, max_length=100)
    message : str = Field(..., min_length=1, max_length=5000)


# endpoints

@router.get("/aws/status")
def aws_status(request: Request):
    """check connection to cloudwatch, s3, and sns."""
    try:
        cached = get_cached_alert("aws:status")
        if cached:
            return {"source": "cache", "status": cached}

        status = check_aws_connection()
        cache_alert("aws:status", status)

        return {"source": "live", "status": status}
    except Exception as e:
        return {"error": str(e)}


@router.post("/aws/fetch-metrics")
@limiter.limit(settings.RATE_LIMIT_POST)
def fetch_metrics(
    request: Request,
    body: FetchMetricsInput,
    _: dict = Depends(get_current_user),
):
    """Fetch real CloudWatch metrics for an EC2 instance."""
    try:
        # Validate instance ID format (starts with 'i-')
        if not body.instance_id or not body.instance_id.startswith("i-"):
            return {
                "source": "error",
                "error": f"Invalid instance ID format: {body.instance_id}"
            }
        
        cache_key = f"aws:metrics:{body.instance_id}:{body.minutes}"
        cached = get_cached_alert(cache_key)
        if cached:
            return {"source": "cache", "data": cached}

        # Fetch metrics - function returns empty arrays on failure
        metrics = fetch_cloudwatch_metrics(body.instance_id, body.minutes)
        cache_alert(cache_key, metrics)

        return {
            "source": "live",
            "instance_id": body.instance_id,
            "minutes": body.minutes,
            "data": metrics,
        }
    except Exception as e:
        logger.error(f"CloudWatch metrics fetch failed: {e}")
        return {
            "source": "error",
            "instance_id": body.instance_id,
            "error": str(e)
        }


@router.get("/aws/instances")
def list_instances(
    request : Request,
    _       : dict = Depends(get_current_user),
):
    """list all ec2 instances in the aws account."""
    try:
        cached = get_cached_alert("aws:instances")
        if cached:
            return {"source": "cache", "instances": cached}

        instances = list_ec2_instances()
        cache_alert("aws:instances", instances)

        return {"source": "live", "instances": instances}
    except Exception as e:
        return {"error": str(e)}


@router.post("/aws/upload-model")
@limiter.limit("10/minute")
def upload_model(
    request : Request,
    body    : UploadModelInput,
    _       : dict = Depends(get_current_user),
):
    """upload a local .pkl model file to s3."""
    try:
        result = upload_model_to_s3(body.local_path, body.s3_key)
        return result
    except Exception as e:
        return {"error": str(e)}


@router.get("/aws/list-models")
def list_models(
    request : Request,
    _       : dict = Depends(get_current_user),
):
    """list all model files stored in s3."""
    try:
        models = list_s3_models()
        return {"models": models, "count": len(models)}
    except Exception as e:
        return {"error": str(e)}


@router.post("/aws/notify")
@limiter.limit("10/minute")
def notify(
    request : Request,
    body    : SNSAlertInput,
    _       : dict = Depends(get_current_user),
):
    """send a real sns alert email/sms to on-call."""
    try:
        result = send_sns_alert(body.subject, body.message)
        return result
    except Exception as e:
        return {"error": str(e)}
    
@router.get("/aws/latest-metrics/{instance_id}")
def get_latest_metrics(
    instance_id: str,
    _: dict = Depends(get_current_user)
):
    """Get latest cached metrics for an EC2 instance"""
    try:
        # Use the correct Redis key
        cpu = redis_client.get(f"real_cpu:{instance_id}")
        
        return {
            "instance_id": instance_id,
            "cpu_percent": float(cpu) if cpu else None,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {"error": str(e)}
    
@router.get("/aws/analyzed-metrics/{instance_id}")
def get_analyzed_metrics(
    instance_id: str,
    _: dict = Depends(get_current_user)
):
    """Get latest analyzed metrics for an EC2 instance"""
    try:
        cpu = redis_client.get(f"real_cpu:{instance_id}")
        latest_alert = db.query(Alert).filter(
            Alert.message.contains(instance_id)
        ).order_by(Alert.created_at.desc()).first()
        
        return {
            "instance_id": instance_id,
            "current_cpu": float(cpu) if cpu else None,
            "latest_alert": {
                "is_anomaly": latest_alert.is_anomaly if latest_alert else None,
                "severity": latest_alert.severity if latest_alert else None,
                "timestamp": latest_alert.created_at.isoformat() if latest_alert else None
            } if latest_alert else None
        }
    except Exception as e:
        return {"error": str(e)}
    
@router.get("/aws/instance-status/{instance_id}")
def get_instance_status(
    instance_id: str,
    _: dict = Depends(get_current_user)
):
    """Get EC2 instance status check"""
    try:
        status_data = get_ec2_status_checks(instance_id)
        return status_data
    except Exception as e:
        return {"error": str(e), "is_healthy": False}


@router.get("/aws/reboot-count/{instance_id}")
def get_reboot_count(
    instance_id: str,
    _: dict = Depends(get_current_user)
):
    """Get recent reboot count from Redis"""
    try:
        reboot_key = f"reboot_count:{instance_id}"
        count = redis_client.get(reboot_key)
        return {"instance_id": instance_id, "count": int(count) if count else 0}
    except Exception as e:
        return {"error": str(e), "count": 0}

@router.get("/aws/memory/{instance_id}")
def get_memory_metrics(instance_id: str, _: dict = Depends(get_current_user)):
    """Get latest memory metrics"""
    try:
        cached = redis_client.get(f"memory:{instance_id}")
        return {"instance_id": instance_id, "memory_percent": float(cached) if cached else None}
    except Exception as e:
        return {"error": str(e)}


@router.get("/aws/disk/{instance_id}")
def get_disk_metrics(instance_id: str, _: dict = Depends(get_current_user)):
    """Get latest disk metrics"""
    try:
        cached = redis_client.get(f"disk:{instance_id}")
        return {"instance_id": instance_id, "disk_percent": float(cached) if cached else None}
    except Exception as e:
        return {"error": str(e)}