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
    
    # relationships
    audit_logs = relationship("AuditLog", back_populates="user")
    healing_actions = relationship("HealingAction", back_populates="user")


class PredictionHistory(Base):
    __tablename__ = "prediction_history"

    id = Column(Integer, primary_key=True, index=True)
    model_name = Column(String, nullable=False)
    input_features = Column(JSON)
    prediction = Column(JSON)
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

    # Optional: add metadata
    source = Column(String, default="cloudwatch")  # cloudwatch, custom, etc.
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
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    # relationships
    user = relationship("User", back_populates="healing_actions")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String, nullable=True)
    action = Column(String, nullable=False)
    resource = Column(String, nullable=False)
    details = Column(JSON, nullable=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # relationships
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