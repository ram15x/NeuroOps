from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.models.database import get_db
from backend.services.redis_service import redis_client
from datetime import datetime
import json
import random
import os
import requests
from backend.models.schemas import BuildInput

router = APIRouter()

BUILD_STAGES = ["checkout", "install", "test", "build", "dockerize", "deploy"]

FAILURE_REASONS = {
    "test": ["Unit test failed", "Test coverage below threshold: 67%", "Integration test timeout"],
    "build": ["Compilation error", "Go build failed", "Java compilation error"],
    "dockerize": ["Docker build failed", "Base image not found", "Dockerfile syntax error"],
    "deploy": ["Deployment timeout", "Connection refused", "Kubernetes API error"]
}

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = "ram15x/NeuroOps"

def trigger_real_github_workflow(service: str, branch: str):
    """Trigger actual GitHub Actions workflow"""
    if not GITHUB_TOKEN:
        return None
    
    # Use the correct workflow file name (deploy.yml)
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/deploy.yml/dispatches"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {"ref": branch}
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        print(f"github_response: {response.status_code}")
        if response.status_code == 204:
            return {
                "status": "triggered",
                "source": "github_actions",
                "workflow_url": f"https://github.com/{GITHUB_REPO}/actions",
                "service": service,
                "branch": branch
            }
        else:
            print(f"github_error: {response.text}")
    except Exception as e:
        print(f"github_exception: {e}")
    
    return None

def simulate_pipeline(service: str, branch: str):
    """Fallback simulation when GitHub not available"""
    stages = []
    failed_at = None
    failure_reason = None
    
    fail_stage = random.randint(2, 5) if random.random() < 0.25 else None
    
    for i, stage in enumerate(BUILD_STAGES):
        if failed_at:
            stages.append({"stage": stage, "status": "skipped", "time_s": 0})
            continue
        
        duration = random.randint(2, 30)
        
        if fail_stage and i == fail_stage:
            stage_reasons = FAILURE_REASONS.get(stage, ["General failure occurred"])
            failure_reason = random.choice(stage_reasons)
            stages.append({"stage": stage, "status": "failed", "time_s": duration, "reason": failure_reason})
            failed_at = stage
        else:
            stages.append({"stage": stage, "status": "success", "time_s": duration})
    
    total_time = sum(s["time_s"] for s in stages)
    status = "failed" if failed_at else "success"
    
    return {
        "service": service,
        "branch": branch,
        "status": status,
        "failed_at": failed_at,
        "failure_reason": failure_reason,
        "stages": stages,
        "total_time": f"{total_time}s",
        "triggered_at": datetime.utcnow().isoformat(),
        "commit": f"#{random.randint(1000,9999)}",
        "source": "simulation"
    }

@router.post("/buildsense/trigger")
def trigger_build(data: BuildInput, db: Session = Depends(get_db)):
    try:
        service = data.service
        branch = data.branch
        
        # Try real GitHub first
        github_result = trigger_real_github_workflow(service, branch)
        
        if github_result:
            pipeline = {
                "service": service,
                "branch": branch,
                "status": "triggered",
                "source": "github_actions",
                "workflow_url": github_result.get("workflow_url"),
                "triggered_at": datetime.utcnow().isoformat(),
                "commit": f"#{random.randint(1000,9999)}"
            }
        else:
            # Fallback to simulation
            pipeline = simulate_pipeline(service, branch)
        
        # Calculate risk
        risk = assess_build_risk(pipeline)
        pipeline["risk"] = risk
        
        # Cache result
        redis_client.setex(f"build:{service}", 300, json.dumps(pipeline))
        
        return pipeline
        
    except Exception as e:
        return {"error": str(e), "message": "Build trigger failed"}

def assess_build_risk(pipeline: dict) -> dict:
    time_value = int(pipeline.get("total_time", "0s").replace("s", "")) if "s" in pipeline.get("total_time", "") else 0
    
    if pipeline.get("status") == "failed":
        level = "HIGH"
        message = f"Build failed at {pipeline.get('failed_at')} stage"
    elif time_value > 120:
        level = "MEDIUM"
        message = f"Build time exceeding normal threshold ({pipeline.get('total_time')})"
    elif time_value > 60:
        level = "LOW"
        message = f"Build time slightly elevated ({pipeline.get('total_time')})"
    else:
        level = "LOW"
        message = "Build healthy"
    
    return {"level": level, "message": message, "total_time": pipeline.get("total_time")}

@router.get("/buildsense/history/{service}")
def build_history(service: str):
    cached = redis_client.get(f"build:{service}")
    if cached:
        return json.loads(cached)
    return {"service": service, "message": "No recent builds found"}

@router.get("/buildsense/overview")
def pipeline_overview():
    services = ["payment-service", "auth-service", "api-gateway", "notification-service", "database-proxy"]
    overview = []
    for s in services:
        cached = redis_client.get(f"build:{s}")
        if cached:
            data = json.loads(cached)
            overview.append({"service": s, "status": data.get("status"), "source": data.get("source", "unknown")})
        else:
            overview.append({"service": s, "status": "no builds yet"})
    return {"pipelines": overview, "total": len(overview)}
