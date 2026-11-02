@echo off
setlocal
cd /d "%~dp0.."
if not exist src-tauri\engine\formcad-engine.exe ( call setup\freeze_backend.bat || exit /b 1 )
call frontend\node_modules\.bin\tauri.cmd dev
exit /b %ERRORLEVEL%
