@echo off
REM Double-click to build the standalone dist\SPWB application.
REM The real builds are made on GitHub - see .github\workflows\build.yml.
cd /d "%~dp0"

python tools\build_standalone.py
echo.
pause
