from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api import inframind, opsgpt, failure, scalewise, autohealing, streaming
from backend.models.database import init_db

app = FastAPI(
    title="NeuroOps API",
    description="AI Powered Self-Healing Cloud Platform",
    version="1.0.0"
)

# ── CORS for dashboard ─────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.on_event("startup")
def startup():
    init_db()

app.include_router(inframind.router,   prefix="/api", tags=["InfraMind"])
app.include_router(opsgpt.router,      prefix="/api", tags=["OpsGPT"])
app.include_router(failure.router,     prefix="/api", tags=["Failure Prediction"])
app.include_router(scalewise.router,   prefix="/api", tags=["ScaleWise"])
app.include_router(autohealing.router, prefix="/api", tags=["Auto-Healing"])
app.include_router(streaming.router,   tags=["Live Streaming"])

@app.get("/")
def home():
    return {"message": "NeuroOps backend running"}