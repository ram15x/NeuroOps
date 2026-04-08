from datetime import datetime, timedelta
from enum import Enum
from sqlalchemy.orm import Session
import time
import json
import boto3
import hashlib

from backend.core.config import settings
from backend.core.logger import get_logger
from backend.models.database import HealingAction
from backend.services.redis_service import redis_client
from backend.services.auto_resolve import update_cluster_stats_on_healing

logger = get_logger(__name__)


class HealingActionType(str, Enum):
    RESTART = "restart"
    RESTART_SERVICE = "restart_service"
    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"
    DISK_CLEANUP = "disk_cleanup"
    ROLLBACK = "rollback"
    NOTIFY = "notify"
    NO_ACTION = "no_action"


class HealingDecision:
    """Decides what action to take based on severity, metric type, and context"""

    def __init__(self, service_name: str, severity: str, metric_value: float, metric_type: str = "cpu", context: dict = None):
        self.service_name = service_name
        self.severity = severity
        self.metric_value = metric_value
        self.metric_type = metric_type
        self.context = context or {}
        self.action = None
        self.reason = None
        self.requires_approval = False

    def decide(self):
        """Decision logic with metric type awareness"""

        logger.info(f"HEALING DECISION: service={self.service_name}, severity={self.severity}, "
                   f"value={self.metric_value}, metric_type={self.metric_type}, context={self.context}")

        # Check cooldown
        cooldown_key = f"healing:cooldown:{self.service_name}"
        last_healing = redis_client.get(cooldown_key)

        if last_healing:
            self.action = HealingActionType.NO_ACTION
            self.reason = f"In cooldown period (last healing at {last_healing})"
            logger.info(f"COOLDOWN ACTIVE: {self.reason}")
            return self

        # ========== DISK CLEANUP LOGIC ==========
        if self.metric_type == "disk" and self.metric_value > 90:
            self.action = HealingActionType.DISK_CLEANUP
            self.reason = f"Disk usage critical ({self.metric_value}%) → cleaning up space"
            self.requires_approval = False
            logger.info(f"ACTION: DISK_CLEANUP for {self.service_name}")
            return self

        # ========== MEMORY RESTART LOGIC ==========
        if self.metric_type == "memory" and self.metric_value > 85:
            self.action = HealingActionType.RESTART_SERVICE
            self.reason = f"High memory detected ({self.metric_value}%) → restarting service"
            self.requires_approval = False
            logger.info(f"ACTION: RESTART_SERVICE for {self.service_name}")
            return self

        # ========== SCALE DOWN LOGIC (LOW CPU FOR 7+ DAYS) ==========
        if self.metric_type == "cpu":
            days_low = self.context.get("days_low_cpu", 0)

            if days_low >= 7 and self.metric_value < 20:
                if getattr(settings, 'SCALE_DOWN_ENABLED', True):
                    self.action = HealingActionType.SCALE_DOWN
                    self.reason = f"CPU below 20% for {days_low} days → scaling down to save costs"
                    self.requires_approval = True
                    logger.info(f"ACTION: SCALE_DOWN for {self.service_name}")
                    return self
                else:
                    self.action = HealingActionType.NO_ACTION
                    self.reason = f"Scale down disabled — CPU low for {days_low} days"
                    logger.info(f"SCALE DOWN SKIPPED: {self.reason}")
                    return self

        # ========== CRITICAL SEVERITY ==========
        if self.severity == "critical":
            self.action = HealingActionType.RESTART
            self.reason = f"Critical {self.metric_type} anomaly detected at {self.metric_value}"
            self.requires_approval = False
            logger.info(f"ACTION: RESTART for {self.service_name}")

            if self.context.get("recent_restart_count", 0) >= settings.HEALING_MAX_RETRIES:
                self.action = HealingActionType.SCALE_UP
                self.reason = "Multiple restarts failed, scaling up"
                logger.info(f"ESCALATING: SCALE_UP for {self.service_name}")

        # ========== WARNING SEVERITY ==========
        elif self.severity == "warning":
            self.action = HealingActionType.SCALE_UP
            self.reason = f"Warning threshold crossed for {self.metric_type} at {self.metric_value}"
            self.requires_approval = True
            logger.info(f"ACTION: SCALE_UP for {self.service_name}")

        # ========== NORMAL SEVERITY ==========
        else:
            self.action = HealingActionType.NO_ACTION
            self.reason = f"Normal operation, no action needed"
            logger.info(f"ACTION: NO_ACTION for {self.service_name}")

        return self

    def get_action(self):
        return {
            "action": self.action.value,
            "reason": self.reason,
            "requires_approval": self.requires_approval,
            "service": self.service_name,
            "severity": self.severity,
            "metric_type": self.metric_type,
            "metric_value": self.metric_value
        }


class HealingExecutor:
    """Executes healing actions with real AWS calls"""

    def __init__(self, db: Session):
        self.db = db

    def _calculate_savings(self, old_type: str, new_type: str) -> dict:
        """Calculate estimated monthly savings from downgrade"""
        pricing = {
            't3.large': 0.0832,
            't3.medium': 0.0416,
            't3.small': 0.0208,
            't3.micro': 0.0104,
            't3.nano': 0.0052,
            't2.large': 0.0928,
            't2.medium': 0.0464,
            't2.small': 0.023,
            't2.micro': 0.0116,
            't2.nano': 0.0058,
        }
        
        old_price = pricing.get(old_type, 0)
        new_price = pricing.get(new_type, 0)
        
        if old_price > 0 and new_price > 0:
            hourly_savings = old_price - new_price
            monthly_savings = hourly_savings * 730
            
            return {
                "hourly_savings": round(hourly_savings, 4),
                "monthly_savings": round(monthly_savings, 2),
                "old_price": old_price,
                "new_price": new_price
            }
        
        return {"hourly_savings": 0, "monthly_savings": 0}

    def _store_previous_state(self, instance_id: str, current_type: str) -> dict:
        """Store previous instance state for rollback"""
        try:
            state_key = f"rollback:{instance_id}"
            redis_client.setex(
                state_key,
                86400,
                json.dumps({
                    "instance_type": current_type,
                    "timestamp": datetime.utcnow().isoformat(),
                    "action_taken": "scale"
                })
            )
            logger.info(f"Stored previous state for {instance_id}: {current_type}")
            return {"success": True}
        except Exception as e:
            logger.error(f"Failed to store previous state: {e}")
            return {"success": False, "error": str(e)}

    def _execute_rollback(self, instance_id: str) -> dict:
        """Rollback to previous instance type"""
        try:
            state_key = f"rollback:{instance_id}"
            stored = redis_client.get(state_key)
            
            if not stored:
                return {"success": False, "error": "No previous state found for rollback"}
            
            previous = json.loads(stored)
            previous_type = previous.get("instance_type")
            
            if not previous_type:
                return {"success": False, "error": "Invalid previous state data"}
            
            ec2 = boto3.client(
                "ec2",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )
            
            response = ec2.describe_instances(InstanceIds=[instance_id])
            current_type = response['Reservations'][0]['Instances'][0]['InstanceType']
            
            if current_type == previous_type:
                return {"success": False, "error": f"Already at {current_type}, no rollback needed"}
            
            logger.info(f"Rolling back {instance_id}: {current_type} → {previous_type}")
            
            ec2.stop_instances(InstanceIds=[instance_id])
            ec2.get_waiter('instance_stopped').wait(InstanceIds=[instance_id])
            
            ec2.modify_instance_attribute(
                InstanceId=instance_id,
                Attribute='instanceType',
                Value=previous_type
            )
            
            ec2.start_instances(InstanceIds=[instance_id])
            
            logger.info(f"Waiting for instance {instance_id} to start after rollback...")
            waiter = ec2.get_waiter('instance_running')
            waiter.wait(InstanceIds=[instance_id])
            logger.info(f"Instance {instance_id} is now running as {previous_type}")
            
            redis_client.delete(state_key)
            
            return {
                "success": True,
                "message": f"Rolled back from {current_type} to {previous_type}",
                "old_type": current_type,
                "new_type": previous_type
            }
            
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return {"success": False, "error": str(e)}

    def _verify_healing(self, instance_id: str, metric_before: float, metric_type: str = "cpu") -> dict:
        """Verify if healing action actually worked for different metric types"""
        try:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(minutes=5)
            
            cloudwatch = boto3.client(
                "cloudwatch",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )
            
            if metric_type == "cpu":
                metric_name = "CPUUtilization"
                namespace = "AWS/EC2"
                threshold = 0.7
            elif metric_type == "memory":
                metric_name = "mem_used_percent"
                namespace = "CWAgent"
                threshold = 0.7
            elif metric_type == "disk":
                metric_name = "disk_used_percent"
                namespace = "CWAgent"
                threshold = 0.7
            else:
                return {"verified": False, "reason": "Unknown metric type"}
            
            response = cloudwatch.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=60,
                Statistics=["Average"]
            )
            
            datapoints = sorted(response.get("Datapoints", []), key=lambda x: x["Timestamp"])
            
            if datapoints:
                current_value = datapoints[-1]["Average"]
                improved = current_value < metric_before * threshold if metric_before > 0 else False
                
                return {
                    "verified": improved,
                    "value_before": metric_before,
                    "value_after": current_value,
                    "improvement_pct": round((metric_before - current_value) / metric_before * 100, 1) if metric_before > 0 else 0,
                    "metric_type": metric_type
                }
            
            return {"verified": False, "reason": "No data after healing"}
            
        except Exception as e:
            logger.error(f"Healing verification failed: {e}")
            return {"verified": False, "error": str(e)}

    def _call_aws_restart(self, service_name: str) -> dict:
        """Call AWS to restart EC2 instance"""
        try:
            ec2 = boto3.client(
                "ec2",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )

            if service_name.startswith("i-"):
                ec2.reboot_instances(InstanceIds=[service_name])
                logger.info(f"EC2 reboot initiated for {service_name}")
                return {
                    "success": True,
                    "message": f"EC2 instance {service_name} reboot initiated"
                }
            else:
                return {
                    "success": False,
                    "message": f"Cannot restart {service_name} — not an EC2 instance ID"
                }
        except Exception as e:
            logger.error(f"Failed to restart EC2 {service_name}", error=str(e))
            return {"success": False, "error": str(e)}

    def _call_aws_restart_service(self, service_name: str, service_type: str = "docker") -> dict:
        """Restart a specific service via SSM"""
        try:
            ssm = boto3.client(
                "ssm",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )

            commands = {
                "docker": f"docker restart {service_name} 2>/dev/null || docker restart $(docker ps -q)",
                "nginx": "systemctl restart nginx",
                "systemd": f"systemctl restart {service_name}",
                "python": f"pkill -f {service_name} && cd /opt/app && python3 {service_name}/main.py &",
                "memory_leak": "sudo sh -c 'echo 1 > /proc/sys/vm/drop_caches'"
            }

            command = commands.get(service_type, commands["docker"])
            instance_id = service_name if service_name.startswith("i-") else settings.EC2_INSTANCE_ID

            response = ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName="AWS-RunShellScript",
                Parameters={"commands": [command]}
            )

            logger.info(f"Service restart initiated for {service_name} on {instance_id}")
            return {
                "success": True,
                "message": f"Restarted {service_type} service: {service_name}",
                "command": command,
                "command_id": response.get("Command", {}).get("CommandId")
            }

        except Exception as e:
            logger.error(f"Service restart failed: {e}")
            return {"success": False, "error": str(e)}

    def _call_disk_cleanup(self, instance_id: str) -> dict:
        """Clean up disk space when > 90% full"""
        try:
            ssm = boto3.client(
                "ssm",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )

            commands = [
                "sudo journalctl --vacuum-time=3d",
                f"sudo find {settings.TMP_CLEANUP_PATH} -type f -atime +7 -delete",
                "sudo docker system prune -af --volumes 2>/dev/null || true",
                "sudo rm -rf /var/cache/yum/* 2>/dev/null || true",
                f"sudo find {settings.LOG_CLEANUP_PATH} -name '*.log' -mtime +{settings.LOG_CLEANUP_MAX_AGE_DAYS} -delete 2>/dev/null || true",
            ]

            command = " && ".join(commands)

            response = ssm.send_command(
                InstanceIds=[instance_id],
                DocumentName="AWS-RunShellScript",
                Parameters={"commands": [command]}
            )

            logger.info(f"Disk cleanup initiated for instance {instance_id}")

            return {
                "success": True,
                "message": "Disk cleanup initiated (logs, temp files, Docker cache)",
                "command_id": response.get("Command", {}).get("CommandId")
            }

        except Exception as e:
            logger.error(f"Disk cleanup failed: {e}")
            return {"success": False, "error": str(e)}

    def _call_aws_scale(self, service_name: str, direction: str) -> dict:
        """Call AWS to scale ASG"""
        try:
            asg = boto3.client(
                "autoscaling",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )

            asg_name = None
            current_capacity = 0
            paginator = asg.get_paginator('describe_auto_scaling_groups')
            for page in paginator.paginate():
                for group in page['AutoScalingGroups']:
                    for instance in group['Instances']:
                        if instance['InstanceId'] == service_name:
                            asg_name = group['AutoScalingGroupName']
                            current_capacity = group['DesiredCapacity']
                            break

            if asg_name:
                desired = current_capacity + 1 if direction == "up" else max(1, current_capacity - 1)
                asg.set_desired_capacity(
                    AutoScalingGroupName=asg_name,
                    DesiredCapacity=desired,
                    HonorCooldown=True
                )
                logger.info(f"Scaled ASG {asg_name} from {current_capacity} to {desired}")
                return {
                    "success": True,
                    "message": f"Scaled ASG {asg_name} to {desired} instances"
                }
            else:
                return {"success": False, "message": f"No ASG found for {service_name}"}

        except Exception as e:
            logger.error(f"Failed to scale", error=str(e))
            return {"success": False, "error": str(e)}

    def _call_aws_scale_up_instance(self, instance_id: str) -> dict:
        """Change EC2 instance to next larger type when not in an ASG"""
        try:
            ec2 = boto3.client(
                "ec2",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )
            response = ec2.describe_instances(InstanceIds=[instance_id])
            current_type = response['Reservations'][0]['Instances'][0]['InstanceType']

            upgrade_path = {
                't3.nano': 't3.micro',
                't3.micro': 't3.small',
                't3.small': 't3.medium',
                't3.medium': 't3.large',
                't2.nano': 't2.micro',
                't2.micro': 't2.small',
                't2.small': 't2.medium',
                't2.medium': 't2.large',
            }

            new_type = upgrade_path.get(current_type)
            if not new_type:
                return {"success": False, "error": f"no upgrade path for {current_type}"}

            logger.info(f"scaling up {instance_id}: {current_type} to {new_type}")

            self._store_previous_state(instance_id, current_type)

            ec2.stop_instances(InstanceIds=[instance_id])
            ec2.get_waiter('instance_stopped').wait(InstanceIds=[instance_id])

            ec2.modify_instance_attribute(
                InstanceId=instance_id,
                Attribute='instanceType',
                Value=new_type
            )

            ec2.start_instances(InstanceIds=[instance_id])
            
            logger.info(f"Waiting for instance {instance_id} to start after scale up...")
            waiter = ec2.get_waiter('instance_running')
            waiter.wait(InstanceIds=[instance_id])
            logger.info(f"Instance {instance_id} is now running as {new_type}")

            return {
                "success": True,
                "message": f"scaled up from {current_type} to {new_type}",
                "old_type": current_type,
                "new_type": new_type
            }
        except Exception as e:
            logger.error(f"scale up instance failed: {e}")
            return {"success": False, "error": str(e)}

    def _call_aws_scale_down_instance(self, instance_id: str) -> dict:
        """Change EC2 instance to next smaller type to save costs"""
        try:
            ec2 = boto3.client(
                "ec2",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )
            response = ec2.describe_instances(InstanceIds=[instance_id])
            current_type = response['Reservations'][0]['Instances'][0]['InstanceType']

            downgrade_path = {
                't3.large': 't3.medium',
                't3.medium': 't3.small',
                't3.small': 't3.micro',
                't3.micro': 't3.nano',
                't2.large': 't2.medium',
                't2.medium': 't2.small',
                't2.small': 't2.micro',
                't2.micro': 't2.nano',
            }

            new_type = downgrade_path.get(current_type)
            if not new_type:
                return {"success": False, "error": f"Cannot downgrade {current_type} further (already smallest)"}

            logger.info(f"Scaling down {instance_id}: {current_type} → {new_type}")

            self._store_previous_state(instance_id, current_type)

            ec2.stop_instances(InstanceIds=[instance_id])
            ec2.get_waiter('instance_stopped').wait(InstanceIds=[instance_id])

            ec2.modify_instance_attribute(
                InstanceId=instance_id,
                Attribute='instanceType',
                Value=new_type
            )

            ec2.start_instances(InstanceIds=[instance_id])
            
            logger.info(f"Waiting for instance {instance_id} to start after scale down...")
            waiter = ec2.get_waiter('instance_running')
            waiter.wait(InstanceIds=[instance_id])
            logger.info(f"Instance {instance_id} is now running as {new_type}")

            savings = self._calculate_savings(current_type, new_type)

            return {
                "success": True,
                "message": f"Scaled down from {current_type} to {new_type}",
                "old_type": current_type,
                "new_type": new_type,
                "estimated_savings": savings
            }
        except Exception as e:
            logger.error(f"Scale down failed: {e}")
            return {"success": False, "error": str(e)}

    def execute(self, decision: HealingDecision) -> dict:
        """Execute the healing action with real AWS calls if enabled"""

        action_data = decision.get_action()
        logger.info(f"EXECUTING: action={action_data['action']} for {action_data['service']}, metric_type={action_data['metric_type']}")

        # Set cooldown
        cooldown_key = f"healing:cooldown:{action_data['service']}"
        redis_client.setex(cooldown_key, settings.HEALING_COOLDOWN_MINUTES * 60, datetime.utcnow().isoformat())

        aws_result = {}
        status = "pending"
        message = ""
        rollback_triggered = False
        verification = {"verified": False}

        if settings.AUTO_HEALING_ENABLED:
            if action_data["action"] == "restart":
                aws_result = self._call_aws_restart(action_data["service"])

            elif action_data["action"] == "restart_service":
                service_type = decision.context.get("service_type", "docker")
                aws_result = self._call_aws_restart_service(action_data["service"], service_type)

            elif action_data["action"] == "disk_cleanup":
                aws_result = self._call_disk_cleanup(action_data["service"])

            elif action_data["action"] == "scale_up":
                aws_result = self._call_aws_scale(action_data["service"], "up")
                if not aws_result.get("success") and "No ASG found" in aws_result.get("message", ""):
                    aws_result = self._call_aws_scale_up_instance(action_data["service"])

            elif action_data["action"] == "scale_down":
                if getattr(settings, 'SCALE_DOWN_ENABLED', True):
                    aws_result = self._call_aws_scale_down_instance(action_data["service"])
                else:
                    status = "skipped"
                    message = "Scale down disabled (Free Tier)"
                    aws_result = {"success": False, "error": "Scale down disabled for Free Tier"}

            else:
                status = "skipped"
                message = f"No action needed for {action_data['action']}"

            if status == "pending":
                status = "completed" if aws_result.get("success") else "failed"
                message = aws_result.get("message", aws_result.get("error", "Unknown error"))

            # ========== HEALING VERIFICATION ==========
            if status == "completed" and action_data["action"] in ["restart", "scale_up", "scale_down", "restart_service", "disk_cleanup"]:
                logger.info(f"Waiting 30 seconds for healing to take effect...")
                time.sleep(30)
                
                verification = self._verify_healing(
                    action_data["service"], 
                    action_data["metric_value"], 
                    action_data["metric_type"]
                )
                
                if verification.get("verified"):
                    logger.info(f"Healing SUCCESSFUL for {action_data['service']}: {verification.get('improvement_pct')}% improvement")
                    message += f" Verified: {verification.get('improvement_pct')}% improvement"
                else:
                    logger.warning(f"Healing MAY HAVE FAILED for {action_data['service']}: {verification.get('reason', 'No verification')}")
                    message += f" Unverified: {verification.get('reason', 'No improvement detected')}"
                    
                    # ========== AUTO ROLLBACK ON FAILURE ==========
                    if action_data["action"] in ["scale_up", "scale_down", "restart_service"]:
                        logger.info(f"Healing failed, triggering automatic rollback for {action_data['service']}...")
                        rollback_result = self._execute_rollback(action_data["service"])
                        if rollback_result.get("success"):
                            rollback_triggered = True
                            message += f" Auto-rollback executed: {rollback_result.get('message')}"
                        else:
                            message += f" Auto-rollback failed: {rollback_result.get('error')}"

                # ========== AUTO-RESOLVE INTEGRATION ==========
                # Update cluster stats for auto-resolve tracking
                try:
                    cluster_id = decision.context.get("cluster_id")
                    if not cluster_id and action_data["service"]:
                        pattern = f"{action_data['service']}_{action_data['metric_type']}_{action_data['reason'][:50]}"
                        cluster_id = f"cluster_{hashlib.md5(pattern.encode()).hexdigest()[:16]}"
                    
                    auto_resolve_result = update_cluster_stats_on_healing(
                        cluster_id=cluster_id,
                        healing_success=verification.get("verified", False),
                        db=self.db
                    )
                    
                    if auto_resolve_result.get("auto_resolved"):
                        logger.info(f"AUTO-RESOLVED: Cluster {cluster_id} marked as resolved")
                        message += f" Auto-resolved: This issue will not page on-call next time"
                        
                        if hasattr(self, 'healing_action'):
                            self.healing_action.details["auto_resolved"] = True
                            self.healing_action.details["auto_resolve_result"] = auto_resolve_result
                            self.db.commit()
                            
                except Exception as e:
                    logger.error(f"Auto-resolve integration failed: {e}")
                
                aws_result["verification"] = verification

        else:
            status = "simulated"
            message = f"[SIMULATION] Would execute: {action_data['action']} on {action_data['service']} (metric_type={action_data['metric_type']})"
            aws_result = {}

        result = {
            "status": status,
            "action": action_data["action"],
            "reason": action_data["reason"],
            "service": action_data["service"],
            "message": message,
            "rollback_triggered": rollback_triggered,
            "metric_type": action_data["metric_type"],
            "metric_value": action_data["metric_value"],
            **aws_result
        }

        # Store in database
        healing_action = HealingAction(
            service_name=action_data["service"],
            severity=action_data["severity"],
            action_taken=action_data["action"],
            status=status,
            triggered_by="auto",
            details={
                "reason": action_data["reason"],
                "metric_value": action_data["metric_value"],
                "metric_type": action_data["metric_type"],
                "requires_approval": action_data["requires_approval"],
                "aws_result": aws_result,
                "rollback_triggered": rollback_triggered,
                "verification": verification
            },
            created_at=datetime.utcnow(),
            completed_at=datetime.utcnow() if status in ["completed", "failed"] else None
        )
        self.db.add(healing_action)
        self.db.commit()
        
        self.healing_action = healing_action

        return result

    def manual_rollback(self, service_name: str, previous_action_id: int = None) -> dict:
        """Manual rollback for an instance"""
        result = self._execute_rollback(service_name)

        healing_action = HealingAction(
            service_name=service_name,
            severity="critical",
            action_taken="rollback",
            status="completed" if result.get("success") else "failed",
            triggered_by="manual",
            details={
                "previous_action_id": previous_action_id,
                "rollback_result": result
            },
            created_at=datetime.utcnow(),
            completed_at=datetime.utcnow()
        )
        self.db.add(healing_action)
        self.db.commit()

        return result