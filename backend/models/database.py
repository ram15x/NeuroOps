from sqlalchemy import create_engine, Column, Integer, Float, Boolean, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from datetime import datetime
import os

load_dotenv("backend/.env")

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ── Alert Table ────────────────────────────────────────
class Alert(Base):
    __tablename__ = "alerts"

    id            = Column(Integer, primary_key=True, index=True)
    metric_value  = Column(Float)
    rolling_mean  = Column(Float)
    rolling_std   = Column(Float)
    value_diff    = Column(Float)
    is_anomaly    = Column(Boolean)
    severity      = Column(String)
    anomaly_score = Column(Float)
    message       = Column(String)
    created_at    = Column(DateTime, default=datetime.utcnow)

# ── Create Tables ──────────────────────────────────────
def init_db():
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created!")

# ── DB Session ─────────────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()