from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional
import json

from backend.models.database import AuditLog
from backend.core.logger import get_logger

logger = get_logger("audit")


class AuditLogger:
    @staticmethod
    def log(
        db: Session,
        user_id: Optional[int],
        username: Optional[str],
        action: str,
        resource: str,
        details: dict = None,
        ip_address: str = None,
        user_agent: str = None
    ):
        audit = AuditLog(
            user_id=user_id,
            username=username,
            action=action,
            resource=resource,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=datetime.utcnow()
        )
        db.add(audit)
        db.commit()
        
        # Also log to structured logger
        logger.info(
            "audit_event",
            user_id=user_id,
            username=username,
            action=action,
            resource=resource,
            details=details,
            ip=ip_address
        )
    
    @staticmethod
    def get_user_history(db: Session, user_id: int, limit: int = 50):
        return db.query(AuditLog).filter(
            AuditLog.user_id == user_id
        ).order_by(AuditLog.created_at.desc()).limit(limit).all()