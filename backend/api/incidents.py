from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from backend.models.database import get_db, Alert, HealingAction
from backend.api.auth import get_current_user

router = APIRouter()

@router.get("/incidents/recent")
def get_recent_incidents(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get recent incidents from alerts and healing actions"""
    
    # Get critical alerts from last 7 days
    cutoff = datetime.utcnow() - timedelta(days=7)
    alerts = db.query(Alert).filter(
        Alert.severity == "critical",
        Alert.created_at > cutoff
    ).order_by(Alert.created_at.desc()).limit(limit).all()
    
    # Get healing actions
    healing = db.query(HealingAction).filter(
        HealingAction.created_at > cutoff
    ).order_by(HealingAction.created_at.desc()).limit(limit).all()
    
    incidents = []
    for a in alerts:
        incidents.append({
            "id": a.id,
            "title": f"Critical Alert: {a.message[:50]}",
            "severity": a.severity,
            "detected_at": a.created_at.isoformat(),
            "status": "resolved" if a.auto_resolved else "active",
            "source": "alert"
        })
    
    return {"incidents": incidents, "total": len(incidents)}
