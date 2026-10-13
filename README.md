# Ayussha Plant QC

Web application for the dry mix concrete plant: inward material QC, the production log with lot
traceability, PDF test reports and batch certificates, Excel exports, user logins with roles, an audit
trail, and an AI review of the records through the Claude API.

It runs the same way on a PC or server at the plant (on the plant LAN) or on a cloud server.

## What it does

| Area | Details |
|---|---|
| Logins and roles | Administrator, QC / lab, Plant operator, Management (view only). One-time passwords that must be changed at first sign-in. Lockout after 5 failed sign-ins for 15 minutes. |
| Setup | Plant settings (company, plant, batching tolerance, product lines, shifts), materials, test parameters with minimum/maximum limits and method reference, recipes. Nothing is pre-filled: all limits and the tolerance come from your specifications. |
| Material QC | Test per lot: each value marked within limits or out of limit. Overall result, then a decision: Accepted, On hold or Rejected. An out-of-limit lot can only be accepted with a written remark. Limits are copied onto the test when it is saved, so later changes in Setup never rewrite past tests. |
| Production log | Planned against actual weight per material, deviation %, batching tolerance check, bags and weights. Each material's lot is matched to its QC test; lots on hold, rejected or never tested are flagged. A test page shows every production record that used its lot. |
| Imports and plant API | CSV import of production records (template included), and a token-protected JSON API for the plant control system. |
| Reports | Material test report (PDF), batch traceability certificate (PDF), QC register and production log (Excel) for any date range. |
| AI review | Claude reads the records for a chosen period and summarises out-of-limit results, repeated issues, open decisions and data gaps. It is instructed to use only those records. Reviews are saved. Optional; needs a Claude API key. |
| Audit trail | Every sign-in and every change, with who and when. |

## Install with Docker (recommended)

You need Docker installed on the machine that will run the app
(Docker Desktop on Windows or macOS, Docker Engine on Linux).

```sh
git clone <this repository>
cd ayussha-plant-qc
cp .env.example .env
```

Edit `.env` and set at least `INITIAL_ADMIN_PASSWORD` (10+ characters, upper and lower case, a digit). Then:

```sh
docker compose up -d --build
```

Open `http://<machine-address>:8000` in a browser, sign in as `admin` with that password, and set your
own password when asked. Then work through **Overview → Getting the plant ready**:

1. **Setup → Plant settings**: company name, plant name, batching tolerance, product lines, shifts.
2. **Setup → Materials**: each material you receive.
3. **Setup → Test parameters**: each test per material with limits from your specification.
4. **Users**: an account for each person. The one-time password is shown once.

Data is kept in the Docker volume `plantqc-data`, so it survives restarts and updates.

### Update to a new version

```sh
git pull
docker compose up -d --build
```

### Back up

```sh
docker compose exec plantqc sh scripts/backup.sh
docker compose cp plantqc:/data/backups ./backups
```

Copy the `backups` folder to another machine or drive regularly. A backup on the same disk does not
protect against that disk failing. The 30 most recent backups are kept inside the volume.

## Run without Docker (for development)

Python 3.11 or newer.

```sh
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env            # set INITIAL_ADMIN_PASSWORD
set -a; . ./.env; set +a        # load the settings (Linux/macOS)
uvicorn app.main:app --reload
```

Run the tests with `pytest`.

## Settings

All settings are environment variables; see `.env.example` for the full list with explanations.

| Setting | Purpose |
|---|---|
| `INITIAL_ADMIN_PASSWORD` | First administrator's password; used only when no users exist. |
| `SECRET_KEY` | Signs sign-in cookies. Generated and stored in the data folder if empty. |
| `COOKIE_SECURE` | Set `true` when served over HTTPS. |
| `DATABASE_URL` | Empty = SQLite file in the data folder. PostgreSQL is supported for multi-plant use. |
| `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` | Enables the AI review. Usage is billed to the key's Claude API account. |
| `PLANT_API_TOKEN` | Enables `POST /api/v1/production-records` for the plant system. |
| `TIMEZONE` | Default `Asia/Kolkata`. |

## Running on a cloud server

Put the app behind a reverse proxy that provides HTTPS (for example Caddy or Nginx with a certificate),
then set `COOKIE_SECURE=true`. Do not expose port 8000 to the internet without HTTPS: passwords would
travel unencrypted.

## Connecting to the plant control system

See [docs/plant-integration.md](docs/plant-integration.md). The connection depends on the data
interface your equipment supplier provides, which is not decided yet. Until then, production data can be
entered in the form or imported from CSV.

## Project layout

```
app/
  main.py          app start-up, error pages, security headers
  config.py        settings from environment variables
  models.py        database tables
  logic.py         QC and production rules (limits, deviation, tolerance)
  services.py      saving tests and production records, lot lookup, dashboard
  security.py      passwords, sessions, CSRF, role permissions
  reports.py       PDF and Excel output
  ai.py            Claude API review
  routes/          pages and the plant API
  templates/       HTML pages
  static/          stylesheet and script
tests/             automated tests (pytest)
scripts/backup.sh  database backup
```
