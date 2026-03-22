from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from backend.api import (
    inframind, opsgpt, failure, scalewise,
    autohealing, streaming, buildsense, deployguard, auth, features,registry,pipeline
)

from backend.models.database import init_db
from backend.services.rate_limiter import limiter

app = FastAPI(
    title="NeuroOps API",
    description="AI Powered Self-Healing Cloud Platform",
    version="1.0.0"
)

# attach limiter to app
app.state.limiter = limiter

# handle rate limit errors cleanly
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "error"  : "Rate limit exceeded",
            "message": "Too many requests. Please slow down.",
            "limit"  : str(exc.detail)
        }
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.on_event("startup")
def startup():
    init_db()

# v1 routes
app.include_router(auth.router,         prefix="/api/v1", tags=["Authentication"])
app.include_router(inframind.router,    prefix="/api/v1", tags=["InfraMind"])
app.include_router(opsgpt.router,       prefix="/api/v1", tags=["OpsGPT"])
app.include_router(failure.router,      prefix="/api/v1", tags=["Failure Prediction"])
app.include_router(scalewise.router,    prefix="/api/v1", tags=["ScaleWise"])
app.include_router(autohealing.router,  prefix="/api/v1", tags=["Auto-Healing"])
app.include_router(buildsense.router,   prefix="/api/v1", tags=["BuildSense"])
app.include_router(deployguard.router,  prefix="/api/v1", tags=["DeployGuard"])
app.include_router(streaming.router,    tags=["Live Streaming"])
app.include_router(features.router, prefix="/api/v1", tags=["Feature Store"])
app.include_router(registry.router, prefix="/api/v1", tags=["Model Registry"])
app.include_router(pipeline.router, prefix="/api/v1", tags=["Data Pipeline"])

@app.get("/")
def home():
    return {
        "platform": "NeuroOps",
        "version" : "1.0.0",
        "api_v1"  : "/api/v1",
        "docs"    : "/docs"
    }