from fastapi import APIRouter
from backend.services.redis_service import redis_client
import json

router = APIRouter()

# ── AWS EC2 Pricing Data (Real AWS Prices) ─────────────
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

# ── Analyze Resource Usage ─────────────────────────────
@router.post("/scalewise/analyze")
def analyze_cost(data: dict):
    try:
        instance_type = data.get("instance_type", "t2.micro")
        cpu_usage     = data.get("cpu_usage", 0)
        ram_usage     = data.get("ram_usage", 0)
        hours_running = data.get("hours_running", HOURS_PER_MONTH)

        if instance_type not in EC2_PRICING:
            return {"error": f"Unknown instance type: {instance_type}"}

        current = EC2_PRICING[instance_type]
        current_cost = round(current["price_hr"] * hours_running, 2)

        # ── Detect Waste ───────────────────────────────
        waste_detected = cpu_usage < 20 and ram_usage < 30
        recommendations = []

        # ── Find Better Instance ───────────────────────
        best_match = None
        best_saving = 0

        for itype, specs in EC2_PRICING.items():
            if itype == instance_type:
                continue

            # must handle the workload
            cpu_ok = specs["cpu"] >= (current["cpu"] * cpu_usage / 100)
            ram_ok = specs["ram"] >= (current["ram"] * ram_usage / 100)

            if cpu_ok and ram_ok and specs["price_hr"] < current["price_hr"]:
                saving = round(
                    (current["price_hr"] - specs["price_hr"]) * hours_running, 2
                )
                if saving > best_saving:
                    best_saving = saving
                    best_match = itype

        # ── Build Recommendations ──────────────────────
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

        # ── Monthly Projection ─────────────────────────
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

        # ── Cache Result ───────────────────────────────
        cache_key = f"scalewise:{instance_type}:{cpu_usage}:{ram_usage}"
        redis_client.setex(cache_key, 300, json.dumps(result))

        return result

    except Exception as e:
        return {"error": str(e)}


# ── Get All Instance Prices ────────────────────────────
@router.get("/scalewise/pricing")
def get_pricing():
    pricing_list = []
    for itype, specs in EC2_PRICING.items():
        pricing_list.append({
            "instance_type": itype,
            "cpu"          : specs["cpu"],
            "ram_gb"       : specs["ram"],
            "price_per_hr" : f"${specs['price_hr']}",
            "price_per_month": f"${round(specs['price_hr'] * HOURS_PER_MONTH, 2)}"
        })
    return {"instances": pricing_list, "total": len(pricing_list)}


# ── Fleet Analysis ─────────────────────────────────────
@router.post("/scalewise/fleet")
def analyze_fleet(data: dict):
    try:
        instances = data.get("instances", [])
        if not instances:
            return {"error": "No instances provided"}

        total_current  = 0
        total_optimized = 0
        fleet_results  = []

        for inst in instances:
            result = analyze_cost(inst)
            if "error" not in result:
                current  = float(result["current_cost"].replace("$","").replace("/month",""))
                optimized = float(result["optimized_cost"].replace("$","").replace("/month",""))
                total_current   += current
                total_optimized += optimized
                fleet_results.append(result)

        total_saving = round(total_current - total_optimized, 2)

        return {
            "fleet_size"      : len(fleet_results),
            "total_current"   : f"${round(total_current, 2)}/month",
            "total_optimized" : f"${round(total_optimized, 2)}/month",
            "total_saving"    : f"${total_saving}/month",
            "instances"       : fleet_results
        }

    except Exception as e:
        return {"error": str(e)}