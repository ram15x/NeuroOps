from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.models.database import get_db
from backend.services.redis_service import redis_client
from datetime import datetime
import json
import random
from backend.models.schemas import BuildInput


router = APIRouter()

# build status definition
BUILD_STAGES = ["checkout", "install", "test", "build", "dockerize", "deploy"]

FAILURE_REASONS = [
    "Unit test failed: NullPointerException in PaymentService",
    "Docker build failed: Base image not found",
    "Deployment timeout: Pod stuck in Pending state",
    "Test coverage below threshold: 67% (required 80%)",
    "Linting error: 23 ESLint violations found",
    "Memory limit exceeded during build",
    "Connection refused: Registry unreachable",
]

#simulate pipeline
def simulate_pipeline(service: str, branch: str) -> dict:
    stages = []
    failed_at = None

    # 20% chance of failure
    fail_stage = random.randint(2, 5) if random.random() < 0.2 else None

    for i, stage in enumerate(BUILD_STAGES):
        if failed_at:
            stages.append({
                "stage" : stage,
                "status": "skipped",
                "time_s": 0
            })
            continue

        duration = random.randint(2, 30)

        if fail_stage and i == fail_stage:
            stages.append({
                "stage" : stage,
                "status": "failed",
                "time_s": duration,
                "reason": random.choice(FAILURE_REASONS)
            })
            failed_at = stage
        else:
            stages.append({
                "stage" : stage,
                "status": "success",
                "time_s": duration
            })

    total_time = sum(s["time_s"] for s in stages)
    status     = "failed" if failed_at else "success"

    return {
        "service"    : service,
        "branch"     : branch,
        "status"     : status,
        "failed_at"  : failed_at,
        "stages"     : stages,
        "total_time" : f"{total_time}s",
        "triggered_at": datetime.utcnow().isoformat(),
        "commit"     : f"#{random.randint(1000,9999)}",
    }

#trigger build
@router.post("/buildsense/trigger")
def trigger_build(data: BuildInput, db: Session = Depends(get_db)):
    service = data.service
    branch  = data.branch
    try:
        service = data.service
        branch  = data.branch

        # run pipeline simulation
        pipeline = simulate_pipeline(service, branch)

        # risk assessment
        risk    = assess_build_risk(pipeline)
        pipeline["risk"] = risk

        # AI suggestion if failed
        if pipeline["status"] == "failed":
            pipeline["suggestion"] = get_fix_suggestion(pipeline["failed_at"])

        # Cache result
        redis_client.setex(
            f"build:{service}",
            300,
            json.dumps(pipeline)
        )

        return pipeline

    except Exception as e:
        return {"error": str(e)}


#get build history
@router.get("/buildsense/history/{service}")
def build_history(service: str):
    cached = redis_client.get(f"build:{service}")
    if cached:
        return json.loads(cached)
    return {"service": service, "message": "No recent builds found"}


#pipeline health overview
@router.get("/buildsense/overview")
def pipeline_overview():
    services = [
        "payment-service",
        "auth-service",
        "api-gateway",
        "notification-service",
        "database-proxy"
    ]
    overview = []
    for s in services:
        cached = redis_client.get(f"build:{s}")
        if cached:
            data = json.loads(cached)
            overview.append({
                "service": s,
                "status" : data["status"],
                "branch" : data["branch"],
                "time"   : data["total_time"],
                "commit" : data["commit"]
            })
        else:
            overview.append({
                "service": s,
                "status" : "no builds yet",
                "branch" : "—",
                "time"   : "—",
                "commit" : "—"
            })
    return {"pipelines": overview, "total": len(overview)}


def assess_build_risk(pipeline: dict) -> dict:
    failed_stages = [s for s in pipeline["stages"] if s["status"] == "failed"]
    total_time    = sum(s["time_s"] for s in pipeline["stages"])

    if pipeline["status"] == "failed":
        level   = "HIGH"
        message = f"Build failed at {pipeline['failed_at']} stage"
    elif total_time > 120:
        level   = "MEDIUM"
        message = "Build time exceeding normal threshold"
    else:
        level   = "LOW"
        message = "Build healthy and within normal parameters"

    return {
        "level"  : level,
        "message": message
    }

def get_fix_suggestion(failed_stage: str) -> str:
    suggestions = {
        "test"     : "Check test logs, fix failing unit tests before redeployment",
        "build"    : "Verify Dockerfile and base image availability",
        "deploy"   : "Check Kubernetes pod logs and resource limits",
        "dockerize": "Ensure Docker daemon is running and registry is accessible",
        "install"  : "Clear dependency cache and retry installation",
        "checkout" : "Verify repository access and branch permissions"
    }
    return suggestions.get(failed_stage, "Check pipeline logs for details")