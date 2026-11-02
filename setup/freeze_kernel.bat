@echo off
setlocal
cd /d "%~dp0..\kernel"
set "ROOT=%~dp0.."
if not exist venv\Scripts\activate.bat ( echo [formCAD] kernel venv missing, run formCAD.bat install-kernel & exit /b 1 )
call venv\Scripts\activate.bat
python -c "import PyInstaller" >nul 2>nul || ( pip install pyinstaller==6.22.3 || exit /b 1 )
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
pyinstaller --noconfirm --clean --onedir --name formcad-kernel --distpath dist --workpath build --specpath build --collect-all OCP --collect-all build123d formcad_kernel.py || exit /b 1
(echo {"id":1,"method":"hello","params":{}}& echo {"id":2,"method":"shutdown","params":{}}) | dist\formcad-kernel\formcad-kernel.exe | findstr /c:"result" >nul || ( echo [formCAD] the frozen kernel did not answer hello & exit /b 1 )
echo [formCAD] kernel folder ready: kernel\dist\formcad-kernel, ship it from formCAD-binaries, never inside the app
exit /b 0
