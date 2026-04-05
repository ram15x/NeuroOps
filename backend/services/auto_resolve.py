"""
Auto-Resolve Service for GAP 1
Automatically resolves repeat offenders after successful auto-fixes
"""

import json
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from backend.services.aws_service import send_sns_alert
from backend.models.database import Alert, AlertCluster, HealingAction
from backend.services.redis_service import redis_client


def check_and_auto_resolve_cluster(
    cluster_id: str,
    db: Session,
    send_notification: bool = True
) -> dict:
    """
    Check if a cluster qualifies for auto-resolution and resolve it.
    
    Conditions for auto-resolve:
    1. Same cluster occurred 3+ times in last 7 days
    2. Last 2 occurrences were auto-fixed successfully
    3. No manual intervention was required
    
    Returns:
        dict with status and details
    """
    cluster = db.query(AlertCluster).filter(
        AlertCluster.cluster_id == cluster_id
    ).first()
    
    if not cluster:
        return {"error": f"Cluster {cluster_id} not found", "auto_resolved": False}
    
    # Check if already resolved
    if cluster.status == "auto_resolved":
        return {"message": "Already auto-resolved", "auto_resolved": True, "cluster": cluster_id}
    
    # Condition 1: Occurred 3+ times in last 7 days
    if cluster.occurrence_count_7d < 3:
        return {
            "auto_resolved": False,
            "reason": f"Only {cluster.occurrence_count_7d} occurrences in 7 days (need 3+)",
            "cluster": cluster_id
        }
    
    # Condition 2: Auto-fix success rate >= 66% (2 out of last 3)
    success_rate = 0
    if cluster.auto_fix_total_attempts > 0:
        success_rate = cluster.auto_fix_success_count / cluster.auto_fix_total_attempts
    
    if success_rate < 0.66:
        return {
            "auto_resolved": False,
            "reason": f"Auto-fix success rate {success_rate:.0%} (need 66%+)",
            "cluster": cluster_id
        }
    
    # Condition 3: No recent manual intervention (check healing actions)
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    manual_actions = db.query(HealingAction).filter(
        HealingAction.service_name.in_(cluster.affected_services or []),
        HealingAction.created_at >= seven_days_ago,
        HealingAction.triggered_by != "auto"
    ).count()
    
    if manual_actions > 0:
        return {
            "auto_resolved": False,
            "reason": f"{manual_actions} manual interventions in last 7 days",
            "cluster": cluster_id
        }
    
    # ALL CONDITIONS MET - AUTO RESOLVE
    cluster.status = "auto_resolved"
    cluster.resolved_at = datetime.utcnow()
    db.commit()
    
    # Also mark all related alerts as auto_resolved
    db.query(Alert).filter(
        Alert.cluster_id == cluster_id,
        Alert.auto_resolved == False
    ).update({"auto_resolved": True})
    db.commit()
    
    # Send notification
    if send_notification:
        notification_message = (
            f"[NeuroOps] Auto-Resolved\n\n"
            f"Cluster: {cluster.cluster_id}\n"
            f"Root Cause: {cluster.root_cause_pattern[:100]}\n"
            f"Total Alerts: {cluster.total_alerts}\n"
            f"Occurrences (7d): {cluster.occurrence_count_7d}\n"
            f"Auto-Fix Success Rate: {success_rate:.0%}\n\n"
            f"No action needed. This issue will be auto-resolved in the future."
        )
        
        # Send SNS notification
        try:
            send_sns_alert(
                subject="[NeuroOps] Auto-Resolved Incident",message=notification_message
                )
        except Exception as e:
            print(f"SNS send failed: {e}")
        
        # Also store in Redis for dashboard bell
        redis_client.lpush(
            "dashboard:notifications",
            json.dumps({
                "title": "Auto-Resolved",
                "message": f"Cluster {cluster.cluster_id[:20]}... auto-resolved",
                "severity": "normal",
                "timestamp": datetime.utcnow().isoformat()
            })
        )
    
    return {
        "auto_resolved": True,
        "cluster": cluster_id,
        "reason": f"Occurred {cluster.occurrence_count_7d} times with {success_rate:.0%} auto-fix success",
        "resolved_at": cluster.resolved_at.isoformat()
    }


def check_and_auto_resolve_alert(
    alert_id: int,
    db: Session,
    send_notification: bool = True
) -> dict:
    """
    Check if a single alert qualifies for auto-resolution.
    Alerts are auto-resolved if they belong to an auto-resolved cluster.
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    
    if not alert:
        return {"error": f"Alert {alert_id} not found", "auto_resolved": False}
    
    if alert.auto_resolved:
        return {"message": "Already auto-resolved", "auto_resolved": True, "alert_id": alert_id}
    
    # Check if parent cluster is auto-resolved
    if alert.cluster_id:
        cluster = db.query(AlertCluster).filter(
            AlertCluster.cluster_id == alert.cluster_id
        ).first()
        
        if cluster and cluster.status == "auto_resolved":
            alert.auto_resolved = True
            db.commit()
            
            return {
                "auto_resolved": True,
                "alert_id": alert_id,
                "cluster_id": alert.cluster_id,
                "reason": "Parent cluster auto-resolved"
            }
    
    return {
        "auto_resolved": False,
        "alert_id": alert_id,
        "reason": "No auto-resolved parent cluster"
    }


def update_cluster_stats_on_healing(
    cluster_id: str,
    healing_success: bool,
    db: Session
):
    """
    Update cluster statistics after a healing action.
    Called when auto-healing completes (success or failure).
    """
    cluster = db.query(AlertCluster).filter(
        AlertCluster.cluster_id == cluster_id
    ).first()
    
    if not cluster:
        return {"error": f"Cluster {cluster_id} not found"}
    
    cluster.auto_fix_total_attempts += 1
    if healing_success:
        cluster.auto_fix_success_count += 1
    
    db.commit()
    
    # After updating stats, check if cluster can be auto-resolved
    result = check_and_auto_resolve_cluster(cluster_id, db, send_notification=True)
    
    return {
        "cluster": cluster_id,
        "auto_fix_total": cluster.auto_fix_total_attempts,
        "auto_fix_success": cluster.auto_fix_success_count,
        "auto_resolved": result.get("auto_resolved", False)
    }


def get_auto_resolve_status(db: Session) -> dict:
    """
    Get overall auto-resolve statistics
    """
    total_clusters = db.query(AlertCluster).count()
    auto_resolved_clusters = db.query(AlertCluster).filter(
        AlertCluster.status == "auto_resolved"
    ).count()
    
    total_alerts = db.query(Alert).filter(Alert.is_anomaly == True).count()
    auto_resolved_alerts = db.query(Alert).filter(
        Alert.auto_resolved == True
    ).count()
    
    return {
        "clusters": {
            "total": total_clusters,
            "auto_resolved": auto_resolved_clusters,
            "auto_resolve_rate": round(auto_resolved_clusters / total_clusters * 100, 1) if total_clusters > 0 else 0
        },
        "alerts": {
            "total": total_alerts,
            "auto_resolved": auto_resolved_alerts,
            "auto_resolve_rate": round(auto_resolved_alerts / total_alerts * 100, 1) if total_alerts > 0 else 0
        }
    }