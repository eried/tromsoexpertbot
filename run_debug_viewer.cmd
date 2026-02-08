@echo off
echo Aurora Detection Debug Viewer
echo ==============================
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
pip install Pillow aiohttp python-dotenv numpy astral >nul 2>&1

REM Run the debug viewer
echo.
echo Starting debug viewer...
echo.
python tools\debug_viewer.py

pause
