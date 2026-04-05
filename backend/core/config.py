from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
load_dotenv()

class Settings(BaseSettings):
    # App
    APP_NAME: str = "NeuroOps"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    
    # Database
    DB_HOST: str = "localhost"
    DB_PORT: int = 5433
    DB_NAME: str = "neuroops_db"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
    
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    
    @property
    def REDIS_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
    
    # Ollama
    OLLAMA_HOST: str = "localhost"
    OLLAMA_PORT: int = 11434
    OLLAMA_MODEL: str = "phi3:mini"
    OLLAMA_TIMEOUT: int = 30
    
    
    @property
    def OLLAMA_URL(self) -> str:
        return f"http://{self.OLLAMA_HOST}:{self.OLLAMA_PORT}"
    
    # ML Models
    MODEL_PATH: str = "ml_models/saved/"
    
    # InfraMind
    INFRAMIND_MODEL_FILE: str = "inframind_model.pkl"
    INFRAMIND_SCALER_FILE: str = "inframind_scaler.pkl"
    SHAP_BACKGROUND_SAMPLES: int = 100
    
    # ========== UPDATED: REAL DATA MODELS ==========
    # Failure Model - Now using XGBoost trained on REAL EC2 data
    FAILURE_MODEL_FILE: str = "xgboost_production_model.pkl"
    FAILURE_MODEL_METADATA: str = "model_metadata.pkl"
    FAILURE_SCALER_FILE: str = ""  # XGBoost doesn't need scaler
    
    # RUL Model - New model trained on REAL EC2 data
    RUL_MODEL_FILE: str = "rul_real_model.pkl"
    RUL_SCALER_FILE: str = "rul_real_scaler.pkl"
    RUL_MODEL_METADATA: str = "rul_model_metadata.pkl"
    
    # Keep old config for backward compatibility (will be removed later)
    RUL_MODEL_A_FILE: str = "rul_real_model.pkl"  # Point to new model
    RUL_SCALER_A_FILE: str = "rul_real_scaler.pkl"
    RUL_MODEL_B_FILE: str = ""  # Deprecated
    RUL_SCALER_B_FILE: str = ""  # Deprecated
    # ========== END UPDATED ==========
    
    RUL_MODEL_A_NAME: str = "RandomForestRegressor (RUL on REAL EC2 data)"
    RUL_URGENCY_CRITICAL: int = 10
    RUL_URGENCY_HIGH: int = 30
    RUL_URGENCY_MEDIUM: int = 60
    HOURS_PER_CYCLE: float = 1.0
    
    # A/B Testing
    AB_AGREEMENT_STRONG: float = 90.0
    AB_AGREEMENT_MODERATE: float = 70.0
    
    # Severity thresholds
    SEVERITY_CRITICAL_THRESHOLD: float = -0.15
    SEVERITY_WARNING_THRESHOLD: float = -0.05
    
    # Rule-based anomaly detection
    ANOMALY_VALUE_THRESHOLD: float = 90.0
    ANOMALY_VALUE_DIFF_THRESHOLD: float = 50.0
    ANOMALY_FORCED_SCORE: float = -0.20
    
    # Drift Detection
    BASELINE_ANOMALY_RATE: float = 0.05
    DRIFT_THRESHOLD: float = 0.15
    DRIFT_WARNING_THRESHOLD: float = 0.15
    DRIFT_CRITICAL_THRESHOLD: float = 0.30
    WINDOW_SIZE: int = 100
    MIN_PREDICTIONS_FOR_DRIFT: int = 20
    DRIFT_STATUS_CACHE_TTL: int = 300
    INITIAL_CONTAMINATION: float = 0.05
    
    # Log Clustering
    LOG_CLUSTER_MAX_ROWS: int = 5000
    LOG_CLUSTER_MAX_FEATURES: int = 500
    LOG_CLUSTER_DEFAULT_K: int = 8
    LOG_CLUSTER_MAX_K: int = 20
    LOG_CLUSTER_CACHE_TTL: int = 86400
    
    # OpsGPT
    OPSGPT_CACHE_TTL: int = 300
    OPSGPT_BATCH_MAX: int = 5
    
    # Task Manager
    TASK_TTL: int = 3600
    
    # ========== FEATURE STORE ==========
    FEATURE_STORE_TTL: int = 86400  # 24 hours cache TTL
    FEATURE_STORE_MAX_HISTORY: int = 1000  # max history records per entity
    FEATURE_STORE_BATCH_SIZE: int = 100  # batch size for bulk operations
    FEATURE_STORE_RETENTION_DAYS: int = 30  # days to keep feature history
    
    # ========== AUTO-HEALING ==========
    AUTO_HEALING_ENABLED: bool = True
    HEALING_COOLDOWN_MINUTES: int = 30
    HEALING_MAX_RETRIES: int = 2
    SCALE_DOWN_ENABLED: bool = False  
    HEALING_ACTION_CRITICAL: str = "RESTART AND SCALE"
    HEALING_ACTION_WARNING: str = "SCALE_UP"
    HEALING_ACTION_NORMAL: str = "NO_ACTION"
    HEALING_STEPS_CRITICAL: List[str] = [
        "1. Restart crashed container",
        "2. Scale replicas to 3",
        "3. Notify on-call engineer",
        "4. Create incident ticket"
    ]
    HEALING_STEPS_WARNING: List[str] = [
        "1. Increase CPU limit by 50%",
        "2. Scale replicas to 2",
        "3. Monitor for 5 minutes",
        "4. Alert team on Slack"
    ]
    HEALING_STEPS_NORMAL: List[str] = [
        "1. Continue monitoring",
        "2. Log health check"
    ]
    HEALING_CACHE_TTL: int = 300
    INCIDENT_CREATION_ENABLED: bool = True
    
    # ========== METRICS ANALYZER ==========
    MAX_INSTANCES_PER_RUN: int = 5
    ANALYZER_RETRY_DELAY: int = 5  # seconds between retries
    
    # Failure Correlation
    NUM_SENSORS: int = 4  # Reduced to 4 (CPU, Memory, Disk, Age) for REAL data
    CORRELATION_MIN_SERVICES: int = 2
    CORRELATION_RUL_THRESHOLD: int = 20
    CORRELATION_MESSAGE_CORRELATED: str = "Multiple services showing similar degradation patterns — potential systemic issue"
    CORRELATION_MESSAGE_INDEPENDENT: str = "Services showing independent degradation patterns"
    URGENCY_RISK_LEVELS: List[str] = ["CRITICAL", "HIGH"]
    
    # Sensor Variation (keeping for backward compatibility)
    SENSOR_VARIATION_STRENGTH: float = 0.08
    SENSOR_VARIATION_MIN: float = 0.97
    SENSOR_VARIATION_MAX: float = 1.05
    DEGRADATION_FACTOR_MIN: float = 0.7
    DEGRADATION_FACTOR_MAX: float = 1.3
    CRITICAL_SENSORS: List[int] = [1, 2, 3]
    MODERATE_SENSORS: List[int] = [4]
    CRITICAL_SENSOR_DEGRADATION_MIN: float = 0.95
    CRITICAL_SENSOR_DEGRADATION_MAX: float = 1.15
    MODERATE_SENSOR_DEGRADATION_MIN: float = 0.98
    MODERATE_SENSOR_DEGRADATION_MAX: float = 1.08
    STABLE_SENSOR_DEGRADATION_MIN: float = 0.99
    STABLE_SENSOR_DEGRADATION_MAX: float = 1.01
    SENSOR_VALUE_CAPS: Dict[str, float] = {
        "sensor3": 1700.0,
        "sensor4": 1500.0
    }
    SENSOR_CAP_MULTIPLIER: float = 1.05
    
    # Service Baselines (updated for REAL data - using 4 features)
    SERVICE_BASELINES: Dict[str, Dict[str, float]] = {
        "default": {
            "cpu": 50.0,
            "memory": 40.0,
            "disk": 30.0,
            "age": 30
        },
        "engine_api": {
            "cpu": 45.0,
            "memory": 35.0,
            "disk": 25.0,
            "age": 30
        },
        "payment_service": {
            "cpu": 60.0,
            "memory": 50.0,
            "disk": 40.0,
            "age": 30
        },
        "auth_service": {
            "cpu": 40.0,
            "memory": 30.0,
            "disk": 20.0,
            "age": 30
        },
        "cache_layer": {
            "cpu": 35.0,
            "memory": 45.0,
            "disk": 15.0,
            "age": 30
        }
    }
    
    SERVICE_DEGRADATION_RATES: Dict[str, float] = {
        "default": 1.0,
        "engine_api": 1.0,
        "payment_service": 1.2,
        "auth_service": 0.8,
        "cache_layer": 1.5
    }
    
    # Data Paths
    DATA_PATH: str = "datasets"
    
    # Rate Limits
    RATE_LIMIT_POST: str = "20/minute"
    RATE_LIMIT_GET: str = "30/minute"
    
    # JWT
    JWT_SECRET: str = "your-secret-key-change-in-prod"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_MINUTES: int = 30
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    
    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "null"
    ]
    
    # AWS
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"
    S3_BUCKET: str = "neuroops-models"
    SNS_TOPIC_ARN: Optional[str] = None
    EC2_INSTANCE_ID: str = "i-00dfb80a59da9a56d"
    
    # Health Check
    HEALTH_CHECK_TIMEOUT: int = 5
    
    # Dashboard
    DASHBOARD_REFRESH_MS: int = 5000
    WEBSOCKET_HEARTBEAT: int = 30
    
    # Alerts
    ALERT_CACHE_TTL: int = 300
    DEFAULT_ADMIN_USERNAME: str = "admin"
    DEFAULT_ADMIN_EMAIL: str = "admin@neuroops.local"
    DEFAULT_ADMIN_PASSWORD: str = "admin123"
    SYSTEM_STATUS_TTL: int = 60
    SLACK_WEBHOOK_URL: Optional[str] = None
    SLACK_NOTIFICATIONS_ENABLED: bool = False
    
    # Pydantic V2 configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"
    )

settings = Settings()