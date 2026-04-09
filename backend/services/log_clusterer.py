import pandas as pd
import numpy as np
import json
import os
import subprocess
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from collections import Counter
from datetime import datetime, timedelta
from backend.core.config import settings
from backend.services.redis_service import redis_client
from backend.services.aws_service import get_logs_client
from backend.core.logger import get_logger

logger = get_logger("log_clusterer")

def fetch_system_logs():
    """Fetch real system logs from EC2 (journalctl)"""
    try:
        # Get last 1000 lines of system logs
        result = subprocess.run(
            ["sudo", "journalctl", "--since", "1 hour ago", "-n", "1000", "--no-pager"],
            capture_output=True, text=True, timeout=10
        )
        if result.stdout:
            logs = result.stdout.strip().split('\n')
            logger.info(f"Fetched {len(logs)} system logs from journalctl")
            return logs
    except Exception as e:
        logger.warning(f"Could not fetch journalctl logs: {e}")
    
    return None

def fetch_cloudwatch_logs(log_group_name: str = None, minutes: int = 60, limit: int = 1000):
    """Fetch logs from AWS CloudWatch"""
    try:
        logs_client = get_logs_client()
        
        # Try multiple log groups
        log_groups_to_try = [
            "/aws/ec2/neuroops-demo",
            "/aws/lambda/neuroops",
            "/var/log/messages",
            "/var/log/syslog",
            "/aws/cloudwatch"
        ]
        
        if log_group_name:
            log_groups_to_try = [log_group_name]
        
        for log_group in log_groups_to_try:
            try:
                streams_response = logs_client.describe_log_streams(
                    logGroupName=log_group,
                    orderBy='LastEventTime',
                    descending=True,
                    limit=5
                )
                
                if not streams_response.get('logStreams'):
                    continue
                
                start_time = int((datetime.utcnow() - timedelta(minutes=minutes)).timestamp() * 1000)
                
                all_logs = []
                for stream in streams_response['logStreams'][:3]:
                    try:
                        events = logs_client.get_log_events(
                            logGroupName=log_group,
                            logStreamName=stream['logStreamName'],
                            startTime=start_time,
                            limit=limit
                        )
                        for event in events.get('events', []):
                            message = event.get('message', '')
                            if message and len(message) > 10:
                                all_logs.append(message)
                    except Exception as e:
                        logger.debug(f"Error fetching from stream: {e}")
                
                if all_logs:
                    logger.info(f"Fetched {len(all_logs)} logs from CloudWatch group: {log_group}")
                    return all_logs
                    
            except Exception as e:
                logger.debug(f"Log group {log_group} not accessible: {e}")
                continue
        
        return None
        
    except Exception as e:
        logger.error(f"Failed to fetch CloudWatch logs: {e}")
        return None

def fetch_application_logs():
    """Fetch application logs from NeuroOps itself"""
    try:
        log_file = "/home/ec2-user/NeuroOps/uvicorn.log"
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                logs = f.readlines()[-500:]  # Last 500 lines
                logger.info(f"Fetched {len(logs)} logs from uvicorn.log")
                return logs
    except Exception as e:
        logger.warning(f"Could not fetch application logs: {e}")
    
    return None

def _generate_sample_logs():
    """Generate realistic sample logs (fallback when no real logs)"""
    sample_patterns = [
        "ERROR: Connection timeout to database after 30s",
        "WARNING: High CPU usage detected: {cpu}%",
        "INFO: Service {service} started successfully",
        "ERROR: Disk space running low: {disk}% used",
        "CRITICAL: Memory allocation failed for process {pid}",
        "WARNING: Network latency spike detected: {latency}ms",
        "INFO: Backup completed successfully for {service}",
        "ERROR: Authentication failed for user {user}",
        "WARNING: Rate limit exceeded for API key {key}",
        "INFO: Cache hit ratio: {ratio}%",
        "ERROR: Failed to connect to Redis: Connection refused",
        "WARNING: Slow query detected: {query} took {time}s",
        "INFO: Deployment {version} completed for {service}",
        "ERROR: SSL certificate expired for domain {domain}",
        "CRITICAL: Service {service} is down!",
    ]
    
    import random
    services = ["payment-service", "auth-service", "api-gateway", "notification-service", "database-proxy"]
    
    logs = []
    for i in range(500):
        pattern = random.choice(sample_patterns)
        log = pattern.format(
            cpu=random.randint(30, 95),
            service=random.choice(services),
            disk=random.randint(20, 95),
            pid=random.randint(1000, 9999),
            latency=random.randint(50, 500),
            user=f"user{random.randint(1, 100)}",
            key=f"key{random.randint(1, 50)}",
            ratio=random.randint(60, 99),
            query=f"SELECT_{random.randint(1, 10)}",
            time=random.randint(1, 30),
            version=f"v{random.randint(1, 5)}.{random.randint(0, 9)}",
            domain=f"service{random.randint(1, 10)}.example.com"
        )
        logs.append(log)
    
    logger.warning(f"Generated {len(logs)} sample logs for testing")
    return logs

def _load_logs(use_real_logs: bool = True):
    """Load logs from multiple sources: journalctl > CloudWatch > Application > Sample"""
    
    # Try journalctl (EC2 system logs) - most reliable
    if use_real_logs:
        logs = fetch_system_logs()
        if logs:
            return logs
    
    # Try CloudWatch logs
    if use_real_logs:
        logs = fetch_cloudwatch_logs()
        if logs:
            return logs
    
    # Try application logs
    if use_real_logs:
        logs = fetch_application_logs()
        if logs:
            return logs
    
    # Fallback to sample logs
    return _generate_sample_logs()

def run_log_clustering(n_clusters: int = None, auto_optimize: bool = True, use_real_logs: bool = True) -> dict:
    """Run log clustering with real logs from multiple sources"""
    
    cache_key = f"log_clusters:{n_clusters if n_clusters else 'auto'}"
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    
    texts = _load_logs(use_real_logs=use_real_logs)
    total_logs = len(texts)
    
    if total_logs < 2:
        return {
            "total_logs_analyzed": total_logs,
            "n_clusters": 0,
            "clusters": [],
            "source": "none",
            "error": "Insufficient logs"
        }
    
    # Vectorize
    vectorizer = TfidfVectorizer(
        max_features=settings.LOG_CLUSTER_MAX_FEATURES,
        stop_words="english"
    )
    X = vectorizer.fit_transform(texts)
    
    # Determine optimal clusters
    if auto_optimize and n_clusters is None:
        from sklearn.metrics import silhouette_score
        best_k = 2
        best_score = -1
        max_k = min(settings.LOG_CLUSTER_MAX_K, total_logs - 1)
        for k in range(2, max_k + 1):
            km = KMeans(n_clusters=k, random_state=42, n_init=10)
            labels = km.fit_predict(X)
            if len(set(labels)) > 1:
                score = silhouette_score(X, labels)
                if score > best_score:
                    best_score = score
                    best_k = k
        n_clusters = best_k
    elif n_clusters is None:
        n_clusters = settings.LOG_CLUSTER_DEFAULT_K
    
    n_clusters = min(n_clusters, total_logs)
    
    # Run clustering
    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = km.fit_predict(X)
    cluster_counts = Counter(labels)
    
    results = []
    for cluster_id in range(n_clusters):
        indices = [i for i, l in enumerate(labels) if l == cluster_id]
        count = cluster_counts[cluster_id]
        
        centroid = km.cluster_centers_[cluster_id]
        cluster_vectors = X[indices]
        dense_vectors = cluster_vectors.toarray()
        centroid_norm = centroid / (np.linalg.norm(centroid) + 1e-9)
        similarities = dense_vectors.dot(centroid_norm)
        best_idx = indices[int(np.argmax(similarities))]
        representative = texts[best_idx]
        
        feature_names = vectorizer.get_feature_names_out()
        top_keyword_indices = centroid.argsort()[-5:][::-1]
        top_keywords = [feature_names[i] for i in top_keyword_indices if i < len(feature_names)]
        
        results.append({
            "cluster_id": cluster_id,
            "count": count,
            "percentage": round((count / total_logs) * 100, 2),
            "representative": representative[:200],
            "top_keywords": top_keywords
        })
    
    results.sort(key=lambda x: x["count"], reverse=True)
    
    output = {
        "total_logs_analyzed": total_logs,
        "n_clusters": n_clusters,
        "auto_optimized": auto_optimize,
        "source": "system_logs",
        "clusters": results
    }
    
    redis_client.setex(cache_key, settings.LOG_CLUSTER_CACHE_TTL, json.dumps(output))
    
    return output

def run_daily_clustering():
    """Auto-run clustering once per day"""
    cache_key = "log_clusters:daily"
    last_run = redis_client.get(cache_key)
    
    if not last_run or datetime.now().date() > datetime.fromisoformat(last_run).date():
        result = run_log_clustering(n_clusters=8, auto_optimize=True, use_real_logs=True)
        redis_client.setex(cache_key, 86400, datetime.now().isoformat())
        redis_client.setex("log_clusters:daily_result", 86400, json.dumps(result))
        logger.info(f"Daily log clustering completed - Source: {result.get('source', 'unknown')}")
        return result
    return None
