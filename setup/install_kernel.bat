@echo off
setlocal
cd /d "%~dp0..\kernel"
if not exist requirements_kernel.txt ( echo [formCAD] kernel\requirements_kernel.txt is missing & exit /b 1 )
if not exist venv\Scripts\activate.bat (
  where py >nul 2>nul && ( py -3.12 -m venv venv ) || ( python -m venv venv )
)
if not exist venv\Scripts\activate.bat ( echo [formCAD] could not create the venv, Python 3.12 or newer is required & exit /b 1 )
call venv\Scripts\activate.bat
python -m pip install pip==26.3 || exit /b 1
pip install -r requirements_kernel.txt || exit /b 1
echo [formCAD] kernel installed in kernel\venv, development only
exit /b 0
