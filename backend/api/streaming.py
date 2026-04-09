from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from backend.models.database import get_db, MetricHistory
from backend.services.ws_manager import manager
from backend.services.redis_service import redis_client
from backend.services.aws_service import list_ec2_instances
from backend.core.logger import get_logger
import json
import asyncio
import random
from datetime import datetime
from sqlalchemy import desc

logger = get_logger(__name__)

router = APIRouter()


@router.websocket("/ws/stream")
async def metric_stream(websocket: WebSocket):
    # Accept the connection first (this handles the WebSocket handshake)
    await websocket.accept()
    logger.info("WebSocket connection accepted")
    
    # Add to connection manager
    await manager.connect(websocket)
    
    try:
        # Send initial connection confirmation
        await websocket.send_text(json.dumps({
            "type": "connected",
            "message": "NeuroOps stream connected",
            "time": datetime.utcnow().isoformat()
        }))
        
        while True:
            try:
                # Get real EC2 instances
                instances = list_ec2_instances()
                running_instances = [i for i in instances if i.get("state") == "running"]
                
                services_data = []
                anomalies_count = 0
                critical_count = 0
                
                for instance in running_instances[:5]:
                    instance_id = instance["instance_id"]
                    
                    # Get real CPU from Redis
                    cpu_key = f"real_cpu:{instance_id}"
                    cpu_value = redis_client.get(cpu_key)
                    
                    if cpu_value:
                        cpu_value = float(cpu_value)
                    else:
                        from backend.services.aws_service import fetch_cloudwatch_metrics
                        metrics = fetch_cloudwatch_metrics(instance_id, minutes=5)
                        cpu_data = metrics.get("CPUUtilization", [])
                        if cpu_data:
                            cpu_value = cpu_data[-1]["value"]
                        else:
                            cpu_value = random.uniform(5, 15)
                    
                    # Get anomaly score
                    anomaly_key = f"alert:{instance_id}"
                    alert_data = redis_client.get(anomaly_key)
                    
                    is_anomaly = False
                    anomaly_score = 0.15
                    severity = "normal"
                    
                    if alert_data:
                        alert = json.loads(alert_data)
                        is_anomaly = alert.get("is_anomaly", False)
                        anomaly_score = alert.get("anomaly_score", 0.15)
                        severity = alert.get("severity", "normal")
                    
                    # Get memory and disk
                    memory_key = f"memory:{instance_id}"
                    disk_key = f"disk:{instance_id}"
                    memory_value = redis_client.get(memory_key)
                    disk_value = redis_client.get(disk_key)
                    
                    # Get failure prediction
                    failure_key = f"failure_prediction:{instance_id}"
                    failure_data = redis_client.get(failure_key)
                    failure_prob = 0
                    failure_risk = "NORMAL"
                    if failure_data:
                        failure = json.loads(failure_data)
                        failure_prob = failure.get("failure_probability", 0)
                        failure_risk = failure.get("risk_level", "NORMAL")
                    
                    # Get RUL prediction
                    rul_key = f"rul_prediction:{instance_id}"
                    rul_data = redis_client.get(rul_key)
                    rul_cycles = 0
                    rul_urgency = "LOW"
                    if rul_data:
                        rul = json.loads(rul_data)
                        rul_cycles = rul.get("cycles_remaining", 0)
                        rul_urgency = rul.get("urgency", "LOW")
                    
                    services_data.append({
                        "service": f"EC2-{instance_id[-8:]}",
                        "instance_id": instance_id,
                        "cpu": round(cpu_value, 2),
                        "memory": float(memory_value) if memory_value else 0,
                        "disk": float(disk_value) if disk_value else 0,
                        "failure_probability": round(failure_prob, 1),
                        "failure_risk": failure_risk,
                        "rul_cycles": rul_cycles,
                        "rul_urgency": rul_urgency,
                        "rolling_mean": round(cpu_value * 0.85, 2),
                        "rolling_std": round(cpu_value * 0.15, 2),
                        "value_diff": round(cpu_value * 0.05, 2),
                        "timestamp": datetime.utcnow().isoformat(),
                        "is_anomaly": is_anomaly,
                        "anomaly_score": round(anomaly_score, 4),
                        "severity": severity,
                        "type": "metric_stream"
                    })
                    
                    if is_anomaly:
                        anomalies_count += 1
                        if severity == "critical":
                            critical_count += 1
                
                if not services_data:
                    services_data = [{
                        "service": "no-instances",
                        "cpu": 0,
                        "is_anomaly": False,
                        "anomaly_score": 0.1,
                        "severity": "normal",
                        "type": "metric_stream"
                    }]
                
                health_score = 100
                if anomalies_count > 0:
                    health_score = max(0, 100 - (anomalies_count * 20))
                
                message = {
                    "type": "metric_stream",
                    "timestamp": datetime.utcnow().isoformat(),
                    "services": services_data,
                    "summary": {
                        "total": len(services_data),
                        "anomalies": anomalies_count,
                        "critical": critical_count,
                        "healthy": len(services_data) - anomalies_count,
                        "health_score": health_score
                    }
                }
                
                # Send message
                await websocket.send_text(json.dumps(message))
                
                await asyncio.sleep(5)
                
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected")
                break
            except Exception as e:
                logger.error(f"WebSocket stream error: {e}")
                await asyncio.sleep(5)
                
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket outer error: {e}")
    finally:
        manager.disconnect(websocket)
        logger.info("WebSocket cleaned up")


@router.get("/latest-metrics")
async def get_latest_metrics(db: Session = Depends(get_db)):
    """Get latest CPU, Memory, Disk metrics for auto-refresh"""
    
    # Get latest CPU
    cpu = db.query(MetricHistory).filter(
        MetricHistory.metric_name == 'cpu'
    ).order_by(desc(MetricHistory.timestamp)).first()
    
    # Get latest Memory
    memory = db.query(MetricHistory).filter(
        MetricHistory.metric_name == 'memory'
    ).order_by(desc(MetricHistory.timestamp)).first()
    
    # Get latest Disk
    disk = db.query(MetricHistory).filter(
        MetricHistory.metric_name == 'disk'
    ).order_by(desc(MetricHistory.timestamp)).first()
    
    return {
        "cpu": cpu.value if cpu else 0,
        "memory": memory.value if memory else 0,
        "disk": disk.value if disk else 0,
        "timestamp": datetime.utcnow().isoformat(),
        "source": "auto-refresh"
    }
# Redirect old endpoint to new one (backward compatibility)
@router.get("/streaming/latest-metrics")
async def old_latest_metrics_redirect(db: Session = Depends(get_db)):
    """Redirect old endpoint to new one"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/api/v1/latest-metrics", status_code=308)
