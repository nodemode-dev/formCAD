@echo off
setlocal
cd /d "%~dp0..\mesher"
if not exist requirements_mesher.txt ( echo [formCAD] mesher\requirements_mesher.txt is missing & exit /b 1 )
if not exist venv\Scripts\activate.bat (
  where py >nul 2>nul && ( py -3.12 -m venv venv ) || ( python -m venv venv )
)
if not exist venv\Scripts\activate.bat ( echo [formCAD] could not create the venv, Python 3.12 or newer is required & exit /b 1 )
call venv\Scripts\activate.bat
python -m pip install pip==26.3 || exit /b 1
pip install -r requirements_mesher.txt || exit /b 1
python formcad_mesher.py --selfcheck || exit /b 1
echo [formCAD] mesher installed in mesher\venv, development only
exit /b 0
