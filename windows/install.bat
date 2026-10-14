@echo off
rem Ayussha Plant - one-time setup on Windows.
rem Needs Python 3.11 or newer from https://www.python.org/downloads/ (tick "Add python.exe to PATH" when installing).
setlocal
cd /d "%~dp0.."

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python 3.11 or newer was not found.
  echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH", then run this file again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating the Python environment...
  %PY% -m venv .venv || goto :fail
)

echo Installing the app's packages (this needs internet the first time)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install --prefer-binary -r requirements.txt || goto :fail

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo.
  echo A settings file .env was created. Set INITIAL_ADMIN_PASSWORD in it now:
  echo at least 10 characters with upper and lower case letters and a digit.
  notepad ".env"
)

echo.
echo Setup finished. Start the app with windows\start.bat
pause
exit /b 0

:fail
echo.
echo Setup did not finish. Read the messages above for the reason.
pause
exit /b 1
