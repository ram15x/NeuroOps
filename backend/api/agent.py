from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

from backend.models.database import get_db, MetricHistory
from backend.api.auth import get_current_user

router = APIRouter()


class AgentMetrics(BaseModel):
    instance_id: str
    timestamp: str
    cpu: dict
    memory: dict
    disk: dict


@router.post("/agent/metrics")
def receive_agent_metrics(
    metrics: AgentMetrics,
    db: Session = Depends(get_db)
):
    """
    Receive metrics from NeuroOps agent
    Stores CPU, Memory, Disk in MetricHistory table
    """
    try:
        # Parse timestamp
        ts = datetime.fromisoformat(metrics.timestamp)
        
        # Store CPU
        cpu_history = MetricHistory(
            instance_id=metrics.instance_id,
            metric_name="cpu",
            value=metrics.cpu["percent"],
            timestamp=ts,
            source="agent"
        )
        db.add(cpu_history)
        
        # Store Memory
        memory_history = MetricHistory(
            instance_id=metrics.instance_id,
            metric_name="memory",
            value=metrics.memory["percent"],
            timestamp=ts,
            source="agent"
        )
        db.add(memory_history)
        
        # Store Disk
        disk_history = MetricHistory(
            instance_id=metrics.instance_id,
            metric_name="disk",
            value=metrics.disk["percent"],
            timestamp=ts,
            source="agent"
        )
        db.add(disk_history)
        
        db.commit()
        
        return {"status": "success", "message": "Metrics stored"}
        
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}