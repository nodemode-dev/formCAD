@echo off
setlocal
cd /d "%~dp0.."
for %%p in (frontend\dist backend\build backend\dist-engine kernel\build kernel\dist src-tauri\target src-tauri\gen src-tauri\engine) do if exist %%p rmdir /s /q %%p
if exist build_app.log del /q build_app.log
if /i "%~1"=="--all" (
  if exist frontend\node_modules rmdir /s /q frontend\node_modules
  if exist backend\venv rmdir /s /q backend\venv
  if exist kernel\venv rmdir /s /q kernel\venv
)
echo [formCAD] clean
exit /b 0
