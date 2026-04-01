import uuid
import json
from datetime import datetime

from backend.core.config import settings
from backend.services.redis_service import redis_client

def create_job(task_type: str, data: dict = None) -> str:
    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "task_type": task_type,
        "data": data or {},
        "status": "pending",
        "result": None,
        "created_at": datetime.utcnow().isoformat(),
        "finished_at": None
    }
    redis_client.setex(f"job:{job_id}", settings.TASK_TTL, json.dumps(job))
    return job_id

def update_job(job_id: str, status: str, result: dict = None):
    job_data = redis_client.get(f"job:{job_id}")
    if job_data:
        job = json.loads(job_data)
        job["status"] = status
        if result:
            job["result"] = result
        job["finished_at"] = datetime.utcnow().isoformat()
        redis_client.setex(f"job:{job_id}", settings.TASK_TTL, json.dumps(job))

def get_job(job_id: str) -> dict:
    job_data = redis_client.get(f"job:{job_id}")
    if job_data:
        return json.loads(job_data)
    return {"error": "Job not found"}

def delete_job(job_id: str):
    redis_client.delete(f"job:{job_id}")