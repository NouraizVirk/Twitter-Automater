@echo off
title Twitter Autopilot - Setup
color 0B
cls

echo ============================================
echo   Twitter Autopilot - First-Time Setup
echo ============================================
echo.

:: ── Check Python ─────────────────────────────────────────────────────────────
echo [1/6] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found! Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)
python --version
echo [OK] Python found.
echo.

:: ── Create virtual environment ────────────────────────────────────────────────
echo [2/6] Creating virtual environment...
if not exist ".venv" (
    python -m venv .venv
    echo [OK] Virtual environment created.
) else (
    echo [OK] Virtual environment already exists.
)
echo.

:: ── Activate venv ─────────────────────────────────────────────────────────────
call .venv\Scripts\activate.bat
echo [OK] Virtual environment activated.
echo.

:: ── Install Python packages ───────────────────────────────────────────────────
echo [3/6] Installing Python packages (this may take 2-5 minutes)...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Package installation failed! Check your internet connection.
    pause
    exit /b 1
)
echo [OK] Python packages installed.
echo.

:: ── Install Playwright Chromium ───────────────────────────────────────────────
echo [4/6] Installing Playwright browser binaries...
python -m playwright install chromium
echo [OK] Playwright ready.
echo.

:: ── Check / Install FFmpeg ────────────────────────────────────────────────────
echo [5/6] Checking FFmpeg (for video generation)...
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [WARN] FFmpeg not found. Video generation will be disabled.
    echo [HINT] To enable videos: download FFmpeg from https://ffmpeg.org/download.html
    echo        and add it to your PATH, then re-run this setup.
    echo        (Images will still work perfectly without FFmpeg)
) else (
    echo [OK] FFmpeg found and ready.
)
echo.

:: ── Initialize database ───────────────────────────────────────────────────────
echo [6/6] Initializing database...
python -c "from db.models import init_db; init_db(); print('[OK] Database initialized.')"
echo.

echo ============================================
echo   Setup Complete!
echo ============================================
echo.
echo   Next steps:
echo   1. Get your FREE Groq API key at: https://console.groq.com
echo   2. Double-click start.bat to launch the autopilot
echo   3. Open http://localhost:5000 in your browser
echo   4. Enter your Groq API key in the dashboard settings
echo.
echo   The system will automatically:
echo   - Find viral AI/SaaS content
echo   - Rewrite it with AI into engaging tweets
echo   - Generate AI images with Pollinations.ai
echo   - Post to your Twitter on a schedule
echo.
pause
