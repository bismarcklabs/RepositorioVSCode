@echo off
cd /d C:\Users\pedro\crypto-dashboard

echo Creating virtual environment...
python -m venv venv

echo.
echo Activating virtual environment...
call venv\Scripts\activate.bat

echo.
echo Installing dependencies from requirements.txt...
pip install -r requirements.txt

echo.
echo Installation complete! You can now run:
echo   streamlit run app/main.py
echo.
pause
