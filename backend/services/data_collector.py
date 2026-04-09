"""
Enhanced Data Collector for RUL Model Training
Collects and stores metrics for ML training
"""
import json
import csv
import os
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from backend.models.database import MetricHistory, Alert, HealingAction
from backend.services.redis_service import redis_client
from backend.core.logger import get_logger

logger = get_logger(__name__)

TRAINING_DATA_DIR = os.path.join(settings.DATA_DIR, "training_data")
os.makedirs(TRAINING_DATA_DIR, exist_ok=True)

def collect_training_data(db: Session, days: int = 30):
    """Collect historical data for model training"""
    
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    # Collect metrics
    metrics = db.query(MetricHistory).filter(
        MetricHistory.timestamp > cutoff_date
    ).all()
    
    # Collect alerts (anomalies)
    alerts = db.query(Alert).filter(
        Alert.created_at > cutoff_date,
        Alert.is_anomaly == True
    ).all()
    
    # Collect healing actions
    healing = db.query(HealingAction).filter(
        HealingAction.created_at > cutoff_date
    ).all()
    
    # Save to CSV for training
    metrics_file = os.path.join(TRAINING_DATA_DIR, f"metrics_{datetime.utcnow().strftime('%Y%m%d')}.csv")
    alerts_file = os.path.join(TRAINING_DATA_DIR, f"alerts_{datetime.utcnow().strftime('%Y%m%d')}.csv")
    
    # Save metrics
    with open(metrics_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'instance_id', 'metric_name', 'value', 'source'])
        for m in metrics:
            writer.writerow([m.timestamp, m.instance_id, m.metric_name, m.value, m.source])
    
    # Save alerts
    with open(alerts_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'severity', 'anomaly_score', 'message'])
        for a in alerts:
            writer.writerow([a.created_at, a.severity, a.anomaly_score, a.message])
    
    logger.info(f"Collected {len(metrics)} metrics and {len(alerts)} alerts for training")
    
    return {
        "metrics_count": len(metrics),
        "alerts_count": len(alerts),
        "healing_count": len(healing),
        "metrics_file": metrics_file,
        "alerts_file": alerts_file
    }

def collect_real_rul_data(db: Session):
    """
    Collect data specifically for RUL (Remaining Useful Life) model
    Tracks degradation patterns over time
    """
    
    # Get all instances
    instances = db.query(MetricHistory.instance_id).distinct().all()
    
    rul_data = []
    
    for instance in instances:
        instance_id = instance[0]
        
        # Get all CPU metrics for this instance
        cpu_metrics = db.query(MetricHistory).filter(
            MetricHistory.instance_id == instance_id,
            MetricHistory.metric_name == 'cpu'
        ).order_by(MetricHistory.timestamp).all()
        
        if len(cpu_metrics) < 10:
            continue
        
        # Calculate degradation trend
        cpu_values = [m.value for m in cpu_metrics]
        cpu_trend = calculate_trend(cpu_values)
        
        # Calculate anomaly frequency
        anomaly_count = db.query(Alert).filter(
            Alert.message.like(f'%{instance_id}%'),
            Alert.is_anomaly == True
        ).count()
        
        # Calculate health score (0-100, lower = worse)
        health_score = max(0, 100 - (cpu_trend * 10) - (anomaly_count * 5))
        
        rul_data.append({
            "instance_id": instance_id,
            "cpu_avg": sum(cpu_values) / len(cpu_values),
            "cpu_max": max(cpu_values),
            "cpu_trend": cpu_trend,
            "anomaly_count": anomaly_count,
            "health_score": health_score,
            "data_points": len(cpu_values),
            "first_seen": cpu_metrics[0].timestamp,
            "last_seen": cpu_metrics[-1].timestamp
        })
    
    # Save RUL training data
    rul_file = os.path.join(TRAINING_DATA_DIR, f"rul_training_data_{datetime.utcnow().strftime('%Y%m%d')}.json")
    with open(rul_file, 'w') as f:
        json.dump(rul_data, f, indent=2, default=str)
    
    logger.info(f"Collected RUL data for {len(rul_data)} instances")
    
    return rul_data

def calculate_trend(values):
    """Calculate trend (slope) of values"""
    if len(values) < 2:
        return 0
    n = len(values)
    x = list(range(n))
    slope = (n * sum(x[i] * values[i] for i in range(n)) - sum(x) * sum(values)) / (n * sum(x_i**2 for x_i in x) - sum(x)**2)
    return max(-10, min(10, slope))  # Clamp between -10 and 10

def start_daily_data_collection():
    """Start background task for daily data collection"""
    import threading
    import time
    
    def collect_loop():
        while True:
            try:
                from backend.models.database import SessionLocal
                db = SessionLocal()
                collect_training_data(db, days=30)
                collect_real_rul_data(db)
                db.close()
                logger.info("Daily data collection completed")
            except Exception as e:
                logger.error(f"Data collection failed: {e}")
            time.sleep(86400)  # 24 hours
    
    thread = threading.Thread(target=collect_loop, daemon=True)
    thread.start()
    logger.info("Daily data collection started")
