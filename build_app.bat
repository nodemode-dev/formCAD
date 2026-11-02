@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "CFG="
set "OPEN=0"
set "CLEAN=0"
:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--no-install" ( shift & goto parse )
if /i "%~1"=="--install" ( shift & goto parse )
if /i "%~1"=="--open" ( set "OPEN=1" & shift & goto parse )
if /i "%~1"=="--clean" ( set "CLEAN=1" & shift & goto parse )
if /i "%~1"=="--config" (
  if "%~2"=="" goto usage
  set CFG=!CFG! --config "%~2"
  shift & shift & goto parse
)
if /i "%~1"=="-h" goto usage
if /i "%~1"=="--help" goto usage
goto usage
:usage
echo build_app.bat [--no-install] [--install] [--open] [--clean] [--config FILE]
echo   builds the FormCAD desktop app from this folder, start to finish
echo   --config FILE is passed to tauri build exactly as given
exit /b 2
:parsed
echo.
echo [formCAD] == checking the tools
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if errorlevel 1 (
  py -3.12 -c "import sys" >nul 2>nul
  if errorlevel 1 ( echo [formCAD] error: Python 3.12 or newer is required & exit /b 1 )
)
where node >nul 2>nul || ( echo [formCAD] error: Node 22 or newer is required & exit /b 1 )
node -e "process.exit(Number(process.versions.node.split('.')[0]) >= 22 ? 0 : 1)" || ( echo [formCAD] error: Node 22 or newer is required & exit /b 1 )
where cargo >nul 2>nul || ( echo [formCAD] error: Rust is missing, install it from https://rustup.rs & exit /b 1 )
where rustc >nul 2>nul || ( echo [formCAD] error: rustc is missing, install it from https://rustup.rs & exit /b 1 )

echo [formCAD] == installing the engine and the window
if not exist backend\venv\Scripts\activate.bat goto doinstall
if not exist frontend\node_modules goto doinstall
goto skipinstall
:doinstall
call setup\install_all.bat --lite || exit /b 1
:skipinstall
echo [formCAD] == installing the desktop packages
call setup\install_desktop.bat || exit /b 1

if "%CLEAN%"=="1" (
  echo [formCAD] == cleaning earlier builds
  pushd src-tauri
  cargo clean
  popd
  if exist backend\build\pyinstaller rmdir /s /q backend\build\pyinstaller
  if exist backend\dist-engine rmdir /s /q backend\dist-engine
  if exist src-tauri\engine rmdir /s /q src-tauri\engine
)

echo [formCAD] == building the window
call setup\build_frontend.bat || exit /b 1
echo [formCAD] == freezing the engine
call setup\freeze_backend.bat || exit /b 1
if not exist src-tauri\icons\icon.ico (
  if exist assets\formcad_icon.png ( call frontend\node_modules\.bin\tauri.cmd icon assets\formcad_icon.png -o src-tauri\icons || exit /b 1 )
)

echo [formCAD] == building the desktop app
call frontend\node_modules\.bin\tauri.cmd build !CFG!
if errorlevel 1 (
  echo [formCAD] error: tauri build failed
  exit /b 1
)
echo [formCAD] bundles are in src-tauri\target\release\bundle
if "%OPEN%"=="1" if exist src-tauri\target\release\formcad.exe start "" src-tauri\target\release\formcad.exe
exit /b 0
