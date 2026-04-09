from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from backend.models.database import get_db, MetricHistory
from backend.services.redis_service import redis_client

router = APIRouter()

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

        # Store CPU
        cpu_history = MetricHistory(
            instance_id=instance_id,
            metric_name="cpu",
            value=metrics.cpu["percent"],
            timestamp=ts,
            source="agent"
        )
        db.add(cpu_history)
        redis_client.setex(f"real_cpu:{instance_id}", 300, metrics.cpu["percent"])

        # Store Memory
        memory_history = MetricHistory(
            instance_id=instance_id,
            metric_name="memory",
            value=metrics.memory["percent"],
            timestamp=ts,
            source="agent"
        )
        db.add(memory_history)
        redis_client.setex(f"memory:{instance_id}", 300, metrics.memory["percent"])

        # Store Disk
        disk_history = MetricHistory(
            instance_id=instance_id,
            metric_name="disk",
            value=metrics.disk["percent"],
            timestamp=ts,
            source="agent"
        )
        db.add(disk_history)
        redis_client.setex(f"disk:{instance_id}", 300, metrics.disk["percent"])

        db.commit()
        return {"status": "success", "message": "Metrics stored"}

    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}
