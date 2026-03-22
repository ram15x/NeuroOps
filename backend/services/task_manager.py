import uuid
from datetime import datetime

# in-memory job store - stores task status and results
# in production this would be replaced by Redis or a database
jobs = {}

def create_job(task_type: str) -> str:
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "job_id"    : job_id,
        "task_type" : task_type,
        "status"    : "pending",
        "result"    : None,
        "created_at": datetime.utcnow().isoformat(),
        "finished_at": None
    }
    return job_id

def update_job(job_id: str, status: str, result: dict):
    if job_id in jobs:
        jobs[job_id]["status"]      = status
        jobs[job_id]["result"]      = result
        jobs[job_id]["finished_at"] = datetime.utcnow().isoformat()

def get_job(job_id: str) -> dict:
    return jobs.get(job_id, {"error": "Job not found"})