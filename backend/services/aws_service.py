import boto3
import json
import os
import time
from functools import wraps
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from backend.core.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

# Rate limiting setup
_rate_limit_tracker = defaultdict(list)
RATE_LIMIT_PER_MINUTE = 60  # Max 60 calls per minute
RATE_LIMIT_PER_HOUR = 1000  # Max 1000 calls per hour

def rate_limit(limit_per_minute: int = 60, limit_per_hour: int = 1000):
    """Decorator for rate limiting AWS API calls"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            now = time.time()
            minute_ago = now - 60
            hour_ago = now - 3600
            
            # Clean old entries (keep last hour for hour limit check)
            _rate_limit_tracker[func.__name__] = [
                t for t in _rate_limit_tracker[func.__name__] 
                if t > hour_ago
            ]
            
            # Check minute limit
            minute_calls = len([t for t in _rate_limit_tracker[func.__name__] if t > minute_ago])
            if minute_calls >= limit_per_minute:
                logger.warning(f"Rate limit exceeded for {func.__name__}: {minute_calls}/{limit_per_minute} per minute")
                raise Exception(f"Rate limit exceeded for {func.__name__}. Please wait before retrying.")
            
            # Check hour limit
            if len(_rate_limit_tracker[func.__name__]) >= limit_per_hour:
                logger.warning(f"Hourly rate limit exceeded for {func.__name__}: {len(_rate_limit_tracker[func.__name__])}/{limit_per_hour}")
                raise Exception(f"Hourly rate limit exceeded for {func.__name__}. Please try again later.")
            
            _rate_limit_tracker[func.__name__].append(now)
            return func(*args, **kwargs)
        return wrapper
    return decorator


def get_ec2_client():
    return boto3.client(
        "ec2",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION
    )


def get_cloudwatch_client():
    return boto3.client(
        "cloudwatch",
        aws_access_key_id     = settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key = settings.AWS_SECRET_ACCESS_KEY,
        region_name           = settings.AWS_REGION,
    )


def get_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id     = settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key = settings.AWS_SECRET_ACCESS_KEY,
        region_name           = settings.AWS_REGION,
    )


def get_sns_client():
    return boto3.client(
        "sns",
        aws_access_key_id     = settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key = settings.AWS_SECRET_ACCESS_KEY,
        region_name           = settings.AWS_REGION,
    )


@rate_limit()
def fetch_cloudwatch_metrics(instance_id: str, minutes: int = 60) -> dict:
    """
    fetch cpu, network in/out, disk read/write for a given ec2 instance.
    returns a dict with metric name -> list of (timestamp, value) datapoints.
    """
    try:
        client = get_cloudwatch_client()
    except Exception as e:
        logger.error(f"Failed to get CloudWatch client: {e}")
        return {
            "CPUUtilization": [],
            "NetworkIn": [],
            "NetworkOut": [],
            "DiskReadBytes": [],
            "DiskWriteBytes": []
        }
    
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(minutes=minutes)

    metric_queries = [
        {"name": "CPUUtilization", "namespace": "AWS/EC2", "stat": "Average", "unit": "Percent"},
        {"name": "NetworkIn", "namespace": "AWS/EC2", "stat": "Sum", "unit": "Bytes"},
        {"name": "NetworkOut", "namespace": "AWS/EC2", "stat": "Sum", "unit": "Bytes"},
        {"name": "DiskReadBytes", "namespace": "AWS/EC2", "stat": "Sum", "unit": "Bytes"},
        {"name": "DiskWriteBytes", "namespace": "AWS/EC2", "stat": "Sum", "unit": "Bytes"},
    ]

    results = {}
    for mq in metric_queries:
        try:
            response = client.get_metric_statistics(
                Namespace=mq["namespace"],
                MetricName=mq["name"],
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=300,
                Statistics=[mq["stat"]],
                Unit=mq["unit"],
            )
            datapoints = sorted(response.get("Datapoints", []), key=lambda x: x["Timestamp"])
            results[mq["name"]] = [
                {"timestamp": dp["Timestamp"].isoformat(), "value": dp[mq["stat"]]}
                for dp in datapoints
            ]
        except Exception as e:
            logger.warning(f"CloudWatch metric {mq['name']} failed: {e}")
            results[mq["name"]] = []

    return results


@rate_limit()
def list_ec2_instances() -> list:
    """
    list all ec2 instances in the account with id, name, state, type.
    uses ec2 client, not cloudwatch.
    """
    try:
        ec2 = boto3.client(
            "ec2",
            aws_access_key_id     = settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key = settings.AWS_SECRET_ACCESS_KEY,
            region_name           = settings.AWS_REGION,
        )
        response  = ec2.describe_instances()
        instances = []

        for reservation in response.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                name = ""
                for tag in inst.get("Tags", []):
                    if tag["Key"] == "Name":
                        name = tag["Value"]
                        break
                instances.append({
                    "instance_id"   : inst["InstanceId"],
                    "name"          : name,
                    "state"         : inst["State"]["Name"],
                    "instance_type" : inst["InstanceType"],
                    "launch_time"   : inst["LaunchTime"].isoformat(),
                })

        return instances
    except Exception as e:
        logger.error(f"ec2 list failed: {e}")
        return []


@rate_limit()
def upload_model_to_s3(local_path: str, s3_key: str) -> dict:
    """
    upload a local .pkl file to s3 bucket.
    s3_key example: 'models/inframind_model.pkl'
    """
    client = get_s3_client()
    try:
        client.upload_file(local_path, settings.S3_BUCKET, s3_key)
        url = f"https://{settings.S3_BUCKET}.s3.{settings.AWS_REGION}.amazonaws.com/{s3_key}"
        logger.info(f"uploaded {local_path} to s3://{settings.S3_BUCKET}/{s3_key}")
        return {"success": True, "s3_key": s3_key, "url": url}
    except Exception as e:
        logger.error(f"s3 upload failed: {e}")
        return {"success": False, "error": str(e)}

@rate_limit()
def send_sns_alert_with_timeline(subject: str, message: str, alert_id: int = None, timeline: dict = None) -> dict:
    """
    Publish an alert message with root cause timeline included.
    Used when critical anomaly is detected.
    """
    client = get_sns_client()
    
    # Enrich message with timeline if provided
    if timeline and alert_id and "error" not in timeline:
        enriched_message = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚨 NEUROOPS ALERT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{message}

━━━━━━━━━━━━━━━━━━━━━━
🔍 ROOT CAUSE TIMELINE
━━━━━━━━━━━━━━━━━━━━━━

📌 Root Cause: {timeline.get('root_cause', 'Unknown')}
🎯 Confidence: {timeline.get('confidence', 0)}%

📊 Event Timeline:
"""
        # Add top 5 events
        for event in timeline.get('timeline', [])[:5]:
            enriched_message += f"   • {event['time_relative']}: {event['description']}\n"
        
        enriched_message += f"""
━━━━━━━━━━━━━━━━━━━━━━
💡 Recommendation
━━━━━━━━━━━━━━━━━━━━━━
{timeline.get('recommendation', 'Manual investigation required')}

━━━━━━━━━━━━━━━━━━━━━━
🔗 View full timeline: {settings.DASHBOARD_URL}/rootcause/{alert_id}
━━━━━━━━━━━━━━━━━━━━━━
"""
        message = enriched_message
    
    try:
        response = client.publish(
            TopicArn=settings.SNS_TOPIC_ARN,
            Subject=subject[:100],
            Message=message,
        )
        message_id = response.get("MessageId", "")
        logger.info(f"SNS alert sent with timeline: {message_id}")
        return {"success": True, "message_id": message_id}
    except Exception as e:
        logger.error(f"SNS publish failed: {e}")
        return {"success": False, "error": str(e)}
@rate_limit()
def download_model_from_s3(s3_key: str, local_path: str) -> dict:
    """
    download a model from s3 to local path.
    """
    client = get_s3_client()
    try:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        client.download_file(settings.S3_BUCKET, s3_key, local_path)
        logger.info(f"downloaded s3://{settings.S3_BUCKET}/{s3_key} to {local_path}")
        return {"success": True, "local_path": local_path}
    except Exception as e:
        logger.error(f"s3 download failed: {e}")
        return {"success": False, "error": str(e)}


@rate_limit()
def list_s3_models() -> list:
    """
    list all objects in the s3 bucket under models/ prefix.
    """
    client = get_s3_client()
    try:
        response = client.list_objects_v2(
            Bucket = settings.S3_BUCKET,
            Prefix = "models/"
        )
        objects = []
        for obj in response.get("Contents", []):
            objects.append({
                "key"           : obj["Key"],
                "size_kb"       : round(obj["Size"] / 1024, 2),
                "last_modified" : obj["LastModified"].isoformat(),
            })
        return objects
    except Exception as e:
        logger.error(f"s3 list failed: {e}")
        return []


@rate_limit()
def send_sns_alert(subject: str, message: str) -> dict:
    """
    publish an alert message to the sns topic.
    used when critical anomaly is detected.
    """
    client = get_sns_client()
    try:
        response = client.publish(
            TopicArn = settings.SNS_TOPIC_ARN,
            Subject  = subject[:100],  # sns subject limit is 100 chars
            Message  = message,
        )
        message_id = response.get("MessageId", "")
        logger.info(f"sns alert sent: {message_id}")
        return {"success": True, "message_id": message_id}
    except Exception as e:
        logger.error(f"sns publish failed: {e}")
        return {"success": False, "error": str(e)}


def check_aws_connection() -> dict:
    """
    verify that all three aws clients can connect.
    returns status per service.
    """
    status = {
        "cloudwatch" : False,
        "s3"         : False,
        "sns"        : False,
        "region"     : settings.AWS_REGION,
        "bucket"     : settings.S3_BUCKET,
    }
    
    #check cloudWatch
    try:
        cw = get_cloudwatch_client()
        cw.list_metrics(Namespace="AWS/EC2")
        status["cloudwatch"] = True
    except Exception as e:
        logger.warning(f"cloudwatch check failed: {e}")

    # check s3
    try:
        s3 = get_s3_client()
        s3.head_bucket(Bucket=settings.S3_BUCKET)
        status["s3"] = True
    except Exception as e:
        logger.warning(f"s3 check failed: {e}")

    # check sns
    try:
        sns = get_sns_client()
        sns.get_topic_attributes(TopicArn=settings.SNS_TOPIC_ARN)
        status["sns"] = True
    except Exception as e:
        logger.warning(f"sns check failed: {e}")

    status["all_connected"] = all([
        status["cloudwatch"],
        status["s3"],
        status["sns"],
    ])

    return status


@rate_limit()
def get_ec2_status_checks(instance_id: str) -> dict:
    """Fetch EC2 status check results (instance reachability)"""
    try:
        ec2 = get_ec2_client()
        response = ec2.describe_instance_status(
            InstanceIds=[instance_id],
            IncludeAllInstances=True
        )
        
        if response.get('InstanceStatuses'):
            status = response['InstanceStatuses'][0]
            return {
                "instance_status": status.get('InstanceStatus', {}).get('Status', 'unknown'),
                "system_status": status.get('SystemStatus', {}).get('Status', 'unknown'),
                "details": status.get('InstanceStatus', {}).get('Details', []),
                "is_healthy": status.get('InstanceStatus', {}).get('Status') == 'ok' and
                              status.get('SystemStatus', {}).get('Status') == 'ok'
            }
        else:
            return {
                "instance_status": "unknown",
                "system_status": "unknown",
                "details": [],
                "is_healthy": False,
                "error": "No status data"
            }
    except Exception as e:
        logger.error(f"Failed to get EC2 status for {instance_id}", error=str(e))
        return {"error": str(e), "is_healthy": False}


@rate_limit()
def fetch_ec2_memory_metrics(instance_id: str, minutes: int = 5) -> list:
    """Fetch memory usage metrics from CustomMetrics"""
    try:
        client = get_cloudwatch_client()
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(minutes=minutes)
        
        response = client.get_metric_statistics(
            Namespace="CustomMetrics",
            MetricName="MemoryUsage",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=60,
            Statistics=["Average"]
        )
        
        datapoints = sorted(response.get("Datapoints", []), key=lambda x: x["Timestamp"])
        if datapoints:
            logger.info(f"Found memory data from CustomMetrics: {datapoints[-1]['Average']}%")
        else:
            logger.warning(f"No memory data in CustomMetrics for {instance_id}")
        
        return [{"timestamp": dp["Timestamp"].isoformat(), "value": dp["Average"]} for dp in datapoints]
    except Exception as e:
        logger.error(f"Failed to fetch memory metrics: {e}")
        return []


@rate_limit()
def fetch_ec2_disk_metrics(instance_id: str, minutes: int = 5) -> list:
    """Fetch disk usage metrics from CustomMetrics"""
    try:
        client = get_cloudwatch_client()
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(minutes=minutes)
        
        response = client.get_metric_statistics(
            Namespace="CustomMetrics",
            MetricName="DiskUsage",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=60,
            Statistics=["Average"]
        )
        
        datapoints = sorted(response.get("Datapoints", []), key=lambda x: x["Timestamp"])
        if datapoints:
            logger.info(f"Found disk data from CustomMetrics: {datapoints[-1]['Average']}%")
        else:
            logger.warning(f"No disk data in CustomMetrics for {instance_id}")
        
        return [{"timestamp": dp["Timestamp"].isoformat(), "value": dp["Average"]} for dp in datapoints]
    except Exception as e:
        logger.error(f"Failed to fetch disk metrics: {e}")
        return []


@rate_limit()
def scale_up_instance(instance_id: str) -> dict:
    """Change EC2 instance to next larger type"""
    try:
        ec2 = get_ec2_client()
        
        # Current instance type
        response = ec2.describe_instances(InstanceIds=[instance_id])
        current_type = response['Reservations'][0]['Instances'][0]['InstanceType']
        
        # Type upgrade path
        upgrade_path = {
            't3.micro': 't3.small',
            't3.small': 't3.medium', 
            't3.medium': 't3.large',
            't2.micro': 't2.small',
            't2.small': 't2.medium',
        }
        
        new_type = upgrade_path.get(current_type)
        if not new_type:
            return {"success": False, "error": f"Cannot upgrade {current_type} further"}
        
        # Stop, modify, start
        ec2.stop_instances(InstanceIds=[instance_id])
        waiter = ec2.get_waiter('instance_stopped')
        waiter.wait(InstanceIds=[instance_id])
        
        ec2.modify_instance_attribute(InstanceId=instance_id, Attribute='instanceType', Value=new_type)
        
        ec2.start_instances(InstanceIds=[instance_id])
        
        logger.info(f"Scaled up {instance_id}: {current_type} → {new_type}")
        
        return {"success": True, "old_type": current_type, "new_type": new_type}
        
    except Exception as e:
        logger.error(f"Scale up failed: {e}")
        return {"success": False, "error": str(e)}  # <-- REMOVE the 's' at the end!
    
def get_logs_client():
    """Get CloudWatch Logs client"""
    return boto3.client(
        "logs",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
    )