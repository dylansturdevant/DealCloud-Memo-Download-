@echo off
setlocal
cd /d "%~dp0"
echo Setting up DealCloud Memo Downloader...
if exist "dealcloud-memo-venv\Scripts\python.exe" goto install
py --version >nul 2>&1
if errorlevel 1 goto no_python
py -m venv dealcloud-memo-venv
if errorlevel 1 goto failed
:install
"dealcloud-memo-venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
"dealcloud-memo-venv\Scripts\python.exe" -m pip check
if errorlevel 1 goto failed
echo.
echo Setup complete. Double-click launch.bat to open the app.
pause
exit /b 0
:no_python
echo Python launcher not found. Ask IT to install an approved Python 3.10+ and Windows launcher.
echo Python 3.11 or 3.12 is a reasonable initial choice; current package compatibility still needs checking.
pause
exit /b 1
:failed
echo.
echo Setup failed. Keep the complete error above. Do not bypass organization security settings.
pause
exit /b 1
