@echo off
setlocal
cd /d "%~dp0..\mesher"
set "ROOT=%~dp0.."
if not exist venv\Scripts\activate.bat ( echo [formCAD] mesher venv missing, run formCAD.bat install-mesher & exit /b 1 )
call venv\Scripts\activate.bat
python -c "import PyInstaller" >nul 2>nul || ( pip install pyinstaller==6.22.3 || exit /b 1 )
set "OCCT="
for /f "usebackq delims=" %%i in (`python -c "import importlib.metadata as m; print(next(f for f in m.files('netgen-occt') if f.match('*TKernel*')).locate().resolve().parent)"`) do set "OCCT=%%i"
if not defined OCCT ( echo [formCAD] the OpenCascade libraries of netgen-occt were not found & exit /b 1 )
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
pyinstaller --noconfirm --clean --onedir --name formcad-mesher --distpath dist --workpath build --specpath build --collect-all netgen --collect-all pyngcore --add-binary "%OCCT%\*TK*;occt" --exclude-module netgen.gui --exclude-module netgen.webgui --exclude-module tkinter formcad_mesher.py || exit /b 1
dist\formcad-mesher\formcad-mesher.exe --selfcheck || ( echo [formCAD] the frozen mesher failed its selfcheck & exit /b 1 )
(echo {"id":1,"method":"hello","params":{}}& echo {"id":2,"method":"shutdown","params":{}}) | dist\formcad-mesher\formcad-mesher.exe | findstr /c:"result" >nul || ( echo [formCAD] the frozen mesher did not answer hello & exit /b 1 )
echo [formCAD] mesher folder ready: mesher\dist\formcad-mesher, ship it from formai-binaries, never inside the app
exit /b 0
