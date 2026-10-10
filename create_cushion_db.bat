@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    python cushion_snapshot_app.py
) else (
    py cushion_snapshot_app.py
)
if errorlevel 1 pause
