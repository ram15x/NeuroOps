from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from backend.models.database import get_db, MetricHistory

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
        
        db.add(MetricHistory(
            instance_id=metrics.instance_id,
            metric_name="cpu",
            value=metrics.cpu["percent"],
            timestamp=ts,
            source="agent"
        ))
        db.add(MetricHistory(
            instance_id=metrics.instance_id,
            metric_name="memory",
            value=metrics.memory["percent"],
            timestamp=ts,
            source="agent"
        ))
        db.add(MetricHistory(
            instance_id=metrics.instance_id,
            metric_name="disk",
            value=metrics.disk["percent"],
            timestamp=ts,
            source="agent"
        ))
        db.commit()
        return {"status": "success"}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}
