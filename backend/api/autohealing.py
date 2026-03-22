from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.models.database import get_db, Alert
from backend.services.redis_service import redis_client
import json
from backend.models.schemas import HealingInput, PipelineInput
from backend.api.auth import get_current_user
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime

router = APIRouter()

#healing rules
HEALING_RULES = {
    "critical": {
        "action"     : "RESTART AND SCALE",
        "description": "Restart service and scale replicas",
        "steps": [
            "1. Restart crashed container",
            "2. Scale replicas to 3",
            "3. Notify on-call engineer",
            "4. Create incident ticket"
        ]
    },
    "warning": {
        "action"     : "SCALE_UP",
        "description": "Scale up resources",
        "steps": [
            "1. Increase CPU limit by 50%",
            "2. Scale replicas to 2",
            "3. Monitor for 5 minutes",
            "4. Alert team on Slack"
        ]
    },
    "normal": {
        "action"     : "NO_ACTION",
        "description": "System healthy, no action needed",
        "steps": [
            "1. Continue monitoring",
            "2. Log health check"
        ]
    }
}

#trigger healinh6
@router.post("/autohealing/trigger")
def trigger_healing(data: HealingInput, db: Session = Depends(get_db)):
    try:
        severity     = data.severity
        service_name = data.service
        metric_value = data.metric_value
        reason       = data.reason


        #get healing plans
        rule = HEALING_RULES.get(severity, HEALING_RULES["normal"])

        healing_result = execute_healing(
            service_name, rule, severity, metric_value
        )

        #cache healing status
        cache_key = f"healing:{service_name}"
        redis_client.setex(
            cache_key, 300,
            json.dumps(healing_result)
        )

        return healing_result

    except Exception as e:
        return {"error": str(e)}


#detect and heal pipeline
@router.post("/autohealing/pipeline")
def full_pipeline(data: dict, db: Session = Depends(get_db),current_user: dict = Depends(get_current_user)):
    
    """
    Full NeuroOps pipeline:
    1. Receive metric
    2. Check severity
    3. Analyze log with OpsGPT
    4. Trigger auto-healing
    5. Return full report
    """
    try:
        current_user: dict = Depends(get_current_user)
        service_name = data.service
        metric_value = data.metric_value
        severity     = data.severity
        log_message  = data.log



        #determine action
        rule = HEALING_RULES.get(severity, HEALING_RULES["normal"])

        #exe heal
        healing = execute_healing(
            service_name, rule, severity, metric_value
        )

        #build report
        report = {
            "pipeline"     : "NeuroOps Auto-Healing Pipeline",
            "timestamp"    : datetime.utcnow().isoformat(),
            "service"      : service_name,
            "trigger": {
                "metric_value" : metric_value,
                "severity"     : severity,
                "log"          : log_message or "No log provided"
            },
            "healing"      : healing,
            "status"       : "RESOLVED" if severity != "critical" else "IN_PROGRESS"
        }

        #save it to db
        alert = Alert(
            metric_value  = metric_value,
            rolling_mean  = 0,
            rolling_std   = 0,
            value_diff    = 0,
            is_anomaly    = severity != "normal",
            severity      = severity,
            anomaly_score = -0.2 if severity == "critical" else -0.1,
            message       = f"Auto-healing triggered for {service_name}"
        )
        db.add(alert)
        db.commit()

        return report

    except Exception as e:
        return {"error": str(e)}


#get healing status
@router.get("/autohealing/status/{service_name}")
def get_healing_status(service_name: str):
    cache_key = f"healing:{service_name}"
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    return {
        "service": service_name,
        "status" : "No recent healing events found"
    }


#heal rules overview
@router.get("/autohealing/rules")
def get_rules():
    return {"rules": HEALING_RULES}


#execute simulated healing 
def execute_healing(
    service_name: str,
    rule: dict,
    severity: str,
    metric_value: float
) -> dict:
    return {
        "service"      : service_name,
        "severity"     : severity,
        "metric_value" : metric_value,
        "action"       : rule["action"],
        "description"  : rule["description"],
        "steps_executed": rule["steps"],
        "executed_at"  : datetime.utcnow().isoformat(),
        "success"      : True,
        "message"      : f"Auto-healing executed for {service_name}: {rule['action']}"
    }