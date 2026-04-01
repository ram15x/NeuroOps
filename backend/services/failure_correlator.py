from backend.services.rul_predictor import predict_rul

# if this many or more services are in danger at the same time, its a correlation event
CORRELATION_THRESHOLD = 2

# urgency levels that count as "in danger"
DANGER_LEVELS = {"CRITICAL", "HIGH", "MEDIUM"}


def correlate_failures(services) -> dict:
    """Correlate failures across multiple services"""
    try:
        results = []
        danger_services = []

        # Handle both list of dicts and CorrelationRequest object
        if hasattr(services, 'services'):
            # It's a CorrelationRequest object
            service_list = services.services
        else:
            # It's a list
            service_list = services

        for svc in service_list:
            # Handle both dict and ServiceSensorInput object
            if hasattr(svc, 'service_name'):
                name = svc.service_name
                sensors = svc.sensors if hasattr(svc, 'sensors') else [0.0] * 24
            else:
                name = svc.get("service_name", "unknown")
                sensors = svc.get("sensors", [0.0] * 24)

            # pad or trim to exactly 24 values
            sensors = (sensors + [0.0] * 24)[:24]

            rul = predict_rul(sensors)

            entry = {
                "service_name": name,
                "cycles_remaining": rul["cycles_remaining"],
                "hours_remaining": rul["hours_remaining"],
                "urgency": rul["urgency"],
                "recommendation": rul["recommendation"]
            }
            results.append(entry)

            if rul["urgency"] in DANGER_LEVELS:
                danger_services.append(name)

        # correlation logic
        is_correlated = len(danger_services) >= CORRELATION_THRESHOLD

        if is_correlated:
            if len(danger_services) >= 4:
                correlation_level = "CRITICAL"
                root_cause = "Mass infrastructure degradation. Likely shared hardware, network, or environment issue."
            elif len(danger_services) >= 3:
                correlation_level = "HIGH"
                root_cause = "Multiple services failing together. Investigate shared dependencies."
            else:
                correlation_level = "MEDIUM"
                root_cause = "Two services degrading simultaneously. Possible shared resource contention."
        else:
            correlation_level = "NONE"
            root_cause = "Failures appear isolated. No correlated degradation detected."

        return {
            "total_services_analyzed": len(results),
            "services_in_danger": len(danger_services),
            "danger_services": danger_services,
            "is_correlated_failure": is_correlated,
            "correlation_level": correlation_level,
            "root_cause_hint": root_cause,
            "per_service": results
        }
        
    except Exception as e:
        return {
            "total_services_analyzed": 0,
            "services_in_danger": 0,
            "danger_services": [],
            "is_correlated_failure": False,
            "correlation_level": "ERROR",
            "root_cause_hint": f"Correlation analysis failed: {str(e)}",
            "per_service": [],
            "error": str(e)
        }