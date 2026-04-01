import json
import ollama
from datetime import datetime
from sqlalchemy.orm import Session
from backend.services.slack_notifier import get_slack_notifier
from backend.core.config import settings
from backend.models.database import Incident, PredictionHistory
from backend.services.redis_service import redis_client
from backend.core.logger import get_logger

logger = get_logger("root_cause")


class RootCauseAnalyzer:
    """Automatically analyzes anomalies and finds root cause"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def analyze_anomaly(self, anomaly_data: dict) -> dict:
        """
        Analyze anomaly and return root cause
        anomaly_data contains: metric_name, value, anomaly_score, severity
        """
        
        # Build prompt for OpsGPT
        prompt = f"""You are an expert cloud infrastructure engineer.
Analyze this anomaly and determine the root cause:

Metric: {anomaly_data.get('metric_name', 'unknown')}
Current Value: {anomaly_data.get('value', 0)}
Anomaly Score: {anomaly_data.get('anomaly_score', 0)}
Severity: {anomaly_data.get('severity', 'normal')}

Respond in this exact format:
ROOT_CAUSE: [one line root cause]
IMPACT: [one line business impact]
RECOMMENDATION: [one line fix]
SERVICE: [affected service name]
CONFIDENCE: [high/medium/low]
"""
        
        try:
            response = ollama.chat(
                model=settings.OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                options={"timeout": settings.OLLAMA_TIMEOUT}
            )
            
            ai_response = response["message"]["content"]
            
            # Parse response
            root_cause = self._extract_field(ai_response, "ROOT_CAUSE")
            impact = self._extract_field(ai_response, "IMPACT")
            recommendation = self._extract_field(ai_response, "RECOMMENDATION")
            service = self._extract_field(ai_response, "SERVICE")
            confidence = self._extract_field(ai_response, "CONFIDENCE")
            
            result = {
                "root_cause": root_cause,
                "impact": impact,
                "recommendation": recommendation,
                "service": service,
                "confidence": confidence,
                "analyzed_at": datetime.utcnow().isoformat()
            }
            
            # Store as incident
            incident = self._create_incident(anomaly_data, result)
            
            # Cache result
            cache_key = f"root_cause:{anomaly_data.get('metric_name')}"
            redis_client.setex(cache_key, 3600, json.dumps(result))
            
            logger.info(
                "root_cause_analyzed",
                metric=anomaly_data.get('metric_name'),
                root_cause=root_cause[:100],
                confidence=confidence
            )
            
            return result
            
        except Exception as e:
            logger.error("root_cause_analysis_failed", error=str(e))
            return {
                "root_cause": "Analysis failed",
                "impact": "Unknown",
                "recommendation": "Check logs manually",
                "service": anomaly_data.get('metric_name', 'unknown'),
                "confidence": "low",
                "error": str(e)
            }
    
    def _extract_field(self, text: str, field: str) -> str:
        for line in text.split("\n"):
            if line.startswith(f"{field}:"):
                return line.replace(f"{field}:", "").strip()
        return "unknown"
    
    def _create_incident(self, anomaly_data: dict, analysis: dict):
        """Create incident record in database"""
        
        incident = Incident(
            title=f"Anomaly detected: {anomaly_data.get('metric_name')}",
            description=f"Anomaly score: {anomaly_data.get('anomaly_score')}, Value: {anomaly_data.get('value')}",
            severity=anomaly_data.get('severity', 'warning'),
            status="open",
            service_name=analysis.get('service', anomaly_data.get('metric_name')),
            root_cause=analysis.get('root_cause'),
            resolution=analysis.get('recommendation'),
            detected_at=datetime.utcnow()
        )
        
        self.db.add(incident)
        self.db.commit()
        self.db.refresh(incident)
        
        # Send Slack notification
        try:
            slack = get_slack_notifier()
            slack.send_incident_alert(
                incident_id=incident.id,
                title=incident.title,
                severity=incident.severity,
                service_name=incident.service_name,
                cpu_value=anomaly_data.get('value', 0),
                root_cause=analysis.get('root_cause', 'Unknown'),
                recommendation=analysis.get('recommendation', 'Check logs'),
                instance_id=anomaly_data.get('metric_name', '').replace('ec2_', '').replace('_cpu', '')
            )
        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}")
        
        return incident
    
    def get_cached_root_cause(self, metric_name: str) -> dict:
        """Get cached root cause if available"""
        cache_key = f"root_cause:{metric_name}"
        cached = redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
        return None


def auto_analyze_anomaly(db: Session, anomaly_data: dict) -> dict:
    """Helper function to trigger analysis"""
    analyzer = RootCauseAnalyzer(db)
    return analyzer.analyze_anomaly(anomaly_data)