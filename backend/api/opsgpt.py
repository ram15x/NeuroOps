from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.models.database import get_db
from backend.services.redis_service import redis_client
import ollama
import json

router = APIRouter()

# ── Log Analysis Endpoint ──────────────────────────────
@router.post("/opsgpt/analyze")
def analyze_log(data: dict, db: Session = Depends(get_db)):
    try:
        log_text = data.get("log", "")

        if not log_text:
            return {"error": "No log provided"}

        # ── Check Redis Cache ──────────────────────────
        cache_key = f"opsgpt:{hash(log_text)}"
        cached = redis_client.get(cache_key)
        if cached:
            result = json.loads(cached)
            result["from_cache"] = True
            return result

        # ── Build Prompt ───────────────────────────────
        prompt = f"""You are an expert cloud infrastructure engineer.
Analyze this system log and respond in this exact format:

SEVERITY: [critical/warning/info]
CAUSE: [one line root cause]
IMPACT: [one line business impact]
FIX: [one line recommended fix]

Log: {log_text}"""

        # ── Call Phi-3 Mini ────────────────────────────
        response = ollama.chat(
            model="phi3:mini",
            messages=[{"role": "user", "content": prompt}]
        )

        ai_response = response["message"]["content"]

        # ── Parse Response ─────────────────────────────
        result = {
            "log"          : log_text,
            "analysis"     : ai_response,
            "severity"     : extract_field(ai_response, "SEVERITY"),
            "cause"        : extract_field(ai_response, "CAUSE"),
            "impact"       : extract_field(ai_response, "IMPACT"),
            "fix"          : extract_field(ai_response, "FIX"),
            "from_cache"   : False
        }

        # ── Cache Result ───────────────────────────────
        redis_client.setex(cache_key, 300, json.dumps(result))

        return result

    except Exception as e:
        return {"error": str(e)}


# ── Batch Log Analysis ─────────────────────────────────
@router.post("/opsgpt/analyze-batch")
def analyze_batch(data: dict):
    try:
        logs = data.get("logs", [])
        if not logs:
            return {"error": "No logs provided"}

        results = []
        for log in logs[:5]:  # max 5 logs at once
            response = ollama.chat(
                model="phi3:mini",
                messages=[{
                    "role": "user",
                    "content": f"Classify this log in one word (critical/warning/info): {log}"
                }]
            )
            results.append({
                "log"      : log,
                "severity" : response["message"]["content"].strip().lower()
            })

        return {"results": results, "total": len(results)}

    except Exception as e:
        return {"error": str(e)}


def extract_field(text: str, field: str) -> str:
    for line in text.split("\n"):
        if line.startswith(f"{field}:"):
            return line.replace(f"{field}:", "").strip()
    return "unknown"