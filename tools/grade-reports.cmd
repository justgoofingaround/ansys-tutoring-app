@echo off
rem ----------------------------------------------------------------------
rem  Open the report grading app on this machine.
rem
rem  Double-click. A browser opens on http://127.0.0.1:8765 showing the
rem  reports students submitted. From there you can run the AI review and
rem  write the feedback students see.
rem
rem  Only this computer can reach that page, and running the AI review needs
rem  the token in tools\checker.env. Knowing the instructor password for the
rem  web app is not enough: this is deliberately yours alone.
rem
rem  Close this window to shut the app down.
rem ----------------------------------------------------------------------
setlocal
cd /d "%~dp0.."

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" -c "import httpx, uvicorn, fastapi" >nul 2>nul
if errorlevel 1 (
  echo This checkout is not set up yet: Python cannot find the packages it needs.
  echo.
  echo From this folder's parent, run once:
  echo     python -m venv .venv
  echo     .venv\Scripts\pip install -r requirements.txt
  echo.
  pause
  exit /b 2
)

"%PY%" tools\grader_app.py --open
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo The grading app stopped with code %RC%.
  pause
)
exit /b %RC%
