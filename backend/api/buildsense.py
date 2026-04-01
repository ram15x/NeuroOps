from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.models.database import get_db
from backend.services.redis_service import redis_client
from datetime import datetime
import json
import random
from backend.models.schemas import BuildInput

router = APIRouter()

# build status definition
BUILD_STAGES = ["checkout", "install", "test", "build", "dockerize", "deploy"]

# Enhanced failure reasons with stage mapping
FAILURE_REASONS = {
    "test": [
        "Unit test failed: NullPointerException in PaymentService",
        "Test coverage below threshold: 67% (required 80%)",
        "Integration test timeout: Database connection refused",
        "AssertionError: Expected 200 but got 500 in AuthService",
        "Test suite failed: 12 tests failed, 3 errors"
    ],
    "build": [
        "Compilation error: Undefined reference to validatePayment()",
        "Go build failed: cannot find module golang.org/x/time/rate",
        "Java compilation: incompatible types in PaymentProcessor",
        "Rust build: 'unwrap()' called on 'None' value"
    ],
    "dockerize": [
        "Docker build failed: Base image not found",
        "Dockerfile syntax error: Unknown instruction: RUM",
        "COPY failed: no source files specified",
        "Image size exceeded limit: 2.3GB (max 1GB)"
    ],
    "deploy": [
        "Deployment timeout: Pod stuck in Pending state",
        "Connection refused: Registry unreachable",
        "Kubernetes API error: Insufficient quota",
        "Helm upgrade failed: template parse error"
    ],
    "install": [
        "npm install failed: Package not found",
        "Pip install: Could not find a version that satisfies the requirement",
        "Go mod download: git repository not found",
        "Dependency conflict: requests==2.28.0 incompatible with urllib3"
    ],
    "checkout": [
        "Repository access denied: Invalid SSH key",
        "Branch not found: feature/payment-refactor",
        "Git clone failed: Connection timeout",
        "Submodule update failed: Not initialized"
    ]
}

# Smart suggestion engine with stage and reason analysis
def get_intelligent_suggestion(failed_at: str, reason: str, pipeline_context: dict = None) -> dict:
    """
    Returns intelligent suggestions based on failure stage and actual reason
    """
    reason_lower = reason.lower()
    
    # Stage-specific intelligent suggestions
    if failed_at == "test":
        if "coverage" in reason_lower:
            return {
                "action": "Increase Test Coverage",
                "steps": [
                    "Run `pytest --cov=backend --cov-report=term-missing` to see uncovered lines",
                    "Add unit tests for uncovered functions in PaymentService",
                    "Update pytest.ini to set min coverage = 80%",
                    "Consider using coverage-badge to track progress"
                ],
                "quick_fix": "Add test cases for edge conditions and error paths",
                "severity": "HIGH"
            }
        elif "nullpointer" in reason_lower:
            return {
                "action": "Fix NullPointerException",
                "steps": [
                    "Check PaymentService for uninitialized objects",
                    "Add null checks before method calls",
                    "Use Optional pattern or @NotNull annotations",
                    "Review recent commits that modified PaymentService"
                ],
                "quick_fix": "Initialize paymentRepository before usage",
                "severity": "HIGH"
            }
        elif "timeout" in reason_lower:
            return {
                "action": "Resolve Test Timeout",
                "steps": [
                    "Check database connection pool size",
                    "Increase test timeout in pytest.ini",
                    "Mock external services in unit tests",
                    "Check for slow queries in integration tests"
                ],
                "quick_fix": "Set timeout=30 in @pytest.mark.timeout decorator",
                "severity": "MEDIUM"
            }
        else:
            return {
                "action": "Fix Failing Tests",
                "steps": [
                    f"Run failing test locally: pytest -k '{reason.split(':')[0]}'",
                    "Check test logs for detailed error",
                    "Verify test data fixtures are correct",
                    "Review recent code changes that affected test behavior"
                ],
                "quick_fix": "Debug the specific test case identified in logs",
                "severity": "HIGH"
            }
    
    elif failed_at == "dockerize":
        if "coverage" in reason_lower:
            return {
                "action": "Coverage Threshold Not Met",
                "steps": [
                    "Increase test coverage to meet 80% threshold",
                    "Add unit tests for uncovered modules",
                    "Use pytest-cov to identify missing coverage",
                    "Consider excluding certain files from coverage check"
                ],
                "quick_fix": "Add test coverage for critical paths before dockerizing",
                "severity": "HIGH"
            }
        elif "base image" in reason_lower or "image not found" in reason_lower:
            return {
                "action": "Fix Docker Base Image",
                "steps": [
                    "Check if Docker Hub is accessible",
                    "Verify base image name in Dockerfile: FROM python:3.11-slim",
                    "Pull base image manually: docker pull python:3.11-slim",
                    "Use authenticated registry if needed: docker login"
                ],
                "quick_fix": "docker pull python:3.11-slim && docker build -t app .",
                "severity": "HIGH"
            }
        elif "syntax error" in reason_lower:
            return {
                "action": "Fix Dockerfile Syntax",
                "steps": [
                    "Run docker build -t test . to see exact error",
                    "Check for missing colons or incorrect commands",
                    "Validate Dockerfile with hadolint",
                    "Refer to Dockerfile best practices documentation"
                ],
                "quick_fix": "Correct Dockerfile command syntax and rebuild",
                "severity": "MEDIUM"
            }
        elif "image size" in reason_lower:
            return {
                "action": "Reduce Docker Image Size",
                "steps": [
                    "Use multi-stage builds to reduce final image size",
                    "Remove unnecessary packages after build",
                    "Use alpine-based base images where possible",
                    "Clean apt cache: rm -rf /var/lib/apt/lists/*"
                ],
                "quick_fix": "Add --squash flag or use smaller base image",
                "severity": "MEDIUM"
            }
        else:
            return {
                "action": "Fix Docker Build",
                "steps": [
                    "Check Docker daemon: docker ps",
                    "Verify Dockerfile exists and is valid",
                    "Ensure all required files are in build context",
                    "Check disk space: df -h"
                ],
                "quick_fix": "docker build --no-cache -t service:latest .",
                "severity": "HIGH"
            }
    
    elif failed_at == "deploy":
        if "timeout" in reason_lower or "stuck" in reason_lower:
            return {
                "action": "Resolve Deployment Timeout",
                "steps": [
                    "Check pod status: kubectl get pods -n <namespace>",
                    "Describe pending pod: kubectl describe pod <pod-name>",
                    "Check resource quotas: kubectl describe resourcequotas",
                    "Verify node resources: kubectl top nodes"
                ],
                "quick_fix": "Increase resource limits or add more nodes to cluster",
                "severity": "HIGH"
            }
        elif "registry" in reason_lower or "connection refused" in reason_lower:
            return {
                "action": "Fix Registry Connectivity",
                "steps": [
                    "Check registry URL: docker images | grep service",
                    "Verify credentials: docker login registry.example.com",
                    "Test connectivity: curl -v https://registry.example.com/v2/",
                    "Check network policies and firewalls"
                ],
                "quick_fix": "docker push with correct authentication",
                "severity": "CRITICAL"
            }
        elif "insufficient quota" in reason_lower:
            return {
                "action": "Resolve Resource Quota",
                "steps": [
                    "Check namespace quota: kubectl get quota -n <namespace>",
                    "Request quota increase from cluster admin",
                    "Optimize pod resource requests and limits",
                    "Clean up unused resources in namespace"
                ],
                "quick_fix": "kubectl delete pod <old-pod> to free resources",
                "severity": "HIGH"
            }
        else:
            return {
                "action": "Fix Deployment",
                "steps": [
                    "Check deployment logs: kubectl logs deployment/<service>",
                    "Verify rollout status: kubectl rollout status deployment/<service>",
                    "Check events: kubectl get events --sort-by='.lastTimestamp'",
                    "Rollback if needed: kubectl rollout undo deployment/<service>"
                ],
                "quick_fix": "kubectl rollout restart deployment/<service>",
                "severity": "HIGH"
            }
    
    elif failed_at == "install":
        if "package not found" in reason_lower:
            return {
                "action": "Fix Missing Package",
                "steps": [
                    "Check package name and version in requirements.txt",
                    "Verify package exists in repository",
                    "Use correct package index: pip install -i https://pypi.org/simple",
                    "Consider using alternative package or fork"
                ],
                "quick_fix": "Update package version to existing one",
                "severity": "MEDIUM"
            }
        elif "dependency conflict" in reason_lower:
            return {
                "action": "Resolve Dependency Conflicts",
                "steps": [
                    "Run pip check to see conflicts",
                    "Use pip-tools to compile dependencies",
                    "Freeze exact versions in requirements.txt",
                    "Consider using virtual environment"
                ],
                "quick_fix": "pip install --upgrade pip && pip install -r requirements.txt",
                "severity": "MEDIUM"
            }
        else:
            return {
                "action": "Fix Installation",
                "steps": [
                    "Clear pip cache: pip cache purge",
                    "Upgrade pip: pip install --upgrade pip",
                    "Check Python version compatibility",
                    "Install with verbose flag: pip install -v -r requirements.txt"
                ],
                "quick_fix": "rm -rf .venv && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt",
                "severity": "MEDIUM"
            }
    
    elif failed_at == "build":
        if "compilation error" in reason_lower:
            return {
                "action": "Fix Compilation Error",
                "steps": [
                    f"Check error: {reason}",
                    "Verify function signatures match calls",
                    "Add missing imports or type definitions",
                    "Run local build: python setup.py build"
                ],
                "quick_fix": "Fix syntax errors in reported line",
                "severity": "HIGH"
            }
        else:
            return {
                "action": "Fix Build Error",
                "steps": [
                    "Review build logs for exact error",
                    "Check if all dependencies are installed",
                    "Verify build environment configuration",
                    "Clean build artifacts and rebuild"
                ],
                "quick_fix": "rm -rf build/ dist/ && python setup.py clean && python setup.py build",
                "severity": "HIGH"
            }
    
    elif failed_at == "checkout":
        if "access denied" in reason_lower or "ssh key" in reason_lower:
            return {
                "action": "Fix Git Authentication",
                "steps": [
                    "Check SSH key: ssh -T git@github.com",
                    "Add SSH key to agent: ssh-add ~/.ssh/id_rsa",
                    "Verify repository permissions",
                    "Use HTTPS with personal access token as fallback"
                ],
                "quick_fix": "git config --global url.'https://github.com/'.insteadOf 'git@github.com:'",
                "severity": "HIGH"
            }
        elif "branch not found" in reason_lower:
            return {
                "action": "Check Branch Existence",
                "steps": [
                    "List branches: git branch -r",
                    "Verify branch name spelling",
                    "Fetch latest branches: git fetch --all",
                    "Create branch if it doesn't exist"
                ],
                "quick_fix": "git checkout -b <branch> origin/<branch>",
                "severity": "MEDIUM"
            }
        else:
            return {
                "action": "Fix Git Checkout",
                "steps": [
                    "Verify git is installed: git --version",
                    "Check repository URL is correct",
                    "Clear git cache: git gc --prune=now",
                    "Try cloning with depth=1 for faster clone"
                ],
                "quick_fix": "git clone --depth 1 <repo-url>",
                "severity": "MEDIUM"
            }
    
    # Default fallback
    return {
        "action": "Check Pipeline Logs",
        "steps": [
            f"Review logs for {failed_at} stage",
            "Check recent code changes that might affect build",
            "Verify all required services are running",
            "Try rebuilding with --no-cache flag"
        ],
        "quick_fix": "Rerun pipeline with debug logging enabled",
        "severity": "MEDIUM"
    }

#simulate pipeline with enhanced failure reasons
def simulate_pipeline(service: str, branch: str) -> dict:
    stages = []
    failed_at = None
    failure_reason = None

    # 25% chance of failure (slightly increased for better testing)
    fail_stage = random.randint(2, 5) if random.random() < 0.25 else None

    for i, stage in enumerate(BUILD_STAGES):
        if failed_at:
            stages.append({
                "stage": stage,
                "status": "skipped",
                "time_s": 0
            })
            continue

        duration = random.randint(2, 30)

        if fail_stage and i == fail_stage:
            # Pick a reason specific to this stage
            stage_reasons = FAILURE_REASONS.get(stage, ["General failure occurred"])
            failure_reason = random.choice(stage_reasons)
            
            stages.append({
                "stage": stage,
                "status": "failed",
                "time_s": duration,
                "reason": failure_reason
            })
            failed_at = stage
        else:
            stages.append({
                "stage": stage,
                "status": "success",
                "time_s": duration
            })

    total_time = sum(s["time_s"] for s in stages)
    status = "failed" if failed_at else "success"

    result = {
        "service": service,
        "branch": branch,
        "status": status,
        "failed_at": failed_at,
        "failure_reason": failure_reason,
        "stages": stages,
        "total_time": f"{total_time}s",
        "triggered_at": datetime.utcnow().isoformat(),
        "commit": f"#{random.randint(1000,9999)}",
    }
    
    return result

#trigger build
@router.post("/buildsense/trigger")
def trigger_build(data: BuildInput, db: Session = Depends(get_db)):
    try:
        service = data.service
        branch = data.branch

        # run pipeline simulation
        pipeline = simulate_pipeline(service, branch)

        # enhanced risk assessment
        risk = assess_build_risk(pipeline)
        pipeline["risk"] = risk

        # AI suggestion with intelligent context
        if pipeline["status"] == "failed":
            suggestion = get_intelligent_suggestion(
                pipeline["failed_at"],
                pipeline.get("failure_reason", ""),
                pipeline
            )
            pipeline["suggestion"] = suggestion
            pipeline["quick_fix"] = suggestion["quick_fix"]
            
            # Add helpful next steps
            pipeline["next_steps"] = suggestion["steps"]
            pipeline["severity"] = suggestion["severity"]

        # Cache result
        redis_client.setex(
            f"build:{service}",
            300,
            json.dumps(pipeline)
        )

        return pipeline

    except Exception as e:
        return {"error": str(e), "message": "Build trigger failed"}


#get build history
@router.get("/buildsense/history/{service}")
def build_history(service: str):
    cached = redis_client.get(f"build:{service}")
    if cached:
        return json.loads(cached)
    return {"service": service, "message": "No recent builds found"}


#pipeline health overview
@router.get("/buildsense/overview")
def pipeline_overview():
    services = [
        "payment-service",
        "auth-service",
        "api-gateway",
        "notification-service",
        "database-proxy"
    ]
    overview = []
    failed_count = 0
    success_count = 0
    
    for s in services:
        cached = redis_client.get(f"build:{s}")
        if cached:
            data = json.loads(cached)
            status = data["status"]
            if status == "failed":
                failed_count += 1
            else:
                success_count += 1
                
            overview.append({
                "service": s,
                "status": status,
                "branch": data["branch"],
                "time": data["total_time"],
                "commit": data["commit"],
                "failed_at": data.get("failed_at"),
                "severity": data.get("severity", "LOW") if status == "failed" else "N/A"
            })
        else:
            overview.append({
                "service": s,
                "status": "no builds yet",
                "branch": "—",
                "time": "—",
                "commit": "—"
            })
    
    # Add summary statistics
    total_builds = len([o for o in overview if o["status"] not in ["no builds yet"]])
    
    return {
        "pipelines": overview, 
        "total": len(overview),
        "summary": {
            "total_builds": total_builds,
            "successful": success_count,
            "failed": failed_count,
            "success_rate": f"{round(success_count/total_builds*100, 1)}%" if total_builds > 0 else "0%"
        }
    }


def assess_build_risk(pipeline: dict) -> dict:
    failed_stages = [s for s in pipeline["stages"] if s["status"] == "failed"]
    total_time = sum(s["time_s"] for s in pipeline["stages"])
    
    # Extract numeric time value
    time_value = int(pipeline["total_time"].replace("s", "")) if "s" in pipeline["total_time"] else 0

    if pipeline["status"] == "failed":
        # Enhanced risk based on which stage failed
        stage_risk_map = {
            "test": "HIGH",
            "deploy": "CRITICAL",
            "dockerize": "HIGH",
            "build": "HIGH",
            "install": "MEDIUM",
            "checkout": "MEDIUM"
        }
        level = stage_risk_map.get(pipeline["failed_at"], "HIGH")
        
        message = f"Build failed at {pipeline['failed_at']} stage"
        if pipeline.get("failure_reason"):
            message += f": {pipeline['failure_reason'][:100]}"
            
    elif time_value > 120:
        level = "MEDIUM"
        message = f"Build time exceeding normal threshold ({pipeline['total_time']})"
    elif time_value > 60:
        level = "LOW"
        message = f"Build time slightly elevated ({pipeline['total_time']})"
    else:
        level = "LOW"
        message = "Build healthy and within normal parameters"

    return {
        "level": level,
        "message": message,
        "total_time": pipeline["total_time"]
    }