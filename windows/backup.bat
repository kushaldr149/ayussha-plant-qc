@echo off
rem Ayussha Plant - back up the database. Safe to run while the app is running.
setlocal
cd /d "%~dp0.."
if exist ".env" for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do set "%%A=%%B"
".venv\Scripts\python.exe" scripts\backup.py
echo Copy the data\backups folder to another drive or computer regularly.
pause
