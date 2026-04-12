#!/usr/bin/env python
"""
Auto-evaluate models and swap production model based on performance
Run this every 24 hours via Task Scheduler
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.ab_tester import evaluate_and_swap_models
from datetime import datetime

print("=" * 60)
print("A/B MODEL EVALUATOR")
print("=" * 60)
print(f"Running at: {datetime.now()}")
print("-" * 60)

result = evaluate_and_swap_models()

print("\nResult:")
print(result)
print("\n" + "=" * 60)
print("EVALUATION COMPLETE!")
print("=" * 60)