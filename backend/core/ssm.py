"""
AWS SSM Parameter Store integration for secure configuration.
"""
import boto3
import os
from functools import lru_cache


@lru_cache(maxsize=32)
def get_ssm_parameter(name: str, decrypt: bool = True) -> str:
    """
    Retrieve a parameter from AWS SSM Parameter Store.
    Falls back to environment variable if not in AWS.
    """
    # Check if we're running in AWS
    if os.getenv("AWS_EXECUTION_ENV") or os.getenv("ENV") == "production":
        try:
            client = boto3.client('ssm', region_name=os.getenv("AWS_REGION", "us-east-1"))
            response = client.get_parameter(Name=name, WithDecryption=decrypt)
            return response['Parameter']['Value']
        except Exception as e:
            print(f"SSM parameter {name} not found, falling back to env: {e}")
    
    # Fallback to environment variable for local development
    env_name = name.replace("/neuroops/", "").replace("/", "_").upper()
    return os.getenv(env_name, "")


def load_config_from_ssm():
    """
    Load all configuration from SSM in production.
    Returns a dict of config values.
    """
    if not (os.getenv("AWS_EXECUTION_ENV") or os.getenv("ENV") == "production"):
        return {}
    
    config = {}
    
    # Database
    config["DB_PASSWORD"] = get_ssm_parameter("/neuroops/db/password", decrypt=True)
    config["DB_HOST"] = get_ssm_parameter("/neuroops/db/host", decrypt=False)
    config["DB_NAME"] = get_ssm_parameter("/neuroops/db/name", decrypt=False)
    config["DB_USER"] = get_ssm_parameter("/neuroops/db/user", decrypt=False)
    config["DB_PORT"] = get_ssm_parameter("/neuroops/db/port", decrypt=False)
    
    # Redis
    config["REDIS_HOST"] = get_ssm_parameter("/neuroops/redis/host", decrypt=False)
    config["REDIS_PORT"] = get_ssm_parameter("/neuroops/redis/port", decrypt=False)
    
    # JWT
    config["JWT_SECRET"] = get_ssm_parameter("/neuroops/jwt/secret", decrypt=True)
    
    # AWS
    config["AWS_ACCESS_KEY_ID"] = get_ssm_parameter("/neuroops/aws/access_key", decrypt=True)
    config["AWS_SECRET_ACCESS_KEY"] = get_ssm_parameter("/neuroops/aws/secret_key", decrypt=True)
    
    # OpenRouter
    config["OPENROUTER_API_KEY"] = get_ssm_parameter("/neuroops/openrouter/api_key", decrypt=True)
    
    # GitHub
    config["GITHUB_TOKEN"] = get_ssm_parameter("/neuroops/github/token", decrypt=True)
    
    return {k: v for k, v in config.items() if v}