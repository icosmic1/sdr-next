$ErrorActionPreference = "Stop"
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -r requirements.txt
Write-Host "Setup complete. Run .\run.ps1" -ForegroundColor Green
