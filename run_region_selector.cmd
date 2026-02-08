@echo off
echo Aurora Detection Region Selector
echo =================================
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
pip install Pillow aiohttp python-dotenv >nul 2>&1

REM Run the region selector
echo.
echo Starting region selector...
echo.
python tools\region_selector.py

pause
