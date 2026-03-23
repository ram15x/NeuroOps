from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

#infraMind input
class MetricInput(BaseModel):
    metric: Optional[str] = "unknown"
    value: float = Field(..., ge=0, le=1000, description="Metric value")
    rolling_mean: float = Field(..., ge=0, le=1000)
    rolling_std: float = Field(..., ge=0, le=1000)
    value_diff: float = Field(..., ge=-1000, le=1000)
    force: Optional[bool] = False

#OpsGPT input
class LogInput(BaseModel):
    log: str = Field(..., min_length=5, max_length=5000)

# failure prediction input
class FailureInput(BaseModel):
    unit_id: Optional[str] = "unknown"
    sensor1: float = 0.0
    sensor2: float = 0.0
    sensor3: float = 0.0
    sensor4: float = 0.0
    sensor5: float = 0.0
    sensor6: float = 0.0
    sensor7: float = 0.0
    sensor8: float = 0.0
    sensor9: float = 0.0
    sensor10: float = 0.0
    sensor11: float = 0.0
    sensor12: float = 0.0
    sensor13: float = 0.0
    sensor14: float = 0.0
    sensor15: float = 0.0
    sensor16: float = 0.0
    sensor17: float = 0.0
    sensor18: float = 0.0
    sensor19: float = 0.0
    sensor20: float = 0.0
    sensor21: float = 0.0
    sensor22: float = 0.0
    sensor23: float = 0.0
    sensor24: float = 0.0

#scaleWise input
class CostInput(BaseModel):
    instance_type: str = Field(..., min_length=1)
    cpu_usage: float = Field(..., ge=0, le=100)
    ram_usage: float = Field(..., ge=0, le=100)
    hours_running: Optional[float] = 730.0

#auto-heal input
class HealingInput(BaseModel):
    service: str = Field(..., min_length=1)
    severity: str = Field(..., pattern="^(critical|warning|normal)$")
    metric_value: Optional[float] = 0.0
    reason: Optional[str] = "Anomaly detected"

#pipeline input
class PipelineInput(BaseModel):
    service: str = Field(..., min_length=1)
    metric_value: Optional[float] = 0.0
    severity: str = Field(..., pattern="^(critical|warning|normal)$")
    log: Optional[str] = ""

#buildsense input
class BuildInput(BaseModel):
    service: str = Field(..., min_length=1)
    branch: Optional[str] = "main"

#deployguard input
class DeployInput(BaseModel):
    service: str = Field(..., min_length=1)
    version: Optional[str] = "v1.0.0"
    cpu_usage: float = Field(..., ge=0, le=100)
    memory_usage: float = Field(..., ge=0, le=100)
    error_rate: float = Field(..., ge=0, le=100)
    recent_failures: int = Field(..., ge=0)
    deployment_size_mb: float = Field(..., ge=0)

# Safe-window input
class SafeWindowInput(BaseModel):
    cpu_usage: float = Field(..., ge=0, le=100)
    memory_usage: float = Field(..., ge=0, le=100)
    error_rate: float = Field(..., ge=0, le=100)
    recent_failures: int = Field(..., ge=0)
    deployment_size_mb: float = Field(..., ge=0)

# fleet input
class FleetInput(BaseModel):
    instances: list
    
class ClusterRequest(BaseModel):
    n_clusters: Optional[int] = Field(default=8, ge=2, le=20)
    
class ServiceSensorInput(BaseModel):
    service_name: str         = Field(..., min_length=1)
    sensors     : List[float] = Field(..., min_items=1, max_items=24)

class CorrelationRequest(BaseModel):
    services: List[ServiceSensorInput] = Field(..., min_items=2, max_items=10)
    
class FeatureStoreInput(BaseModel):
    entity_id  : str            = Field(..., min_length=1)
    entity_type: Optional[str]  = "unknown"
    features   : Dict[str, Any] = Field(..., min_items=1)
    
class ModelRegistryInput(BaseModel):
    model_name   : str        = Field(..., min_length=1)
    version      : str        = Field(..., min_length=1)
    accuracy     : float      = Field(..., ge=0, le=100)
    model_type   : str        = Field(..., min_length=1)
    dataset      : str        = Field(..., min_length=1)
    features     : List[str]  = Field(..., min_items=1)
    extra_metrics: Dict[str, Any] = {}

class ModelPromoteInput(BaseModel):
    model_name: str = Field(..., min_length=1)
    version   : str = Field(..., min_length=1)