@echo off
rem Ayussha Plant QC - start the app on Windows. Keep this window open while the app is in use.
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo The app is not set up yet. Run windows\install.bat first.
  pause
  exit /b 1
)
if not exist ".env" (
  echo The settings file .env is missing. Run windows\install.bat first.
  pause
  exit /b 1
)

rem Load settings from .env (lines starting with # are comments).
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do set "%%A=%%B"

if "%HOST%"=="" set "HOST=127.0.0.1"
if "%PORT%"=="" set "PORT=8000"

echo.
echo Ayussha Plant QC is starting.
if "%HOST%"=="127.0.0.1" (
  echo Open http://127.0.0.1:%PORT% in a browser on this computer.
) else (
  echo Open http://127.0.0.1:%PORT% on this computer, or http://^<this computer's IP address^>:%PORT% from other computers on the network.
)
echo Close this window or press Ctrl+C to stop the app.
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host %HOST% --port %PORT% --no-use-colors
pause
