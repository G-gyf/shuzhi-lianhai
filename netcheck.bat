@echo off
cd /d "%~dp0"
echo ============================================
echo  [1/4] ping github.com
ping -n 2 github.com
echo.
echo  [2/4] HTTPS handshake test (curl, 15s timeout)
curl.exe -I --max-time 15 https://github.com
echo.
echo  [3/4] git proxy settings (blank = none)
git config --get http.proxy
git config --get https.proxy
echo.
echo  [4/4] git ssl backend (blank = schannel default)
git config --get http.sslBackend
echo.
echo ============================================
echo  How to read:
echo   - If [2] also fails: network / VPN / firewall issue, NOT git.
echo     Try: retry push.bat, turn VPN on/off, or ipconfig /flushdns
echo   - If [2] works but push fails: try
echo       git config --global http.sslBackend openssl
echo     (to revert: git config --global --unset http.sslBackend)
echo   - If proxy lines are non-empty but you are NOT using a proxy:
echo       git config --global --unset http.proxy
echo       git config --global --unset https.proxy
echo ============================================
pause
