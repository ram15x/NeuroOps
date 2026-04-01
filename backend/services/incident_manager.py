from datetime import datetime
from sqlalchemy.orm import Session
from backend.models.database import Incident
from backend.core.logger import get_logger

logger = get_logger(__name__)


class IncidentManager:
    """Manages incident creation and tracking"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_incident(
        self,
        title: str,
        description: str,
        severity: str,
        service_name: str,
        root_cause: str = None,
        resolution: str = None,
        user_id: int = None
    ) -> Incident:
        """Create a new incident record"""
        
        incident = Incident(
            title=title,
            description=description,
            severity=severity,
            status="open",
            service_name=service_name,
            root_cause=root_cause,
            resolution=resolution,
            detected_at=datetime.utcnow(),
            created_by=user_id
        )
        
        self.db.add(incident)
        self.db.commit()
        self.db.refresh(incident)
        
        logger.info(
            "incident_created",
            incident_id=incident.id,
            title=title,
            severity=severity,
            service=service_name
        )
        
        return incident
    
    def resolve_incident(self, incident_id: int, resolution: str) -> Incident:
        """Mark incident as resolved"""
        
        incident = self.db.query(Incident).filter(Incident.id == incident_id).first()
        if incident:
            incident.status = "resolved"
            incident.resolution = resolution
            incident.resolved_at = datetime.utcnow()
            self.db.commit()
            logger.info("incident_resolved", incident_id=incident_id)
        
        return incident
    
    def get_open_incidents(self, service_name: str = None) -> list:
        """Get all open incidents"""
        
        query = self.db.query(Incident).filter(Incident.status == "open")
        if service_name:
            query = query.filter(Incident.service_name == service_name)
        
        return query.order_by(Incident.detected_at.desc()).all()