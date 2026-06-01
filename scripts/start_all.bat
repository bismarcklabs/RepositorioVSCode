@echo off
setlocal

set ROOT=c:\Users\pedro\crypto-dashboard
set PYTHON=%ROOT%\venv\Scripts\python.exe
set STREAMLIT=%ROOT%\venv\Scripts\streamlit.exe

echo Iniciando Scanner...
start "CryptoScanner" cmd /k "cd /d %ROOT% && %PYTHON% scripts\run_scanner.py --interval 15"

echo Esperando 6 segundos para que el scanner cargue...
timeout /t 6 /nobreak >nul

echo Iniciando Dashboard...
start "CryptoDashboard" cmd /k "cd /d %ROOT% && %STREAMLIT% run app\main.py"

endlocal
