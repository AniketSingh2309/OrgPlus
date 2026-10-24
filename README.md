# Org+

A Google Workspace activity dashboard for the head of an organisation. For every user it shows the last sign-in, what they did, the apps they use, their devices, their security status, and a GitHub-style 6-month activity grid.

It uses only free Google APIs (Admin SDK Directory + Reports, and optionally Classroom). Paid Workspace features are detected per domain and unlock automatically. Org+ is **read-only**: it never makes write calls to Google, and it never reads email bodies or file contents.

## What's in the box

| Area | Pages |
|---|---|
| Core | Overview (KPIs, org grid, editable score weights, Needs attention, top people, app adoption, departments, admin actions) · People · Person profile (Overview with grid + day drill-down + timeline, Drive activity, Meetings, Sign-ins, Apps & devices) · Apps · Security · Devices |
| Free extras | Licence utilisation & waste (₹) · Joiners & leavers · Storage · Meeting load · After-hours by team · External sharing + shared drives · Groups hygiene · Admin role audit · Sign-in map · Team comparison · Weekly digest · CSV for every table + PDF of any page · Manager view |
| Paid (auto-detected) | Unlimited history (BigQuery) · Email flow (Gmail logs) · Legal hold (Vault) · Google security alerts (Alert Center) · DLP · Access policy blocks · AI adoption (Gemini) · Chrome insights · Classroom (free, behind `ENABLE_CLASSROOM`) |
| Admin | Connect (upload key, scope checklist, plan detection, backfill progress) · Plan & features · Settings |

Light and dark mode, mobile layouts, loading skeletons and empty states throughout.

## Architecture

```
web (Next.js 14) ──/api/* proxy──▶ api (FastAPI) ──▶ PostgreSQL ◀── worker (APScheduler)
  NextAuth (Google, your domain)    verifies a 5-min JWT                 │
  signs a short-lived JWT           per-viewer scope + audit log          └──▶ Google APIs (read-only)
```

PostgreSQL holds one control database (`orgplus_control`, the list of organisations) and
**one database per organisation** (`orgplus_org_<id>`). Each request is routed by the
signed-in user's email domain to that organisation's database only. See
[Database security](#database-security).

```
backend/orgpulse/
  google_client.py   delegated credentials (.with_subject), cached services, backoff, pagination, read-only guard
  db.py, orgs.py     per-organisation routing (use_org), control DB, provisioning CLI
  sync/              mappers (pure), directory, usage, events (cursor per app), extras, runner, upserts
  plan/              skus (edition/tier), probes (capabilities), detect, connection (scope checklist)
  features/          registry of feature modules + require_feature() (402 when locked)
  modules/           paid modules: each registers capability, routes, sync job and UI cards
  api/               routers: overview, people, org, insights, admin, exports; deps (auth, roles)
  scoring.py         daily score, quartile levels, Monday-first grid, streaks
  alerts.py          "Needs attention" rules
web/                 Next.js app router; components/activity-grid.tsx is our own grid
```

## Setup

### 1. Google Cloud

1. Create a project and a **service account**. Create a JSON key for it.
2. Enable these APIs: **Admin SDK API**, plus as needed **Enterprise License Manager API** (plan detection), **Google Drive API** (shared drives), **Google Vault API**, **Google Workspace Alert Center API**, **Chrome Management API**, **Google Classroom API**, **BigQuery API**.

### 2. Workspace Admin console

Go to **Security → API controls → Domain-wide delegation → Add new**, enter the service account's **client ID**, and add these scopes:

```
https://www.googleapis.com/auth/admin.directory.user.readonly,https://www.googleapis.com/auth/admin.directory.group.readonly,https://www.googleapis.com/auth/admin.directory.orgunit.readonly,https://www.googleapis.com/auth/admin.directory.rolemanagement.readonly,https://www.googleapis.com/auth/admin.directory.device.mobile.readonly,https://www.googleapis.com/auth/admin.directory.device.chromeos.readonly,https://www.googleapis.com/auth/admin.directory.user.security,https://www.googleapis.com/auth/admin.reports.audit.readonly,https://www.googleapis.com/auth/admin.reports.usage.readonly
```

Optional scopes, each unlocking one feature: `apps.licensing` (plan detection), `drive.readonly` (shared drives, metadata only), `ediscovery.readonly` (Vault), `apps.alerts` (Alert Center), `chrome.management.reports.readonly`, and the three `classroom.*.readonly` scopes. The `/connect` screen lists exactly which scopes are missing, ready to paste.

`admin.directory.user.security` has no read-only variant. Org+ only uses it for `tokens.list`.

The impersonated account must be a **super admin**, or hold a custom role with read privileges for Users, Groups, Org units, Devices and Reports.

### 3. Postgres (installed on this machine, no passwords)

Install PostgreSQL 16+ on the server, then lock it down once:

1. In `postgresql.conf` set `listen_addresses = 'localhost'`.
2. Replace the server's `pg_hba.conf` with [deploy/postgres/pg_hba.conf](deploy/postgres/pg_hba.conf).
   On Windows, also copy [pg_ident.conf](deploy/postgres/pg_ident.conf) and put your Windows
   account name in it. On Linux/macOS, follow the comments in `pg_hba.conf` instead.
   (`SHOW hba_file;` in psql shows where both files live.) Restart Postgres.
3. `psql -U postgres -f deploy/postgres/init.sql`

### 4. Configure and run

```bash
cp .env.example .env            # fill in APP_URL, NEXTAUTH_SECRET, CREDENTIAL_ENC_KEY, SMTP_*
cd backend && python -m venv .venv && .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
python -m orgpulse.crypto --new-key   # paste into CREDENTIAL_ENC_KEY
openssl rand -base64 48               # paste into NEXTAUTH_SECRET
```

Start the three processes (each in its own terminal, or as services). Only the **worker**
gets the provisioning role:

```bash
uvicorn orgpulse.api.main:app --port 8000      # API (backend/)
ADMIN_DATABASE_URL=postgresql://orgplus_admin@localhost:5432/postgres python -m orgpulse.worker
                                               # PowerShell: $env:ADMIN_DATABASE_URL="..."; python -m orgpulse.worker
cd ../web && npm install && npm run dev        # web on :3000 (npm run build && npm start in production)
```

**Postgres sets itself up.** Each time the worker starts it creates the control database
if it's missing, creates any organisation in `ALLOWED_DOMAINS`, and migrates every
organisation's database to the current schema. After a deploy, restart the worker and
the databases are up to date; there's no separate migration step.

### 5. Sign up and connect

1. Open http://localhost:3000/signup: name, **Google Workspace** email (personal Gmail/Outlook
   addresses are refused) and a password (10+ characters). No email is sent.
2. Scan the QR code with an authenticator app (Google Authenticator, Microsoft Authenticator,
   Authy, 1Password…) and enter its 6-digit code. Every sign-in needs password **and** code.
3. Sign in. The **first account of a new organisation** creates its private database (a few
   seconds) and is its admin until the directory syncs. After that, Workspace super admins,
   `ORG_ADMINS` and managers can sign in; anyone else gets "Org+ is only for admins and managers".
4. Go to **Connect**, upload the service-account key and enter the admin email, then follow
   the four steps. The first sync is the **180-day backfill**. Run it on day one, because
   Google deletes older logs.

Lost phone? An admin clicks **Reset authenticator** in Settings → Accounts and sends the person
the one-time link it shows (or: `python -m orgpulse.accounts reset-mfa them@yourdomain.com`).
Forgot password emails a reset link (needs SMTP); the authenticator code is still required.

To check credentials from the command line instead: `python -m orgpulse.check --skip-db`.

Organisation commands (with `ADMIN_DATABASE_URL` set): `python -m orgpulse.orgs list`,
`add newdomain.com`, `migrate`, and `adopt yourdomain.com --from-db orgpulse` to move an
existing single-organisation database in (needs a superuser URL; the source is copied, not changed).

For quick development without per-organisation databases, leave `CONTROL_DATABASE_URL` unset,
set `DATABASE_URL`, run `alembic upgrade head`, and use `DEV_AUTH_BYPASS` (accounts need the control database).

### Deploy on a server (e.g. AWS EC2)

One Ubuntu 24.04 machine runs everything natively: Postgres 16, the API, the worker,
the web app, and Caddy for automatic HTTPS. Copy the project to the server, then:

```bash
sudo bash deploy/linux/setup.sh orgplus.yourdomain.com head@yourdomain.com
```

It installs the packages, locks Postgres to localhost ([pg_hba.linux.conf](deploy/postgres/pg_hba.linux.conf)),
generates the secrets in `/opt/orgplus/.env`, builds everything and starts three systemd
services (`orgplus-api`, `orgplus-worker`, `orgplus-web`). Only ports 80/443 are public.
To update, copy the new code and run the same command again.

### Real-time updates

Every page updates by itself the moment data changes; nobody needs to reload.
Any process that changes data (worker syncs, API settings changes) sends a Postgres
`NOTIFY`; the API relays it to the browsers of that organisation over **Socket.IO**
(`/socket.io` on the API), and each open page refetches what it shows. Notices carry
no personal data, only what changed. The socket checks the same signed session as the
API, your domain, and the browser's origin (`WEB_ORIGINS`). Browsers connect to
`API_PUBLIC_URL`. If the socket drops, the header shows "Reconnecting…" and pages fall
back to refreshing every 30 seconds.

### Sign-in map (city locations)

The map uses the free **DB-IP "IP to City Lite"** database (CC BY 4.0, no account; credited on the map). The worker downloads it into `data/` on first start and refreshes it monthly. To fetch it manually:

```bash
cd backend && python -m orgpulse.geoip_update      # writes GEOIP_DB (default data/dbip-city-lite.mmdb)
python -m orgpulse.worker --once geo               # locate sign-ins that were synced before
```

A MaxMind GeoLite2 City `.mmdb` also works: point `GEOIP_DB` at it.

### Try it with demo data

```bash
cd backend && python -m orgpulse.demo          # 42 fictional people, ~180 days of activity
python -m orgpulse.demo --clear                # remove it before connecting a real domain
```

With `DEV_AUTH_BYPASS=true` and `DEV_USER_EMAIL` set (local only), the web app skips sign-in.

## Sync schedule (worker, UTC)

| Job | When | Source |
|---|---|---|
| `events_fast` | hourly | Reports `login`, `token` |
| `events_slow` | every 6 h | `drive, meet, calendar, chat, groups, admin, saml` (+ `classroom`) |
| `directory` | daily 01:00 | users (full), OUs, groups + members, admin roles, mobile + ChromeOS devices, OAuth tokens |
| `licences` | daily 01:40 | License Manager (`Google-Apps`, `101031`) |
| `usage` | daily 03:00 | `userUsageReport(all, date)` from the last complete day, re-pulling the last 3 days |
| `plan` | daily 04:00 | edition + capability probes; flips are logged and shown as a banner |
| modules | per module | only for capabilities that are **on** |
| digest | Monday 02:30 (08:00 IST) | email to the recipients set in Settings |

Every job is idempotent: upserts use unique keys `(tenant, user, date, metric)` and `(tenant, app, time, uniqueQualifier, event_seq)`. Jobs hold a Postgres advisory lock, back off exponentially on 429, 5xx and rate-limit 403s, and record their cursor, progress and errors in `sync_state`. For production you can replace APScheduler with cron, for example `python -m orgpulse.worker --once events_fast`.

## Activity score

`daily score = Σ count × weight`. The default weights are dc 3, de 1, dv 0, es 0.5, er 0, mt 1, **mh 2**, ch 0.1, cal 1; admins can edit them on the Overview page. `mh` is **meeting hours**, derived as `meet:total_call_minutes / 60`.

Grid levels 1–4 are the quartiles of that user's non-zero days. The last 3 days show as outlined "not reported yet" cells, because usage reports lag by 2–3 days. Weeks start on Monday. Streaks skip weekends.

## Things to verify against your live domain

- **Usage parameter names.** The mapping in `sync/mappers.py` (`USAGE_PARAMS`) uses the documented names, with fallbacks for Chat and Calendar. Any metric that never appears is logged with the similar parameter names Google actually returned. It also shows on the Connect page and in `GET /api/sync/status`. Adjust the candidates if needed.
- **Third-party app "unverified".** `tokens.list` has no verification flag, so Org+ treats `anonymous: true` (an app not registered with Google) as unverified.
- **Licences bought.** The Licensing API reports assignments only, so enter the number of licences you pay for in Settings to see unassigned seats.
- **Reports application names** used by the probes: `rules` (DLP), `context_aware_access`, `gemini_in_workspace_apps`, `gmail`. If Google renames one, the probe reports `locked` or `error` rather than crashing.
- **Gmail log field shapes** (email flow) and **BigQuery export columns** (`BQ_COLUMNS`) are parsed best-effort. Check them on a domain that has those features.

## Security model

- **Accounts**: work email + password + authenticator app. Passwords are hashed with
  **Argon2id**. Two-step sign-in (TOTP, RFC 6238) is mandatory: an account can't sign in until
  its authenticator is confirmed, and every sign-in needs the current 6-digit code. Each code
  works once. TOTP secrets are encrypted with the master key, and the QR code is drawn by
  Org+ itself, never by an outside service.
- **No email check at sign-up**: nothing proves an address belongs to the person typing it,
  so whoever signs up first for an address owns that Org+ account. Admins can see and remove
  accounts in Settings → Accounts.
- **Links** (password reset, authenticator re-setup) are single-use, expire (1 h / 24 h), and
  only their SHA-256 is stored.
- **Brute force**: 5 failed sign-ins (wrong password or code) lock the account for 15 minutes; sign-in, sign-up and
  link requests are rate-limited per IP and per email. Unknown emails get the same answer,
  in the same time, as wrong passwords, so accounts can't be discovered.
- **Sessions**: an HttpOnly, SameSite cookie lasting 8 hours. Every API call re-checks the
  account; a new password or a reset authenticator signs out every other session at once.
- **Who gets in**: the email's domain picks the organisation. Once its directory has synced,
  only Workspace super admins, `ORG_ADMINS` and managers can sign in; suspended Workspace
  users can't.
- `ORG_ADMINS` and Workspace super admins see everything. Managers see only their OU and their reporting chain, and individuals without reports are refused. Every profile view is written to `audit_views`.
- The uploaded service-account key and admin email are encrypted with the organisation's own key and never returned to the browser.
- `google_client.execute()` refuses every non-GET request except BigQuery queries and, when explicitly enabled, the digest send.
- After-hours data is shown per team, and teams under 3 people are hidden.

## Database security

Postgres runs **without passwords**; it's protected by isolation instead:

| Layer | What it does |
|---|---|
| Localhost only | Postgres listens on `localhost` only, and `pg_hba.conf` rejects every connection from the network. |
| pg_hba.conf | [deploy/postgres/pg_hba.conf](deploy/postgres/pg_hba.conf) decides who may log in as what. The superuser is checked by the operating system (SSPI on Windows, peer on Linux), never trusted. `orgplus_admin` may only open the `postgres` database, and its URL is given only to the worker and the `orgs` commands, never to the API. Each org role may open only the database with its own name (`sameuser`). Everything else is rejected. |
| One database per organisation | Every organisation has its own database, owned by its own role (`NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT`). `CONNECT`/`TEMPORARY` are revoked from `PUBLIC`, so a role can't even connect to another organisation's database, or to `postgres`/`template1`. |
| Least privilege | The API (internet-facing) can't create databases: only the worker holds `ADMIN_DATABASE_URL`, and the API warns if it can see it. Sign-ups are queued in the control DB and the worker creates their database. |
| Routing | The API resolves the organisation from the signed-in email's domain and opens *only* that database (`use_org`). Unknown domains get 403, and code running without an organisation can't open any database. |
| Per-organisation keys | Each organisation has its own Fernet data key, stored in the control DB encrypted with `CREDENTIAL_ENC_KEY`. The service-account JSON and admin email are sealed with it, so one org's key can't open another's secrets. |
| Minimisation | No email bodies or file contents are ever fetched. Raw directory and device records drop personal extras (phones, addresses, recovery email, IDs, serials) before storage. |
| Live updates | Notices go through the control DB (NOTIFY doesn't cross databases) and reach only that organisation's sockets. |

Without passwords, the boundary is the machine itself: any program running on the server
can connect as these roles. Run Org+ on a server dedicated to it, with only administrators
able to log in.

Analytics tables (activity, usage) stay readable inside each organisation's isolated database,
because dashboards query them. For encryption at rest, keep the Postgres data directory on an
encrypted disk (BitLocker, LUKS, or your cloud provider's encrypted volumes). Back up `CREDENTIAL_ENC_KEY`:
without it the stored Google credentials can't be decrypted and must be re-uploaded.

## Tests

```bash
cd backend && pytest                       # mappers, scoring, SKUs, probes, require_feature, read-only guard
TEST_DATABASE_URL=postgresql://... pytest  # + API tests against a migrated, disposable database
MULTI_ORG_ADMIN_URL=postgresql://postgres@localhost/postgres pytest tests/test_multi_org.py
                                           # isolation: provisioning, cross-org access denied, routing, keys
cd web && npm test                         # locked cards / <Feature> gating
```

Every table also keeps a `tenant_id`, a second safety net inside each organisation's database.
