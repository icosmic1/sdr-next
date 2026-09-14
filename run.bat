@echo off
if not exist .venv\Scripts\uvicorn.exe (
  echo Run setup.bat first.
  exit /b 1
)
.venv\Scripts\uvicorn.exe app.main:app --reload --host 127.0.0.1 --port 8000
