@echo off
setlocal
cd /d "%~dp0..\frontend"
if not exist node_modules ( echo [formCAD] frontend deps missing, run formCAD.bat install & exit /b 1 )
call npm run dev
exit /b %ERRORLEVEL%
