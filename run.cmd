@echo off
REM Zeres MID Register - Windows launcher.
REM Double-click this file, or run it from PowerShell as .\run.cmd
REM
REM A .cmd file rather than a .ps1 on purpose: PowerShell's execution policy
REM blocks double-clicked .ps1 scripts on a default Windows install, which is
REM exactly the wall this is meant to remove.

cd /d "%~dp0"

REM Find Python. The py launcher ships with the python.org installer; plain
REM python is what winget and the Microsoft Store put on PATH.
set PY=
where py >nul 2>&1 && set PY=py -3
if "%PY%"=="" ( where python >nul 2>&1 && set PY=python )
if "%PY%"=="" (
  echo.
  echo   Python was not found.
  echo.
  echo   Install it, then run this again:
  echo       winget install Python.Python.3.12
  echo.
  echo   Close and reopen this window afterwards so PATH updates.
  echo.
  pause
  exit /b 1
)

REM First run: build the virtual environment and install dependencies.
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo   First run - setting up. This takes a minute or two.
  echo.
  %PY% -m venv .venv
  if errorlevel 1 goto :failed
  .venv\Scripts\python.exe -m pip install --upgrade pip --quiet
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto :failed
  echo.
  echo   Setup complete.
  echo.
)

echo   Starting. Your browser will open shortly.
echo   Leave this window open while you use the app; close it to stop.
echo.
.venv\Scripts\python.exe -m app
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo   Something went wrong - the messages above say what.
echo   If it mentions permissions, make sure this folder is somewhere you own
echo   (Documents is fine) and NOT inside C:\Windows or Program Files.
echo.
pause
exit /b 1
