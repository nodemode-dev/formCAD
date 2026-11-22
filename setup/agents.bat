@echo off
setlocal
cd /d "%~dp0.."
if not exist backend\venv\Scripts\activate.bat ( echo [formCAD] error: backend venv missing, run formCAD.bat install 1>&2 & exit /b 1 )
call backend\venv\Scripts\activate.bat
python setup\agents.py %*
exit /b %ERRORLEVEL%
