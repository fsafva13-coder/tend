@echo off
rem Double-click this file to start Tend on Windows.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First-time setup: creating the virtual environment...
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
".venv\Scripts\python.exe" run.py
pause
