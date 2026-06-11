@echo off
:: Crypto Dashboard — arranque para Task Scheduler o doble clic
:: Configura en Task Scheduler apuntando a este .bat

cd /d "%~dp0.."

call venv\Scripts\activate.bat

if not exist data\ mkdir data
if not exist logs\ mkdir logs

echo [start_dashboard] Lanzando Streamlit en http://localhost:8501
venv\Scripts\python.exe -m streamlit run app/main.py --server.address=0.0.0.0 --server.port=8501 --server.headless=true --browser.serverAddress=localhost

pause
