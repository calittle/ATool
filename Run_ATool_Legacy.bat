@echo off
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe ATool.py
) else (
  py -3 ATool.py
)
if errorlevel 1 pause
