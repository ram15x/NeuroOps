@echo off
echo ========================================
echo NeuroOps Auto Pipeline Started
echo ========================================
echo Time: %date% %time%
echo.

cd /d C:\Users\ramna\OneDrive\Desktop\Projects\NeuroOps
call neuroops_env\Scripts\activate
python scripts/auto_convert_and_train.py

echo.
echo Pipeline completed at %date% %time%
pause
