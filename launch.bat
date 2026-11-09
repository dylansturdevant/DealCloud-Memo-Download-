@echo off
setlocal
cd /d "%~dp0"
if not exist "dealcloud-memo-venv\Scripts\python.exe" goto setup
"dealcloud-memo-venv\Scripts\python.exe" -c "import streamlit, pandas, dealcloud_sdk, openpyxl; assert hasattr(streamlit, 'fragment')" >nul 2>&1
if errorlevel 1 goto setup
goto run
:setup
call "%~dp0setup.bat"
if errorlevel 1 exit /b 1
:run
echo Opening the local DealCloud app at http://127.0.0.1:8501
echo Keep this window open while using the app. Press Ctrl+C here to stop the server.
"dealcloud-memo-venv\Scripts\python.exe" -m streamlit run app.py --server.address=127.0.0.1 --server.port=8501 --server.maxUploadSize=10 --server.fileWatcherType=none --browser.gatherUsageStats=false
if errorlevel 1 (
 echo App exited with an error. If port 8501 is occupied, close the other local app or use another port.
 pause
)
