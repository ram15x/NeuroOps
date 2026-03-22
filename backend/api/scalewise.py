from fastapi import APIRouter
from backend.services.redis_service import redis_client
from backend.models.schemas import CostInput, SafeWindowInput
import json

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

        # check if instance is underutilized
        waste_detected  = cpu_usage < 20 and ram_usage < 30
        recommendations = []
        best_match      = None
        best_saving     = 0

        # find cheaper instance that can still handle the workload
        for itype, specs in EC2_PRICING.items():
            if itype == instance_type:
                continue

            cpu_ok = specs["cpu"] >= (current["cpu"] * cpu_usage / 100)
            ram_ok = specs["ram"] >= (current["ram"] * ram_usage / 100)

            if cpu_ok and ram_ok and specs["price_hr"] < current["price_hr"]:
                saving = round(
                    (current["price_hr"] - specs["price_hr"]) * hours_running, 2
                )
                if saving > best_saving:
                    best_saving = saving
                    best_match  = itype

        if waste_detected:
            recommendations.append(
                f"Instance is underutilized - CPU: {cpu_usage}%, RAM: {ram_usage}%"
            )

        if best_match:
            recommendations.append(
                f"Downgrade {instance_type} to {best_match} - save ${best_saving}/month"
            )

        if not recommendations:
            recommendations.append("Instance is right-sized. No changes needed.")

        optimized_cost = round(current_cost - best_saving, 2) if best_match else current_cost
        saving_percent = round((best_saving / current_cost) * 100, 1) if current_cost > 0 else 0

        result = {
            "instance_type"   : instance_type,
            "cpu_usage"       : f"{cpu_usage}%",
            "ram_usage"       : f"{ram_usage}%",
            "current_cost"    : f"${current_cost}/month",
            "optimized_cost"  : f"${optimized_cost}/month",
            "potential_saving": f"${best_saving}/month",
            "saving_percent"  : f"{saving_percent}%",
            "waste_detected"  : waste_detected,
            "recommended_type": best_match or instance_type,
            "recommendations" : recommendations
        }

        cache_key = f"scalewise:{instance_type}:{cpu_usage}:{ram_usage}"
        redis_client.setex(cache_key, 300, json.dumps(result))

        return result

    except Exception as e:
        return {"error": str(e)}


@router.get("/scalewise/pricing")
def get_pricing():
    pricing_list = []
    for itype, specs in EC2_PRICING.items():
        pricing_list.append({
            "instance_type"  : itype,
            "cpu"            : specs["cpu"],
            "ram_gb"         : specs["ram"],
            "price_per_hr"   : f"${specs['price_hr']}",
            "price_per_month": f"${round(specs['price_hr'] * HOURS_PER_MONTH, 2)}"
        })
    return {"instances": pricing_list, "total": len(pricing_list)}


@router.post("/scalewise/fleet")
def analyze_fleet(data: dict):
    try:
        instances = data.get("instances", [])
        if not instances:
            return {"error": "No instances provided"}

        total_current   = 0
        total_optimized = 0
        fleet_results   = []

        for inst in instances:
            # convert dict to CostInput for each instance
            cost_input = CostInput(**inst)
            result     = analyze_cost(cost_input)
            if "error" not in result:
                current   = float(result["current_cost"].replace("$", "").replace("/month", ""))
                optimized = float(result["optimized_cost"].replace("$", "").replace("/month", ""))
                total_current   += current
                total_optimized += optimized
                fleet_results.append(result)

        total_saving = round(total_current - total_optimized, 2)

        return {
            "fleet_size"     : len(fleet_results),
            "total_current"  : f"${round(total_current, 2)}/month",
            "total_optimized": f"${round(total_optimized, 2)}/month",
            "total_saving"   : f"${total_saving}/month",
            "instances"      : fleet_results
        }

    except Exception as e:
        return {"error": str(e)}


@router.post("/scalewise/safe-window")
def find_safe_window(data: SafeWindowInput):
    try:
        current_score = calculate_risk_score(data.model_dump())
        windows       = []
        hours         = ["02:00", "03:00", "04:00", "10:00", "14:00"]

        for hour in hours:
            simulated = data.model_dump()
            if hour in ["02:00", "03:00", "04:00"]:
                simulated["cpu_usage"]    = max(0, data.cpu_usage * 0.4)
                simulated["memory_usage"] = max(0, data.ram_usage * 0.6)

            sim_score = calculate_risk_score(simulated)
            windows.append({
                "time"       : hour,
                "risk"       : f"{sim_score}%",
                "level"      : get_risk_level(sim_score),
                "recommended": sim_score < 40
            })

        best = min(windows, key=lambda x: float(x["risk"].replace("%", "")))

        return {
            "current_risk"  : f"{current_score}%",
            "windows"       : windows,
            "best_window"   : best,
            "recommendation": f"Deploy at {best['time']} for lowest risk"
        }

    except Exception as e:
        return {"error": str(e)}


def calculate_risk_score(data: dict) -> float:
    cpu    = data.get("cpu_usage", 0) / 100
    memory = data.get("ram_usage", data.get("memory_usage", 0)) / 100
    return round((cpu * 0.5 + memory * 0.5) * 100, 2)


def get_risk_level(score: float) -> str:
    if score >= 70:
        return "HIGH"
    elif score >= 40:
        return "MEDIUM"
    else:
        return "LOW"