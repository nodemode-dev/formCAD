@echo off
setlocal
cd /d "%~dp0..\frontend"
where node >nul 2>nul || ( echo [formCAD] error: Node 22.12 or newer is required 1>&2 & exit /b 1 )
node -e "const [a, b] = process.versions.node.split('.').map(Number); process.exit(a > 22 || (a === 22 && b >= 12) ? 0 : 1)" || ( echo [formCAD] error: Node 22.12 or newer is required 1>&2 & exit /b 1 )
if exist package-lock.json ( call npm ci || exit /b 1 ) else ( call npm install || exit /b 1 )
echo [formCAD] frontend installed
exit /b 0
