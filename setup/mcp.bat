@echo off
setlocal
cd /d "%~dp0..\backend"
if not exist venv\Scripts\activate.bat ( echo [formCAD] engine venv missing, run formCAD.bat install 1>&2 & exit /b 1 )
call venv\Scripts\activate.bat
python formcad_engine.py mcp %*
exit /b %ERRORLEVEL%
