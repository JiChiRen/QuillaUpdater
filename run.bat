@echo off
REM Launch the Quilla Updater GUI.
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PY="
py -3 -c "import tkinter" >nul 2>nul && set "PY=py -3"
if not defined PY (
  python -c "import tkinter" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo Python 3 with tkinter was not found.
  echo Install Python 3.8+ from python.org with "tcl/tk" enabled, then retry.
  echo.
  pause
  exit /b 1
)

%PY% -c "import serial" >nul 2>nul
if errorlevel 1 (
  echo Installing the only dependency: pyserial
  %PY% -m pip install --quiet pyserial
  if errorlevel 1 (
    echo.
    echo pip install failed. Run manually:  %PY% -m pip install pyserial
    pause
    exit /b 1
  )
)

start "" %PY% -m quilla_updater.gui
endlocal
