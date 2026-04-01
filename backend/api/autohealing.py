from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from backend.models.database import get_db, Alert, HealingAction, AuditLog, User
from datetime import datetime, timedelta
import json

from backend.core.config import settings
from backend.services.redis_service import redis_client
from backend.services.audit_logger import AuditLogger
from backend.services.healing_executor import HealingDecision, HealingExecutor
from backend.models.schemas import HealingInput, PipelineInput
from backend.api.auth import get_current_user

router = APIRouter()


def get_healing_rules():
    """Load healing rules from config"""
    return {
        "critical": {
            "action": settings.HEALING_ACTION_CRITICAL,
            "description": "Restart service and scale replicas",
            "steps": settings.HEALING_STEPS_CRITICAL
        },
        "warning": {
            "action": settings.HEALING_ACTION_WARNING,
            "description": "Scale up resources",
            "steps": settings.HEALING_STEPS_WARNING
        },
        "normal": {
            "action": settings.HEALING_ACTION_NORMAL,
            "description": "System healthy, no action needed",
            "steps": settings.HEALING_STEPS_NORMAL
        }
    }


@router.post("/autohealing/trigger")
def trigger_healing(
    request: Request,
    data: HealingInput,
    db: Session = Depends(get_db)
):
    try:
        severity = data.severity
        service_name = data.service
        metric_value = data.metric_value
        metric_type = data.metric_type
        reason = data.reason

        # Get recent healing attempts for this service (for context)
        recent_healings = db.query(HealingAction).filter(
            HealingAction.service_name == service_name,
            HealingAction.created_at >= datetime.utcnow() - timedelta(minutes=settings.HEALING_COOLDOWN_MINUTES)
        ).count()
        
        context = {
            "recent_restart_count": recent_healings,
            "metric_type": metric_type
        }
        
        # Make decision using new engine
        decision = HealingDecision(
            service_name=service_name,
            severity=severity,
            metric_value=metric_value,
            metric_type=metric_type,
            context=context
        ).decide()
        
        # Execute
        executor = HealingExecutor(db)
        healing_result = executor.execute(decision)

        # audit log
        AuditLogger.log(
            db=db,
            user_id=None,
            username="auto",
            action="healing_trigger",
            resource=service_name,
            details={
                "severity": severity,
                "action": decision.action.value,
                "metric_value": metric_value,
                "metric_type": metric_type,
                "reason": reason,
                "requires_approval": decision.requires_approval
            },
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent")
        )

        # cache healing status
        cache_key = f"healing:{service_name}"
        redis_client.setex(
            cache_key, settings.HEALING_CACHE_TTL,
            json.dumps(healing_result)
        )

        return healing_result

    except Exception as e:
        return {"error": str(e)}


@router.post("/autohealing/pipeline")
def full_pipeline(
    request: Request,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Full NeuroOps pipeline:
    1. Receive metric
    2. Check severity
    3. Analyze log with OpsGPT
    4. Trigger auto-healing
    5. Return full report
    """
    try:
        service_name = data.get("service")
        metric_value = data.get("metric_value")
        metric_type = data.get("metric_type", "cpu")
        severity = data.get("severity")
        log_message = data.get("log", "")

        # Get recent healing attempts for context
        recent_healings = db.query(HealingAction).filter(
            HealingAction.service_name == service_name,
            HealingAction.created_at >= datetime.utcnow() - timedelta(minutes=settings.HEALING_COOLDOWN_MINUTES)
        ).count()
        
        context = {
            "recent_restart_count": recent_healings,
            "metric_type": metric_type
        }
        
        # Make decision
        decision = HealingDecision(
            service_name=service_name,
            severity=severity,
            metric_value=metric_value,
            metric_type=metric_type,
            context=context
        ).decide()
        
        # Execute
        executor = HealingExecutor(db)
        healing = executor.execute(decision)

        # audit log
        AuditLogger.log(
            db=db,
            user_id=current_user.id,
            username=current_user.username,
            action="pipeline_trigger",
            resource=service_name,
            details={
                "severity": severity,
                "metric_value": metric_value,
                "metric_type": metric_type,
                "action": decision.action.value
            },
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent")
        )

        report = {
            "pipeline": "NeuroOps Auto-Healing Pipeline",
            "timestamp": datetime.utcnow().isoformat(),
            "service": service_name,
            "trigger": {
                "metric_value": metric_value,
                "metric_type": metric_type,
                "severity": severity,
                "log": log_message or "No log provided"
            },
            "healing": healing,
            "status": "RESOLVED" if severity != "critical" else "IN_PROGRESS"
        }

        alert = Alert(
            metric_value=metric_value,
            rolling_mean=0,
            rolling_std=0,
            value_diff=0,
            is_anomaly=severity != "normal",
            severity=severity,
            anomaly_score=settings.ANOMALY_FORCED_SCORE if severity == "critical" else -0.1,
            message=f"Auto-healing triggered for {service_name} ({metric_type} at {metric_value}%)"
        )
        db.add(alert)
        db.commit()

        return report

    except Exception as e:
        return {"error": str(e)}


@router.post("/autohealing/rollback/{service_name}")
def rollback_healing(
    service_name: str,
    previous_action_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Rollback a previous healing action (called automatically on failure)"""
    try:
        executor = HealingExecutor(db)
        result = executor.rollback(service_name, previous_action_id)
        
        AuditLogger.log(
            db=db,
            user_id=None,
            username="auto",
            action="healing_rollback",
            resource=service_name,
            details={"previous_action_id": previous_action_id},
            ip_address=request.client.host
        )
        
        return result
        
    except Exception as e:
        return {"error": str(e)}


@router.post("/autohealing/manual-rollback/{instance_id}")
def manual_rollback(
    instance_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Manually trigger rollback for an instance (admin only)"""
    try:
        executor = HealingExecutor(db)
        result = executor._execute_rollback(instance_id)
        
        AuditLogger.log(
            db=db,
            user_id=current_user.id,
            username=current_user.username,
            action="manual_rollback",
            resource=instance_id,
            details=result,
            ip_address=request.client.host
        )
        
        return result
        
    except Exception as e:
        return {"error": str(e)}


@router.get("/autohealing/status/{service_name}")
def get_healing_status(service_name: str):
    cache_key = f"healing:{service_name}"
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    
    return {
        "service": service_name,
        "status": "No recent healing events found"
    }


@router.get("/autohealing/history/{service_name}")
def get_healing_history(
    service_name: str,
    db: Session = Depends(get_db),
    limit: int = 10
):
    """Get healing action history from database"""
    history = db.query(HealingAction).filter(
        HealingAction.service_name == service_name
    ).order_by(HealingAction.created_at.desc()).limit(limit).all()
    
    return {
        "service": service_name,
        "history": [
            {
                "id": h.id,
                "severity": h.severity,
                "action": h.action_taken,
                "status": h.status,
                "triggered_by": h.triggered_by,
                "created_at": h.created_at.isoformat() if h.created_at else None
            }
            for h in history
        ]
    }


@router.get("/autohealing/rules")
def get_rules():
    return {"rules": get_healing_rules()}


def trigger_auto_healing(service_name: str, severity: str, metric_value: float, metric_type: str = "cpu", reason: str = "") -> dict:
    """Programmatic trigger for auto-healing (used by background analyzer)"""
    from backend.services.healing_executor import HealingDecision, HealingExecutor
    from backend.models.database import SessionLocal
    
    db = SessionLocal()
    try:
        decision = HealingDecision(
            service_name=service_name,
            severity=severity,
            metric_value=metric_value,
            metric_type=metric_type,
            context={"recent_restart_count": 0, "metric_type": metric_type}
        ).decide()
        
        executor = HealingExecutor(db)
        result = executor.execute(decision)
        
        db.commit()
        return result
    except Exception as e:
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()
        

@router.get("/autohealing/timeline")
def get_healing_timeline(
    days: int = 7,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get healing actions timeline for charts"""
    try:
        start_date = datetime.utcnow() - timedelta(days=days)
        
        history = db.query(HealingAction).filter(
            HealingAction.created_at >= start_date
        ).order_by(HealingAction.created_at.asc()).all()
        
        # Group by date
        timeline = {}
        for action in history:
            date = action.created_at.strftime('%Y-%m-%d')
            if date not in timeline:
                timeline[date] = {
                    "total": 0,
                    "success": 0,
                    "failed": 0,
                    "actions": []
                }
            timeline[date]["total"] += 1
            if action.status == "completed":
                timeline[date]["success"] += 1
            else:
                timeline[date]["failed"] += 1
            timeline[date]["actions"].append({
                "time": action.created_at.strftime('%H:%M:%S'),
                "action": action.action_taken,
                "severity": action.severity,
                "status": action.status,
                "service": action.service_name
            })
        
        return {
            "timeline": timeline,
            "total_actions": len(history),
            "success_rate": round(len([a for a in history if a.status == "completed"]) / len(history) * 100, 1) if history else 0
        }
    except Exception as e:
        return {"error": str(e)}
    
    
@router.get("/autohealing/services")
def get_active_services(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get list of active services for dashboard dropdown"""
    try:
        # Get services that have had healing actions (for history)
        services_with_history = db.query(HealingAction.service_name).distinct().all()
        historical_services = [s[0] for s in services_with_history]
        
        # Try to get EC2 instances as primary source
        try:
            from backend.services.aws_service import list_ec2_instances
            instances = list_ec2_instances()
            running_instances = [i for i in instances if i.get("state") == "running"]
            service_names = [i["instance_id"] for i in running_instances[:20]]
            
            if service_names:
                return {
                    "services": service_names,
                    "source": "aws_ec2",
                    "count": len(service_names)
                }
        except Exception as e:
            pass
        
        # Fallback to historical services
        if historical_services:
            return {
                "services": historical_services[:20],
                "source": "history",
                "count": len(historical_services[:20])
            }
        
        # Final fallback
        return {
            "services": ["api-gateway", "auth-service", "payment-processor", "cache-layer", "database-primary"],
            "source": "default",
            "count": 5
        }
        
    except Exception as e:
        return {"services": ["api-gateway", "auth-service"], "source": "error", "error": str(e)}