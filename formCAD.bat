@echo off
setlocal
cd /d "%~dp0"
set "CMD=%~1"
set "ARG=%~2"
if "%CMD%"=="" set "CMD=boot"
if /i "%CMD%"=="boot" ( call setup\boot_all.bat & goto :done )
if /i "%CMD%"=="dev" ( call setup\boot_all.bat & goto :done )
if /i "%CMD%"=="install" ( call setup\install_all.bat %ARG% & goto :done )
if /i "%CMD%"=="install-desktop" ( call setup\install_desktop.bat & goto :done )
if /i "%CMD%"=="install-kernel" ( call setup\install_kernel.bat & goto :done )
if /i "%CMD%"=="install-mesher" ( call setup\install_mesher.bat & goto :done )
if /i "%CMD%"=="backend" ( call setup\boot_backend.bat & goto :done )
if /i "%CMD%"=="frontend" ( call setup\boot_frontend.bat & goto :done )
if /i "%CMD%"=="build" ( call setup\build_frontend.bat & goto :done )
if /i "%CMD%"=="serve" ( call setup\serve.bat & goto :done )
if /i "%CMD%"=="freeze" ( call setup\freeze_backend.bat & goto :done )
if /i "%CMD%"=="freeze-kernel" ( call setup\freeze_kernel.bat & goto :done )
if /i "%CMD%"=="freeze-mesher" ( call setup\freeze_mesher.bat & goto :done )
if /i "%CMD%"=="desktop" (
  if /i "%ARG%"=="build" ( call setup\desktop_build.bat %3 %4 %5 %6 %7 %8 %9 ) else ( call setup\desktop_dev.bat )
  goto :done
)
if /i "%CMD%"=="doctor" ( call setup\doctor.bat & goto :done )
if /i "%CMD%"=="test" ( call setup\test.bat %2 %3 %4 %5 %6 %7 %8 %9 & goto :done )
if /i "%CMD%"=="mcp" ( call setup\mcp.bat & goto :done )
if /i "%CMD%"=="agents" ( call setup\agents.bat %2 %3 %4 %5 %6 %7 %8 %9 & goto :done )
if /i "%CMD%"=="clean" ( call setup\clean.bat %ARG% & goto :done )
if /i "%CMD%"=="version" ( call :version & goto :done )
if /i "%CMD%"=="--version" ( call :version & goto :done )
if /i "%CMD%"=="help" ( call :usage & exit /b 0 )
echo [formCAD] unknown command: %CMD%
call :usage
exit /b 2
:done
exit /b %ERRORLEVEL%
:version
for /f "tokens=2 delims='" %%v in ('findstr /b /c:"export const VERSION" frontend\src\version.ts') do echo FormCAD %%v
exit /b 0
:usage
echo formCAD.bat [command]
echo   boot ^| install [--lite] ^| install-desktop ^| install-kernel ^| install-mesher ^| backend ^| frontend
echo   build ^| serve ^| freeze ^| freeze-kernel ^| freeze-mesher ^| desktop dev ^| desktop build ^| doctor ^| test [layer] ^| mcp ^| agents sync^|check^|install [--dry-run] ^| clean [--all] ^| version ^| help
exit /b 0
