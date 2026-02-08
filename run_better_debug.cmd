@echo off
echo Aurora Parameter Tuner
echo ======================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found. Please install Python 3.11+
    pause
    exit /b 1
)

REM Install dependencies if needed
echo Checking dependencies...
pip install Pillow python-dotenv numpy >nul 2>&1

REM Run the parameter tuner
echo.
echo Starting parameter tuner...
echo.
python tools\param_tuner.py

pause
