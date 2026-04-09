import os
from backend.core.config import settings

MODEL_DIR = os.path.join(settings.PROJECT_ROOT, "ml_models/saved")
ACTIVE_MODEL_FILE = os.path.join(settings.PROJECT_ROOT, ".active_model.json")
AB_TEST_RESULTS_FILE = os.path.join(settings.PROJECT_ROOT, ".ab_test_results.json")
LOG_FILE = os.path.join(settings.PROJECT_ROOT, "auto_deploy.log")
