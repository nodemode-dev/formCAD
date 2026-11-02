@echo off
setlocal
cd /d "%~dp0..\frontend"
if not exist node_modules (
  if exist package-lock.json ( call npm ci || exit /b 1 ) else ( call npm install || exit /b 1 )
)
call npm run build || exit /b 1
echo [formCAD] built frontend\dist
exit /b 0
