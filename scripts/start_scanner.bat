@echo off
setlocal

set ROOT=c:\Users\pedro\crypto-dashboard
set PYTHON=%ROOT%\venv\Scripts\python.exe
set STREAMLIT=%ROOT%\venv\Scripts\streamlit.exe

echo Iniciando Scanner...
start "CryptoScanner" cmd /k "cd /d %ROOT% && %PYTHON% scripts\run_scanner.py --interval 15"

endlocal