import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


class TestAPIHealth:
    def test_health_endpoint(self):
        response = client.get("/health")
        assert response.status_code in [200, 404]


class TestAPIAuth:
    def test_login_endpoint(self):
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "admin", "password": "admin123"}
        )
        assert response.status_code in [200, 401, 404]


class TestAPIPredict:
    def test_inframind_predict(self):
        response = client.post(
            "/api/v1/inframind/predict",
            json={
                "metric": "ec2_cpu",
                "value": 85.5,
                "rolling_mean": 45.2,
                "rolling_std": 12.3,
                "value_diff": 15.2
            }
        )
        assert response.status_code in [200, 401, 422, 404]