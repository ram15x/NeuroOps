#!/usr/bin/env python3
import psutil
import requests
import socket
import subprocess
from datetime import datetime

BACKEND_URL = "http://localhost:8000"

def get_instance_id():
    """Get EC2 instance ID from metadata"""
    try:
        # Try EC2 metadata
        result = subprocess.run(
            ["curl", "-s", "http://169.254.169.254/latest/meta-data/instance-id"],
            capture_output=True, text=True, timeout=2
        )
        if result.stdout and result.stdout.strip():
            return result.stdout.strip()
    except:
        pass
    
    # Fallback to hostname
    return socket.gethostname()

def collect_metrics():
    return {
        "cpu": {"percent": psutil.cpu_percent(interval=1)},
        "memory": {"percent": psutil.virtual_memory().percent},
        "disk": {"percent": psutil.disk_usage('/').percent}
    }

def send_metrics(instance_id, metrics):
    payload = {
        "instance_id": instance_id,
        "timestamp": datetime.utcnow().isoformat(),
        **metrics
    }
    try:
        r = requests.post(f"{BACKEND_URL}/api/v1/agent/metrics", json=payload, timeout=10)
        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {instance_id}: CPU:{metrics['cpu']['percent']:.1f}% MEM:{metrics['memory']['percent']:.1f}% DISK:{metrics['disk']['percent']:.1f}% (HTTP {r.status_code})")
    except Exception as e:
        print(f"Error: {e}")

def main():
    print("NeuroOps Agent Starting...")
    instance_id = get_instance_id()
    print(f"Instance ID: {instance_id}")
    
    while True:
        metrics = collect_metrics()
        send_metrics(instance_id, metrics)
        import time
        time.sleep(30)

if __name__ == "__main__":
    main()
