from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from backend.models.database import get_db, Alert
from backend.services.root_cause_timeline import get_timeline_for_alert
from backend.api.auth import get_current_user

router = APIRouter()


@router.get("/rootcause/timeline/{alert_id}")
def get_root_cause_timeline(
    alert_id: int,
    time_window: int = 30,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Get root cause timeline for a specific alert.
    
    Shows:
    - Deployments before alert
    - Metric trends
    - Error logs
    - Healing actions after alert
    - Root cause conclusion
    """
    result = get_timeline_for_alert(alert_id, db, time_window)
    
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    
    return result


@router.get("/rootcause/latest")
def get_latest_root_cause(
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get root cause analysis for latest alerts"""
    try:
        alerts = db.query(Alert).filter(
            Alert.is_anomaly == True
        ).order_by(Alert.created_at.desc()).limit(limit).all()
        
        results = []
        for alert in alerts:
            try:
                timeline = get_timeline_for_alert(alert.id, db, time_window=30)
                if "error" not in timeline:
                    results.append({
                        "alert_id": alert.id,
                        "alert_time": alert.created_at.isoformat(),
                        "alert_message": alert.message[:100] if alert.message else "",
                        "severity": alert.severity,
                        "priority_score": alert.priority_score,
                        "root_cause": timeline.get("root_cause", "Unknown"),
                        "confidence": timeline.get("confidence", 0)
                    })
                else:
                    # Still include alert even if timeline fails
                    results.append({
                        "alert_id": alert.id,
                        "alert_time": alert.created_at.isoformat(),
                        "alert_message": alert.message[:100] if alert.message else "",
                        "severity": alert.severity,
                        "priority_score": alert.priority_score,
                        "root_cause": "Timeline analysis failed",
                        "confidence": 0
                    })
            except Exception as e:
                results.append({
                    "alert_id": alert.id,
                    "alert_time": alert.created_at.isoformat(),
                    "alert_message": alert.message[:100] if alert.message else "",
                    "severity": alert.severity,
                    "priority_score": alert.priority_score,
                    "root_cause": f"Error: {str(e)[:50]}",
                    "confidence": 0
                })
        
        return {"alerts": results, "total": len(results)}
        
    except Exception as e:
        return {"error": str(e), "alerts": []}