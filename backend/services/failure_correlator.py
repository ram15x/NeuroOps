from backend.services.rul_predictor import predict_rul

# if this many or more services are in danger at the same time, its a correlation event
CORRELATION_THRESHOLD = 2

# urgency levels that count as "in danger"
DANGER_LEVELS = {"CRITICAL", "HIGH", "MEDIUM"}


def correlate_failures(services: list) -> dict:
    # services is a list of dicts: {service_name, sensors: [s1..s24]}

    results = []
    danger_services = []

    for svc in services:
        name    = svc.get("service_name", "unknown")
        sensors = svc.get("sensors", [0.0] * 24)

        # pad or trim to exactly 24 values
        sensors = (sensors + [0.0] * 24)[:24]

        rul = predict_rul(sensors)

        entry = {
            "service_name"    : name,
            "cycles_remaining": rul["cycles_remaining"],
            "hours_remaining" : rul["hours_remaining"],
            "urgency"         : rul["urgency"],
            "recommendation"  : rul["recommendation"]
        }
        results.append(entry)

        if rul["urgency"] in DANGER_LEVELS:
            danger_services.append(name)

    # correlation logic
    # if multiple services are degrading together its likely not isolated
    is_correlated = len(danger_services) >= CORRELATION_THRESHOLD

    if is_correlated:
        if len(danger_services) >= 4:
            correlation_level = "CRITICAL"
            root_cause        = "Mass infrastructure degradation. Likely shared hardware, network, or environment issue."
        elif len(danger_services) >= 3:
            correlation_level = "HIGH"
            root_cause        = "Multiple services failing together. Investigate shared dependencies."
        else:
            correlation_level = "MEDIUM"
            root_cause        = "Two services degrading simultaneously. Possible shared resource contention."
    else:
        correlation_level = "NONE"
        root_cause        = "Failures appear isolated. No correlated degradation detected."

    return {
        "total_services_analyzed": len(results),
        "services_in_danger"     : len(danger_services),
        "danger_services"        : danger_services,
        "is_correlated_failure"  : is_correlated,
        "correlation_level"      : correlation_level,
        "root_cause_hint"        : root_cause,
        "per_service"            : results
    }