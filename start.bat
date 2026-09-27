@echo off
cd /d "%~dp0"

fltmc >nul 2>&1 || (
    powershell -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

title DeskBeam

rem Kill old instance by port (read port from config.json, default 8769)
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "try{(Get-Content config.json -Raw | ConvertFrom-Json).port}catch{8769}"`) do set DB_PORT=%%P
if not defined DB_PORT set DB_PORT=8769
powershell -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; Get-NetTCPConnection -LocalPort %DB_PORT% -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }"

if not exist .venv python -m venv .venv

rem Install/repair dependencies whenever a required module is missing. Gating
rem only on ".venv exists" meant a failed first install was never retried.
.venv\Scripts\python -c "import websockets, av, aiortc, numpy, cv2, dxcam" >nul 2>&1
if not errorlevel 1 goto deps_ok
echo   installing dependencies...
.venv\Scripts\python -m pip install -r requirements.txt
if not errorlevel 1 goto deps_ok
echo   direct PyPI failed - retrying via Tsinghua mirror...
.venv\Scripts\python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 60 --retries 5
:deps_ok

if not exist cert.pem .venv\Scripts\python certgen.py

if not exist config.json copy config.example.json config.json >nul

rem Ensure an inbound firewall rule for the video port exists (idempotent).
rem The venv python.exe is not covered by any existing program rule, so LAN /
rem Tailscale clients would otherwise be blocked.
powershell -NoProfile -Command "$p='%DB_PORT%'; $n='DeskBeamUDP-'+$p; $r=Get-NetFirewallRule -DisplayName $n -ErrorAction SilentlyContinue; if ($r -and $r.Enabled -eq 'True') { Write-Host ('  firewall: inbound TCP '+$p+' already allowed') } else { New-NetFirewallRule -DisplayName $n -Direction Inbound -Action Allow -Protocol TCP -LocalPort $p -Profile Any | Out-Null; Write-Host ('  firewall: added inbound TCP '+$p+' (Any profile)') }"

rem The RTP/UDP path additionally needs inbound UDP on an ephemeral ICE port,
rem which a fixed-port rule cannot cover -> allow this venv's python itself.
powershell -NoProfile -Command "$exe='%~dp0.venv\Scripts\python.exe'; $n='DeskBeamUDP-python'; $r=Get-NetFirewallRule -DisplayName $n -ErrorAction SilentlyContinue; if ($r -and $r.Enabled -eq 'True') { Write-Host '  firewall: venv python inbound already allowed' } else { New-NetFirewallRule -DisplayName $n -Direction Inbound -Action Allow -Program $exe -Profile Any | Out-Null; Write-Host '  firewall: added inbound allow for venv python (TCP+UDP)' }"

echo.
echo  DeskBeam  https://localhost:%DB_PORT%
echo.

.venv\Scripts\python server.py
pause
