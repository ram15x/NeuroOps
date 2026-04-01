import pandas as pd
import numpy as np
import json
import os
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from collections import Counter
from backend.core.config import settings
from backend.services.redis_service import redis_client
from backend.core.logger import get_logger

logger = get_logger("log_clusterer")

LOGS_PATH = os.path.join(settings.DATA_PATH, "processed/logs_clean.csv")

def _load_logs():
    """Load logs with caching"""
    df = pd.read_csv(LOGS_PATH)
    
    if "EventTemplate" in df.columns:
        texts = df["EventTemplate"].dropna().astype(str).tolist()
    elif "Content" in df.columns:
        texts = df["Content"].dropna().astype(str).tolist()
    else:
        raise ValueError("logs_clean.csv has no usable text column")
    
    # cap at config max rows
    if len(texts) > settings.LOG_CLUSTER_MAX_ROWS:
        texts = texts[:settings.LOG_CLUSTER_MAX_ROWS]
    
    return texts

def _find_optimal_clusters(X, max_k: int = None):
    """Auto-select n_clusters using elbow method"""
    if max_k is None:
        max_k = settings.LOG_CLUSTER_MAX_K
    
    inertias = []
    k_range = range(2, min(max_k + 1, X.shape[0]))
    
    for k in k_range:
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        kmeans.fit(X)
        inertias.append(kmeans.inertia_)
    
    # find elbow point using rate of change
    if len(inertias) < 2:
        return 2
    
    diffs = [inertias[i] - inertias[i+1] for i in range(len(inertias)-1)]
    if not diffs:
        return 2
    
    optimal_idx = np.argmax(diffs) if diffs else 0
    return k_range[optimal_idx]

def run_log_clustering(n_clusters: int = None, auto_optimize: bool = True) -> dict:
    """Run log clustering with caching and auto elbow method"""
    
    # check cache
    cache_key = f"log_clusters:{n_clusters if n_clusters else 'auto'}"
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    
    texts = _load_logs()
    total_logs = len(texts)
    
    if total_logs < 2:
        return {
            "total_logs_analyzed": total_logs,
            "n_clusters": 0,
            "clusters": [],
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
        "clusters": results
    }
    
    # cache for 24 hours
    redis_client.setex(cache_key, settings.LOG_CLUSTER_CACHE_TTL, json.dumps(output))
    
    return output

def run_daily_clustering():
    """Auto-run clustering once per day"""
    cache_key = "log_clusters:daily"
    last_run = redis_client.get(cache_key)
    
    # Run if not run today
    if not last_run or datetime.now().date() > datetime.fromisoformat(last_run).date():
        result = run_log_clustering(n_clusters=8, auto_optimize=True)
        redis_client.setex(cache_key, 86400, datetime.now().isoformat())
        redis_client.setex("log_clusters:daily_result", 86400, json.dumps(result))
        logger.info("Daily log clustering completed")
        return result
    return None

def run_daily_clustering():
    """Auto-run clustering once per day"""
    from datetime import datetime
    import json
    
    cache_key = "log_clusters:daily"
    last_run = redis_client.get(cache_key)
    
    # Run if not run today
    if not last_run or datetime.now().date() > datetime.fromisoformat(last_run).date():
        result = run_log_clustering(n_clusters=8, auto_optimize=True)
        redis_client.setex(cache_key, 86400, datetime.now().isoformat())
        redis_client.setex("log_clusters:daily_result", 86400, json.dumps(result))
        logger.info("Daily log clustering completed")
        return result
    return None