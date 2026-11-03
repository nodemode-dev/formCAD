@echo off
setlocal
cd /d "%~dp0.."
set "LITE=0"
if /i "%~1"=="--lite" set "LITE=1"
echo [formCAD] installing engine
call setup\install_backend.bat || exit /b 1
if "%LITE%"=="1" (
  echo [formCAD] skipping the kernel dev venv, 2D features work without it
) else (
  call setup\install_kernel.bat || echo [formCAD] kernel did not install, retry with formCAD.bat install-kernel
  call setup\install_mesher.bat || echo [formCAD] mesher did not install, retry with formCAD.bat install-mesher
)
echo [formCAD] installing frontend
call setup\install_frontend.bat || exit /b 1
echo [formCAD] done. Boot with formCAD.bat
exit /b 0
