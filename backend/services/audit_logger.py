import json
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from backend.models.database import AuditLog

logger = logging.getLogger(__name__)

class AuditLogger:
    @staticmethod
    def log(db: Session, user_id: int, username: str, action: str, resource: str, 
            details: dict = None, ip_address: str = None, user_agent: str = None):
        try:
            # Convert dict to JSON string - THIS IS THE FIX
            details_json = json.dumps(details) if details else None
            
            audit_log = AuditLog(
                user_id=user_id,
                username=username,
                action=action,
                resource=resource,
                details=details_json,  # Now a string, not dict
                ip_address=ip_address,
                user_agent=user_agent,
                created_at=datetime.utcnow()
            )
            db.add(audit_log)
            db.commit()
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")
            db.rollback()

audit_logger = AuditLogger()
