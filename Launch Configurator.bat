@echo off
if exist "%~dp0dist\Fuzzyficator.exe" (
    start "" "%~dp0dist\Fuzzyficator.exe"
    exit /b 0
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launch Configurator.ps1"
if errorlevel 1 pause
