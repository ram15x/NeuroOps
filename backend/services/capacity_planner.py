

import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional
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
            
            if not history:
                return {
                    "error": "No historical CPU data available",
                    "confidence": "low",
                    "recommendation": "Collecting data - check back in 7 days"
                }
            
            history = [float(x) for x in history if x]
            
            if len(history) < 24:
                return {
                    "current_avg": round(np.mean(history), 2) if history else 0,
                    "growth_rate_per_day": 0,
                    "days_until_80_percent": None,
                    "recommendation": f"Collecting data ({len(history)}/168 hours) - check back in {7 - len(history)//24} days",
                    "confidence": "low"
                }
            
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
            
            # Calculate growth rate (per day, not per hour)
            growth_rate_per_hour = model.coef_[0]
            growth_rate_per_day = growth_rate_per_hour * 24
            current_avg = np.mean(history[-24:]) if len(history) >= 24 else np.mean(history)
            
            return {
                "metric": "cpu",
                "current_avg": round(current_avg, 2),
                "growth_rate_per_day": round(growth_rate_per_day, 2),
                "predictions": [round(p, 2) for p in predictions[:7]],
                "days_until_80_percent": days_to_80,
                "recommendation": self._get_recommendation("cpu", days_to_80, growth_rate_per_day),
                "confidence": "medium" if len(history) > 48 else "low"
            }
            
        except Exception as e:
            logger.error(f"CPU trend prediction failed: {e}")
            return {
                "error": str(e),
                "current_avg": 0,
                "growth_rate_per_day": 0,
                "days_until_80_percent": None,
                "recommendation": "Error calculating trend - using fallback values",
                "confidence": "low"
            }
    
    def predict_memory_trend(self, days: int = 30) -> Dict:
        """Predict memory usage trend"""
        try:
            # Get memory history from Redis
            memory_key = f"memory_history:{self.instance_id}"
            history = redis_client.lrange(memory_key, 0, 167)
            
            if not history:
                # Fallback to current value only
                current = redis_client.get(f"memory:{self.instance_id}")
                current_memory = float(current) if current else 0
                
                return {
                    "metric": "memory",
                    "current": round(current_memory, 2),
                    "growth_rate_per_day": 0,
                    "predictions": [current_memory] * 7,
                    "days_until_90_percent": None,
                    "recommendation": "Collecting memory data - check back in 7 days",
                    "confidence": "low"
                }
            
            history = [float(x) for x in history if x]
            
            if len(history) < 24:
                current_memory = history[-1] if history else 0
                return {
                    "metric": "memory",
                    "current": round(current_memory, 2),
                    "growth_rate_per_day": 0,
                    "predictions": [current_memory] * 7,
                    "days_until_90_percent": None,
                    "recommendation": f"Collecting data ({len(history)}/168 hours)",
                    "confidence": "low"
                }
            
            X = np.array(range(len(history))).reshape(-1, 1)
            y = np.array(history)
            model = LinearRegression()
            model.fit(X, y)
            
            future_X = np.array(range(len(history), len(history) + days)).reshape(-1, 1)
            predictions = model.predict(future_X)
            
            days_to_90 = None
            for i, pred in enumerate(predictions):
                if pred >= 90:
                    days_to_90 = i
                    break
            
            growth_rate_per_day = model.coef_[0] * 24
            current_memory = np.mean(history[-24:]) if len(history) >= 24 else history[-1]
            
            return {
                "metric": "memory",
                "current": round(current_memory, 2),
                "growth_rate_per_day": round(growth_rate_per_day, 2),
                "predictions": [round(p, 2) for p in predictions[:7]],
                "days_until_90_percent": days_to_90,
                "recommendation": self._get_recommendation("memory", days_to_90, growth_rate_per_day),
                "confidence": "medium" if len(history) > 48 else "low"
            }
            
        except Exception as e:
            logger.error(f"Memory trend prediction failed: {e}")
            return {
                "error": str(e),
                "current": 0,
                "growth_rate_per_day": 0,
                "days_until_90_percent": None,
                "recommendation": "Error calculating trend - using fallback values",
                "confidence": "low"
            }
    
    def predict_disk_trend(self, days: int = 30) -> Dict:
        """Predict disk usage trend"""
        try:
            disk_key = f"disk_history:{self.instance_id}"
            history = redis_client.lrange(disk_key, 0, 167)
            
            if not history:
                current = redis_client.get(f"disk:{self.instance_id}")
                current_disk = float(current) if current else 0
                
                return {
                    "metric": "disk",
                    "current": round(current_disk, 2),
                    "growth_rate_per_day": 0,
                    "predictions": [current_disk] * 7,
                    "days_until_95_percent": None,
                    "recommendation": "Collecting disk data - check back in 7 days",
                    "confidence": "low"
                }
            
            history = [float(x) for x in history if x]
            
            if len(history) < 24:
                current_disk = history[-1] if history else 0
                return {
                    "metric": "disk",
                    "current": round(current_disk, 2),
                    "growth_rate_per_day": 0,
                    "predictions": [current_disk] * 7,
                    "days_until_95_percent": None,
                    "recommendation": f"Collecting data ({len(history)}/168 hours)",
                    "confidence": "low"
                }
            
            X = np.array(range(len(history))).reshape(-1, 1)
            y = np.array(history)
            model = LinearRegression()
            model.fit(X, y)
            
            future_X = np.array(range(len(history), len(history) + days)).reshape(-1, 1)
            predictions = model.predict(future_X)
            
            days_to_95 = None
            for i, pred in enumerate(predictions):
                if pred >= 95:
                    days_to_95 = i
                    break
            
            growth_rate_per_day = model.coef_[0] * 24
            current_disk = np.mean(history[-24:]) if len(history) >= 24 else history[-1]
            
            return {
                "metric": "disk",
                "current": round(current_disk, 2),
                "growth_rate_per_day": round(growth_rate_per_day, 2),
                "predictions": [round(p, 2) for p in predictions[:7]],
                "days_until_95_percent": days_to_95,
                "recommendation": self._get_recommendation("disk", days_to_95, growth_rate_per_day),
                "confidence": "medium" if len(history) > 48 else "low"
            }
            
        except Exception as e:
            logger.error(f"Disk trend prediction failed: {e}")
            return {
                "error": str(e),
                "current": 0,
                "growth_rate_per_day": 0,
                "days_until_95_percent": None,
                "recommendation": "Error calculating trend - using fallback values",
                "confidence": "low"
            }
    
    def predict_instance_need(self, days: int = 30) -> Dict:
        """Predict if new instances will be needed"""
        cpu_pred = self.predict_cpu_trend(days)
        memory_pred = self.predict_memory_trend(days)
        
        if "error" in cpu_pred and "error" in memory_pred:
            return {
                "instance_id": self.instance_id,
                "error": "Insufficient data for prediction",
                "recommendation": "Collecting data - check back in 7 days"
            }
        
        instances_needed = 0
        reasons = []
        
        cpu_days = cpu_pred.get("days_until_80_percent")
        if cpu_days is not None and cpu_days < days:
            instances_needed += 1
            reasons.append(f"CPU will reach 80% in {cpu_days} days")
        
        memory_days = memory_pred.get("days_until_90_percent")
        if memory_days is not None and memory_days < days:
            instances_needed += 1
            reasons.append(f"Memory will reach 90% in {memory_days} days")
        
        if instances_needed == 0:
            recommendation = f"No new instances needed in the next {days} days"
        else:
            recommendation = f"Consider adding {instances_needed} more EC2 instance(s) in the next {days} days"
        
        return {
            "instance_id": self.instance_id,
            "days": days,
            "instances_needed": instances_needed,
            "reasons": reasons,
            "recommendation": recommendation,
            "cpu_prediction": cpu_pred,
            "memory_prediction": memory_pred
        }
    
    def _get_recommendation(self, metric: str, days: Optional[int], growth_rate: float) -> str:
        if days is None:
            if growth_rate <= 0:
                return f"✅ {metric.upper()} usage is stable or declining. No action needed."
            else:
                return f"📈 {metric.upper()} is trending up but below threshold. Monitor trend."
        elif days < 7:
            return f"⚠️ {metric.upper()} will reach threshold in {days} days — URGENT action required!"
        elif days < 14:
            return f"⚠️ {metric.upper()} will reach threshold in {days} days — Plan scaling soon."
        elif days < 30:
            return f"📈 {metric.upper()} will reach threshold in {days} days — Monitor closely."
        else:
            return f"✅ {metric.upper()} usage is healthy. No immediate action needed."


def get_capacity_report(instance_id: str) -> dict:
    """Get capacity planning report for an EC2 instance"""
    planner = CapacityPlanner(instance_id)
    
    cpu_pred = planner.predict_cpu_trend()
    memory_pred = planner.predict_memory_trend()
    disk_pred = planner.predict_disk_trend()
    
    # Determine overall recommendation
    if "error" in cpu_pred and "error" in memory_pred:
        recommendation = "Collecting data - check back in 7 days"
    else:
        cpu_days = cpu_pred.get("days_until_80_percent")
        memory_days = memory_pred.get("days_until_90_percent")
        
        if cpu_days is not None and cpu_days < 7:
            recommendation = "⚠️ Urgent: CPU will reach threshold within 7 days"
        elif memory_days is not None and memory_days < 7:
            recommendation = "⚠️ Urgent: Memory will reach threshold within 7 days"
        elif cpu_days is not None and cpu_days < 30:
            recommendation = f"📈 Plan scaling: CPU threshold in {cpu_days} days"
        elif memory_days is not None and memory_days < 30:
            recommendation = f"📈 Plan scaling: Memory threshold in {memory_days} days"
        else:
            recommendation = "✅ System stable - no scaling needed in next 30 days"
    
    return {
        "instance_id": instance_id,
        "cpu": {
            "current_avg": cpu_pred.get("current_avg", 0),
            "growth_rate_per_day": cpu_pred.get("growth_rate_per_day", 0),
            "days_until_80_percent": cpu_pred.get("days_until_80_percent")
        },
        "memory": {
            "current": memory_pred.get("current", 0),
            "growth_rate_per_day": memory_pred.get("growth_rate_per_day", 0),
            "days_until_90_percent": memory_pred.get("days_until_90_percent")
        },
        "disk": {
            "current": disk_pred.get("current", 0),
            "growth_rate_per_day": disk_pred.get("growth_rate_per_day", 0),
            "days_until_95_percent": disk_pred.get("days_until_95_percent")
        },
        "instance_need": {
            "recommendation": recommendation
        }
    }