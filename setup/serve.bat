@echo off
setlocal
cd /d "%~dp0.."
if not exist frontend\dist\index.html ( call setup\build_frontend.bat || exit /b 1 )
set "FORMCAD_DIST=%cd%\frontend\dist"
cd backend
if not exist venv\Scripts\activate.bat ( echo [formCAD] engine venv missing, run formCAD.bat install & exit /b 1 )
call venv\Scripts\activate.bat
if not defined FORMCAD_HOST set "FORMCAD_HOST=127.0.0.1"
if not defined FORMCAD_PORT set "FORMCAD_PORT=8290"
echo [formCAD] serving http://%FORMCAD_HOST%:%FORMCAD_PORT%
python -m uvicorn app.main:app --host %FORMCAD_HOST% --port %FORMCAD_PORT%
exit /b %ERRORLEVEL%
