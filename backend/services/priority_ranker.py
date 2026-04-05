"""
Priority Ranker Service for GAP 1
Ranks alerts and clusters by priority using ML and business rules
"""

import json
import numpy as np
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.models.database import Alert, AlertCluster, Service
from backend.services.redis_service import redis_client


def calculate_alert_priority(
    severity: str,
    business_impact: int,
    metric_value: float,
    metric_name: str,
    db: Session = None
) -> float:
    """
    Calculate priority score for a single alert.
    Higher score = fix first.
    
    Score components:
    - Severity weight: critical=100, warning=50, normal=10
    - Business impact: 1-100 (user configurable per service)
    - Repeat offender bonus: +30 if same issue occurred 5+ times in 7 days
    - Metric severity: higher metric value = higher score (normalized)
    """
    priority_score = 0.0
    
    # 1. Severity weight (base)
    severity_weights = {
        "critical": 100,
        "warning": 50,
        "normal": 10
    }
    priority_score += severity_weights.get(severity, 10)
    
    # 2. Business impact (1-100)
    priority_score += business_impact
    
    # 3. Metric value contribution (0-30)
    # Normalize metric value (assuming 0-100 range, cap at 100)
    normalized_metric = min(max(metric_value, 0), 100)
    metric_contribution = normalized_metric * 0.3  # Max 30 points
    priority_score += metric_contribution
    
    # 4. Repeat offender detection (if db provided)
    if db:
        # Count similar alerts in last 7 days
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        repeat_count = db.query(Alert).filter(
            Alert.message.like(f"%{metric_name.split('_')[0]}%"),
            Alert.created_at >= seven_days_ago,
            Alert.is_anomaly == True
        ).count()
        
        if repeat_count >= 5:
            priority_score += 30
        elif repeat_count >= 3:
            priority_score += 15
        elif repeat_count >= 2:
            priority_score += 5
    
    # Cap at 200 (max priority)
    return min(priority_score, 200.0)


def calculate_cluster_priority(
    cluster_data: dict,
    db: Session = None
) -> dict:
    """
    Calculate priority score for an alert cluster.
    
    Args:
        cluster_data: Cluster dict from log_clusterer containing:
            - cluster_id, count, percentage, representative, top_keywords
        db: Database session for historical data
    
    Returns:
        dict with priority_score, priority_rank, and metadata
    """
    priority_score = 0.0
    
    # 1. Cluster size (number of alerts in this cluster)
    alert_count = cluster_data.get("count", 0)
    # Max 50 points for size (500+ alerts = 50 points)
    size_score = min(alert_count / 10, 50)
    priority_score += size_score
    
    # 2. Percentage of total alerts
    percentage = cluster_data.get("percentage", 0)
    # Max 30 points for percentage
    percentage_score = min(percentage, 30)
    priority_score += percentage_score
    
    # 3. Keyword severity detection
    keywords = cluster_data.get("top_keywords", [])
    severity_keywords = {
        "critical": ["crash", "down", "failed", "error", "timeout", "exception", "fatal"],
        "warning": ["slow", "delay", "retry", "warning", "degraded", "high"]
    }
    
    keyword_score = 0
    for kw in keywords:
        kw_lower = kw.lower()
        if any(critical in kw_lower for critical in severity_keywords["critical"]):
            keyword_score += 10
        elif any(warning in kw_lower for warning in severity_keywords["warning"]):
            keyword_score += 5
    
    priority_score += min(keyword_score, 30)
    
    # 4. Historical repeat offender (if db provided)
    if db:
        # Find similar cluster in database
        representative = cluster_data.get("representative", "")
        similar_cluster = db.query(AlertCluster).filter(
            AlertCluster.root_cause_pattern.like(f"%{representative[:50]}%")
        ).first()
        
        if similar_cluster:
            # Repeat count in last 7 days
            if similar_cluster.occurrence_count_7d >= 5:
                priority_score += 30
            elif similar_cluster.occurrence_count_7d >= 3:
                priority_score += 15
            elif similar_cluster.occurrence_count_7d >= 2:
                priority_score += 5
            
            # Auto-fix success rate bonus
            if similar_cluster.auto_fix_total_attempts > 0:
                success_rate = similar_cluster.auto_fix_success_count / similar_cluster.auto_fix_total_attempts
                if success_rate >= 0.8:
                    priority_score += 10  # High confidence in auto-fix
    
    # 5. Time decay - newer clusters get higher priority
    # (handled separately in API by sorting creation time)
    
    # Cap at 200
    priority_score = min(priority_score, 200.0)
    
    return {
        "priority_score": round(priority_score, 2),
        "priority_rank": 0,  # Will be set after sorting
        "size_score": round(size_score, 2),
        "percentage_score": round(percentage_score, 2),
        "keyword_score": round(keyword_score, 2)
    }


def get_ranked_alerts(db: Session, limit: int = 50) -> list:
    """
    Get alerts sorted by priority score (highest first)
    """
    alerts = db.query(Alert).filter(
        Alert.is_anomaly == True,
        Alert.auto_resolved == False
    ).order_by(Alert.priority_score.desc()).limit(limit).all()
    
    return [
        {
            "id": a.id,
            "message": a.message,
            "severity": a.severity,
            "priority_score": a.priority_score,
            "metric_value": a.metric_value,
            "created_at": a.created_at.isoformat(),
            "cluster_id": a.cluster_id
        }
        for a in alerts
    ]


def get_ranked_clusters(db: Session, limit: int = 20) -> list:
    """
    Get clusters sorted by priority score (highest first)
    """
    clusters = db.query(AlertCluster).filter(
        AlertCluster.status == "active"
    ).order_by(AlertCluster.priority_score.desc()).limit(limit).all()
    
    return [
        {
            "cluster_id": c.cluster_id,
            "root_cause_pattern": c.root_cause_pattern,
            "total_alerts": c.total_alerts,
            "priority_score": c.priority_score,
            "priority_rank": idx + 1,
            "occurrence_count_7d": c.occurrence_count_7d,
            "status": c.status,
            "first_seen": c.first_seen.isoformat() if c.first_seen else None,
            "last_seen": c.last_seen.isoformat() if c.last_seen else None
        }
        for idx, c in enumerate(clusters)
    ]


def update_priority_scores(db: Session, alert_id: int = None):
    """
    Update priority scores for alerts or clusters.
    Can be called after new alerts are added or periodically.
    """
    cache_key = "priority:ranked_alerts"
    
    if alert_id:
        # Update single alert
        alert = db.query(Alert).filter(Alert.id == alert_id).first()
        if alert:
            # Recalculate priority
            service_name = alert.message.split()[0] if alert.message else "unknown"
            service = db.query(Service).filter(
                Service.service_name.like(f"%{service_name}%")
            ).first()
            business_impact = service.business_impact if service else 10
            
            alert.priority_score = calculate_alert_priority(
                severity=alert.severity,
                business_impact=business_impact,
                metric_value=alert.metric_value,
                metric_name=alert.message,
                db=db
            )
            db.commit()
    else:
        # Update all recent alerts (last 24 hours)
        one_day_ago = datetime.utcnow() - timedelta(days=1)
        alerts = db.query(Alert).filter(Alert.created_at >= one_day_ago).all()
        
        for alert in alerts:
            service_name = alert.message.split()[0] if alert.message else "unknown"
            service = db.query(Service).filter(
                Service.service_name.like(f"%{service_name}%")
            ).first()
            business_impact = service.business_impact if service else 10
            
            alert.priority_score = calculate_alert_priority(
                severity=alert.severity,
                business_impact=business_impact,
                metric_value=alert.metric_value,
                metric_name=alert.message,
                db=db
            )
        
        db.commit()
    
    # Cache the ranked results
    ranked_alerts = get_ranked_alerts(db)
    redis_client.setex(cache_key, 60, json.dumps(ranked_alerts))  # Cache for 60 seconds
    
    return ranked_alerts


def assign_cluster_to_alert(alert_id: int, cluster_id: str, db: Session):
    """
    Assign an alert to a cluster (called after clustering runs)
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if alert:
        alert.cluster_id = cluster_id
        db.commit()
        
        # Update cluster's total alert count
        cluster = db.query(AlertCluster).filter(AlertCluster.cluster_id == cluster_id).first()
        if cluster:
            cluster.total_alerts = db.query(Alert).filter(
                Alert.cluster_id == cluster_id
            ).count()
            cluster.last_seen = datetime.utcnow()
            db.commit()
    
    return True