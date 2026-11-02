@echo off
setlocal
cd /d "%~dp0..\backend"
if not exist venv\Scripts\activate.bat ( echo [formCAD] engine venv missing, run formCAD.bat install & exit /b 1 )
call venv\Scripts\activate.bat
if exist requirements_desktop.txt ( pip install -r requirements_desktop.txt || exit /b 1 ) else ( pip install pyinstaller==6.22.3 || exit /b 1 )
where cargo >nul 2>nul || ( echo [formCAD] Rust is not installed, get it from https://rustup.rs & exit /b 1 )
if not exist ..\frontend\node_modules\.bin\tauri.cmd ( pushd ..\frontend & call npm install & popd )
echo [formCAD] desktop toolchain ready
exit /b 0
