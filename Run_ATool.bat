@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Set up ATool first: py -3 -m venv .venv
  echo Then: .venv\Scripts\python -m pip install -r requirements.txt
  pause
  exit /b 1
)
".venv\Scripts\python.exe" ATool_Qt.py %*
if errorlevel 1 pause
