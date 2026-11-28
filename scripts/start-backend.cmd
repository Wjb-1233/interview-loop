@echo off
rem Unified backend launcher: always uses backend\.venv, never a global interpreter.
rem Usage: start-backend.cmd [extra uvicorn args, e.g. --reload]
setlocal
cd /d "%~dp0..\backend" || exit /b 1
if not exist ".venv\Scripts\python.exe" (
  echo [start-backend] missing backend\.venv\Scripts\python.exe
  echo   py -3.11 -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install --constraint constraints.txt --requirement requirements-dev.txt
  exit /b 1
)
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8081 %*
