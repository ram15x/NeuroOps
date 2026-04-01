from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.models.database import get_db
from backend.services.redis_service import redis_client
from datetime import datetime
from backend.models.schemas import DeployInput, SafeWindowInput
import json
import random

router = APIRouter()

# risk factor weights
RISK_WEIGHTS = {
    "cpu_usage"      : 0.25,
    "memory_usage"   : 0.20,
    "error_rate"     : 0.25,
    "recent_failures": 0.20,
    "deployment_size": 0.10,
}

def calculate_risk_score(data: dict) -> float:
    cpu         = data.get("cpu_usage", 0) / 100
    memory      = data.get("memory_usage", 0) / 100
    error_rate  = data.get("error_rate", 0) / 100
    failures    = min(data.get("recent_failures", 0) / 10, 1.0)
    deploy_size = min(data.get("deployment_size_mb", 0) / 500, 1.0)

    score = (
        cpu         * RISK_WEIGHTS["cpu_usage"]       +
        memory      * RISK_WEIGHTS["memory_usage"]    +
        error_rate  * RISK_WEIGHTS["error_rate"]      +
        failures    * RISK_WEIGHTS["recent_failures"] +
        deploy_size * RISK_WEIGHTS["deployment_size"]
    )

    return round(score * 100, 2)


def get_risk_level(score: float) -> str:
    if score >= 70:
        return "HIGH"
    elif score >= 40:
        return "MEDIUM"
    else:
        return "LOW"


def get_recommendations(data: dict, score: float) -> list:
    recs = []

    if data.get("cpu_usage", 0) > 70:
        recs.append("CPU usage is high — scale up before deploying")

    if data.get("memory_usage", 0) > 75:
        recs.append("Memory usage critical — possible memory leak risk")

    if data.get("error_rate", 0) > 5:
        recs.append("Error rate above 5% — fix existing errors first")

    if data.get("recent_failures", 0) >= 3:
        recs.append("Multiple recent failures detected — investigate root cause")

    if data.get("deployment_size_mb", 0) > 300:
        recs.append("Large deployment size — consider blue/green deployment")

    if data.get("cpu_usage", 0) < 30 and data.get("memory_usage", 0) < 40:
        recs.append("System resources healthy — safe deployment window")

    if score >= 70:
        recs.append("BLOCK DEPLOYMENT — risk too high, resolve issues first")
    elif score >= 40:
        recs.append("PROCEED WITH CAUTION — monitor closely after deploy")
    else:
        recs.append("SAFE TO DEPLOY — all systems within normal range")

    return recs


def predict_outcomes(score: float, data: dict) -> dict:
    success_prob     = max(0, 100 - score)
    memory_leak_risk = "HIGH" if data.get("memory_usage", 0) > 75 else "LOW"
    crash_risk       = "HIGH" if data.get("recent_failures", 0) >= 3 else "LOW"
    perf_degradation = "LIKELY" if data.get("cpu_usage", 0) > 70 else "UNLIKELY"

    return {
        "success_probability": f"{round(success_prob, 1)}%",
        "memory_leak_risk"   : memory_leak_risk,
        "crash_risk"         : crash_risk,
        "performance_impact" : perf_degradation,
        "estimated_rollback" : "HIGH" if score >= 70 else "LOW"
    }


@router.post("/deployguard/predict")
def predict_deploy_risk(data: DeployInput, db: Session = Depends(get_db)):
    try:
        # convert pydantic model to dict — all helper functions expect a dict
        data_dict  = data.model_dump()
        score      = calculate_risk_score(data_dict)
        risk_level = get_risk_level(score)
        recs       = get_recommendations(data_dict, score)
        decision   = "BLOCKED" if score >= 70 else "APPROVED"
        outcomes   = predict_outcomes(score, data_dict)

        result = {
            "service"           : data.service,
            "version"           : data.version,
            "risk_score"        : f"{score}%",
            "risk_level"        : risk_level,
            "decision"          : decision,
            "recommendations"   : recs,
            "predicted_outcomes": outcomes,
            "analyzed_at"       : datetime.utcnow().isoformat(),
            "factors"           : {
                "cpu_usage"      : f"{data.cpu_usage}%",
                "memory_usage"   : f"{data.memory_usage}%",
                "error_rate"     : f"{data.error_rate}%",
                "recent_failures": data.recent_failures,
                "deploy_size_mb" : data.deployment_size_mb
            }
        }

        redis_client.setex(f"deployguard:{data.service}", 300, json.dumps(result))
        return result

    except Exception as e:
        return {"error": str(e)}


@router.get("/deployguard/history/{service}")
def deploy_history(service: str):
    cached = redis_client.get(f"deployguard:{service}")
    if cached:
        return json.loads(cached)
    return {"service": service, "message": "No recent deployments found"}


@router.post("/deployguard/safe-window")
def deployguard_safe_window(data: SafeWindowInput):
    data_dict     = data.model_dump()
    current_score = calculate_risk_score(data_dict)

    windows = []
    hours   = ["02:00", "03:00", "04:00", "10:00", "14:00"]

    for hour in hours:
        simulated = data_dict.copy()
        if hour in ["02:00", "03:00", "04:00"]:
            simulated["cpu_usage"]    = max(0, data_dict.get("cpu_usage", 0) * 0.4)
            simulated["memory_usage"] = max(0, data_dict.get("memory_usage", 0) * 0.6)

        sim_score = calculate_risk_score(simulated)
        windows.append({
            "time"       : hour,
            "risk"       : f"{sim_score}%",
            "level"      : get_risk_level(sim_score),
            "recommended": sim_score < 40
        })

    best = min(windows, key=lambda x: float(x["risk"].replace("%", "")))

    return {
        "current_risk"  : f"{current_score}%",
        "windows"       : windows,
        "best_window"   : best,
        "recommendation": f"Deploy at {best['time']} for lowest risk"
    }