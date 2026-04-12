from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

# ========== INFRAMIND ==========
class MetricInput(BaseModel):
    metric: Optional[str] = "cpu"
    value: float = Field(..., ge=0, le=100, description="Current metric value")
    rolling_mean: float = Field(..., description="Rolling average over last N periods")
    rolling_std: float = Field(..., ge=0, description="Standard deviation over last N periods")
    value_diff: float = Field(..., description="Difference from previous value")
    force: Optional[bool] = Field(False, description="Force prediction even if model unavailable")

# ========== OPSGPT ==========
class LogInput(BaseModel):
    log: str = Field(..., min_length=5, max_length=5000, description="Log message to analyze")

class ClusterRequest(BaseModel):
    n_clusters: Optional[int] = Field(default=8, ge=2, le=20, description="Number of clusters for log grouping")

# ========== FAILURE PREDICTION (REAL AWS METRICS) ==========
class FailurePredictInput(BaseModel):
    """Real AWS EC2 metrics for failure prediction"""
    instance_id: str = Field(..., min_length=10, example="i-00dfb80a59da9a56d", description="EC2 Instance ID")
    cpu_usage: float = Field(..., ge=0, le=100, description="CPU utilization percentage")
    memory_usage: float = Field(..., ge=0, le=100, description="Memory utilization percentage")
    disk_usage: float = Field(..., ge=0, le=100, description="Disk utilization percentage")
    instance_age_days: int = Field(..., ge=0, description="Instance age in days")
    status_check_ok: Optional[bool] = Field(True, description="Instance status check passing")
    recent_reboots: Optional[int] = Field(0, ge=0, description="Number of reboots in last 24h")

class RULPredictInput(BaseModel):
    """Real AWS EC2 metrics for RUL prediction"""
    instance_id: str = Field(..., min_length=10, example="i-00dfb80a59da9a56d")
    cpu_usage: float = Field(..., ge=0, le=100)
    memory_usage: float = Field(..., ge=0, le=100)
    disk_usage: float = Field(..., ge=0, le=100)
    instance_age_days: int = Field(..., ge=0)

class ABTestInput(BaseModel):
    """Input for A/B testing models"""
    instance_id: str = Field(..., min_length=10, example="i-00dfb80a59da9a56d")
    cpu_usage: float = Field(..., ge=0, le=100)
    memory_usage: float = Field(..., ge=0, le=100)
    disk_usage: float = Field(..., ge=0, le=100)
    instance_age_days: int = Field(..., ge=0)

class ServiceSensorInput(BaseModel):
    """Individual service metrics for correlation"""
    service_name: str = Field(..., min_length=1, example="payment-service")
    sensors: List[float] = Field(..., min_items=1, max_items=4, description="[cpu, memory, disk, age]")

class CorrelationRequest(BaseModel):
    """Multi-service correlation request"""
    services: List[ServiceSensorInput] = Field(..., min_items=2, max_items=10)

# ========== SCALEWISE ==========
class CostInput(BaseModel):
    instance_type: str = Field(..., min_length=1, example="t3.medium")
    cpu_usage: float = Field(..., ge=0, le=100)
    ram_usage: float = Field(..., ge=0, le=100)
    hours_running: Optional[float] = Field(730.0, ge=1)

# ========== AUTO-HEALING ==========
class HealingInput(BaseModel):
    service: str = Field(..., min_length=1, example="i-00dfb80a59da9a56d")
    severity: str = Field(..., pattern="^(critical|warning|normal)$")
    metric_value: Optional[float] = Field(0.0, description="Metric value that triggered healing")
    metric_type: Optional[str] = Field("cpu", pattern="^(cpu|memory|disk|network)$")
    reason: Optional[str] = Field("Anomaly detected")

class PipelineInput(BaseModel):
    service: str = Field(..., min_length=1)
    metric_value: Optional[float] = 0.0
    metric_type: Optional[str] = "cpu"
    severity: str = Field(..., pattern="^(critical|warning|normal)$")
    log: Optional[str] = ""

# ========== BUILDSENSE ==========
class BuildInput(BaseModel):
    service: str = Field(..., min_length=1, example="payment-service")
    branch: Optional[str] = Field("main", min_length=1)

# ========== DEPLOYGUARD ==========
class DeployInput(BaseModel):
    service: str = Field(..., min_length=1, example="payment-service")
    version: Optional[str] = Field("v1.0.0")
    cpu_usage: float = Field(..., ge=0, le=100)
    memory_usage: float = Field(..., ge=0, le=100)
    error_rate: float = Field(..., ge=0, le=100)
    recent_failures: int = Field(..., ge=0)
    deployment_size_mb: float = Field(..., ge=0)

class SafeWindowInput(BaseModel):
    cpu_usage: float = Field(..., ge=0, le=100)
    memory_usage: float = Field(..., ge=0, le=100)
    error_rate: float = Field(..., ge=0, le=100)
    recent_failures: int = Field(..., ge=0)
    deployment_size_mb: float = Field(..., ge=0)

# ========== FLEET MANAGEMENT ==========
class FleetInput(BaseModel):
    instances: List[str] = Field(..., min_items=1, description="List of instance IDs")

# ========== FEATURE STORE ==========
class FeatureStoreInput(BaseModel):
    entity_id: str = Field(..., min_length=1)
    entity_type: Optional[str] = "ec2_instance"
    features: Dict[str, Any] = Field(..., min_items=1)

# ========== MODEL REGISTRY ==========
class ModelRegistryInput(BaseModel):
    model_name: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    accuracy: float = Field(..., ge=0, le=100)
    model_type: str = Field(..., min_length=1)
    dataset: str = Field(..., min_length=1)
    features: List[str] = Field(..., min_items=1)
    extra_metrics: Dict[str, Any] = Field(default_factory=dict)

class ModelPromoteInput(BaseModel):
    model_name: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)

# ========== LEGACY COMPATIBILITY (Deprecated) ==========
class FailureInput(BaseModel):
    """DEPRECATED: Use FailurePredictInput instead. Kept for backward compatibility."""
    unit_id: Optional[str] = "unknown"
    cpu_usage: Optional[float] = Field(None, ge=0, le=100)
    memory_usage: Optional[float] = Field(None, ge=0, le=100)
    disk_usage: Optional[float] = Field(None, ge=0, le=100)
    instance_age_days: Optional[int] = Field(None, ge=0)
    # Legacy sensor fields - deprecated
    sensor1: Optional[float] = None
    sensor2: Optional[float] = None
    sensor3: Optional[float] = None
    sensor4: Optional[float] = None