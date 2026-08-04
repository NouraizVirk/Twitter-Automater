@echo off
title Twitter Autopilot
color 0A
cls

echo ============================================
echo   Twitter Autopilot - Starting Up
echo ============================================
echo.

:: ── Step 1: Launch Chrome with remote debugging ─────────────────────────────
echo [1/3] Launching Chrome with remote debugging port 9222...

set CHROME_PATH=
for %%p in (
    "C:\Program Files\Google\Chrome\Application\chrome.exe"
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
) do (
    if exist %%p (
        set CHROME_PATH=%%~p
        goto :found_chrome
    )
)

echo [ERROR] Chrome not found! Please install Google Chrome.
pause
exit /b 1

:found_chrome
echo [OK] Found Chrome at: %CHROME_PATH%

:: Check if Chrome debugging is already running
curl -s http://localhost:9222/json/version >nul 2>&1
if %errorlevel% EQU 0 (
    echo [OK] Chrome with remote debugging already running.
) else (
    echo [!] Closing existing Chrome instances to enable Autopilot connection...
    taskkill /F /IM chrome.exe /T >nul 2>&1
    timeout /t 2 /nobreak >nul
    start "" "%CHROME_PATH%" ^
        --remote-debugging-port=9222 ^
        --disable-blink-features=AutomationControlled ^
        --enable-webgl ^
        --user-data-dir="%CD%\chrome-profile" ^
        --no-first-run ^
        --no-default-browser-check
    echo [OK] Chrome launched. Waiting for it to start...
    timeout /t 4 /nobreak >nul
)

:: ── Step 2: Activate virtual environment ─────────────────────────────────────
echo.
echo [2/3] Activating Python environment...

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    echo [OK] Virtual environment activated.
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo [OK] Virtual environment activated.
) else (
    echo [WARN] No virtual environment found. Using system Python.
    echo [HINT] Run setup.bat first for best results.
)

:: ── Step 3: Start the Autopilot ──────────────────────────────────────────────
echo.
echo [3/3] Starting Twitter Autopilot...
echo.
echo ============================================
echo   Dashboard: http://localhost:5000
echo   Press Ctrl+C to stop
echo ============================================
echo.

python -X utf8 app.py

:: If Python exits, pause to show error
echo.
echo [!] Autopilot stopped. Check the output above for errors.
pause
