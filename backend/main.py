"""
NeuroOps - AI-Powered Infrastructure Operations Platform
FastAPI Application Entry Point - Clean Version
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import os
import logging

from backend.core.config import settings
from backend.core.logger import get_logger
from backend.services.metrics_analyzer import start_metrics_analyzer
from backend.models.database import init_db

# Import all routers (no duplicates)
from backend.api import (
    auth, health, agent, streaming, incidents, aws,
    inframind, opsgpt, failure, scalewise, autohealing,
    buildsense, deployguard, features, registry, pipeline,
    rootcause, services
)

logger = get_logger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="NeuroOps API",
    description="AI-Powered Infrastructure Operations Platform",
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# ========== MIDDLEWARE ==========
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== GLOBAL EXCEPTION HANDLERS ==========
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "status": "error", "code": exc.status_code}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "status": "error"}
    )

# ========== ROUTER REGISTRATION (Logical Order) ==========
# Health & Core
app.include_router(health.router, prefix="/api/v1", tags=["Health"])
app.include_router(auth.router, prefix="/api/v1", tags=["Authentication"])

# Data Collection
app.include_router(agent.router, prefix="/api/v1", tags=["Agent"])
app.include_router(streaming.router, prefix="/api/v1", tags=["Live Streaming"])
app.include_router(aws.router, prefix="/api/v1", tags=["AWS"])

# ML & Intelligence
app.include_router(inframind.router, prefix="/api/v1", tags=["Anomaly Detection"])
app.include_router(failure.router, prefix="/api/v1", tags=["Failure Prediction"])
app.include_router(opsgpt.router, prefix="/api/v1", tags=["Log Analysis"])

# Operations
app.include_router(scalewise.router, prefix="/api/v1", tags=["Cost Optimization"])
app.include_router(autohealing.router, prefix="/api/v1", tags=["Auto Healing"])
app.include_router(buildsense.router, prefix="/api/v1", tags=["CI/CD"])
app.include_router(deployguard.router, prefix="/api/v1", tags=["Deployment"])

# Data Management
app.include_router(features.router, prefix="/api/v1", tags=["Feature Store"])
app.include_router(registry.router, prefix="/api/v1", tags=["Model Registry"])
app.include_router(pipeline.router, prefix="/api/v1", tags=["Data Pipeline"])

# Analytics
app.include_router(incidents.router, prefix="/api/v1", tags=["Incidents"])
app.include_router(rootcause.router, prefix="/api/v1", tags=["Root Cause"])
app.include_router(services.router, prefix="/api/v1", tags=["Services"])

# ========== STATIC FILES ==========
if os.path.exists("dashboard"):
    app.mount("/dashboard", StaticFiles(directory="dashboard", html=True), name="dashboard")

# ========== LIFESPAN EVENTS ==========
@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    init_db()
    logger.info(f"NeuroOps v{settings.APP_VERSION} started successfully")
    start_metrics_analyzer(interval_seconds=60)

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("NeuroOps shutting down")

# ========== ROOT ENDPOINTS ==========
@app.get("/")
async def root():
    return {
        "platform": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "api": "/api/v1",
        "docs": "/docs",
        "status": "operational"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": settings.APP_VERSION}
