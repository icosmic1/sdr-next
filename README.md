# SDR Next — Python Real-Time Research Copilot

A small, single-process SDR prioritization application. It imports companies from CSV, researches company-owned public web pages plus live public news APIs, stores evidence in SQLite, calculates a deterministic Next Best Action score, refreshes on a schedule, and serves a responsive dashboard.

## What is real and what is not

- Research requests are made live when an account is imported or manually refreshed. It queries company-owned pages, Google News RSS, and the Hacker News Algolia API; both API providers work without an API key and can be disabled in `.env`.
- On startup, every tracked company is queued for live research. The in-process scheduler then queues company refreshes every 30 minutes by default.
- A prospect can be refreshed on demand in the dashboard. This queues a background public-web search for that prospect name plus company and keeps person evidence separate from company signals.
- **Draft outreach** uses Gemini from the server only. It turns the account and existing verified evidence into a suggested subject line, email, and call angle; it never treats generated text as research evidence.
- Every displayed signal includes the source URL and evidence excerpt.
- Public web research is near-real-time, not an instantaneous webhook.
- The research engine intentionally avoids LinkedIn scraping and blocks private/reserved network destinations.
- Keyword extraction is intentionally conservative. For commercial-grade coverage, add a licensed enrichment/news provider and its credentials rather than scraping restricted networks.

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
- `POST /api/prospects/{id}/refresh` (background; returns `202 Accepted`)
- `POST /api/prospects/{id}/follow-ups` (create an owned, dated next step)
- `PATCH /api/follow-ups/{id}` (complete, snooze, or update a follow-up)
- `PUT /api/prospects/{id}/contact-preference` (do-not-contact control)
- `GET /api/follow-ups`
- `GET /api/research-jobs/{id}`
- `GET /api/research-status`
- `GET /api/activity`
- `PATCH /api/accounts/{id}/icp`
- `GET /api/scoring-rules`
- `PUT /api/scoring-rules`
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

## Live research providers

The external providers are enabled by default and need no credentials:

- Google News RSS: current web-news mentions for the exact company name.
- Hacker News Algolia API: public technology-community stories mentioning the company.

Set `GOOGLE_NEWS_ENABLED=false` or `HACKER_NEWS_ENABLED=false` to disable a provider, and use `MAX_EXTERNAL_NEWS_RESULTS` to cap per-provider results. Provider errors are isolated: a failed news API does not prevent company-owned site research. Person research uses the same public providers with an exact person-plus-company query; it does not scrape LinkedIn or any restricted network.

## Gemini outreach assistant

Add a Gemini key to the local `.env` file (never commit it):

```text
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.6-flash
```

Use **Draft outreach** beside a prospect. The key is read only by the FastAPI server and is never sent to the dashboard/browser. A draft is generated only when requested, and its evidence links remain visible for review before sending.

## Dynamic workspace controls

The Activity, ICP settings, and Scoring rules views use SQLite-backed data. Imports, research completions, ICP changes, and scoring-rule saves are recorded in Activity. The app seeds a transparent default scoring configuration on its first start; editing a rule persists it and immediately recalculates every tracked account.

## Run tests

```bash
pytest -q
```

## Production notes

SQLite and the in-process scheduler are suitable for a local demo or one application instance. The default is one queue worker; use `RESEARCH_WORKER_COUNT=1` with SQLite. For a public deployment, use one worker process. When the product needs multiple instances, migrate to managed PostgreSQL and an external scheduled job before scaling.
