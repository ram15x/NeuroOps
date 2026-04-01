from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.models.database import get_db, Incident
from backend.api.auth import get_current_user

router = APIRouter()

@router.get("/incidents/recent")
def get_recent_incidents(
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    incidents = db.query(Incident).order_by(
        Incident.detected_at.desc()
    ).limit(limit).all()
    
    return {
        "incidents": [
            {
                "id": i.id,
                "title": i.title,
                "severity": i.severity,
                "root_cause": i.root_cause,
                "detected_at": i.detected_at.isoformat(),
                "status": i.status
            }
            for i in incidents
        ]
    }