$ErrorActionPreference = "Stop"
if (-not (Test-Path ".venv\Scripts\uvicorn.exe")) { throw "Run .\setup.ps1 first." }
& .\.venv\Scripts\uvicorn.exe app.main:app --reload --host 127.0.0.1 --port 8000
