from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.models.database import get_db, Alert
from backend.services.redis_service import redis_client
import json
from datetime import datetime

router = APIRouter()

# ── Healing Action Rules ───────────────────────────────
HEALING_RULES = {
    "critical": {
        "action"     : "RESTART_AND_SCALE",
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

# ── Trigger Healing ────────────────────────────────────
@router.post("/autohealing/trigger")
def trigger_healing(data: dict, db: Session = Depends(get_db)):
    try:
        severity     = data.get("severity", "normal").lower()
        service_name = data.get("service", "unknown-service")
        metric_value = data.get("metric_value", 0)
        reason       = data.get("reason", "Anomaly detected")

        # ── Get Healing Plan ───────────────────────────
        rule = HEALING_RULES.get(severity, HEALING_RULES["normal"])

        # ── Simulate Healing Execution ─────────────────
        healing_result = execute_healing(
            service_name, rule, severity, metric_value
        )

        # ── Cache Healing Status ───────────────────────
        cache_key = f"healing:{service_name}"
        redis_client.setex(
            cache_key, 300,
            json.dumps(healing_result)
        )

        return healing_result

    except Exception as e:
        return {"error": str(e)}


# ── Full Pipeline: Detect + Heal ───────────────────────
@router.post("/autohealing/pipeline")
def full_pipeline(data: dict, db: Session = Depends(get_db)):
    """
    Full NeuroOps pipeline:
    1. Receive metric
    2. Check severity
    3. Analyze log with OpsGPT
    4. Trigger auto-healing
    5. Return full report
    """
    try:
        service_name = data.get("service", "unknown")
        metric_value = data.get("metric_value", 0)
        severity     = data.get("severity", "normal")
        log_message  = data.get("log", "")

        # ── Step 1: Determine Action ───────────────────
        rule = HEALING_RULES.get(severity, HEALING_RULES["normal"])

        # ── Step 2: Execute Healing ────────────────────
        healing = execute_healing(
            service_name, rule, severity, metric_value
        )

        # ── Step 3: Build Full Report ──────────────────
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

        # ── Save to DB ─────────────────────────────────
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


# ── Get Healing Status ─────────────────────────────────
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


# ── Healing Rules Overview ─────────────────────────────
@router.get("/autohealing/rules")
def get_rules():
    return {"rules": HEALING_RULES}


# ── Execute Healing (Simulated) ────────────────────────
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