# LinkedIn Profile API

A hosted HTTPS API that accepts a LinkedIn profile URL and returns structured JSON —
name, headline, location, about, experience, education, skills, certifications,
languages, and image URLs.

It is built around a **pluggable data-provider architecture**. Out of the box it runs
on synthetic/fixture data, so the whole thing is testable, demoable, and deployable
**without touching LinkedIn or risking an account**. A real browser-automation scraper
is included as an **optional, off-by-default** provider — see
[Known Limitations / ToS](#known-limitations--tos) before you even think about enabling it.

> **This is a portfolio / demonstration project, not a production scraping service.**
> Scraping LinkedIn violates its User Agreement and carries a real risk of account
> suspension. The default configuration deliberately does not touch LinkedIn.

---

## Table of contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [The provider model](#the-provider-model)
- [Quick start](#quick-start)
- [Testing it locally](#testing-it-locally)
- [Configuration](#configuration)
- [API reference](#api-reference)
- [Response schema](#response-schema)
- [Deployment](#deployment)
- [The optional LinkedIn scraper](#the-optional-linkedin-scraper)
- [Known Limitations / ToS](#known-limitations--tos)
- [Project layout](#project-layout)
- [License](#license)

---

## What it does

You give it a LinkedIn profile URL; it gives you clean, predictable JSON.

Because the underlying work (a real scrape) is slow and must be rate-limited, the API is
**asynchronous** — you submit a job and poll for the result, rather than blocking on one
long request:

1. **`POST /api/v1/profile`** with a URL.
   - If a fresh copy is already cached, you get the data immediately (**`200`**).
   - Otherwise a background job is queued and you get a `job_id` back (**`202`**).
2. **`GET /api/v1/profile/{job_id}`** to poll until the job is `done` (or `error`), then
   read the structured profile from the `data` field.

Every completed result is **cached in SQLite**, keyed by the *canonical* profile URL, so
a profile already fetched within the TTL window (default 7 days) is never re-fetched. All
`/api/v1/*` access is guarded by an `X-API-Key` header.

**At a glance:**

| | |
|---|---|
| **Predictable JSON shape** | Unavailable fields are `null` (scalars) or `[]` (sections) — never missing. Clients can rely on the contract in [`docs/schema.json`](docs/schema.json). |
| **Async job model** | Submit → poll. Long fetches never block the request; the same result can be re-read cheaply. |
| **TTL cache** | SQLite-backed, keyed by canonical URL. No duplicate work within the TTL window. |
| **Graceful degradation** | A private or partial profile returns whatever *was* available plus a `warnings` array, rather than failing outright. |
| **Pluggable providers** | `mock` / `fixture` / `linkedin`, chosen by one env var. The app depends on an interface, not a data source. |
| **No secrets in git** | All config via `.env`; only `.env.example` is committed. `.gitignore` covers `.env`, `data/`, and `session/` from the first commit. |
| **Runs anywhere** | Single container, config via env, reads `PORT` from the platform, health endpoint for probes. |

## How it works

```mermaid
flowchart LR
    client([Client]) -->|"POST /api/v1/profile<br/>X-API-Key"| api[FastAPI app]
    api -->|cache hit?| cache[(SQLite<br/>profiles + jobs)]
    api -->|"miss → enqueue"| queue[[Job queue]]
    queue --> worker[Worker]
    worker -->|fetch| provider{{Provider}}
    provider -->|store result| cache
    client -->|"GET /profile/{job_id}"| api

    provider -.-> mock[mock<br/>synthetic]
    provider -.-> fixture[fixture<br/>canned JSON]
    provider -.-> linkedin[linkedin<br/>Playwright · OFF by default]
```

### Request lifecycle

1. **Validate + canonicalize the URL** ([`app/urls.py`](app/urls.py)). Anything that isn't a
   `linkedin.com/in/<slug>` URL is rejected with `422`. Inputs like
   `linkedin.com/in/jane-doe`, `http://linkedin.com/in/jane-doe?trk=abc`, and
   `https://www.linkedin.com/in/jane-doe/` all normalize to the single canonical form
   `https://www.linkedin.com/in/jane-doe` — so the same person requested three different
   ways hits **one** cache row.
2. **Check the cache** ([`app/cache.py`](app/cache.py)). A hit that is still within
   `CACHE_TTL_SECONDS` short-circuits everything and is returned immediately with `200`.
3. **On a miss, create + enqueue a job** ([`app/jobs.py`](app/jobs.py), [`app/db.py`](app/db.py)).
   The client gets a `202` with a `job_id`.
4. **A worker claims the job**, calls the selected **provider**, applies retries with
   exponential backoff on *transient* failures, stores the result in the cache, and marks
   the job `done`. Non-transient failures (not found, private, dead session) fail the job
   fast with a clear message instead of retrying pointlessly.
5. **The worker runs inline** inside the API process by default (great for a demo), or as a
   **standalone process** ([`app/worker.py`](app/worker.py)) that atomically claims queued
   jobs from the DB — so you can scale workers out without touching the API code.

Cross-cutting: structured JSON logging with a per-request `request_id`
([`app/logging_config.py`](app/logging_config.py)), constant-time API-key comparison
([`app/auth.py`](app/auth.py)), and a courtesy randomized delay between remote actions.

### Why it's built this way

- **Provider inversion is the whole point.** The API, queue, cache, and persistence never
  know how a profile is obtained — they depend on a `ProfileProvider` interface. That single
  decision is what lets the entire system be tested and deployed with **zero** LinkedIn
  contact, while still leaving a real scraper as a drop-in option. It also means "swap in a
  different data source" is a localized change, not a rewrite.
- **Async jobs, not blocking calls.** A real scrape can take many seconds and must be paced.
  A submit-then-poll design keeps requests fast, makes retries/caching natural, and models
  how you'd actually run this behind a queue.
- **SQLite by default.** Zero-setup persistence that's perfect for a demo. The DB layer is
  small and self-contained ([`app/db.py`](app/db.py)), so moving to Postgres later is
  localized to that one module.
- **Politeness, not evasion.** The scraper applies only a randomized courtesy delay. There is
  deliberately **no** anti-bot-detection — see [Known Limitations / ToS](#known-limitations--tos).

## The provider model

The core of the design is that the app depends on a **`ProfileProvider` protocol**
([`app/providers/base.py`](app/providers/base.py)), never on any specific data source:

```python
class ProfileProvider(Protocol):
    name: str
    async def fetch(self, url: str) -> ProfileResult: ...
    async def healthcheck(self) -> ProviderHealth: ...
```

`get_provider()` picks the implementation from the `PROVIDER` env var:

| `PROVIDER` | Source | Needs network / account? | Use for |
|------------|--------|--------------------------|---------|
| `mock` *(default)* | Deterministic synthetic data seeded from the URL slug | No | Local dev, demos, load-testing the API |
| `fixture` | Canned JSON in `tests/fixtures/profiles/` | No | The automated test suite |
| `linkedin` | Real Playwright + Chromium scraper | **Yes — and violates ToS** | Manual, at-your-own-risk experiments only |

The `mock` provider is worth calling out: it fabricates a **fully-shaped, deterministic**
profile from a hash of the URL slug. The same URL always yields the same person, so demos and
screenshots are stable, yet every downstream layer (queue → worker → cache → persistence →
API) is exercised for real. Every mock result carries a `warnings` entry stating it's synthetic.

This inversion is what makes the API **fully testable and CI-safe without ever hitting
LinkedIn**. The heavy scraper dependencies (Playwright, BeautifulSoup) are an optional install
extra and are imported lazily, so the core app and the test suite don't require a browser
engine at all.

## Quick start

**Requirements:** Python 3.11+. (Optional scraper only: also Playwright + Chromium.)

### 1. Install

```bash
git clone <your-repo-url> linkedin-profile-api
cd linkedin-profile-api
python -m venv .venv
# activate it:
. .venv/bin/activate            # macOS/Linux
.venv\Scripts\Activate.ps1      # Windows PowerShell
pip install -e ".[dev]"         # core app + test/lint tooling
```

> There's a `Makefile` with shortcuts (`make install`, `make run`, `make test`, …).
> On Windows without `make`, run the underlying commands shown in each section — they're
> all plain `python -m …` invocations.

### 2. Configure

```bash
cp .env.example .env                   # Windows PowerShell: copy .env.example .env
```

Generate a strong API key and paste it into `.env` as `API_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

The remaining defaults (`PROVIDER=mock`, SQLite at `./data/profiles.db`) work immediately —
**no LinkedIn credentials are required** to run and evaluate the whole API.

### 3. Run

```bash
uvicorn app.main:app --reload          # or:  make run  /  linkedin-api
```

Open **<http://localhost:8000/docs>** for interactive Swagger docs. You're ready — jump to
[Testing it locally](#testing-it-locally).

## Testing it locally

There are three ways to exercise it, from easiest to most scriptable.

### A. The automated test suite

The suite runs **entirely offline** against the `fixture` provider — no credentials, no
network, no live LinkedIn — so it's safe for CI and for a fresh clone.

```bash
pytest            # or: make test   →  expect: 37 passed
ruff check .      # lint             →  expect: All checks passed!
```

It covers URL normalization, the HTML parsers (against saved HTML fixtures), the mock/fixture
providers, the TTL cache, and the **full API lifecycle** — auth, validation, enqueue → poll →
done, cache hits, and error handling — driven through the real ASGI app with the inline worker.
The API tests force `PROVIDER=fixture` and a test `API_KEY`, so they never read your `.env`.

### B. One-shot from the command line (no server needed)

Fetch a single profile straight through a provider and print the JSON — handy for a quick look:

```bash
python -m app.cli https://www.linkedin.com/in/jane-doe
python -m app.cli https://www.linkedin.com/in/jane-doe --provider fixture --quiet
```

With the default `mock` provider this returns a complete, deterministic profile for any slug.
(`--provider fixture` only works for slugs that have a JSON file in `tests/fixtures/profiles/`,
e.g. `ada-lovelace`.)

### C. Exercise the running API end to end

Start the server (`make run`), then walk through the async flow. With the default `mock`
provider a job completes in well under a second, so a single poll is effectively instant.

**Easiest — the browser.** Open <http://localhost:8000/docs>, click **Authorize**, paste your
`API_KEY`, and try `POST /api/v1/profile` then `GET /api/v1/profile/{job_id}` right in the page.

**With `curl` (macOS/Linux, and Windows via `curl.exe`):**

```bash
export API_KEY="paste-your-key-here"      # Windows PS: $env:API_KEY="paste-your-key-here"

# 1) Health — no auth required
curl -s localhost:8000/health

# 2) Submit a URL → 202 with a job_id (cache miss)
curl -s -X POST localhost:8000/api/v1/profile \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"url":"https://www.linkedin.com/in/jane-doe"}'

# 3) Poll the job → status goes queued → running → done, with `data` populated
curl -s localhost:8000/api/v1/profile/PASTE_JOB_ID -H "X-API-Key: $API_KEY"

# 4) Submit the SAME url again → now a cache hit: 200, "cached": true, data inline
curl -s -X POST localhost:8000/api/v1/profile \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"url":"https://www.linkedin.com/in/jane-doe"}'
```

**With PowerShell (Windows-native):**

```powershell
$env:API_KEY = "paste-your-key-here"
$headers = @{ "X-API-Key" = $env:API_KEY }
$base    = "http://localhost:8000"

# 1) Health
Invoke-RestMethod "$base/health" | ConvertTo-Json -Depth 5

# 2) Submit → capture the job_id
$body = '{"url":"https://www.linkedin.com/in/jane-doe"}'
$job  = Invoke-RestMethod -Method Post "$base/api/v1/profile" `
          -Headers $headers -ContentType "application/json" -Body $body
$job.job_id

# 3) Poll
Invoke-RestMethod "$base/api/v1/profile/$($job.job_id)" -Headers $headers |
  ConvertTo-Json -Depth 8

# 4) Same URL again → cache hit ($r.cached is $true, data is filled in)
$r = Invoke-RestMethod -Method Post "$base/api/v1/profile" `
       -Headers $headers -ContentType "application/json" -Body $body
$r.cached
```

**Check the error paths too:**

```bash
# Missing/invalid key → 401
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/api/v1/profile \
  -H "Content-Type: application/json" -d '{"url":"https://www.linkedin.com/in/jane-doe"}'

# Not a profile URL (company page) → 422
curl -s -X POST localhost:8000/api/v1/profile \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"url":"https://www.linkedin.com/company/acme"}'
```

> **Windows note:** in PowerShell, `curl` is an alias for `Invoke-WebRequest`. Use `curl.exe`
> explicitly if you want the real curl, or use the `Invoke-RestMethod` block above.
> `Invoke-RestMethod` throws on non-2xx responses — add `-SkipHttpErrorCheck` (PowerShell 7+)
> to inspect `401`/`422` bodies without a `try/catch`.

## Configuration

All configuration is via environment variables (see [`.env.example`](.env.example)). Variable
names are case-insensitive; values in `.env` are loaded automatically.

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | `changeme-…` | **Set this.** Value clients must send in the `X-API-Key` header. Generate with `secrets.token_urlsafe(32)`. |
| `PROVIDER` | `mock` | Data source: `mock` \| `fixture` \| `linkedin`. |
| `DATABASE_URL` | `sqlite:///./data/profiles.db` | SQLite path. The parent directory is created automatically. (A Postgres URL is parsed by config, but only the SQLite backend ships — see [`app/db.py`](app/db.py).) |
| `CACHE_TTL_SECONDS` | `604800` (7 days) | Don't re-fetch a profile cached more recently than this. |
| `LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR`. |
| `RUN_INLINE_WORKER` | `true` | Run the worker inside the API process. Set `false` to use a standalone `app.worker`. |
| `FETCH_MIN_DELAY_SECONDS` | `1.5` | Lower bound of the courtesy delay between remote actions. |
| `FETCH_MAX_DELAY_SECONDS` | `4.0` | Upper bound of the courtesy delay. |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Bind address/port for the `linkedin-api` entry point. Hosting platforms that inject `PORT` (Render, Fly, Railway…) work with no code change. |
| `LI_EMAIL` / `LI_PASSWORD` | — | LinkedIn credentials — **only** read when `PROVIDER=linkedin`. Use a throwaway account. |
| `SESSION_STATE_PATH` | `./session/state.json` | Where the authenticated browser session is stored. |
| `LINKEDIN_HEADLESS` | `true` | Whether the scraper runs headless. |

Secrets (`API_KEY`, `LI_*`) live only in `.env`, which is git-ignored from the first commit.

## API reference

All `/api/v1/*` endpoints require the `X-API-Key` header. `/health` and `/` are public.

### `GET /health`

Liveness plus provider readiness. No auth. Good for load-balancer / platform health checks.

```json
{
  "status": "ok",
  "version": "0.1.0",
  "provider": { "provider": "mock", "ok": true, "detail": "synthetic data, always ready" }
}
```

### `POST /api/v1/profile`

Submit a profile URL. Body: `{ "url": "https://www.linkedin.com/in/<slug>" }`.

- **`202 Accepted`** — job queued (cache miss):

  ```json
  { "job_id": "a1b2c3…", "status": "queued", "url": "https://www.linkedin.com/in/jane-doe", "cached": false, "data": null }
  ```

- **`200 OK`** — served from cache (`cached: true`, `data` populated, `status: "done"`).
- **`401`** — missing/invalid API key. **`422`** — not a valid LinkedIn profile URL.

### `GET /api/v1/profile/{job_id}`

Poll a job.

```json
{
  "job_id": "a1b2c3…",
  "status": "done",
  "url": "https://www.linkedin.com/in/jane-doe",
  "data": { "url": "…", "source": "mock", "scraped_at": "…", "profile": { … }, "warnings": [] },
  "error": null
}
```

`status` is one of `queued` \| `running` \| `done` \| `error`. On `error`, `error` holds the
message and `data` is `null`. Unknown `job_id` → `404`.

## Response schema

The full JSON Schema of every response object is committed at
[`docs/schema.json`](docs/schema.json) and generated directly from the Pydantic models
([`app/schemas.py`](app/schemas.py)) — regenerate it with `python -m scripts.dump_schema`.

Abridged shape of the `profile` object inside a result:

```jsonc
{
  "name": "Jane Doe",
  "headline": "Staff Engineer at Acme",
  "location": "London, England, United Kingdom",
  "about": "…",
  "profile_photo_url": "https://…",
  "banner_photo_url": "https://…",
  "experience": [
    { "title": "Staff Engineer", "company": "Acme", "employment_type": "Full-time",
      "location": "London", "start_date": "Jan 2021", "end_date": null,
      "is_current": true, "description": "…" }
  ],
  "education":      [ { "school": "…", "degree": "…", "field_of_study": "…", "start_date": "…", "end_date": "…" } ],
  "skills":         [ { "name": "Python", "endorsement_count": 42 } ],
  "certifications": [ { "name": "…", "issuer": "…", "credential_url": "…" } ],
  "languages":      [ { "name": "English", "proficiency": "Native or bilingual" } ]
}
```

The result envelope wraps it with `url`, `source` (which provider produced it),
`scraped_at` (UTC), and a `warnings` array.

## Deployment

The app is a **standard single container**: all config comes from environment variables, it
binds to `$PORT`, exposes `/health` for probes, and runs as a non-root user. That makes it a
clean fit for any Docker host or container PaaS. HTTPS is normally terminated for you by the
platform (Render/Fly/Railway) or by a reverse proxy on a VPS.

### Before you deploy — checklist

- [ ] **Set a strong `API_KEY`** (as a secret, never in the image). The default is a placeholder.
- [ ] **Keep `PROVIDER=mock`** (or `fixture`). Do **not** deploy `PROVIDER=linkedin` to a public
      or shared service — see [what not to deploy](#what-not-to-deploy).
- [ ] **Decide on persistence.** The SQLite DB lives at `/app/data/profiles.db` inside the
      container. See the persistence note below.
- [ ] Optionally tune `CACHE_TTL_SECONDS` and `LOG_LEVEL`.

### ⚠️ Persistence gotcha (read this)

Most PaaS filesystems are **ephemeral** — they're wiped on every deploy and restart. Since the
cache and job history live in SQLite on disk, you must **mount a persistent volume at
`/app/data`** or you'll silently start from an empty cache after each deploy. Every option
below shows how. (For a throwaway demo where a cold cache is fine, you can skip the volume.)

### Option 1 — Any Docker host / VPS (simplest)

The bundled [`docker-compose.yml`](docker-compose.yml) already wires up a persistent named
volume, a health check, and `restart: unless-stopped`:

```bash
git clone <your-repo-url> && cd linkedin-profile-api
printf 'API_KEY=%s\nPROVIDER=mock\n' "$(python -c 'import secrets;print(secrets.token_urlsafe(32))')" > .env
docker compose up -d --build
curl -s localhost:8000/health
```

For public HTTPS, put it behind a reverse proxy that handles TLS (e.g. Caddy or nginx +
Let's Encrypt) and forward to the container's port 8000.

To build/run the image directly instead of via compose:

```bash
docker build -t linkedin-profile-api .
docker run -d -p 8000:8000 \
  -e API_KEY=your-strong-key -e PROVIDER=mock \
  -v profiles-data:/app/data \
  linkedin-profile-api
```

### Option 2 — Render

Render builds straight from the `Dockerfile` and injects `PORT` (the app reads it). Add a
**persistent disk** mounted at `/app/data`. Either configure it in the dashboard or commit a
blueprint like this as `render.yaml`:

```yaml
services:
  - type: web
    name: linkedin-profile-api
    runtime: docker
    dockerfilePath: ./Dockerfile
    plan: starter                # a paid plan is required for a persistent disk
    healthCheckPath: /health
    envVars:
      - key: API_KEY
        generateValue: true      # Render generates and stores a strong secret
      - key: PROVIDER
        value: mock
      - key: CACHE_TTL_SECONDS
        value: "604800"
    disk:
      name: profiles-data
      mountPath: /app/data
      sizeGB: 1
```

### Option 3 — Fly.io

`fly launch` detects the `Dockerfile`. Create a volume and mount it at `/app/data`, and set the
API key as a secret:

```bash
fly launch --no-deploy                       # generates fly.toml
fly volumes create profiles_data --size 1
fly secrets set API_KEY=your-strong-key
fly deploy
```

Minimal `fly.toml`:

```toml
app = "linkedin-profile-api"
primary_region = "iad"

[env]
  PROVIDER = "mock"
  PORT = "8000"

[http_service]
  internal_port = 8000            # matches EXPOSE 8000 in the Dockerfile
  force_https = true

[[mounts]]
  source = "profiles_data"        # the volume name created above
  destination = "/app/data"
```

### Option 4 — Railway / others

Same recipe everywhere: point the platform at the `Dockerfile`, set `API_KEY` (+ `PROVIDER=mock`)
as variables, add a volume mounted at `/app/data`, and let the platform route to the container's
port. The app reads `PORT` from the environment, so nothing in code needs to change.

### Scaling notes

- **One instance + inline worker** (the default) is right for a demo. `RUN_INLINE_WORKER=true`
  runs the job worker inside the API process.
- **Separate workers:** set `RUN_INLINE_WORKER=false` and run `python -m app.worker` as its own
  process/service. It atomically claims queued jobs from the shared DB, so the API and worker(s)
  never double-process a job.
- **Horizontal scale / multiple instances:** SQLite is single-writer and assumes one local disk,
  so it is *not* the right backing store for several instances at once. The DB layer is isolated
  in [`app/db.py`](app/db.py) specifically so you can swap in Postgres (asyncpg) when you outgrow
  a single node — that's the intended "next step," not a rewrite.

### What not to deploy

Do **not** run `PROVIDER=linkedin` on a hosted/public service. It automates a logged-in LinkedIn
session (violating the User Agreement, risking a ban), requires shipping a real session-state
file, and is single-session by design. The scraper is for local, at-your-own-risk experiments
only — see below.

## The optional LinkedIn scraper

> Read [Known Limitations / ToS](#known-limitations--tos) first. Enabling this uses a
> real logged-in session and can get the account banned.

If you understand and accept the risk (e.g. for a private experiment with a throwaway
account you're willing to lose):

```bash
pip install -e ".[scraper]"                 # or: make install-scraper
python -m playwright install chromium
python -m scripts.login                     # headed browser; log in + pass 2FA manually
# set PROVIDER=linkedin and LI_EMAIL / LI_PASSWORD in .env
python -m scripts.smoke_live "https://www.linkedin.com/in/<slug>"
```

`scripts/login.py` performs an interactive, **headed** login once and saves the session
state to `SESSION_STATE_PATH`; the scraper reuses that session. The CSS selectors in
`app/providers/linkedin_parsers.py` are **illustrative** — LinkedIn's markup is
obfuscated and changes frequently, so expect to adjust them, and expect fields to come
back empty (each result says so in `warnings`).

**Deliberate non-goals:** this project applies only a polite, randomized request delay.
It does **not** implement, and will not implement, anti-bot-detection, fingerprint
evasion, CAPTCHA solving, or proxy rotation. Those exist to defeat a platform's access
controls; that is out of scope here by design.

## Known Limitations / ToS

**Please read this.**

- **Scraping LinkedIn violates the LinkedIn User Agreement.** Using the `linkedin`
  provider automates a logged-in session, which is against LinkedIn's terms and **can
  result in permanent suspension of the account used.** Never use a personal account.
  This repository is a **portfolio/demo project, not a production scraping service.**
- **Default is safe.** With `PROVIDER=mock` (or `fixture`) the API never contacts
  LinkedIn and carries none of this risk. That's the intended way to run and evaluate it.
- **No anti-detection.** As above, only courtesy rate-limiting is implemented. There is
  no attempt to evade bot detection.
- **Fragile selectors.** LinkedIn's HTML is dynamic and obfuscated. The scraper's
  parsers are best-effort and will break; graceful degradation returns partial data with
  `warnings` rather than crashing.
- **Personal data / GDPR.** LinkedIn profiles are personal data. Collecting, storing, or
  processing it may be regulated (e.g. GDPR/CCPA) and may require a lawful basis and the
  individual's awareness. The cache stores fetched profiles in SQLite; treat that data
  accordingly, secure it, and delete it when it's no longer needed. **You are the data
  controller for anything you scrape — comply with the law in your jurisdiction.**
- **Rate limits & scale.** The single-session, single-worker design is intentional; this
  is not built to scrape at scale, and doing so would compound both the ToS and legal risk.

## Project layout

```
app/
  main.py              FastAPI app, routes, lifespan, request logging
  config.py            Settings (pydantic-settings) from .env
  urls.py              LinkedIn URL validation + canonicalization
  schemas.py           Pydantic models — the API contract
  auth.py              X-API-Key dependency (constant-time compare)
  db.py                aiosqlite: profiles + jobs tables, atomic job claim
  cache.py             TTL freshness check + store/lookup
  jobs.py              In-process queue, submit(), retries, job processing
  worker.py            Standalone worker entry point
  logging_config.py    Structured JSON logging with request context
  cli.py               `python -m app.cli <url>` one-shot fetch
  providers/
    base.py            ProfileProvider protocol + error hierarchy
    mock.py            Deterministic synthetic provider (default)
    fixture.py         Canned-JSON provider (tests)
    linkedin.py        Optional Playwright scraper (off by default)
    linkedin_parsers.py  Pure HTML → dict parsers (browser-free, unit-tested)
scripts/               login, live smoke test, fixture + schema generators
tests/                 offline suite + HTML/JSON fixtures
docs/schema.json       generated response schema
Dockerfile, docker-compose.yml, Makefile, pyproject.toml, .env.example
```

## License

MIT — see [`LICENSE`](LICENSE). (Update the copyright holder placeholder to your name.)

*Built as a demonstration of API design, async job processing, and a testable,
provider-abstracted architecture — not as a tool to scrape LinkedIn at scale.*
