@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 (
        echo Python 3 was not found. Install Python 3.12+ and retry.
        pause
        exit /b 1
    )
)
call ".venv\Scripts\activate.bat"
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed. Check your internet connection and Python version.
    pause
    exit /b 1
)
set DEMO_MODE=true
if not defined DATABASE_PATH set DATABASE_PATH=paypilot.db

echo.
echo PayPilot demo is available at http://127.0.0.1:8000
start "" /min cmd /c "timeout /t 4 /nobreak >nul ^& start http://127.0.0.1:8000"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
