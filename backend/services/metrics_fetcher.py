import threading
import time
from datetime import datetime
from typing import Optional
from backend.core.config import settings
from backend.core.logger import get_logger
from backend.services.aws_service import fetch_cloudwatch_metrics, list_ec2_instances
from backend.services.redis_service import redis_client
from backend.services.drift_detector import record_prediction

logger = get_logger(__name__)

# Global flag to control fetcher thread
_fetcher_running = False
_fetcher_thread = None


def fetch_and_store_metrics():
    """Fetch metrics from CloudWatch and store in Redis"""
    try:
        # Get all running EC2 instances
        instances = list_ec2_instances()
        running_instances = [i for i in instances if i.get("state") == "running"]

        if not running_instances:
            logger.info("No running EC2 instances found")
            return

        for instance in running_instances:
            instance_id = instance["instance_id"]
            
            # Fetch last 5 minutes of metrics
            metrics = fetch_cloudwatch_metrics(instance_id, minutes=5)
            
            # Get latest CPU value
            cpu_data = metrics.get("CPUUtilization", [])
            if cpu_data:
                latest_cpu = cpu_data[-1]["value"]
                
                # Store in Redis
                metric_key = f"metric:ec2:{instance_id}:cpu"
                redis_client.setex(metric_key, 300, latest_cpu)
                
                # Also store full metrics
                redis_client.setex(f"metric:full:{instance_id}", 300, str(metrics))
                
                # Record prediction for drift detection
                # Simple threshold-based anomaly detection for now
                is_anomaly = latest_cpu > 80.0
                record_prediction(is_anomaly)
                
                logger.info(
                    f"Fetched metrics for {instance_id}: CPU={latest_cpu}%",
                    instance_id=instance_id,
                    cpu=latest_cpu,
                    is_anomaly=is_anomaly
                )
                
                # If anomaly detected, send SNS alert
                if is_anomaly:
                    from backend.services.aws_service import send_sns_alert
                    send_sns_alert(
                        subject=f"CRITICAL: High CPU on {instance_id}",
                        message=f"CPU utilization reached {latest_cpu}% on instance {instance_id}"
                    )
                    
    except Exception as e:
        logger.error("Failed to fetch metrics", error=str(e))


def metrics_fetcher_loop(interval_seconds: int = 60):
    """Background thread that fetches metrics periodically"""
    global _fetcher_running
    
    logger.info(f"Metrics fetcher started, interval={interval_seconds}s")
    
    while _fetcher_running:
        try:
            fetch_and_store_metrics()
        except Exception as e:
            logger.error("Metrics fetcher error", error=str(e))
        
        time.sleep(interval_seconds)


def start_metrics_fetcher(interval_seconds: int = 60):
    """Start the background metrics fetcher thread"""
    global _fetcher_running, _fetcher_thread
    
    if _fetcher_running:
        logger.info("Metrics fetcher already running")
        return
    
    _fetcher_running = True
    _fetcher_thread = threading.Thread(
        target=metrics_fetcher_loop,
        args=(interval_seconds,),
        daemon=True
    )
    _fetcher_thread.start()
    logger.info("Metrics fetcher thread started")


def stop_metrics_fetcher():
    """Stop the background metrics fetcher"""
    global _fetcher_running
    
    _fetcher_running = False
    logger.info("Metrics fetcher stopped")