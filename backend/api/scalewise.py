from fastapi import APIRouter
from backend.services.redis_service import redis_client
from backend.models.schemas import CostInput, SafeWindowInput
from fastapi import APIRouter, Depends, Request, HTTPException
from backend.api.auth import get_current_user
import json
from backend.services.aws_service import list_ec2_instances
from backend.services.aws_pricing import get_ec2_pricing, update_pricing_cache

router = APIRouter()

# real AWS Ec2 pricing data
EC2_PRICING = {
    "t2.micro"   : {"cpu": 1,  "ram": 1,   "price_hr": 0.0116},
    "t2.small"   : {"cpu": 1,  "ram": 2,   "price_hr": 0.023},
    "t2.medium"  : {"cpu": 2,  "ram": 4,   "price_hr": 0.0464},
    "t3.micro"   : {"cpu": 2,  "ram": 1,   "price_hr": 0.0104},
    "t3.small"   : {"cpu": 2,  "ram": 2,   "price_hr": 0.0208},
    "t3.medium"  : {"cpu": 2,  "ram": 4,   "price_hr": 0.0416},
    "t3.large"   : {"cpu": 2,  "ram": 8,   "price_hr": 0.0832},
    "m5.large"   : {"cpu": 2,  "ram": 8,   "price_hr": 0.096},
    "m5.xlarge"  : {"cpu": 4,  "ram": 16,  "price_hr": 0.192},
    "m5.2xlarge" : {"cpu": 8,  "ram": 32,  "price_hr": 0.384},
    "c5.large"   : {"cpu": 2,  "ram": 4,   "price_hr": 0.085},
    "c5.xlarge"  : {"cpu": 4,  "ram": 8,   "price_hr": 0.17},
    "r5.large"   : {"cpu": 2,  "ram": 16,  "price_hr": 0.126},
    "r5.xlarge"  : {"cpu": 4,  "ram": 32,  "price_hr": 0.252},
}
HOURS_PER_MONTH = 730

@router.post("/scalewise/analyze")
def analyze_cost(data: CostInput):
    try:
        instance_type = data.instance_type
        cpu_usage     = data.cpu_usage
        ram_usage     = data.ram_usage
        hours_running = data.hours_running

        if instance_type not in EC2_PRICING:
            return {"error": f"Unknown instance type: {instance_type}"}

        current      = EC2_PRICING[instance_type]
        current_cost = round(current["price_hr"] * hours_running, 2)
        
        # Initialize flags and recommendations
        utilization_flag = False
        flag_reason = None
        recommendations = []
        best_match = None
        best_saving = 0
        upgrade_needed = False
        upgrade_target = None
        upgrade_cost_increase = 0

        # ========== UNDERUTILIZATION DETECTION (Wasteful Spend) ==========
        is_underutilized = cpu_usage < 20 and ram_usage < 30
        
        if is_underutilized:
            utilization_flag = True
            flag_reason = "underutilized"
            recommendations.append(
                f"⚠️ Instance is severely underutilized - CPU: {cpu_usage}%, RAM: {ram_usage}%"
            )
            recommendations.append(
                f"Consider downsizing to save costs while maintaining adequate capacity."
            )

        # ========== FIND CHEAPER ALTERNATIVES (Downgrade Path) ==========
        # Find cheaper instance that can still handle the workload
        for itype, specs in EC2_PRICING.items():
            if itype == instance_type:
                continue
            
            # Calculate required CPU/RAM based on current utilization
            required_cpu = max(1, round(current["cpu"] * cpu_usage / 100))
            required_ram = max(1, round(current["ram"] * ram_usage / 100))
            
            # Check if alternative instance can handle the load
            cpu_ok = specs["cpu"] >= required_cpu
            ram_ok = specs["ram"] >= required_ram
            
            if cpu_ok and ram_ok and specs["price_hr"] < current["price_hr"]:
                saving = round(
                    (current["price_hr"] - specs["price_hr"]) * hours_running, 2
                )
                if saving > best_saving:
                    best_saving = saving
                    best_match = itype
        
        if best_match:
            recommendations.append(
                f"💰 Downgrade {instance_type} → {best_match}: Save ${best_saving}/month"
            )

        # ========== HIGH UTILIZATION DETECTION (Risk / Upgrade Needed) ==========
        if cpu_usage > 85 or ram_usage > 85:
            utilization_flag = True
            flag_reason = "high_utilization"
            
            if cpu_usage > 85:
                recommendations.append(
                    f"⚠️ High CPU utilization: {cpu_usage}% — approaching saturation (recommended < 80%)"
                )
            if ram_usage > 85:
                recommendations.append(
                    f"⚠️ High memory utilization: {ram_usage}% — risk of OOM errors"
                )
            
            # Check if upgrade is needed
            upgrade_required = cpu_usage > 90 or ram_usage > 90
            
            if upgrade_required:
                upgrade_needed = True
                flag_reason = "critical_utilization"
                recommendations.append(
                    "🔴 CRITICAL: Instance at capacity — immediate upgrade recommended to prevent outages"
                )
            
            # Find upgrade candidates (next tier instances)
            upgrade_candidates = []
            for itype, specs in EC2_PRICING.items():
                if itype == instance_type:
                    continue
                
                # Check if upgrade provides more resources
                if (specs["cpu"] > current["cpu"] or specs["ram"] > current["ram"]):
                    # Calculate if it can handle current load with headroom
                    headroom_cpu = (specs["cpu"] - required_cpu) / specs["cpu"] * 100
                    headroom_ram = (specs["ram"] - required_ram) / specs["ram"] * 100
                    
                    if headroom_cpu > 20 and headroom_ram > 20:  # At least 20% headroom
                        cost_increase = round(
                            (specs["price_hr"] - current["price_hr"]) * hours_running, 2
                        )
                        upgrade_candidates.append({
                            "type": itype,
                            "cpu": specs["cpu"],
                            "ram": specs["ram"],
                            "cost_increase": cost_increase,
                            "headroom_cpu": round(headroom_cpu, 1),
                            "headroom_ram": round(headroom_ram, 1)
                        })
            
            if upgrade_candidates:
                # Sort by cost increase (cheapest upgrade first)
                upgrade_candidates.sort(key=lambda x: x["cost_increase"])
                best_upgrade = upgrade_candidates[0]
                upgrade_target = best_upgrade["type"]
                upgrade_cost_increase = best_upgrade["cost_increase"]  # FIXED: was est_upgrade
                
                recommendations.append(
                    f"📈 Recommended upgrade: {instance_type} → {best_upgrade['type']} "
                    f"(+${best_upgrade['cost_increase']}/month, provides {best_upgrade['headroom_cpu']}% CPU headroom)"
                )
                
                if len(upgrade_candidates) > 1:
                    recommendations.append(
                        f"Alternative: {upgrade_candidates[1]['type']} "
                        f"(+${upgrade_candidates[1]['cost_increase']}/month)"
                    )

        # ========== RIGHT-SIZED (Optimal) ==========
        if not utilization_flag and not best_match:
            recommendations.append(
                "✅ Instance is optimally sized. No changes needed."
            )
        elif not utilization_flag and best_match:
            recommendations.append(
                "💡 Consider downsizing to save costs while maintaining adequate performance."
            )

        # Calculate optimized cost
        if upgrade_needed and upgrade_target:
            optimized_cost = round(current_cost + upgrade_cost_increase, 2)
            saving_percent = 0
        elif best_match:
            optimized_cost = round(current_cost - best_saving, 2)
            saving_percent = round((best_saving / current_cost) * 100, 1) if current_cost > 0 else 0
        else:
            optimized_cost = current_cost
            saving_percent = 0

        # Determine status color and severity
        if upgrade_needed:
            status = "CRITICAL"
            severity = "high"
            status_color = "red"
        elif is_underutilized:
            status = "UNDERUTILIZED"
            severity = "warning"
            status_color = "yellow"
        elif cpu_usage > 85 or ram_usage > 85:
            status = "STRESSED"
            severity = "warning"
            status_color = "orange"
        else:
            status = "OPTIMAL"
            severity = "normal"
            status_color = "green"

        result = {
            "instance_type": instance_type,
            "cpu_usage": f"{cpu_usage}%",
            "ram_usage": f"{ram_usage}%",
            "current_cost": f"${current_cost}/month",
            "optimized_cost": f"${optimized_cost}/month",
            "potential_saving": f"${best_saving}/month",
            "saving_percent": f"{saving_percent}%",
            "utilization_flag": utilization_flag,
            "flag_reason": flag_reason,
            "status": status,
            "severity": severity,
            "status_color": status_color,
            "recommended_type": upgrade_target if upgrade_needed else (best_match or instance_type),
            "upgrade_needed": upgrade_needed,
            "recommendations": recommendations,
            "metrics": {
                "cpu_capacity": current["cpu"],
                "ram_capacity_gb": current["ram"],
                "cpu_utilized_cores": round(current["cpu"] * cpu_usage / 100, 1),
                "ram_utilized_gb": round(current["ram"] * ram_usage / 100, 1),
                "headroom_percent": round(min(100 - cpu_usage, 100 - ram_usage), 1)
            }
        }

        # Cache the result
        cache_key = f"scalewise:{instance_type}:{cpu_usage}:{ram_usage}"
        redis_client.setex(cache_key, 300, json.dumps(result))

        return result

    except Exception as e:
        return {"error": str(e)}


@router.get("/scalewise/pricing")
def get_pricing(
    request: Request,
    refresh: bool = False,
    _: dict = Depends(get_current_user)
):
    """Get EC2 pricing from AWS Pricing API"""
    try:
        pricing = get_ec2_pricing(force_refresh=refresh)
        return {
            "source": "live" if refresh else "cache",
            "total": len(pricing),
            "instances": list(pricing.values())
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/scalewise/refresh-pricing")
def refresh_pricing(
    request: Request,
    _: dict = Depends(get_current_user)
):
    """Force refresh EC2 pricing from AWS"""
    try:
        pricing = update_pricing_cache()
        return {
            "success": True,
            "total": len(pricing),
            "instances": list(pricing.values())
        }
    except Exception as e:
        return {"error": str(e)}
    

from backend.services.capacity_planner import get_capacity_report

@router.get("/scalewise/capacity/{instance_id}")
def capacity_plan(
    instance_id: str,
    _: dict = Depends(get_current_user)
):
    """Get capacity planning report for an EC2 instance"""
    try:
        report = get_capacity_report(instance_id)
        return report
    except Exception as e:
        return {"error": str(e)}


@router.get("/scalewise/savings")
def get_savings(_: dict = Depends(get_current_user)):
    """Get real cost savings from ScaleWise recommendations"""
    try:
        instances = list_ec2_instances()
        running_instances = [i for i in instances if i.get("state") == "running"]
        
        if not running_instances:
            return {"savings": 0, "message": "No running instances"}
        
        instance = running_instances[0]
        instance_type = instance.get("instance_type", "t3.medium")
        
        # Get current CPU usage
        cpu_key = f"real_cpu:{instance['instance_id']}"
        cpu_usage = redis_client.get(cpu_key)
        cpu_usage = float(cpu_usage) if cpu_usage else 12.0
        
        # Pricing map (hourly rates)
        pricing = {
            "t3.nano": 0.0052, "t3.micro": 0.0104, "t3.small": 0.0208,
            "t3.medium": 0.0416, "t3.large": 0.0832, "t3.xlarge": 0.1664,
            "t2.micro": 0.0116, "t2.small": 0.023, "t2.medium": 0.0464,
            "m5.large": 0.096, "m5.xlarge": 0.192, "c5.large": 0.085,
            "r5.large": 0.126
        }
        
        current_price = pricing.get(instance_type, 0.0416)
        
        # Find optimal instance based on CPU
        if cpu_usage < 20:
            # Recommend downgrade
            if instance_type in ["t3.medium", "t2.medium"]:
                optimal_type = "t3.micro"
                optimal_price = pricing.get(optimal_type, 0.0104)
            elif instance_type in ["t3.large", "m5.large", "c5.large"]:
                optimal_type = "t3.small"
                optimal_price = pricing.get(optimal_type, 0.0208)
            else:
                optimal_type = instance_type
                optimal_price = current_price
            
            savings_per_month = (current_price - optimal_price) * 730
            recommendation = f"CPU at {cpu_usage}% → Downgrade to {optimal_type}"
            
        elif cpu_usage > 80:
            savings_per_month = 0
            recommendation = f"⚠️ CPU at {cpu_usage}% → Consider scaling up"
        else:
            savings_per_month = 0
            recommendation = f"✅ Instance optimally sized (CPU {cpu_usage}%)"
        
        return {
            "savings": round(max(0, savings_per_month), 2),
            "currency": "USD",
            "period": "month",
            "recommendation": recommendation,
            "instance_type": instance_type,
            "cpu_usage": round(cpu_usage, 1)
        }
        
    except Exception as e:
        return {"savings": 0, "error": str(e)}


@router.post("/scalewise/safe-window")
def find_safe_window(data: SafeWindowInput):
    try:
        current_score = calculate_risk_score(data.model_dump())
        windows = []
        hours = ["02:00", "03:00", "04:00", "10:00", "14:00", "22:00"]

        for hour in hours:
            simulated = data.model_dump()
            
            # Simulate different load patterns based on time
            if hour in ["02:00", "03:00", "04:00"]:
                simulated["cpu_usage"] = max(0, data.cpu_usage * 0.3)
                simulated["ram_usage"] = max(0, data.ram_usage * 0.4)
            elif hour in ["10:00", "14:00"]:
                simulated["cpu_usage"] = data.cpu_usage * 0.9
                simulated["ram_usage"] = data.ram_usage * 0.85
            elif hour == "22:00":
                simulated["cpu_usage"] = max(0, data.cpu_usage * 0.5)
                simulated["ram_usage"] = max(0, data.ram_usage * 0.55)

            sim_score = calculate_risk_score(simulated)
            
            risk_level = get_risk_level(sim_score)
            is_recommended = sim_score < 35  # More conservative threshold
            
            windows.append({
                "time": hour,
                "risk": f"{sim_score}%",
                "level": risk_level,
                "recommended": is_recommended,
                "expected_load": f"CPU: {round(simulated['cpu_usage'])}% / RAM: {round(simulated['ram_usage'])}%"
            })

        # Find best window (lowest risk)
        best = min(windows, key=lambda x: float(x["risk"].replace("%", "")))
        
        # Find second best as alternative
        sorted_windows = sorted(windows, key=lambda x: float(x["risk"].replace("%", "")))
        alternative = sorted_windows[1] if len(sorted_windows) > 1 else None

        return {
            "current_risk": f"{current_score}%",
            "current_level": get_risk_level(current_score),
            "windows": windows,
            "best_window": best,
            "alternative_window": alternative,
            "recommendation": f"Deploy during {best['time']} for lowest risk ({best['risk']})",
            "warning": "Schedule deployments during off-peak hours (2 AM - 4 AM) for minimal business impact"
        }

    except Exception as e:
        return {"error": str(e)}


def calculate_risk_score(data: dict) -> float:
    cpu = data.get("cpu_usage", 0) / 100
    memory = data.get("ram_usage", data.get("memory_usage", 0)) / 100
    
    # Weighted risk calculation with buffer for sudden spikes
    base_risk = (cpu * 0.6 + memory * 0.4) * 100
    
    # Add penalty for near-critical thresholds
    if cpu > 0.85:
        base_risk += (cpu - 0.85) * 50
    if memory > 0.85:
        base_risk += (memory - 0.85) * 40
    
    return round(min(base_risk, 100), 2)


def get_risk_level(score: float) -> str:
    if score >= 75:
        return "CRITICAL"
    elif score >= 55:
        return "HIGH"
    elif score >= 35:
        return "MEDIUM"
    else:
        return "LOW"