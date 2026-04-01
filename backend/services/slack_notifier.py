import requests
import json
from datetime import datetime
from typing import Optional

from backend.core.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)


class SlackNotifier:
    """Send incident alerts to Slack"""

    def __init__(self):
        self.webhook_url = settings.SLACK_WEBHOOK_URL
        self.enabled = settings.SLACK_NOTIFICATIONS_ENABLED

    def send_incident_alert(
        self,
        incident_id: int,
        title: str,
        severity: str,
        service_name: str,
        cpu_value: float,
        root_cause: str,
        recommendation: str,
        instance_id: str = None
    ) -> bool:
        """Send incident alert to Slack"""

        if not self.enabled or not self.webhook_url:
            logger.info("Slack notifications disabled or no webhook URL")
            return False

        # Color based on severity
        colors = {
            "critical": "#ff4444",
            "warning": "#ffaa00",
            "normal": "#00ff88"
        }
        color = colors.get(severity, "#ff4444")

        # Emoji based on severity
        emojis = {
            "critical": "🚨",
            "warning": "⚠️",
            "normal": "ℹ️"
        }
        emoji = emojis.get(severity, "🔔")

        # Build message
        message = {
            "attachments": [
                {
                    "color": color,
                    "title": f"{emoji} {severity.upper()} Incident: {title}",
                    "fields": [
                        {
                            "title": "Instance",
                            "value": instance_id or service_name,
                            "short": True
                        },
                        {
                            "title": "CPU",
                            "value": f"{cpu_value:.1f}%",
                            "short": True
                        },
                        {
                            "title": "Incident ID",
                            "value": str(incident_id),
                            "short": True
                        },
                        {
                            "title": "Time",
                            "value": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                            "short": True
                        },
                        {
                            "title": "Root Cause",
                            "value": root_cause[:500] if root_cause else "Analysis in progress...",
                            "short": False
                        },
                        {
                            "title": "Recommendation",
                            "value": recommendation[:500] if recommendation else "Check logs manually",
                            "short": False
                        }
                    ],
                    "footer": "NeuroOps Auto-Healing Platform",
                    "footer_icon": "https://img.icons8.com/color/48/000000/artificial-intelligence.png",
                    "ts": int(datetime.utcnow().timestamp())
                }
            ]
        }

        try:
            response = requests.post(
                self.webhook_url,
                data=json.dumps(message),
                headers={"Content-Type": "application/json"},
                timeout=5
            )
            
            if response.status_code == 200:
                logger.info(f"Slack alert sent for incident {incident_id}")
                return True
            else:
                logger.error(f"Slack alert failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Slack notification error: {e}")
            return False

    def send_test_message(self) -> bool:
        """Send a test message to verify Slack webhook"""
        
        test_message = {
            "text": "🧪 *NeuroOps Test Message*\n\nYour Slack integration is working correctly!"
        }
        
        try:
            response = requests.post(
                self.webhook_url,
                data=json.dumps(test_message),
                headers={"Content-Type": "application/json"},
                timeout=5
            )
            
            if response.status_code == 200:
                logger.info("Slack test message sent successfully")
                return True
            else:
                logger.error(f"Slack test failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Slack test error: {e}")
            return False


# Singleton instance
_slack_notifier = None


def get_slack_notifier() -> SlackNotifier:
    global _slack_notifier
    if _slack_notifier is None:
        _slack_notifier = SlackNotifier()
    return _slack_notifier