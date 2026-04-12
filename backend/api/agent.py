from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
import json
from backend.models.database import get_db, MetricHistory
from backend.services.redis_service import redis_client
from backend.core.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)

class AgentMetrics(BaseModel):
    instance_id: str
    timestamp: str
    cpu: dict
    memory: dict
    disk: dict


@router.post("/agent/metrics")
def receive_agent_metrics(metrics: AgentMetrics, db: Session = Depends(get_db)):
    try:
        ts = datetime.fromisoformat(metrics.timestamp)
        instance_id = metrics.instance_id

        # ========== 1. Store CPU ==========
        cpu_history = MetricHistory(
            instance_id=instance_id,
            metric_name="cpu",
            value=metrics.cpu["percent"],
            timestamp=ts,
            source="agent"
        )
        db.add(cpu_history)
        redis_client.setex(f"real_cpu:{instance_id}", 300, metrics.cpu["percent"])

        # ========== 2. Store Memory ==========
        memory_history = MetricHistory(
            instance_id=instance_id,
            metric_name="memory",
            value=metrics.memory["percent"],
            timestamp=ts,
            source="agent"
        )
        db.add(memory_history)
        redis_client.setex(f"memory:{instance_id}", 300, metrics.memory["percent"])

        # ========== 3. Store Disk ==========
        disk_history = MetricHistory(
            instance_id=instance_id,
            metric_name="disk",
            value=metrics.disk["percent"],
            timestamp=ts,
            source="agent"
        )
        db.add(disk_history)
        redis_client.setex(f"disk:{instance_id}", 300, metrics.disk["percent"])

        # ========== 4. Update Feature Store ==========
        try:
            feature_data = {
                "timestamp": ts.isoformat(),
                "cpu": metrics.cpu["percent"],
                "memory": metrics.memory["percent"],
                "disk": metrics.disk["percent"]
            }
            
            # Latest snapshot (overwrites, TTL 5 min)
            redis_client.setex(
                f"feature:{instance_id}:latest",
                300,
                json.dumps(feature_data)
            )
            
            # Historical (appends to list, keeps last 100, TTL 24h)
            history_key = f"feature:{instance_id}:history"
            redis_client.rpush(history_key, json.dumps(feature_data))
            redis_client.ltrim(history_key, -100, -1)
            redis_client.expire(history_key, 86400)
            
            # Update CPU history for trend calculation (used by RUL)
            cpu_history_key = f"cpu_history:{instance_id}"
            redis_client.rpush(cpu_history_key, metrics.cpu["percent"])
            redis_client.ltrim(cpu_history_key, -20, -1)  # Keep last 20 values
            redis_client.expire(cpu_history_key, 86400)
            
            logger.debug(f"Feature store updated for {instance_id}")
        except Exception as e:
            logger.warning(f"Feature store update failed: {e}")

        db.commit()
        return {"status": "success", "message": "Metrics stored"}

    except Exception as e:
        db.rollback()
        logger.error(f"Agent metrics failed: {e}")
        return {"status": "error", "message": str(e)}