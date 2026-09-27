@echo off
cd /d "%~dp0"
echo === DeskBeam full-mode build ===
echo.

:: Create temp build venv
set BUILD=.build_venv
if exist "%BUILD%" rmdir /s /q "%BUILD%"
python -m venv "%BUILD%"
if errorlevel 1 ( echo ERROR: python not found & exit /b 1 )

call "%BUILD%\Scripts\activate.bat"
python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple -q
pip install -r requirements.txt pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple -q
if errorlevel 1 ( echo ERROR: pip install failed & exit /b 1 )

echo.
echo Building DeskBeam.exe ...
pyinstaller --onefile --noconsole --uac-admin ^
    --name DeskBeam ^
    --icon icon.ico ^
    --add-data "web;deskbeam_web" ^
    --hidden-import websockets.asyncio.server ^
    --hidden-import websockets.http11 ^
    --hidden-import websockets.datastructures ^
    --hidden-import sendinput ^
    --hidden-import gpu_stream ^
    --hidden-import rtp_stream ^
    --hidden-import dxcam ^
    --collect-all av ^
    --hidden-import aiortc.rtcrtpsender ^
    --hidden-import aiortc.rtpreceiver ^
    server.py

if errorlevel 1 ( echo ERROR: build failed & exit /b 1 )

:: Copy output
if exist DeskBeam.exe del DeskBeam.exe
copy "dist\DeskBeam.exe" DeskBeam.exe >nul
if errorlevel 1 ( echo ERROR: copy failed & exit /b 1 )

echo.
echo === Build complete ===
echo Output: DeskBeam.exe
echo.
echo To deploy, copy these files to the target machine:
echo   DeskBeam.exe
echo   config.json          (set ffmpeg_url to auto-download ffmpeg, or place
echo                         ffmpeg\ffmpeg.exe next to the exe for GPU streaming;
echo                         without it the exe falls back to the CPU dxcam
echo                         pipeline)
echo   cert.pem  (or generate one)
echo   key.pem   (or generate one)
echo.
echo For config.json, start from config.example.json.
echo To generate TLS cert:
echo   python certgen.py
echo.

:: Cleanup build venv
call deactivate >nul 2>&1
rmdir /s /q "%BUILD%" >nul 2>&1
rmdir /s /q dist >nul 2>&1
rmdir /s /q build >nul 2>&1
del DeskBeam.spec >nul 2>&1

pause
