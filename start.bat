@echo off
cd /d "%~dp0"
echo [Shuzhi Lianhai] starting server on http://127.0.0.1:8000 ...
echo [Shuzhi Lianhai] browser will open in 8 seconds. Close this window to stop.
start "" cmd /c "timeout /t 8 /nobreak >nul & start http://127.0.0.1:8000"
python -X utf8 -m uvicorn server.main:app --host 127.0.0.1 --port 8000
pause
