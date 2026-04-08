"""
OpsGPT Analyzer - Two-Tier approach
Tier 1: Rule-based pattern matching (free, instant)
Tier 2: OpenRouter API (free tier, smart)
"""
import re
import os
import requests
import json
from datetime import datetime
from typing import Dict, Any

# ========== TIER 1: RULE-BASED PATTERNS ==========
PATTERNS = {
    # Critical errors
    r"(?i)connection.*timeout|timeout.*connection": {
        "severity": "critical",
        "cause": "Network connectivity issue or service unresponsive",
        "impact": "Service disruption, requests failing",
        "fix": "Check network connectivity, increase timeout, verify service health"
    },
    r"(?i)database.*error|db.*fail|postgres.*error|mysql.*error": {
        "severity": "critical",
        "cause": "Database connection or query failure",
        "impact": "Data unavailability, potential data loss",
        "fix": "Check database health, verify credentials, review slow queries"
    },
    r"(?i)out of memory|oom|memory.*error|memory.*exceed": {
        "severity": "critical",
        "cause": "Memory leak or insufficient memory allocation",
        "impact": "Service crash, potential data corruption",
        "fix": "Increase memory limits, profile memory usage, restart service"
    },
    r"(?i)disk.*full|no space|disk space": {
        "severity": "critical",
        "cause": "Disk space exhausted",
        "impact": "Service unable to write logs or data",
        "fix": "Clean up old files, increase disk size, implement log rotation"
    },
    
    # Warnings
    r"(?i)cpu.*high|high cpu|cpu.*usage": {
        "severity": "warning",
        "cause": "CPU saturation from high load or inefficient code",
        "impact": "Slow response times, potential throttling",
        "fix": "Scale up, optimize code, add caching"
    },
    r"(?i)memory.*high|high memory": {
        "severity": "warning",
        "cause": "Memory usage approaching limits",
        "impact": "Potential OOM errors if trend continues",
        "fix": "Check for memory leaks, increase memory limits"
    },
    r"(?i)latency.*high|slow.*response|response.*time": {
        "severity": "warning",
        "cause": "Increased response latency",
        "impact": "Poor user experience",
        "fix": "Check downstream services, optimize queries, add caching"
    },
    
    # Informational
    r"(?i)retry|retrying|retry.*attempt": {
        "severity": "info",
        "cause": "Temporary failure, automatic retry in progress",
        "impact": "Minimal - transient issue",
        "fix": "Monitor if retries succeed"
    },
    r"(?i)starting|started|initializing": {
        "severity": "info",
        "cause": "Service or component starting up",
        "impact": "Normal operation",
        "fix": "No action needed"
    },
    r"(?i)shutdown|stopping|terminated": {
        "severity": "info",
        "cause": "Service or component shutting down",
        "impact": "Service unavailable during shutdown",
        "fix": "Verify shutdown was intentional"
    }
}

def rule_based_analyze(log_text: str) -> Dict[str, Any]:
    """Tier 1: Quick pattern matching (no API call)"""
    for pattern, response in PATTERNS.items():
        if re.search(pattern, log_text):
            return {
                "log": log_text,
                "severity": response["severity"],
                "cause": response["cause"],
                "impact": response["impact"],
                "fix": response["fix"],
                "analysis": f"SEVERITY: {response['severity'].upper()}\nCAUSE: {response['cause']}\nIMPACT: {response['impact']}\nFIX: {response['fix']}",
                "from_cache": True,
                "tier": "rule-based",
                "timestamp": datetime.utcnow().isoformat()
            }
    return None  # No pattern matched, fallback to API


# ========== TIER 2: OPENROUTER API ==========
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

def get_free_model() -> str:
    """Get best available free model"""
    # Priority order: DeepSeek > Llama > Gemma
    return "deepseek/deepseek-chat-v3-0324:free"

def call_openrouter_api(log_text: str) -> Dict[str, Any]:
    """Tier 2: Call OpenRouter API for complex analysis"""
    
    if not OPENROUTER_API_KEY:
        return {
            "log": log_text,
            "severity": "info",
            "cause": "API key not configured",
            "impact": "Cannot perform advanced analysis",
            "fix": "Add OPENROUTER_API_KEY to .env",
            "analysis": "OpenRouter API key missing. Using basic analysis.",
            "from_cache": False,
            "tier": "api-failed",
            "timestamp": datetime.utcnow().isoformat()
        }
    
    prompt = f"""Analyze this log message and provide:
1. Severity (critical/warning/info)
2. Root cause
3. Business impact
4. Recommended fix

Log: {log_text}

Respond in JSON format with fields: severity, cause, impact, fix"""

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": get_free_model(),
                "messages": [
                    {"role": "system", "content": "You are a DevOps expert analyzing system logs. Respond only in JSON."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 500
            },
            timeout=15
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            # Try to parse JSON response
            try:
                import json as json_parser
                parsed = json_parser.loads(content)
                return {
                    "log": log_text,
                    "severity": parsed.get("severity", "info"),
                    "cause": parsed.get("cause", "Unknown"),
                    "impact": parsed.get("impact", "Unknown"),
                    "fix": parsed.get("fix", "Investigate manually"),
                    "analysis": content,
                    "from_cache": False,
                    "tier": "openrouter-api",
                    "model": get_free_model(),
                    "timestamp": datetime.utcnow().isoformat()
                }
            except:
                return {
                    "log": log_text,
                    "severity": "info",
                    "cause": "Unable to parse API response",
                    "impact": "Unknown",
                    "fix": "Review log manually",
                    "analysis": content[:500],
                    "from_cache": False,
                    "tier": "openrouter-api",
                    "timestamp": datetime.utcnow().isoformat()
                }
        else:
            return {
                "log": log_text,
                "severity": "info",
                "cause": f"API error: {response.status_code}",
                "impact": "Cannot analyze",
                "fix": "Check API key and try again",
                "analysis": f"API returned {response.status_code}",
                "from_cache": False,
                "tier": "api-error",
                "timestamp": datetime.utcnow().isoformat()
            }
            
    except requests.exceptions.Timeout:
        return {
            "log": log_text,
            "severity": "info",
            "cause": "API timeout",
            "impact": "Analysis delayed",
            "fix": "Try again or check network",
            "analysis": "Request timed out after 15 seconds",
            "from_cache": False,
            "tier": "api-timeout",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "log": log_text,
            "severity": "info",
            "cause": f"API error: {str(e)}",
            "impact": "Cannot analyze",
            "fix": "Check API configuration",
            "analysis": f"Error: {str(e)}",
            "from_cache": False,
            "tier": "api-error",
            "timestamp": datetime.utcnow().isoformat()
        }


# ========== MAIN ANALYZER (Two-Tier) ==========
def analyze_log(log_text: str, force_api: bool = False) -> Dict[str, Any]:
    """
    Two-tier log analysis:
    1. Rule-based pattern matching (fast, free)
    2. OpenRouter API (smart, fallback)
    """
    
    # Tier 1: Try rule-based first
    if not force_api:
        result = rule_based_analyze(log_text)
        if result:
            return result
    
    # Tier 2: Fallback to API
    return call_openrouter_api(log_text)