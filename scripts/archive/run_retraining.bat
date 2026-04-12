@echo off
echo ========================================
echo NeuroOps Auto-Retraining Started
echo ========================================
echo Time: %date% %time%
echo.

cd /d C:\Users\ramna\OneDrive\Desktop\Projects\NeuroOps
call neuroops_env\Scripts\activate
python scripts/auto_retrain_models.py

echo.
echo Retraining completed at %date% %time%
pause