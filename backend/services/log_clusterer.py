import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from collections import Counter

# path to the processed logs dataset
LOGS_PATH = "datasets/processed/logs_clean.csv"

def run_log_clustering(n_clusters: int = 8) -> dict:
    # load the logs csv
    df = pd.read_csv(LOGS_PATH)

    # use EventTemplate column if available, fall back to Content
    if "EventTemplate" in df.columns:
        texts = df["EventTemplate"].dropna().astype(str).tolist()
    elif "Content" in df.columns:
        texts = df["Content"].dropna().astype(str).tolist()
    else:
        raise ValueError("logs_clean.csv has no usable text column")

    # cap at 5000 rows so it runs fast during demo
    if len(texts) > 5000:
        texts = texts[:5000]

    total_logs = len(texts)

    # convert text to numeric vectors using tf-idf
    # max 500 features keeps memory low on 16gb ram
    vectorizer = TfidfVectorizer(max_features=500, stop_words="english")
    X = vectorizer.fit_transform(texts)

    # clamp n_clusters so it never exceeds number of unique logs
    n_clusters = min(n_clusters, total_logs)

    # run kmeans clustering
    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = km.fit_predict(X)

    # count how many logs fell into each cluster
    cluster_counts = Counter(labels)

    # for each cluster find the most representative log line
    # representative = the log closest to that cluster's centroid
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

        # get top keywords for this cluster using centroid feature weights
        feature_names = vectorizer.get_feature_names_out()
        top_keyword_indices = centroid.argsort()[-5:][::-1]
        top_keywords = [feature_names[i] for i in top_keyword_indices]

        results.append({
            "cluster_id"    : cluster_id,
            "count"         : count,
            "percentage"    : round((count / total_logs) * 100, 2),
            "representative": representative[:200],  # trim long lines
            "top_keywords"  : top_keywords
        })

    # sort by count descending so biggest cluster appears first
    results.sort(key=lambda x: x["count"], reverse=True)

    return {
        "total_logs_analyzed": total_logs,
        "n_clusters"         : n_clusters,
        "clusters"           : results
    }