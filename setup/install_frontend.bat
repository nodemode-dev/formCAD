@echo off
setlocal
cd /d "%~dp0..\frontend"
where node >nul 2>nul || ( echo [formCAD] Node 22 or newer is required & exit /b 1 )
if exist package-lock.json ( call npm ci || exit /b 1 ) else ( call npm install || exit /b 1 )
echo [formCAD] frontend installed
exit /b 0
