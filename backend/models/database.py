
import json
import numpy as np

class SafeJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.bool_, np.bool)):
            return bool(obj)
        if isinstance(obj, (np.integer, np.int64, np.int32)):
            return int(obj)
        if isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

def safe_json_dumps(obj):
    return json.dumps(obj, cls=SafeJSONEncoder)
import numpy as np

import json
import numpy as np

class NumpyJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for numpy types"""
    def default(self, obj):
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

def safe_json_dumps(obj):
    """Safely dump JSON with numpy type handling"""
    return json.dumps(obj, cls=NumpyJSONEncoder)


def convert_numpy_types(obj):
    """Convert numpy types to Python native types for JSON serialization"""
    if hasattr(obj, 'tolist'):
        return obj.tolist()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    return obj
from sqlalchemy import create_engine, Column, Integer, Float, String, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

from backend.core.config import settings

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    metric_value = Column(Float)
    rolling_mean = Column(Float)
    rolling_std = Column(Float)
    value_diff = Column(Float)
    is_anomaly = Column(Boolean)
    severity = Column(String)
    anomaly_score = Column(Float)
    message = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # NEW for GAP 1: Priority ranking
    priority_score = Column(Float, default=0.0)
    priority_rank = Column(Integer, default=0)
    cluster_id = Column(String, nullable=True)  # Which cluster this alert belongs to
    auto_resolved = Column(Boolean, default=False)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    audit_logs = relationship("AuditLog", back_populates="user")
    healing_actions = relationship("HealingAction", back_populates="user")


class Service(Base):
    """NEW TABLE for GAP 1: Service-level configuration"""
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True)
    service_name = Column(String, unique=True, index=True, nullable=False)
    business_impact = Column(Integer, default=10)  # 1-100, higher = more important
    sla_minutes = Column(Integer, default=5)  # SLA response time in minutes
    on_call_group = Column(String, default="default")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AlertCluster(Base):
    """NEW TABLE for GAP 1: Store cluster information"""
    __tablename__ = "alert_clusters"

    id = Column(Integer, primary_key=True, index=True)
    cluster_id = Column(String, unique=True, index=True, nullable=False)
    root_cause_pattern = Column(String)  # The common root cause for this cluster
    total_alerts = Column(Integer, default=0)
    severity_distribution = Column(JSON, default={})  # {"critical": 10, "warning": 5, "normal": 2}
    affected_services = Column(JSON, default=[])  # List of service names
    priority_score = Column(Float, default=0.0)
    priority_rank = Column(Integer, default=0)
    occurrence_count_7d = Column(Integer, default=0)  # Repeat offender tracking
    auto_fix_success_count = Column(Integer, default=0)
    auto_fix_total_attempts = Column(Integer, default=0)
    status = Column(String, default="active")  # active, auto_resolved, archived
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


class PredictionHistory(Base):

    def __init__(self, **kwargs):
        # Convert dicts to JSON strings
        if 'input_features' in kwargs and isinstance(kwargs['input_features'], dict):
            kwargs['input_features'] = safe_json_dumps(kwargs['input_features'])
        if 'prediction' in kwargs and isinstance(kwargs['prediction'], dict):
            kwargs['prediction'] = safe_json_dumps(kwargs['prediction'])
        super().__init__(**kwargs)

    __tablename__ = "prediction_history"

    id = Column(Integer, primary_key=True, index=True)
    model_name = Column(String, nullable=False)
    input_features = Column(String)
    prediction = Column(String)
    actual_outcome = Column(String, nullable=True)
    confidence_score = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class MetricHistory(Base):
    __tablename__ = "metric_history"

    id = Column(Integer, primary_key=True, index=True)
    instance_id = Column(String, index=True, nullable=False)
    metric_name = Column(String, index=True, nullable=False)
    value = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    source = Column(String, default="cloudwatch")
    unit = Column(String, default="percent")


class HealingAction(Base):
    __tablename__ = "healing_actions"

    id = Column(Integer, primary_key=True, index=True)
    service_name = Column(String, nullable=False)
    severity = Column(String)
    action_taken = Column(String)
    status = Column(String, default="pending")
    triggered_by = Column(String)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    details = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    user = relationship("User", back_populates="healing_actions")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String, nullable=True)
    action = Column(String, nullable=False)
    resource = Column(String, nullable=False)
    details = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="audit_logs")


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String)
    severity = Column(String)
    status = Column(String, default="open")
    service_name = Column(String)
    root_cause = Column(String, nullable=True)
    resolution = Column(String, nullable=True)
    detected_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)


def init_db():
    """Create all tables"""
    Base.metadata.create_all(bind=engine)
    print("Database tables created")


def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()