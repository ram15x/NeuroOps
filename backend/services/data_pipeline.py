import pandas as pd
import numpy as np
from datetime import datetime
from backend.services.feature_store import store_features
from backend.services.drift_detector import record_prediction, check_drift

METRICS_PATH = "datasets/processed/metrics_clean.csv"
FAILURE_PATH = "datasets/processed/failure_clean.csv"
LOGS_PATH    = "datasets/processed/logs_clean.csv"

#sample for pipeline run
SAMPLE_SIZE = 500


def run_metrics_pipeline() -> dict:
    df = pd.read_sql("SELECT timestamp, metric_name, value FROM metric_history WHERE metric_name='cpu'", engine)

    # sample recent rows
    df = df.tail(SAMPLE_SIZE)

    #features per metric
    results = []
    for metric in df["metric"].unique():
        subset = df[df["metric"] == metric]["value"]

        features = {
            "mean"       : round(float(subset.mean()), 4),
            "std"        : round(float(subset.std()), 4),
            "min"        : round(float(subset.min()), 4),
            "max"        : round(float(subset.max()), 4),
            "p95"        : round(float(subset.quantile(0.95)), 4),
            "sample_size": len(subset)
        }

        # store in feature store
        store_features(
            entity_id   = f"metric_{metric}",
            entity_type = "cloudwatch_metric",
            features    = features
        )

        results.append({
            "metric"  : metric,
            "features": features
        })

    return {
        "stage"           : "metrics_pipeline",
        "metrics_processed": len(results),
        "sample_size"     : SAMPLE_SIZE,
        "results"         : results
    }


def run_failure_pipeline() -> dict:
    df = pd.read_sql("SELECT timestamp, value FROM metric_history WHERE metric_name='cpu'", engine)
    df = df.tail(SAMPLE_SIZE)

    sensor_cols = [c for c in df.columns if c.startswith("sensor")]

    features = {}
    for col in sensor_cols:
        features[f"{col}_mean"] = round(float(df[col].mean()), 4)
        features[f"{col}_std"]  = round(float(df[col].std()), 4)

    features["units_sampled"] = int(df["unit"].nunique())
    features["avg_cycle"]     = round(float(df["cycle"].mean()), 2)

    store_features(
        entity_id   = "aws_ec2_fleet",
        entity_type = "sensor_fleet",
        features    = features
    )

    return {
        "stage"          : "failure_pipeline",
        "sensors_computed": len(sensor_cols),
        "units_sampled"  : features["units_sampled"],
        "avg_cycle"      : features["avg_cycle"]
    }


def run_drift_check() -> dict:
    # feed a few recent metric values into drift detector to get current status
    # df = pd.read_csv(METRICS_PATH).tail(100)  # Using real AWS data
    values  = df["value"].tolist()

    # record prediction in drift detector
    for val in values[:20]:
        # treat high values as anomaly signal for drift tracking
        is_anomaly = val > df["value"].quantile(0.95)
        record_prediction(bool(is_anomaly))

    drift_result = check_drift()
    return {
        "stage"         : "drift_check",
        "drift_detected": drift_result.get("drift_detected", False),
        "severity"      : drift_result.get("severity", "normal"),
        "current_rate"  : drift_result.get("current_rate", "0%"),
        "baseline_rate" : drift_result.get("baseline_rate", "5%")
    }


def run_full_pipeline() -> dict:
    started_at = datetime.utcnow().isoformat()
    stages     = []
    errors     = []

    # stage 1 -metrics features
    try:
        result = run_metrics_pipeline()
        stages.append(result)
    except Exception as e:
        errors.append({"stage": "metrics_pipeline", "error": str(e)})

    # stage 2 — failure sensor features
    try:
        result = run_failure_pipeline()
        stages.append(result)
    except Exception as e:
        errors.append({"stage": "failure_pipeline", "error": str(e)})

    # stage 3 — drift check
    try:
        result = run_drift_check()
        stages.append(result)
    except Exception as e:
        errors.append({"stage": "drift_check", "error": str(e)})

    finished_at = datetime.utcnow().isoformat()

    return {
        "pipeline"    : "NeuroOps Data Pipeline",
        "started_at"  : started_at,
        "finished_at" : finished_at,
        "stages_run"  : len(stages),
        "errors"      : errors,
        "status"      : "completed" if not errors else "completed_with_errors",
        "stages"      : stages
    }