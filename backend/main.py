from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from backend.api import streaming
from backend.api import incidents
from backend.api import aws
from backend.core.config import settings
from backend.core.logger import get_logger
from backend.services.metrics_analyzer import start_metrics_analyzer
from backend.models.database import init_db
from backend.services.log_clusterer import run_daily_clustering
import threading
import time
from backend.api import agent
from backend.api import rootcause
from backend.api import services
from backend.api import training
# Routers
from backend.api import (
    auth, inframind, opsgpt, failure, scalewise,
    autohealing, buildsense, deployguard,
    features, registry, pipeline, health
)

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="NeuroOps API",
    description="""
    ## 🤖 AI-Powered Infrastructure Operations Platform

    NeuroOps provides intelligent automation for cloud infrastructure management.

    ### Core Features:

    - **🧠 InfraMind**: Real-time anomaly detection using Isolation Forest
      - Detects CPU/memory spikes
      - Identifies unusual patterns
      - Returns anomaly scores with severity levels

    - **⚠️ Failure Predictor**: ML-based failure prediction
      - Predicts EC2 instance failures before they happen
      - Uses Random Forest with 24 sensor inputs
      - Returns probability and recommended actions

    - **⏱️ RUL Predictor**: Remaining Useful Life estimation
      - Predicts when an instance will fail
      - Provides confidence intervals
      - Suggests maintenance windows

    - **🛠️ Auto-Healing**: Automated remediation
      - Triggers on anomaly detection
      - Restarts services, scales resources
      - Tracks healing history and success rates

    - **💰 ScaleWise**: Cost optimization
      - Analyzes instance utilization
      - Recommends right-sizing
      - Shows potential savings

    - **📝 OpsGPT**: Log analysis
      - Analyzes error logs using LLM
      - Clusters similar errors
      - Provides root cause analysis

    ### Authentication:
    Use `/api/v1/auth/login` to get JWT token.
    Include in header: `Authorization: Bearer <token>`

    ### Rate Limits:
    - 60 requests per minute for prediction endpoints
    - 30 requests per minute for analysis endpoints
    """,
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    contact={
        "name": "NeuroOps Team",
        "email": "neuroops@example.com",
    },
    license_info={
        "name": "MIT",
    },
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

logger = get_logger("main")

# CORS - single instance
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static dashboard
app.mount("/dashboard", StaticFiles(directory="dashboard", html=True), name="dashboard")

# Router registration
app.include_router(auth.router,         prefix="/api/v1", tags=["Authentication"])
app.include_router(inframind.router,    prefix="/api/v1", tags=["InfraMind"])
app.include_router(opsgpt.router,       prefix="/api/v1", tags=["OpsGPT"])
app.include_router(failure.router,      prefix="/api/v1", tags=["Failure Prediction"])
app.include_router(scalewise.router,    prefix="/api/v1", tags=["ScaleWise"])
app.include_router(autohealing.router,  prefix="/api/v1", tags=["Auto-Healing"])
app.include_router(buildsense.router,   prefix="/api/v1", tags=["BuildSense"])
app.include_router(deployguard.router,  prefix="/api/v1", tags=["DeployGuard"])
app.include_router(streaming.router,    prefix="/api/v1", tags=["Live Streaming"])
app.include_router(features.router,     prefix="/api/v1", tags=["Feature Store"])
app.include_router(registry.router,     prefix="/api/v1", tags=["Model Registry"])
app.include_router(pipeline.router,     prefix="/api/v1", tags=["Data Pipeline"])
app.include_router(health.router,       prefix="/api/v1", tags=["Health"])
app.include_router(aws.router,          prefix="/api/v1", tags=["AWS"])
app.include_router(incidents.router,    prefix="/api/v1", tags=["Incidents"])
app.include_router(services.router,     prefix="/api/v1", tags=["Services"])
app.include_router(rootcause.router,    prefix="/api/v1", tags=["RootCause"])
app.include_router(agent.router,        prefix="/api/v1", tags=["Agent"])
app.include_router(training.router,     prefix="/api/v1", tags=["Training"])


def run_daily_clustering_background():
    """Run clustering once on startup, then every 24 hours"""
    while True:
        try:
            logger.info("running_daily_log_clustering")
            result = run_daily_clustering()
            if result:
                logger.info("daily_clustering_completed", clusters=result.get("n_clusters"))
            else:
                logger.info("daily_clustering_skipped_already_run_today")
        except Exception as e:
            logger.error("daily_clustering_failed", error=str(e))
        # Wait 24 hours (86400 seconds)
        time.sleep(86400)


@app.on_event("startup")
def startup():
    """Initialize database, start metric analyzer, and start daily clustering scheduler"""
    init_db()
    logger.info("neuroops_started", version=settings.APP_VERSION)
    
    # Start metrics analyzer (runs every 60 seconds)
    start_metrics_analyzer(interval_seconds=60)
    
    # Start daily clustering in background thread
    clustering_thread = threading.Thread(target=run_daily_clustering_background, daemon=True)
    clustering_thread.start()
    logger.info("daily_clustering_scheduler_started")


@app.get("/")
def home():
    return {
        "platform": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "api": "/api/v1",
        "docs": "/docs"
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}