import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict
from sklearn.linear_model import LinearRegression

from backend.core.logger import get_logger
from backend.services.redis_service import redis_client

logger = get_logger(__name__)


class CapacityPlanner:
    """Predicts future resource needs based on historical trends"""
    
    def __init__(self, instance_id: str):
        self.instance_id = instance_id
    
    def get_historical_data(self, metric_name: str, days: int = 7) -> List[float]:
        """Get historical data from Redis for a metric"""
        values = []
        for i in range(days * 24 * 60 // 60):  # hourly data points
            # This would fetch from stored history
            # For now, use demo data or implement actual storage
            pass
        return values
    
    def predict_cpu_trend(self, days: int = 30) -> Dict:
        """Predict CPU usage trend"""
        try:
            # Get last 7 days of CPU data from Redis
            cpu_key = f"cpu_history:{self.instance_id}"
            history = redis_client.lrange(cpu_key, 0, 167)  # 7 days * 24 hours
            history = [float(x) for x in history]
            
            if len(history) < 24:
                return {"error": "Insufficient data", "confidence": "low"}
            
            # Create time indices (0,1,2,...)
            X = np.array(range(len(history))).reshape(-1, 1)
            y = np.array(history)
            
            # Train linear regression
            model = LinearRegression()
            model.fit(X, y)
            
            # Predict future values
            future_X = np.array(range(len(history), len(history) + days)).reshape(-1, 1)
            predictions = model.predict(future_X)
            
            # Calculate when CPU will hit 80%
            days_to_80 = None
            for i, pred in enumerate(predictions):
                if pred >= 80:
                    days_to_80 = i
                    break
            
            # Calculate growth rate
            growth_rate = model.coef_[0]
            current_avg = np.mean(history[-24:])  # last 24 hours average
            
            return {
                "metric": "cpu",
                "current_avg": round(current_avg, 2),
                "growth_rate_per_day": round(growth_rate, 2),
                "predictions": [round(p, 2) for p in predictions[:7]],
                "days_until_80_percent": days_to_80,
                "recommendation": self._get_recommendation("cpu", days_to_80, growth_rate),
                "confidence": "medium" if len(history) > 48 else "low"
            }
            
        except Exception as e:
            logger.error(f"CPU trend prediction failed: {e}")
            return {"error": str(e)}
    
    def predict_memory_trend(self, days: int = 30) -> Dict:
        """Predict memory usage trend"""
        try:
            # Get memory data from Redis (CustomMetrics)
            memory_data = redis_client.get(f"memory:{self.instance_id}")
            if not memory_data:
                return {"error": "No memory data available", "confidence": "low"}
            
            # For now, use single point. Need historical storage for accurate prediction.
            current_memory = float(memory_data)
            
            # Simple projection (linear growth)
            # In production, use actual historical data
            projected = []
            for i in range(1, days + 1):
                projected.append(min(100, current_memory + (i * 0.5)))  # 0.5% per day assumption
            
            days_to_90 = None
            for i, pred in enumerate(projected):
                if pred >= 90:
                    days_to_90 = i
                    break
            
            return {
                "metric": "memory",
                "current": round(current_memory, 2),
                "growth_rate_per_day": 0.5,
                "predictions": projected[:7],
                "days_until_90_percent": days_to_90,
                "recommendation": self._get_recommendation("memory", days_to_90, 0.5),
                "confidence": "low"
            }
            
        except Exception as e:
            logger.error(f"Memory trend prediction failed: {e}")
            return {"error": str(e)}
    
    def predict_disk_trend(self, days: int = 30) -> Dict:
        """Predict disk usage trend"""
        try:
            disk_data = redis_client.get(f"disk:{self.instance_id}")
            if not disk_data:
                return {"error": "No disk data available", "confidence": "low"}
            
            current_disk = float(disk_data)
            
            projected = []
            for i in range(1, days + 1):
                projected.append(min(100, current_disk + (i * 0.2)))  # 0.2% per day
            
            days_to_95 = None
            for i, pred in enumerate(projected):
                if pred >= 95:
                    days_to_95 = i
                    break
            
            return {
                "metric": "disk",
                "current": round(current_disk, 2),
                "growth_rate_per_day": 0.2,
                "predictions": projected[:7],
                "days_until_95_percent": days_to_95,
                "recommendation": self._get_recommendation("disk", days_to_95, 0.2),
                "confidence": "low"
            }
            
        except Exception as e:
            logger.error(f"Disk trend prediction failed: {e}")
            return {"error": str(e)}
    
    def predict_instance_need(self, days: int = 30) -> Dict:
        """Predict if new instances will be needed"""
        cpu_pred = self.predict_cpu_trend(days)
        memory_pred = self.predict_memory_trend(days)
        
        if "error" in cpu_pred or "error" in memory_pred:
            return {"error": "Insufficient data for prediction"}
        
        instances_needed = 0
        reasons = []
        
        if cpu_pred.get("days_until_80_percent") and cpu_pred["days_until_80_percent"] < days:
            instances_needed += 1
            reasons.append(f"CPU will reach 80% in {cpu_pred['days_until_80_percent']} days")
        
        if memory_pred.get("days_until_90_percent") and memory_pred["days_until_90_percent"] < days:
            instances_needed += 1
            reasons.append(f"Memory will reach 90% in {memory_pred['days_until_90_percent']} days")
        
        return {
            "instance_id": self.instance_id,
            "days": days,
            "instances_needed": instances_needed,
            "reasons": reasons,
            "recommendation": f"Consider adding {instances_needed} more EC2 instance(s) in the next {days} days",
            "cpu_prediction": cpu_pred,
            "memory_prediction": memory_pred
        }
    
    def _get_recommendation(self, metric: str, days: int, growth_rate: float) -> str:
        if days is None:
            return f"{metric.upper()} usage is stable. No action needed."
        elif days < 7:
            return f"⚠️ {metric.upper()} will reach threshold in {days} days — URGENT action required!"
        elif days < 14:
            return f"⚠️ {metric.upper()} will reach threshold in {days} days — Plan scaling soon."
        elif days < 30:
            return f"📈 {metric.upper()} will reach threshold in {days} days — Monitor closely."
        else:
            return f"✅ {metric.upper()} usage is healthy. No immediate action needed."


def get_capacity_report(instance_id: str) -> dict:
    # ... existing code ...
    
    if len(metrics) < 100:
        return {
            "instance_id": instance_id,
            "cpu": {"current_avg": 0, "growth_rate_per_day": 0, "days_until_80_percent": None},
            "memory": {"current": 0, "growth_rate_per_day": 0, "days_until_90_percent": None},
            "instance_need": {"recommendation": "Collecting data - check back in 7 days"}
        }