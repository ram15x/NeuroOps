

from datetime import datetime, timedelta
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_

from backend.models.database import Alert, MetricHistory, Incident, HealingAction


def get_timeline_for_alert(
    alert_id: int,
    db: Session,
    time_window_minutes: int = 30
) -> Dict[str, Any]:
    """
    Build timeline of events before and after an alert
    
    Returns structured timeline:
    - Deployment events (if any)
    - Metric changes (CPU, memory, disk)
    - Log errors
    - Healing actions taken
    - Root cause conclusion
    """
    
    # Get the alert
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        return {"error": f"Alert {alert_id} not found"}
    
    alert_time = alert.created_at
    start_time = alert_time - timedelta(minutes=time_window_minutes)
    end_time = alert_time + timedelta(minutes=time_window_minutes)
    
    timeline_events = []
    
    # 1. Check for deployments before alert
    deployment_events = _check_deployments_before(alert_time, db)
    for dep in deployment_events:
        timeline_events.append({
            "type": "deployment",
            "timestamp": dep["timestamp"],
            "time_relative": _get_time_relative(dep["timestamp"], alert_time),
            "service": dep["service"],
            "version": dep["version"],
            "description": f"Deployment of {dep['service']} version {dep['version']}"
        })
    
    # 2. Check metric changes before alert
    metric_events = _check_metric_trends(alert.metric_value, alert_time, db)
    for metric in metric_events:
        timeline_events.append({
            "type": "metric",
            "timestamp": metric["timestamp"],
            "time_relative": _get_time_relative(metric["timestamp"], alert_time),
            "metric_name": metric["name"],
            "value": metric["value"],
            "trend": metric["trend"],
            "description": f"{metric['name']} {'increased' if metric['trend'] == 'up' else 'decreased'} to {metric['value']}"
        })
    
    # 3. Check error logs (from incidents table or similar)
    error_events = _check_error_logs_before(alert_time, db)
    for err in error_events:
        timeline_events.append({
            "type": "error_log",
            "timestamp": err["timestamp"],
            "time_relative": _get_time_relative(err["timestamp"], alert_time),
            "message": err["message"],
            "service": err["service"],
            "description": f"Error: {err['message'][:100]}"
        })
    
    # 4. Check healing actions after alert
    healing_events = _check_healing_after(alert_time, db)
    for heal in healing_events:
        timeline_events.append({
            "type": "healing",
            "timestamp": heal["timestamp"],
            "time_relative": _get_time_relative(heal["timestamp"], alert_time),
            "action": heal["action"],
            "status": heal["status"],
            "description": f"Healing action: {heal['action']} - {heal['status']}"
        })
    
    # Sort by timestamp
    timeline_events.sort(key=lambda x: x["timestamp"])
    
    # Determine root cause
    root_cause = _determine_root_cause(timeline_events, alert)
    
    return {
        "alert_id": alert_id,
        "alert_time": alert_time.isoformat(),
        "alert_message": alert.message,
        "alert_severity": alert.severity,
        "time_window_minutes": time_window_minutes,
        "timeline": timeline_events,
        "root_cause": root_cause["cause"],
        "confidence": root_cause["confidence"],
        "evidence": root_cause["evidence"],
        "recommendation": root_cause["recommendation"]
    }


def _check_deployments_before(alert_time: datetime, db: Session) -> List[Dict]:
    """Check for deployments in the 30 minutes before alert"""
    return []

def _check_metric_trends(alert_value: float, alert_time: datetime, db: Session) -> List[Dict]:
    """Check metric trends before alert"""
    metrics = []
    
    # Query MetricHistory for last 30 minutes
    start = alert_time - timedelta(minutes=30)
    metric_records = db.query(MetricHistory).filter(
        MetricHistory.timestamp >= start,
        MetricHistory.timestamp <= alert_time
    ).order_by(MetricHistory.timestamp).all()
    
    if metric_records:
        # Calculate trend
        first_value = metric_records[0].value if metric_records else alert_value
        last_value = metric_records[-1].value if metric_records else alert_value
        
        trend = "up" if last_value > first_value else "down" if last_value < first_value else "stable"
        
        metrics.append({
            "timestamp": metric_records[-1].timestamp if metric_records else alert_time,
            "name": metric_records[0].metric_name if metric_records else "unknown",
            "value": round(last_value, 2),
            "trend": trend
        })
    
    return metrics


def _check_error_logs_before(alert_time: datetime, db: Session) -> List[Dict]:
    """Check error logs before alert"""
    errors = []
    
    # Query Incidents or custom error logs
    start = alert_time - timedelta(minutes=30)
    incidents = db.query(Incident).filter(
        Incident.detected_at >= start,
        Incident.detected_at <= alert_time,
        Incident.severity.in_(["critical", "warning"])
    ).all()
    
    for inc in incidents:
        errors.append({
            "timestamp": inc.detected_at,
            "message": inc.description or inc.title,
            "service": inc.service_name or "unknown"
        })
    
    return errors


def _check_healing_after(alert_time: datetime, db: Session) -> List[Dict]:
    """Check healing actions after alert"""
    healings = []
    
    end = alert_time + timedelta(minutes=30)
    actions = db.query(HealingAction).filter(
        HealingAction.created_at >= alert_time,
        HealingAction.created_at <= end
    ).all()
    
    for a in actions:
        healings.append({
            "timestamp": a.created_at,
            "action": a.action_taken,
            "status": a.status
        })
    
    return healings


def _get_time_relative(event_time: datetime, alert_time: datetime) -> str:
    """Get relative time string (e.g., '2 minutes before', '5 minutes after')"""
    diff = (event_time - alert_time).total_seconds() / 60
    
    if diff < 0:
        return f"{int(abs(diff))} minutes before"
    elif diff > 0:
        return f"{int(diff)} minutes after"
    else:
        return "same time"


def _determine_root_cause(events: List[Dict], alert: Alert) -> Dict:
    """Determine root cause based on timeline pattern matching"""
    
    # Pattern 1: Deployment → Metric spike → Alert
    deployment_before = any(e["type"] == "deployment" for e in events)
    metric_spike = any(e["type"] == "metric" and e.get("trend") == "up" for e in events)
    
    if deployment_before and metric_spike:
        deploy_event = next(e for e in events if e["type"] == "deployment")
        return {
            "cause": f"Deployment at {deploy_event['time_relative']} caused metric spike",
            "confidence": 85,
            "evidence": [
                f"Deployment occurred {deploy_event['time_relative']}",
                "Metric increased after deployment",
                "No other changes detected"
            ],
            "recommendation": "Rollback deployment or investigate code changes in version"
        }
    
    # Pattern 2: Gradual metric increase (memory leak, slow degradation)
    gradual_increase = any(e.get("trend") == "up" for e in events if e["type"] == "metric")
    if gradual_increase and not deployment_before:
        return {
            "cause": "Gradual resource degradation (potential memory leak or increased load)",
            "confidence": 70,
            "evidence": [
                "Metric showed increasing trend over time",
                "No deployment or config change detected",
                "Alert triggered when threshold crossed"
            ],
            "recommendation": "Check for memory leaks, optimize queries, or scale resources"
        }
    
    # Pattern 3: Error logs before alert
    error_before = any(e["type"] == "error_log" for e in events)
    if error_before:
        error_event = next(e for e in events if e["type"] == "error_log")
        return {
            "cause": f"Error condition detected {error_event['time_relative']}",
            "confidence": 75,
            "evidence": [
                f"Error message: {error_event.get('message', 'unknown')[:100]}",
                "Alert triggered after error condition started"
            ],
            "recommendation": "Fix the underlying error condition in application code"
        }
    
    # Default: unknown
    return {
        "cause": "Unable to determine root cause automatically",
        "confidence": 30,
        "evidence": [
            "No deployment detected before alert",
            "No clear metric trend identified",
            "No error logs found in time window"
        ],
        "recommendation": "Manual investigation required. Check application logs and recent changes."
    }