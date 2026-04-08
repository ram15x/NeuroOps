"""
Real GitHub Actions integration for BuildSense
"""
import requests
import os
from datetime import datetime

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "ram15x/NeuroOps")

def trigger_github_workflow(service_name: str, branch: str = "main"):
    """Trigger actual GitHub Actions workflow"""
    
    if not GITHUB_TOKEN:
        return {
            "status": "simulated",
            "message": "GITHUB_TOKEN not configured. Add to .env",
            "service": service_name,
            "branch": branch,
            "stages": _simulate_build_stages(service_name)
        }
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/deploy.yml/dispatches"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    payload = {"ref": branch, "inputs": {"service": service_name, "environment": "production"}}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 204:
            return {
                "status": "triggered",
                "message": f"GitHub Actions workflow triggered for {service_name}",
                "service": service_name,
                "branch": branch,
                "workflow_url": f"https://github.com/{GITHUB_REPO}/actions"
            }
        else:
            return {"status": "failed", "message": f"GitHub API error: {response.status_code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def _simulate_build_stages(service_name: str):
    """Fallback simulation when GitHub token not configured"""
    import random
    stages = ["checkout", "install", "test", "build", "dockerize", "deploy"]
    results = []
    failed_at = None
    
    for stage in stages:
        if random.random() < 0.15 and not failed_at:
            failed_at = stage
            results.append({"stage": stage, "status": "failed", "time_s": random.randint(2, 10)})
            break
        else:
            results.append({"stage": stage, "status": "success", "time_s": random.randint(5, 30)})
    
    return {
        "stages": results,
        "status": "failed" if failed_at else "success",
        "failed_at": failed_at,
        "total_time": sum(r["time_s"] for r in results)
    }