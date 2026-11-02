@echo off
setlocal
cd /d "%~dp0.."
start "FormCAD engine" cmd /k "cd /d %cd% && setup\boot_backend.bat"
start "FormCAD frontend" cmd /k "cd /d %cd% && setup\boot_frontend.bat"
echo [formCAD] frontend http://localhost:5290 and engine http://127.0.0.1:8290
exit /b 0
