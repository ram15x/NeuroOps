import threading
import time
from datetime import timezone
import json
from datetime import datetime
from backend.core.config import settings
from backend.core.logger import get_logger
from backend.services.aws_service import fetch_cloudwatch_metrics, list_ec2_instances, send_sns_alert, get_ec2_status_checks, fetch_ec2_memory_metrics, fetch_ec2_disk_metrics
from backend.services.redis_service import redis_client
from backend.services.inframind_caller import analyze_metric
from backend.services.autohealing_service import trigger_auto_healing
from backend.services.failure_predictor import predict_failure_from_status
from backend.services.rul_predictor import predict_rul
from backend.models.database import SessionLocal, Alert, PredictionHistory, MetricHistory
from backend.services.healing_executor import HealingDecision, HealingExecutor

logger = get_logger(__name__)

_analyzer_running = False
_analyzer_thread = None


def run_correlation_check(db, instance_id: str, cpu_value: float):
    """run correlation check between multiple services every 5 minutes"""
    try:
        from backend.services.failure_correlator import correlate_failures
        from backend.models.schemas import ServiceSensorInput, CorrelationRequest

        services = [
            ServiceSensorInput(service_name="payment-service", sensors=[cpu_value]),
            ServiceSensorInput(service_name="auth-service", sensors=[cpu_value]),
            ServiceSensorInput(service_name="api-gateway", sensors=[cpu_value]),
            ServiceSensorInput(service_name="database-proxy", sensors=[cpu_value]),
        ]

        request = CorrelationRequest(services=services)
        result = correlate_failures(request)

        redis_client.setex(f"correlation:{instance_id}", 300, json.dumps(result))

        if result.get("is_correlated_failure"):
            logger.warning(f"CORRELATED FAILURE: {result.get('services_in_danger')} services at risk")

    except Exception as e:
        logger.error(f"Correlation check failed: {e}")


def process_metric(db, instance_id: str, cpu_value: float, timestamp: str):
    """Analyze a single metric with independent fail-safe stages"""
    
    # Initialize results
    infra_result = None
    failure_result = None
    rul_result = None
    healing_result = None
    memory_percent = 0
    disk_percent = 0
    status_ok = True
    recent_reboots = 0
    age_days = 30
    rolling_mean = cpu_value
    rolling_std = 0
    value_diff = 0
    days_low_cpu = 0
    
    # ========== FETCH MEMORY AND DISK FIRST (BEFORE ALERT) ==========
    try:
        memory_data = fetch_ec2_memory_metrics(instance_id, minutes=5)
        if memory_data:
            memory_percent = memory_data[-1]["value"]
            redis_client.setex(f"memory:{instance_id}", 300, str(memory_percent))
        
        disk_data = fetch_ec2_disk_metrics(instance_id, minutes=5)
        if disk_data:
            disk_percent = disk_data[-1]["value"]
            redis_client.setex(f"disk:{instance_id}", 300, str(disk_percent))
            
        logger.info(f"Memory: {memory_percent}%, Disk: {disk_percent}%")
        
        # Store memory/disk history
        if memory_percent > 0:
            mem_history = MetricHistory(
                instance_id=instance_id,
                metric_name="memory",
                value=memory_percent,
                timestamp=datetime.utcnow(),
                source="custom"
            )
            db.add(mem_history)
        if disk_percent > 0:
            disk_history = MetricHistory(
                instance_id=instance_id,
                metric_name="disk",
                value=disk_percent,
                timestamp=datetime.utcnow(),
                source="custom"
            )
            db.add(disk_history)
    except Exception as e:
        logger.error(f"Failed to fetch memory/disk metrics: {e}")
    
    try:
        # Get history from Redis
        cache_key = f"cpu_history:{instance_id}"
        history = redis_client.lrange(cache_key, 0, 4)
        history = [float(x) for x in history if x]
        
        # Add current value
        history.append(cpu_value)
        if len(history) > 5:
            history = history[-5:]
        
        # Store updated history
        redis_client.delete(cache_key)
        for val in history:
            redis_client.lpush(cache_key, val)
        redis_client.ltrim(cache_key, 0, 4)
        
        # Calculate rolling stats
        import numpy as np
        rolling_mean = float(np.mean(history)) if len(history) >= 3 else cpu_value
        rolling_std = float(np.std(history)) if len(history) >= 3 else 0.0
        value_diff = float(cpu_value - (history[-2] if len(history) >= 2 else cpu_value))
        
        # ========== STAGE 1: STORE METRIC HISTORY ==========
        try:
            metric_history = MetricHistory(
                instance_id=instance_id,
                metric_name="cpu",
                value=cpu_value,
                timestamp=datetime.utcnow(),
                source="cloudwatch"
            )
            db.add(metric_history)
            db.flush()
            logger.debug(f"Stored CPU history: {cpu_value}%")
        except Exception as e:
            logger.error(f"Metric history storage failed: {e}")
        
        # ========== STAGE 2: INFRA MIND (Anomaly Detection) ==========
        try:
            result = analyze_metric(
                metric_name=f"ec2_{instance_id}_cpu",
                value=cpu_value,
                rolling_mean=rolling_mean,
                rolling_std=rolling_std,
                value_diff=value_diff
            )
            infra_result = result
            logger.info(f"InfraMind result: score={result['anomaly_score']}, is_anomaly={result['is_anomaly']}, severity={result['severity']}")
            
            # Store alert
            alert = Alert(
                metric_value=cpu_value,
                rolling_mean=rolling_mean,
                rolling_std=rolling_std,
                value_diff=value_diff,
                is_anomaly=result["is_anomaly"],
                severity=result["severity"],
                anomaly_score=float(result["anomaly_score"]),
                message=f"EC2 {instance_id} CPU: {cpu_value}%"
            )
            db.add(alert)
        except Exception as e:
            logger.error(f"InfraMind stage failed: {e}")
            infra_result = {"is_anomaly": False, "severity": "normal", "anomaly_score": 0}
        
        # ========== FETCH STATUS CHECKS ==========
        try:
            status_data = get_ec2_status_checks(instance_id)
            status_ok = status_data.get("is_healthy", False)
            reboot_key = f"reboot_count:{instance_id}"
            recent_reboots = int(redis_client.get(reboot_key) or 0)
            instances = list_ec2_instances()
            for inst in instances:
                if inst.get("instance_id") == instance_id:
                    if inst.get("launch_time"):
                        try:
                            launch_time_str = inst["launch_time"].replace('Z', '+00:00')
                            launch_date = datetime.fromisoformat(launch_time_str)
                            now = datetime.now(timezone.utc)
                            age_days = (now - launch_date).days
                            logger.info(f"Instance age calculated: {age_days} days")
                        except Exception as e:
                            logger.error(f"Failed to parse launch_time: {e}")
        except Exception as e:
            logger.warning(f"Failed to get status data: {e}")
        
        # ========== TRACK LOW CPU DAYS FOR SCALE DOWN ==========
        low_cpu_key = f"low_cpu_days:{instance_id}"
        if cpu_value < 20:
            days_low = redis_client.incr(low_cpu_key)
            redis_client.expire(low_cpu_key, 7 * 86400)
            logger.debug(f"CPU low for {days_low} consecutive days for {instance_id}")
        else:
            redis_client.delete(low_cpu_key)
            days_low = 0
        
        # ========== STAGE 3: FAILURE PREDICTION ==========
        try:
            prediction = predict_failure_from_status(
                cpu_usage=cpu_value,
                status_check_ok=status_ok,
                recent_reboots=recent_reboots,
                instance_age_days=age_days,
                memory_usage=memory_percent,
                disk_usage=disk_percent
            )
            failure_result = prediction
            
            redis_client.setex(
                f"failure_prediction:{instance_id}",
                300,
                json.dumps({
                    "will_fail_soon": prediction["will_fail_soon"],
                    "failure_probability": prediction["failure_probability"],
                    "risk_level": prediction["risk_level"],
                    "action": prediction["action"],
                    "reason": prediction.get("reason", ""),
                    "timestamp": datetime.utcnow().isoformat()
                })
            )
            
            pred_history = PredictionHistory(
                model_name="failure_predictor",
                input_features={
                    "cpu": cpu_value,
                    "memory": memory_percent,
                    "disk": disk_percent,
                    "status_ok": status_ok,
                    "recent_reboots": recent_reboots,
                    "instance_age_days": age_days
                },
                prediction={
                    "will_fail": prediction["will_fail_soon"],
                    "probability": prediction["failure_probability"],
                    "risk": prediction["risk_level"]
                },
                created_at=datetime.utcnow()
            )
            db.add(pred_history)
            
            logger.info(f"Failure prediction: {prediction['risk_level']} ({prediction['failure_probability']}%) with real memory={memory_percent}%, disk={disk_percent}%")
            
            # SNS ALERT BLOCK REMOVED - Now handled by InfraMind critical anomalies only
            
        except Exception as e:
            logger.error(f"Failure prediction stage failed: {e}")
            failure_result = {"risk_level": "UNKNOWN", "failure_probability": 0}
        
        # ========== STAGE 4: RUL COUNTDOWN ==========
        try:
            sensor_values = [
                cpu_value, 1.0 if status_ok else 0.0, recent_reboots, age_days,
                memory_percent, disk_percent, rolling_mean, rolling_std, value_diff,
                float(infra_result.get("anomaly_score", 0)),
                14.62, 21.61, 553.69, 2388.09, 9050.17, 1.3, 47.28, 521.72,
                2388.09, 8138.62, 8.42, 0.03, 392.0, 2388.0
            ][:24]
            
            rul_result = predict_rul(sensor_values)
            
            redis_client.setex(
                f"rul_prediction:{instance_id}",
                300,
                json.dumps({
                    "cycles_remaining": rul_result["cycles_remaining"],
                    "hours_remaining": rul_result["hours_remaining"],
                    "urgency": rul_result["urgency"],
                    "recommendation": rul_result["recommendation"],
                    "lower_bound": rul_result.get("lower_bound"),
                    "upper_bound": rul_result.get("upper_bound"),
                    "confidence_pct": rul_result.get("confidence_pct", 80),
                    "timestamp": datetime.utcnow().isoformat()
                })
            )
            
            logger.info(f"Auto RUL: {rul_result['cycles_remaining']} cycles, urgency={rul_result['urgency']}")
            
            # RUL CRITICAL SNS BLOCK REMOVED - Now handled by InfraMind critical anomalies only
            
        except Exception as e:
            logger.error(f"RUL stage failed: {e}")
            rul_result = {"cycles_remaining": None, "urgency": "UNKNOWN"}
        
        # ========== STAGE 5: FEATURE STORE ==========
        try:
            from backend.services.feature_store import store_features
            
            store_features(
                entity_id=instance_id,
                features={
                    "cpu": cpu_value,
                    "memory": memory_percent,
                    "disk": disk_percent,
                    "anomaly_score": infra_result.get("anomaly_score", 0),
                    "is_anomaly": infra_result.get("is_anomaly", False),
                    "failure_risk": failure_result.get("risk_level", "NORMAL"),
                    "failure_probability": failure_result.get("failure_probability", 0),
                    "rul_cycles": rul_result.get("cycles_remaining", 0),
                    "status_ok": status_ok,
                    "recent_reboots": recent_reboots,
                    "days_low_cpu": days_low,
                    "timestamp": datetime.utcnow().isoformat()
                },
                entity_type="ec2"
            )
            logger.debug(f"Features stored for {instance_id}")
        except Exception as e:
            logger.error(f"Feature store failed: {e}")
        
        # ========== STAGE 6: AUTO-HEALING ==========
        try:
            if days_low >= 7 and cpu_value < 20:
                logger.info(f"LOW CPU for {days_low} days on {instance_id} → triggering scale down")
                context = {"metric_type": "cpu", "recent_restart_count": 0, "days_low_cpu": days_low}
                decision = HealingDecision(instance_id, "normal", cpu_value, context).decide()
                executor = HealingExecutor(db)
                healing_result = executor.execute(decision)
                logger.info(f"Scale down result: {healing_result}")
            
            elif memory_percent > 90:
                logger.info(f"HIGH MEMORY on {instance_id}: {memory_percent}% → triggering service restart")
                context = {"metric_type": "memory", "service_type": "docker", "recent_restart_count": 0}
                decision = HealingDecision(instance_id, "critical", memory_percent, context).decide()
                executor = HealingExecutor(db)
                healing_result = executor.execute(decision)
                logger.info(f"Memory healing result: {healing_result}")
            
            elif disk_percent > 95:
                logger.info(f"HIGH DISK on {instance_id}: {disk_percent}% → triggering disk cleanup")
                context = {"metric_type": "disk", "recent_restart_count": 0}
                decision = HealingDecision(instance_id, "critical", disk_percent, context).decide()
                executor = HealingExecutor(db)
                healing_result = executor.execute(decision)
                logger.info(f"Disk healing result: {healing_result}")
            
            elif infra_result.get("is_anomaly"):
                logger.info(f"CPU ANOMALY on {instance_id}: {cpu_value}%")
                context = {"metric_type": "cpu", "recent_restart_count": 0}
                decision = HealingDecision(instance_id, infra_result.get("severity", "critical"), cpu_value, context).decide()
                executor = HealingExecutor(db)
                healing_result = executor.execute(decision)
                logger.info(f"CPU healing result: {healing_result}")
                
        except Exception as e:
            logger.error(f"Auto-healing stage failed: {e}")
        
        # ========== STAGE 7: CORRELATION ==========
        try:
            if int(time.time()) % 300 < 60:
                run_correlation_check(db, instance_id, cpu_value)
        except Exception as e:
            logger.error(f"Correlation stage failed: {e}")
        
        # Log summary
        logger.info(f"Stage summary for {instance_id}: Infra={infra_result.get('is_anomaly')}, "
                   f"Failure={failure_result.get('risk_level')}, "
                   f"RUL={rul_result.get('cycles_remaining')}, "
                   f"Memory={memory_percent}%, Disk={disk_percent}%, "
                   f"Days Low CPU={days_low}, "
                   f"Healing={healing_result.get('status') if healing_result else 'none'}")
        
        db.commit()
        return infra_result
        
    except Exception as e:
        logger.error(f"Process metric outer wrapper failed: {e}")
        db.rollback()
        return None


def analyze_and_store_metrics():
    """Fetch metrics from CloudWatch with rate limiting"""
    db = SessionLocal()
    try:
        instances = list_ec2_instances()
        running_instances = [i for i in instances if i.get("state") == "running"]
        
        if not running_instances:
            logger.info("No running EC2 instances found")
            return
        
        instances_to_process = running_instances[:settings.MAX_INSTANCES_PER_RUN]
        
        for idx, instance in enumerate(instances_to_process):
            instance_id = instance["instance_id"]
            
            if idx > 0:
                time.sleep(settings.ANALYZER_RETRY_DELAY)
            
            metrics = fetch_cloudwatch_metrics(instance_id, minutes=5)
            cpu_data = metrics.get("CPUUtilization", [])
            
            if cpu_data:
                latest = cpu_data[-1]
                cpu_value = latest["value"]
                timestamp = latest["timestamp"]
                
                process_metric(db, instance_id, cpu_value, timestamp)
                
                redis_client.setex(f"real_cpu:{instance_id}", 300, str(cpu_value))
                
                logger.info(
                    f"Analyzed {instance_id}: CPU={cpu_value}%",
                    instance_id=instance_id,
                    cpu=cpu_value
                )
                
    except Exception as e:
        logger.error("Metrics analysis failed", error=str(e))
    finally:
        db.close()


def analyzer_loop(interval_seconds: int = 60):
    """Background thread with health monitoring"""
    global _analyzer_running
    
    logger.info(f"Metrics analyzer started, interval={interval_seconds}s")
    
    loop_count = 0
    consecutive_failures = 0
    max_consecutive_failures = 5
    
    while _analyzer_running:
        try:
            analyze_and_store_metrics()
            loop_count += 1
            consecutive_failures = 0
            
            if loop_count % 100 == 0:
                logger.info(f"Analyzer healthy checkpoint: {loop_count} cycles completed")
                
        except Exception as e:
            consecutive_failures += 1
            logger.error(f"Analyzer error (attempt {consecutive_failures}/{max_consecutive_failures}): {e}")
            
            if consecutive_failures >= max_consecutive_failures:
                logger.critical(f"Analyzer failed {max_consecutive_failures} times consecutively! Sending alert...")
                try:
                    crash_message = f"""
NEUROOPS ANALYZER CRASHED
The metrics analyzer has failed {max_consecutive_failures} times consecutively.
Manual intervention required.

Please check:
1. AWS credentials
2. EC2 instance status
3. Redis connection
4. Database connection

Dashboard: {settings.DASHBOARD_URL}/index.html
"""
                    send_sns_alert(
                        subject="NEUROOPS ANALYZER CRASHED",
                        message=crash_message
                    )
                except:
                    pass
                consecutive_failures = max_consecutive_failures - 1
        
        time.sleep(interval_seconds)


def start_metrics_analyzer(interval_seconds: int = 60):
    """Start the background analyzer thread"""
    global _analyzer_running, _analyzer_thread
    
    if _analyzer_running:
        logger.info("Metrics analyzer already running")
        return
    
    _analyzer_running = True
    _analyzer_thread = threading.Thread(
        target=analyzer_loop,
        args=(interval_seconds,),
        daemon=True
    )
    _analyzer_thread.start()
    logger.info("Metrics analyzer thread started")


def stop_metrics_analyzer():
    """Stop the background analyzer"""
    global _analyzer_running
    _analyzer_running = False
    logger.info("Metrics analyzer stopped")