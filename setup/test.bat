@echo off
setlocal
set "ROOT=%~dp0.."
set "WHICH=%~1"
if "%WHICH%"=="" set "WHICH=all"
set "REST=%2 %3 %4 %5 %6 %7 %8 %9"
set "PY=%ROOT%\backend\venv\Scripts\python.exe"
if not exist "%PY%" ( echo [formCAD] error: backend venv missing, run formCAD.bat install & exit /b 1 )
set "FAIL=0"
set "KNOWN=0"
for %%L in (all unit engine workers browser scripts) do if /i "%WHICH%"=="%%L" set "KNOWN=1"
if "%KNOWN%"=="0" ( echo [formCAD] unknown test layer: %WHICH% ^(use unit, engine, workers, browser, scripts or nothing for all^) & exit /b 2 )
"%PY%" -c "import pytest" >nul 2>&1 || "%PY%" -m pip install -q -r "%ROOT%\backend\requirements-test.txt"
set "DO=0"
if /i "%WHICH%"=="all" set "DO=1"
if /i "%WHICH%"=="unit" set "DO=1"
if "%DO%"=="1" (
  echo [formCAD] interface logic ^(vitest^)
  pushd "%ROOT%\frontend"
  call npx vitest run %REST% || set "FAIL=1"
  popd
)
set "DO=0"
if /i "%WHICH%"=="all" set "DO=1"
if /i "%WHICH%"=="engine" set "DO=1"
if "%DO%"=="1" (
  echo [formCAD] engine ^(pytest, no worker needed^)
  pushd "%ROOT%\backend"
  "%PY%" -m pytest tests -m "not kernel and not mesher" %REST% || set "FAIL=1"
  popd
)
set "DO=0"
if /i "%WHICH%"=="all" set "DO=1"
if /i "%WHICH%"=="workers" set "DO=1"
if "%DO%"=="1" (
  echo [formCAD] kernel and mesher workers ^(pytest^)
  pushd "%ROOT%\backend"
  "%PY%" -m pytest tests -m "kernel or mesher" %REST% || set "FAIL=1"
  popd
)
set "DO=0"
if /i "%WHICH%"=="all" set "DO=1"
if /i "%WHICH%"=="scripts" set "DO=1"
if "%DO%"=="1" (
  echo [formCAD] dispatcher and setup scripts ^(pytest^)
  pushd "%ROOT%"
  "%PY%" -m pytest setup\tests -q -p no:cacheprovider %REST% || set "FAIL=1"
  popd
)
set "DO=0"
if /i "%WHICH%"=="all" set "DO=1"
if /i "%WHICH%"=="browser" set "DO=1"
if "%DO%"=="1" (
  echo [formCAD] the app in a browser ^(Playwright, dev build on 5290, engine on 8290^)
  pushd "%ROOT%"
  "%PY%" -m pytest e2e %REST% || set "FAIL=1"
  popd
)
exit /b %FAIL%
