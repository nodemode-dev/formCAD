@echo off
cd /d "%~dp0"
call setup\install_all.bat %*
exit /b %ERRORLEVEL%
