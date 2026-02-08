@echo off
echo Aurora Borealis Telegram Bot
echo =============================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found. Please install Python 3.11+
    pause
    exit /b 1
)

REM Install dependencies if needed
echo Installing dependencies...
pip install -r requirements.txt

REM Run the bot
echo.
echo Starting bot...
echo Press Ctrl+C to stop
echo.
python app.py

pause
