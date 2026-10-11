@echo off
cd /d "%~dp0"

fltmc >nul 2>&1 || (
    powershell -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

rem Kill by PID file (most recent instance)
if exist server.pid (
    set /p PID=<server.pid
    taskkill /PID %PID% /F >nul 2>&1
    del server.pid >nul 2>&1
)

rem Kill any process holding our port (catches orphaned/old instances)
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "try{(Get-Content config.json -Raw | ConvertFrom-Json).port}catch{8769}"`) do set DB_PORT=%%P
if not defined DB_PORT set DB_PORT=8769
powershell -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; Get-NetTCPConnection -LocalPort %DB_PORT% -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }"

rem Kill compiled exe
taskkill /IM DeskBeam.exe /F >nul 2>&1

echo Done.
