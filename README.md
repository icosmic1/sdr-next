# SDR Next — Python Real-Time Research Copilot

A small, single-process SDR prioritization application. It imports companies from CSV, researches company-owned public web pages, stores evidence in SQLite, calculates a deterministic Next Best Action score, refreshes on a schedule, and serves a responsive dashboard.

## What is real and what is not

- Research requests are made live when an account is imported or manually refreshed.
- Scheduled refresh runs inside the FastAPI process (default: every 6 hours).
- Every displayed signal includes the source URL and evidence excerpt.
- Public web research is near-real-time, not an instantaneous webhook.
- The research engine intentionally avoids LinkedIn scraping and blocks private/reserved network destinations.
- Keyword extraction is intentionally conservative and should be upgraded with licensed data APIs for commercial accuracy.

## Requirements

- Python 3.11 or newer
- Internet access for live company research

## Windows PowerShell setup

```powershell
Copy-Item .env.example .env
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and import `sample-accounts.csv`.

If PowerShell blocks activation, run once in the same window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## Windows CMD setup

```bat
copy .env.example .env
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## macOS/Linux setup

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Docker setup

```bash
cp .env.example .env
docker compose up --build
```

Open http://127.0.0.1:8000.

## API documentation

Open http://127.0.0.1:8000/docs.

Important endpoints:

- `POST /api/import`
- `GET /api/accounts`
- `GET /api/accounts/{id}`
- `POST /api/accounts/{id}/refresh`
- `POST /api/refresh-all`
- `GET /api/health`

## CSV format

Required columns:

```text
company_name,company_domain,prospect_name,prospect_title
```

Optional columns:

```text
email,phone,industry,employee_count,icp_score
```

Use a verified company domain. Company names alone are intentionally rejected because they are ambiguous.

## Run tests

```bash
pytest -q
```

## Production notes

SQLite and the in-process scheduler are suitable for a local demo or one application instance. For a public deployment, use one worker process. When the product needs multiple instances, migrate to managed PostgreSQL and an external scheduled job before scaling.
