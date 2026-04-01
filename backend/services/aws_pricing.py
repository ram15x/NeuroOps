import boto3
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from backend.core.config import settings
from backend.core.logger import get_logger
from backend.services.redis_service import redis_client

logger = get_logger(__name__)

# Cache key for pricing data
PRICING_CACHE_KEY = "aws:pricing:ec2"
PRICING_CACHE_TTL = 86400  # 24 hours


def get_pricing_client():
    """Get AWS Pricing client"""
    return boto3.client(
        "pricing",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name="us-east-1"  # Pricing API only works in us-east-1
    )


def fetch_ec2_pricing() -> Dict[str, Dict]:
    """
    Fetch real EC2 on-demand pricing from AWS Pricing API
    Returns dict of instance_type -> price info
    """
    client = get_pricing_client()
    
    # EC2 instance types we care about
    instance_types = [
        "t2.micro", "t2.small", "t2.medium",
        "t3.micro", "t3.small", "t3.medium", "t3.large",
        "m5.large", "m5.xlarge", "m5.2xlarge",
        "c5.large", "c5.xlarge",
        "r5.large", "r5.xlarge"
    ]
    
    pricing_data = {}
    
    for instance_type in instance_types:
        try:
            # Query AWS Pricing API
            response = client.get_products(
                ServiceCode="AmazonEC2",
                Filters=[
                    {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
                    {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
                    {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
                    {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
                    {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
                    {"Type": "TERM_MATCH", "Field": "location", "Value": "US East (N. Virginia)"}
                ],
                MaxResults=1
            )
            
            if response.get("PriceList"):
                price_data = json.loads(response["PriceList"][0])
                
                # Extract hourly price from OnDemand terms
                terms = price_data.get("terms", {}).get("OnDemand", {})
                for term in terms.values():
                    for price_dimension in term.get("priceDimensions", {}).values():
                        hourly_price = float(price_dimension.get("pricePerUnit", {}).get("USD", 0))
                        monthly_price = hourly_price * 730  # Average hours per month
                        
                        pricing_data[instance_type] = {
                            "instance_type": instance_type,
                            "price_per_hour": round(hourly_price, 4),
                            "price_per_month": round(monthly_price, 2),
                            "cpu": get_cpu_count(instance_type),
                            "ram_gb": get_ram_gb(instance_type)
                        }
                        break
                    break
            
            logger.info(f"Fetched pricing for {instance_type}: ${pricing_data.get(instance_type, {}).get('price_per_hour', 0)}/hr")
            
        except Exception as e:
            logger.error(f"Failed to fetch pricing for {instance_type}: {e}")
            # Fallback to cached or default
            pricing_data[instance_type] = get_fallback_pricing(instance_type)
    
    return pricing_data


def get_cpu_count(instance_type: str) -> int:
    """Get CPU count for instance type"""
    cpu_map = {
        "t2.micro": 1, "t2.small": 1, "t2.medium": 2,
        "t3.micro": 2, "t3.small": 2, "t3.medium": 2, "t3.large": 2,
        "m5.large": 2, "m5.xlarge": 4, "m5.2xlarge": 8,
        "c5.large": 2, "c5.xlarge": 4,
        "r5.large": 2, "r5.xlarge": 4
    }
    return cpu_map.get(instance_type, 2)


def get_ram_gb(instance_type: str) -> int:
    """Get RAM in GB for instance type"""
    ram_map = {
        "t2.micro": 1, "t2.small": 2, "t2.medium": 4,
        "t3.micro": 1, "t3.small": 2, "t3.medium": 4, "t3.large": 8,
        "m5.large": 8, "m5.xlarge": 16, "m5.2xlarge": 32,
        "c5.large": 4, "c5.xlarge": 8,
        "r5.large": 16, "r5.xlarge": 32
    }
    return ram_map.get(instance_type, 4)


def get_fallback_pricing(instance_type: str) -> Dict:
    """Fallback pricing if API fails"""
    fallback = {
        "t2.micro": {"price_per_hour": 0.0116, "price_per_month": 8.47, "cpu": 1, "ram_gb": 1},
        "t2.small": {"price_per_hour": 0.0230, "price_per_month": 16.79, "cpu": 1, "ram_gb": 2},
        "t2.medium": {"price_per_hour": 0.0464, "price_per_month": 33.87, "cpu": 2, "ram_gb": 4},
        "t3.micro": {"price_per_hour": 0.0104, "price_per_month": 7.59, "cpu": 2, "ram_gb": 1},
        "t3.small": {"price_per_hour": 0.0208, "price_per_month": 15.18, "cpu": 2, "ram_gb": 2},
        "t3.medium": {"price_per_hour": 0.0416, "price_per_month": 30.37, "cpu": 2, "ram_gb": 4},
        "t3.large": {"price_per_hour": 0.0832, "price_per_month": 60.74, "cpu": 2, "ram_gb": 8},
        "m5.large": {"price_per_hour": 0.0960, "price_per_month": 70.08, "cpu": 2, "ram_gb": 8},
        "m5.xlarge": {"price_per_hour": 0.1920, "price_per_month": 140.16, "cpu": 4, "ram_gb": 16},
        "m5.2xlarge": {"price_per_hour": 0.3840, "price_per_month": 280.32, "cpu": 8, "ram_gb": 32},
        "c5.large": {"price_per_hour": 0.0850, "price_per_month": 62.05, "cpu": 2, "ram_gb": 4},
        "c5.xlarge": {"price_per_hour": 0.1700, "price_per_month": 124.10, "cpu": 4, "ram_gb": 8},
        "r5.large": {"price_per_hour": 0.1260, "price_per_month": 91.98, "cpu": 2, "ram_gb": 16},
        "r5.xlarge": {"price_per_hour": 0.2520, "price_per_month": 183.96, "cpu": 4, "ram_gb": 32}
    }
    return fallback.get(instance_type, {"price_per_hour": 0.05, "price_per_month": 36.50, "cpu": 2, "ram_gb": 4})


def get_cached_pricing() -> Dict:
    """Get cached pricing from Redis"""
    cached = redis_client.get(PRICING_CACHE_KEY)
    if cached:
        import json
        return json.loads(cached)
    return None


def update_pricing_cache():
    """Fetch fresh pricing and update Redis cache"""
    logger.info("Updating EC2 pricing cache")
    pricing = fetch_ec2_pricing()
    import json
    redis_client.setex(PRICING_CACHE_KEY, PRICING_CACHE_TTL, json.dumps(pricing))
    logger.info(f"Pricing cache updated with {len(pricing)} instance types")
    return pricing


def get_ec2_pricing(force_refresh: bool = False) -> Dict:
    """
    Get EC2 pricing from cache or fetch fresh
    """
    if not force_refresh:
        cached = get_cached_pricing()
        if cached:
            return cached
    
    return update_pricing_cache()