from backend.core.config import settings
from backend.core.logger import get_logger
from backend.services.healing_executor import HealingDecision, HealingExecutor
from backend.models.database import SessionLocal

logger = get_logger(__name__)


def trigger_auto_healing(service_name: str, severity: str, metric_value: float, reason: str) -> dict:
    """Programmatic trigger with real AWS actions"""
    
    logger.info(f"autohealing_service triggered for {service_name}, severity={severity}, enabled={settings.AUTO_HEALING_ENABLED}")
    
    db = SessionLocal()
    try:
        # Create decision
        decision = HealingDecision(
            service_name=service_name,
            severity=severity,
            metric_value=metric_value,
            context={"recent_restart_count": 0}
        ).decide()
        
        action = decision.action.value
        logger.info(f"Decision made: action={action}, reason={decision.reason}")
        
        # Execute
        executor = HealingExecutor(db)
        result = executor.execute(decision)
        
        db.commit()
        return result
        
    except Exception as e:
        db.rollback()
        logger.error(f"Auto-healing failed for {service_name}", error=str(e))
        return {"success": False, "error": str(e)}
    finally:
        db.close()