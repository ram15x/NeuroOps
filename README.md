# NeuroOps

AI-powered self-healing cloud infrastructure platform built with Python.

## What it does
- Anomaly detection with SHAP explainability (InfraMind)
- LLM-powered log analysis using Phi-3 Mini (OpsGPT)
- Failure prediction + RUL countdown (NASA Turbofan dataset)
- Multi-service failure correlation
- A/B model testing
- Cloud cost optimization (ScaleWise)
- Auto-healing pipeline
- Feature Store + Model Registry
- Automated data pipeline

## Tech Stack
- FastAPI, PostgreSQL, Redis, Scikit-learn, Ollama (Phi-3 Mini)
- JWT Auth, Rate Limiting, WebSocket streaming
- Docker + Docker Compose

## Run locally
```powershell
neuroops_env\Scripts\activate
uvicorn backend.main:app --reload
```

API docs: http://127.0.0.1:8000/docs# CI/CD Test Thu Apr  9 14:18:03 UTC 2026
