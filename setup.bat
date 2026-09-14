@echo off
if not exist .env copy .env.example .env
py -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\pip.exe install -r requirements.txt
if errorlevel 1 exit /b 1
echo Setup complete. Run run.bat
