# Ayussha Plant

Web application for the dry mix concrete plant: inward material QC, the production log with lot
traceability, PDF test reports and batch certificates, Excel exports, user logins with roles, an audit
trail, and an AI review of the records through the Claude API.

It runs the same way on a PC or server at the plant (on the plant LAN) or on a cloud server.

## What it does

| Area | Details |
|---|---|
| Logins and roles | Administrator, Quality team, Plant operators, Management (view only: sees everything, changes nothing). One-time passwords that must be changed at first sign-in. Lockout after 5 failed sign-ins for 15 minutes. |
| Setup | Plant settings (company, plant, batching tolerance, product lines, shifts), materials (with stock unit and reorder level), test parameters with limits and method reference, recipes, customers and sites, vehicles, concrete grades with acceptance values. Nothing is pre-filled: all limits, tolerances and acceptance values come from your specifications. |
| Material QC | Test per lot: each value marked within limits or out of limit. Decision: Accepted, On hold or Rejected. An out-of-limit lot can only be accepted with a written remark. Limits are copied onto the test, so later changes in Setup never rewrite past tests. |
| Production log | Planned against actual weight per material, deviation %, tolerance check, bags and weights. Each material's lot is matched to its QC test; lots on hold, rejected or never tested are flagged. |
| Standard test sets | Setup → Add standard materials creates 20 mm down, 12.5 mm down, M-sand, OPC-43, OPC-53, PPC, PSC, GGBS, fly ash, microsilica, white/black microsilica, Alccofine, micro steel fibres, polypropylene fibres and the in-house products, with the Indian Standard test set where one exists: IS 383:2016 / IS 2386 (aggregates), IS 269:2015, IS 1489 (Part 1):2015, IS 455:2015 (cement), IS 16714:2018 (GGBS), IS 3812 (Part 1):2013 (fly ash), IS 15388:2003 (silica fume), IS 9103:1999 (admixture uniformity, from the manufacturer's stated values), IS 16481:2022 (synthetic micro fibres). Sources and amendments are listed on each page. |
| Plant process | Coating batches (coarse aggregate lots + microsilica/Alccofine lots → coated aggregate lot, dosage %) and grinding batches (one material per batch → ground lot, Blaine and 45 µm residue). Each output lot is on hold until QC decides. Bags are packed per order against the order's mix design: aggregate jumbo bag (coated 20 mm, 12.5 mm, M-sand), cementitious jumbo bag, fibre bag, admixture barrel. Each bag records the lots in it, the deviation from the mix design, and gets a printable label with a QR code. Bags are loaded on a dispatch and the site mixing record lists the bags emptied, admixture dose, water, slump/flow, temperatures, and the water/cementitious ratio from the packed weights. |
| Orders and dispatch | Customer orders per site and grade. Each dispatch loads bags from production records (never more than are in stock), records the truck, mixer on wheels and driver, then delivery, receiver and volume placed. Bags from flagged records need a remark. Delivery note PDF lists the bags and the material lots in them. |
| Strength tests | Specimens cast from a delivery, test ages, results by age. Strength is calculated from failure load and specimen size (cube side² or cylinder π·d²/4) or entered directly. Results are checked against the grade's acceptance age, minimum individual and minimum mean, as entered in Setup. Tests due and overdue are listed. Strength report PDF. |
| Stock | Raw material per lot = received on QC tests − used in production ± adjustments, converted to the material's stock unit (kg/t, L/mL). Usable stock counts accepted lots only; reorder alerts. Filled bags in stock per production record. |
| NCR | Raised from any test, production record, dispatch or strength sample, or on its own. Containment, root cause, corrective action, owner, due date, verification; cannot be closed without root cause, action and verification. Overdue NCRs are flagged. |
| Equipment | Calibration register with history, certificates and next due date (worked out from the interval if not entered). Due within 30 days and overdue items are flagged. |
| Reports | PDFs: material test report, batch traceability certificate, delivery note, strength test report. Excel: QC register, production log, dispatch register, strength register, NCR register, stock by lot, equipment calibration status. |
| Imports and plant API | CSV import of production records, and a token-protected JSON API for the plant control system. |
| AI review | Claude reads the records for a chosen period (QC, production, dispatch, strength, NCRs) and summarises problems, repeated issues, open decisions and data gaps, using only those records. Optional; needs a Claude API key. |
| Audit trail | Every sign-in and every change, with who and when. |

## Install on a Windows PC (without Docker)

1. Install **Python 3.11 or newer** from python.org. In the installer, tick **Add python.exe to PATH**.
2. Download this repository (on GitHub: **Code → Download ZIP**) and unzip it, for example to `C:\PlantQC`.
3. Double-click **`windows\install.bat`**. It sets up the app and opens the settings file `.env` in Notepad.
   Set `INITIAL_ADMIN_PASSWORD` (10+ characters, upper and lower case letters, a digit), save and close Notepad.
4. Double-click **`windows\start.bat`** and open `http://127.0.0.1:8000` in a browser.
   Sign in as `admin` with that password and set your own password when asked.
5. To back up, double-click **`windows\backup.bat`** and copy `data\backups` to another drive regularly.

The app runs while the `start.bat` window is open. To let other computers on the plant network use it,
set `HOST=0.0.0.0` in `.env`, restart, and allow Python through Windows Firewall when Windows asks.
Others then open `http://<this PC's IP address>:8000`.

## Install with Docker (server or cloud)

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
2. **Setup → Materials**: each material you receive, with its stock unit and reorder level.
3. **Setup → Test parameters**: each test per material with limits from your specification.
4. **Setup → Customers, vehicles and grades**: customers and sites, trucks and mixer-on-wheels units, concrete grades with acceptance values from your specification.
5. **Equipment**: each item that needs calibration, with its interval.
6. **Users**: an account for each person. The one-time password is shown once.

Data is kept in the Docker volume `plantqc-data`, so it survives restarts and updates.

### Update to a new version

```sh
git pull
docker compose up -d --build
```

### Back up

```sh
docker compose exec plantqc python scripts/backup.py
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
| `PUBLIC_URL` | Address printed in the bag label QR code, e.g. `http://192.168.1.20:8000`, so a phone on the plant network can open the bag. Empty = the address used to open the app. |

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
  operations.py    orders, dispatch, strength tests, stock, NCRs, equipment
  security.py      passwords, sessions, CSRF, role permissions
  reports.py       PDF and Excel output
  ai.py            Claude API review
  routes/          pages and the plant API
  templates/       HTML pages
  static/          stylesheet and script
tests/             automated tests (pytest)
scripts/backup.py  database backup (scripts/backup.sh for Docker)
windows/           install, start and backup for Windows
```
