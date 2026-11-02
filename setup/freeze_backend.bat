@echo off
setlocal
cd /d "%~dp0.."
set "ROOT=%cd%"
if not exist backend\venv\Scripts\activate.bat ( echo [formCAD] engine venv missing, run formCAD.bat install & exit /b 1 )
call backend\venv\Scripts\activate.bat
python -c "import PyInstaller" >nul 2>nul || ( echo [formCAD] PyInstaller missing, run formCAD.bat install-desktop & exit /b 1 )
if not exist frontend\dist\index.html ( call setup\build_frontend.bat || exit /b 1 )
cd backend
set "EXTRA="
if exist "%ROOT%\setup\pyi_hooks" set EXTRA=%EXTRA% --additional-hooks-dir "%ROOT%\setup\pyi_hooks"
if exist "%ROOT%\backend\app\data" set EXTRA=%EXTRA% --add-data "%ROOT%\backend\app\data;app\data"
if exist build\pyinstaller rmdir /s /q build\pyinstaller
if exist dist-engine rmdir /s /q dist-engine
set "PYTHONPATH=%ROOT%\backend;%PYTHONPATH%"
pyinstaller --noconfirm --clean --onedir --name formcad-engine --distpath dist-engine --workpath build\pyinstaller --specpath build\pyinstaller --add-data "%ROOT%\frontend\dist;frontend_dist" --paths "%ROOT%\backend" --collect-submodules app --collect-submodules uvicorn --collect-submodules keyring --hidden-import numpy --hidden-import ezdxf --collect-submodules fontTools %EXTRA% "%ROOT%\backend\formcad_engine.py" || exit /b 1
if exist "%ROOT%\src-tauri\engine" rmdir /s /q "%ROOT%\src-tauri\engine"
xcopy /e /i /y /q dist-engine\formcad-engine "%ROOT%\src-tauri\engine" >nul || exit /b 1
"%ROOT%\src-tauri\engine\formcad-engine.exe" --selfcheck || exit /b 1
echo [formCAD] engine folder ready: %ROOT%\src-tauri\engine
exit /b 0
