@echo off
setlocal
cd /d "%~dp0..\backend"
if not exist venv\Scripts\activate.bat (
  where py >nul 2>nul && ( py -3.12 -m venv venv ) || ( python -m venv venv )
)
if not exist venv\Scripts\activate.bat ( echo [formCAD] could not create the venv, Python 3.12 or newer is required & exit /b 1 )
call venv\Scripts\activate.bat
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" || ( echo [formCAD] Python 3.12 or newer is required & exit /b 1 )
python -m pip install --upgrade pip || exit /b 1
pip install -r requirements.txt || exit /b 1
echo [formCAD] engine installed in backend\venv
exit /b 0
