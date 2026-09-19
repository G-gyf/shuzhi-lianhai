@echo off
cd /d "%~dp0"
echo [Shuzhi Lianhai] pushing to GitHub (first time will open browser login)...
git push -u origin main
echo.
echo Done. If you see "main -> main", go to railway.com to deploy.
pause
