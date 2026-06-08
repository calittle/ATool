@echo off
cd /d "%~dp0"
py -3 ATool.py
if errorlevel 1 pause