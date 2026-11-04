@echo off
rem Double-click to set up ASCII 3D Shapes for the terminal (see install.py)
setlocal
cd /d "%~dp0"
title ASCII 3D Shapes - Setup

rem "py" comes with python.org installs; "python" may be the Store shortcut,
rem which fails instead of running, so only use it if it really works
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"

if not defined PY (
    echo.
    echo Python is not installed yet. To get it:
    echo.
    echo   1. Go to https://www.python.org/downloads/ and click the Download button.
    echo   2. Run the installer. On its first screen, tick "Add python.exe to PATH".
    echo   3. Then double-click this file again.
    echo.
    pause
    exit /b 1
)

%PY% install.py
echo.
pause
