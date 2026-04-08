import pandas as pd
import numpy as np
import json
import os
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from collections import Counter
from datetime import datetime, timedelta
from backend.core.config import settings
from backend.services.redis_service import redis_client
from backend.services.aws_service import get_logs_client
from backend.core.logger import get_logger

logger = get_logger("log_clusterer")

# Fallback log file (for when CloudWatch is not available)
FALLBACK_LOGS_PATH = os.path.join(settings.DATA_PATH, "processed/logs_clean.csv")


def fetch_cloudwatch_logs(log_group_name: str = None, minutes: int = 60, limit: int = 1000):
    """
    Fetch real logs from AWS CloudWatch
    If no log group specified, tries to find EC2 system logs
    """
    try:
        logs_client = get_logs_client()
        
        # Default log groups to check (EC2, Lambda, etc.)
        # log groups loaded from config (set CLOUDWATCH_LOG_GROUPS_RAW in .env)
        default_log_groups = settings.CLOUDWATCH_LOG_GROUPS
        
        # If specific log group provided, use it
        if log_group_name:
            groups_to_check = [log_group_name]
        else:
            # Try to find existing log groups
            try:
                response = logs_client.describe_log_groups(limit=10)
                groups_to_check = [lg['logGroupName'] for lg in response.get('logGroups', [])]
                if not groups_to_check:
                    groups_to_check = default_log_groups
            except Exception as e:
                logger.warning(f"Cannot fetch log groups: {e}")
                groups_to_check = default_log_groups
        
        # Fetch logs from first available log group
        for log_group in groups_to_check:
            try:
                # Get log streams
                streams_response = logs_client.describe_log_streams(
                    logGroupName=log_group,
                    orderBy='LastEventTime',
                    descending=True,
                    limit=5
                )
                
                if not streams_response.get('logStreams'):
                    continue
                
                # Get recent logs
                start_time = int((datetime.utcnow() - timedelta(minutes=minutes)).timestamp() * 1000)
                
                all_logs = []
                for stream in streams_response['logStreams'][:3]:  # Limit to 3 streams
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
                        logger.debug(f"Error fetching from stream {stream['logStreamName']}: {e}")
                
                if all_logs:
                    logger.info(f"Fetched {len(all_logs)} logs from CloudWatch group: {log_group}")
                    return all_logs
                    
            except Exception as e:
                logger.debug(f"Log group {log_group} not accessible: {e}")
                continue
        
        # Fallback to local file if no CloudWatch logs found
        logger.warning("No CloudWatch logs found, falling back to local file")
        return _load_local_logs()
        
    except Exception as e:
        logger.error(f"Failed to fetch CloudWatch logs: {e}")
        return _load_local_logs()


def _load_local_logs():
    """Fallback: Load logs from local CSV file"""
    try:
        if not os.path.exists(FALLBACK_LOGS_PATH):
            logger.warning(f"Fallback log file not found: {FALLBACK_LOGS_PATH}")
            return _generate_sample_logs()
        
        df = pd.read_csv(FALLBACK_LOGS_PATH)
        
        if "EventTemplate" in df.columns:
            texts = df["EventTemplate"].dropna().astype(str).tolist()
        elif "Content" in df.columns:
            texts = df["Content"].dropna().astype(str).tolist()
        else:
            raise ValueError("logs_clean.csv has no usable text column")
        
        if len(texts) > settings.LOG_CLUSTER_MAX_ROWS:
            texts = texts[:settings.LOG_CLUSTER_MAX_ROWS]
        
        logger.info(f"Loaded {len(texts)} logs from local file (fallback)")
        return texts
    except Exception as e:
        logger.error(f"Failed to load local logs: {e}")
        return _generate_sample_logs()


def _generate_sample_logs():
    """Generate sample logs for testing when no real logs available"""
    logger.warning("Generating sample logs for testing")
    return [
        "ERROR: Connection timeout to database after 30s",
        "WARNING: High CPU usage detected: 95%",
        "INFO: Service started successfully",
        "ERROR: Disk space running low: 85% used",
        "CRITICAL: Memory allocation failed",
        "WARNING: Network latency spike detected",
        "INFO: Backup completed successfully",
        "ERROR: Authentication failed for user",
        "WARNING: Rate limit exceeded",
        "INFO: Cache hit ratio: 85%"
    ] * 100  # Repeat to have enough logs


def _load_logs(use_cloudwatch: bool = True):
    """Load logs - from CloudWatch if available, else fallback"""
    if use_cloudwatch:
        logs = fetch_cloudwatch_logs()
        if logs:
            # Cap at max rows
            if len(logs) > settings.LOG_CLUSTER_MAX_ROWS:
                logs = logs[:settings.LOG_CLUSTER_MAX_ROWS]
            return logs
    
    # Fallback to local file
    return _load_local_logs()


def _find_optimal_clusters(X, max_k: int = None):
    """Auto-select n_clusters using elbow method"""
    if max_k is None:
        max_k = settings.LOG_CLUSTER_MAX_K
    
    if X.shape[0] <= 2:
        return 2
    
    inertias = []
    k_range = range(2, min(max_k + 1, X.shape[0]))
    
    for k in k_range:
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        kmeans.fit(X)
        inertias.append(kmeans.inertia_)
    
    if len(inertias) < 2:
        return 2
    
    diffs = [inertias[i] - inertias[i+1] for i in range(len(inertias)-1)]
    if not diffs:
        return 2
    
    optimal_idx = np.argmax(diffs) if diffs else 0
    return k_range[optimal_idx]


def run_log_clustering(n_clusters: int = None, auto_optimize: bool = True, use_cloudwatch: bool = True) -> dict:
    """Run log clustering with CloudWatch logs and caching"""
    
    # check cache
    cache_key = f"log_clusters:{n_clusters if n_clusters else 'auto'}"
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    
    texts = _load_logs(use_cloudwatch=use_cloudwatch)
    total_logs = len(texts)
    
    if total_logs < 2:
        return {
            "total_logs_analyzed": total_logs,
            "n_clusters": 0,
            "clusters": [],
            "source": "cloudwatch" if use_cloudwatch else "local",
            "error": "Insufficient logs"
        }
    
    # vectorize
    vectorizer = TfidfVectorizer(
        max_features=settings.LOG_CLUSTER_MAX_FEATURES,
        stop_words="english"
    )
    X = vectorizer.fit_transform(texts)
    
    # auto-select clusters if requested
    if auto_optimize and n_clusters is None:
        n_clusters = _find_optimal_clusters(X)
    elif n_clusters is None:
        n_clusters = settings.LOG_CLUSTER_DEFAULT_K
    
    # clamp
    n_clusters = min(n_clusters, total_logs)
    
    # run clustering
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
        "auto_optimized": auto_optimize and n_clusters is not None,
        "source": "cloudwatch" if use_cloudwatch else "local",
        "clusters": results
    }
    
    # cache for 24 hours
    redis_client.setex(cache_key, settings.LOG_CLUSTER_CACHE_TTL, json.dumps(output))
    
    return output


def run_daily_clustering():
    """Auto-run clustering once per day using CloudWatch logs"""
    from datetime import datetime
    import json
    
    cache_key = "log_clusters:daily"
    last_run = redis_client.get(cache_key)
    
    # Run if not run today
    if not last_run or datetime.now().date() > datetime.fromisoformat(last_run).date():
        # Try CloudWatch first, fallback to local
        result = run_log_clustering(n_clusters=8, auto_optimize=True, use_cloudwatch=True)
        redis_client.setex(cache_key, 86400, datetime.now().isoformat())
        redis_client.setex("log_clusters:daily_result", 86400, json.dumps(result))
        logger.info(f"Daily log clustering completed - Source: {result.get('source', 'unknown')}")
        return result
    return None