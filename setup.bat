@echo off
echo ==============================================
echo Alpaca Bot Local Environment Setup
echo ==============================================

echo [1/3] Creating Python virtual environment...
python -m venv venv

echo [2/3] Activating virtual environment...
call venv\Scripts\activate.bat

echo [3/3] Installing dependencies...
pip install --upgrade pip
pip install -r backend\requirements.txt

echo ==============================================
echo Setup Complete!
echo To activate the environment run: venv\Scripts\activate
echo To start the backend run:        cd backend ^&^& uvicorn main:app --reload
echo ==============================================
pause
