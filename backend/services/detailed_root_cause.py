from backend.models.database import SessionLocal, MetricHistory, Alert
from datetime import datetime, timedelta
from typing import Dict, List

class DetailedRootCauseAnalyzer:
    def __init__(self):
        self.db = SessionLocal()
    
    def analyze(self, alert_id: int) -> Dict:
        """Get detailed, actionable root cause"""
        
        # Get alert
        alert = self.db.query(Alert).filter(Alert.id == alert_id).first()
        if not alert:
            return {"error": "Alert not found"}
        
        # Get metrics 30 min before alert
        before_metrics = self.db.query(MetricHistory).filter(
            MetricHistory.timestamp >= alert.created_at - timedelta(minutes=30),
            MetricHistory.timestamp <= alert.created_at
        ).order_by(MetricHistory.timestamp).all()
        
        # Extract CPU values
        cpu_before = [m.value for m in before_metrics if m.metric_name == 'cpu']
        
        if len(cpu_before) < 5:
            return {"root_cause": "Insufficient data for analysis", "confidence": 0}
        
        # Build timeline
        timeline = []
        timestamps = [m.timestamp for m in before_metrics if m.metric_name == 'cpu']
        cpu_values = cpu_before
        
        step = max(1, len(cpu_values) // 5)
        for i in range(0, len(cpu_values), step):
            if i < len(cpu_values):
                timeline.append({
                    "time": timestamps[i].strftime("%H:%M:%S"),
                    "cpu": f"{cpu_values[i]:.1f}%",
                    "change": f"{cpu_values[i] - cpu_values[0]:+.1f}%" if i > 0 else "baseline"
                })
        
        # Determine pattern
        start = cpu_before[0]
        increase = cpu_before[-1] - start
        max_cpu = max(cpu_before)
        
        if start < 5 and increase > 15:
            pattern_type = "sudden_spike"
            cause = "Sudden compute spike - batch job, cron task, or deployment"
            severity = "high"
            confidence = 90
            recommendation = "Check cron jobs, recent deployments, or batch processes running at the alert time"
        elif increase > 10:
            pattern_type = "gradual_increase"
            cause = "Gradual CPU increase - possible memory leak or increasing load"
            severity = "medium"
            confidence = 75
            recommendation = "Check for memory leaks, optimize queries, or consider scaling"
        elif max_cpu > 30:
            pattern_type = "sustained_high"
            cause = "Sustained high CPU - consistent load above threshold"
            severity = "medium"
            confidence = 70
            recommendation = "Monitor trends and adjust thresholds if needed"
        else:
            pattern_type = "normal"
            cause = "Normal variation within threshold"
            severity = "low"
            confidence = 50
            recommendation = "Monitor trends and adjust thresholds if needed"
        
        self.db.close()
        
        return {
            "alert_id": alert_id,
            "alert_time": alert.created_at.isoformat(),
            "alert_message": alert.message[:100] if alert.message else "",
            "root_cause": cause,
            "pattern": pattern_type,
            "severity": severity,
            "timeline": timeline,
            "statistics": {
                "baseline_cpu": f"{cpu_before[0]:.1f}%",
                "peak_cpu": f"{max_cpu:.1f}%",
                "increase": f"{increase:+.1f}%",
                "data_points": len(cpu_before)
            },
            "recommendation": recommendation,
            "confidence": confidence,
            "time_saved_minutes": 8
        }