@echo off
setlocal
cd /d "%~dp0"
title VisionGate Samsung - Local
if not exist "requirements.txt" (
 echo ERROR: Put this BAT in the VisionGate application root.
 pause
 exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
 echo Creating Python 3.13 environment...
 py -3.13 -m venv .venv
 if errorlevel 1 goto fail
)
if not exist ".venv\visiongate-installed.flag" (
 echo Installing dependencies...
 ".venv\Scripts\python.exe" -m pip install -r requirements.txt -r requirements-samsung-models.txt -r requirements-samsung-export.txt
 if errorlevel 1 goto fail
 ".venv\Scripts\python.exe" -m pip check
 if errorlevel 1 goto fail
 echo Preparing OCR models...
 ".venv\Scripts\python.exe" -m tools.samsung_model_setup --download
 if errorlevel 1 goto fail
 type nul > ".venv\visiongate-installed.flag"
)
set "SAMSUNG_ENABLED=true"
set "SAMSUNG_POLICY_PROFILE=role-v1"
set "SAMSUNG_OCR_ENGINE=ppocrv5"
set "SAMSUNG_RECOGNITION_PROFILE=enhanced"
set "FRONTEND_DIST=%CD%\frontend\dist"
set "STORE_ANALYSIS_IMAGES=false"
echo Starting VisionGate on http://127.0.0.1:8080/samsung
start "" "http://127.0.0.1:8080/samsung"
".venv\Scripts\python.exe" -m uvicorn backend.render_app:create_app --factory --host 127.0.0.1 --port 8080
if errorlevel 1 goto fail
echo Server stopped.
pause
exit /b 0
:fail
echo.
echo ERROR: Installation or startup failed. See messages above.
pause
exit /b 1
