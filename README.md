# NavAIReceptionist

**A multi-tenant Django app where a business with multiple locations gives each location its own Twilio
number and AI voice agent.**

The agent answers inbound calls, books appointments into the location's calendar, transfers to a human
when the caller asks, and logs the call in detail. Seven capabilities, nothing more: login, change
password or email, calendar, bookings, agent setup + Twilio, call transfer, user profile.

**Multi-tenant means multi-location.** A business (tenant) adds locations, and Twilio numbers, agent
setup, calendar and staff are configured **per location**.

> **Build state — read this before trusting any path below.**
>
> **20 of the 26 sub-modules are built.** The remaining 6 render as greyed-out roadmap rows in the
> sidebar, which reflects the truth honestly. `LIVE_LINKS` in `apps/accounts/navigation.py` is the
> build-state ledger — a sub-module is built if and only if it has an entry there.
>
> | Module | Built | Not built |
> |---|---|---|
> | **0 · Accounts & Access** (`apps/accounts`) | 0.1 auth & session · 0.2 change password/email · 0.3 user directory & profile · 0.4 location switcher | — |
> | **1 · Business & Locations** (`apps/tenants`) | 1.1 business settings · 1.2 location directory · 1.3 staff assignment · 1.4 provider working hours | — |
> | **2 · Agent Setup & Telephony** (`apps/agents`) | 2.1 agent setup · 2.2 Twilio connection · 2.3 transfer settings · 2.4 test call | — |
> | **3 · Call Runtime** (`apps/runtime`) | — | **the whole module.** The app does not exist. `config/asgi.py`'s `websocket_urlpatterns` is still `[]`, waiting on `apps/runtime/routing.py` |
> | **4 · Calendar & Bookings** (`apps/scheduling`) | **4.1 contact directory · 4.2 services & resources · 4.3 availability & booking · 4.4 calendar views · 4.5 bookings & callbacks** — the whole module | — |
> | **5 · Call Logs** (`apps/calls`) | **5.1 call log list · 5.2 call detail & transcript · 5.3 event log & cost** — `CallSession` plus the transcript, analysis, cost breakdown and tool-call trace surfaces over its JSON columns | 5.4 recording & transfer outcome — a **view** sub-module over 5.1's JSON columns, adding no models |
>
> Also built: `config/` (settings, ASGI + Channels, urls), the design system
> (`static/css/theme.css`, `static/js/layout.js`, `templates/base.html` + partials), and the test suite
> (`conftest.py` + `apps/scheduling/tests/` + `apps/calls/tests/`, **679 passing**).
>
> **Build order note.** Module 3 is numbered before 4 and 5 but depends on both — it writes
> `calls.CallSession` and `scheduling.Appointment`/`CallbackRequest`/`Contact`, and reads `Service` and
> `Resource`. So Modules 4 and 5 are being built first, then 3. `calls.CallSession.contact` FKs
> `scheduling.Contact`, which is why 4 precedes 5 — and 5.1 is what finally made
> `scheduling.Appointment.booked_by_session` migratable, since Django refuses a relation to an
> uninstalled app. That FK had been deliberately absent since 4.3 and landed as an additive
> migration the moment `apps.calls` entered `INSTALLED_APPS`.
>
> A path in the "Project layout" section at the end of this file is a **plan**, not a claim that the
> code exists. Grep before you rely on one.

---

## Architecture — all-Django

One codebase, one deployment. There is **no separate microservice**.

| Layer | Choice |
|---|---|
| Framework | Django 4.2 LTS |
| Realtime | Django Channels / ASGI (Twilio media-stream websocket) |
| UI | Tailwind CSS + HTMX + Lucide icons |
| Database | MySQL (`navai_receptionist`; test database `test_navai_receptionist`) |
| Server | ASGI via Daphne — `config.asgi:application` |
| Telephony | Twilio (Programmable Voice + Media Streams), behind a provider adapter |
| Tenancy | `tenant` FK on every model; location-scoped models also carry a `location` FK |
| User model | `AUTH_USER_MODEL = 'accounts.User'` |

### Why Channels/ASGI is required, not optional

The carrier does not hand us an audio file after the call. It opens a **bidirectional websocket** and
streams μ-law frames while the caller is still talking, and expects agent audio streamed back on the
same socket in real time. That media session is where the product lives: voice activity detection,
barge-in, the turn loop, tool calls, and deferred transfer and hangup signals all happen inside a
long-lived consumer holding per-call state.

WSGI has no way to hold that socket. So the realtime path is a Channels consumer, the app is served
over ASGI, and two rules follow from it:

- **`manage.py runserver` cannot serve the websocket routes at all.** Use Daphne for anything that
  touches a call.
- **No blocking work on the event loop.** A synchronous ORM query or a blocking SDK call inside an
  `async def` consumer freezes audio for *every* concurrent call on that worker. Use
  `database_sync_to_async` / `sync_to_async(thread_sensitive=False)`.

---

## Module catalog

Six modules, `0`–`5`. Modules 0 and 1 are the foundation and are built first; the rest are ordered so
each depends only on what precedes it.

| # | Module | Planned app slug | Owns |
|---|---|---|---|
| 0 | Accounts & Access | `accounts` | login, logout, password change, email change, user profile, roles, the active-location switcher |
| 1 | Business & Locations | `tenants` | the business record, locations, location settings, staff↔location assignment, provider working hours |
| 2 | Agent Setup & Telephony | `agents` | per-location agent config, Twilio credentials + inbound number, transfer settings, test call |
| 3 | Call Runtime | `runtime` | Twilio webhooks + signature verification, the media-stream consumer, turn loop, LLM tools, transfer execution, recording |
| 4 | Calendar & Bookings | `scheduling` | contacts, services, resources, availability, appointments, calendar views, callback requests |
| 5 | Call Logs | `calls` | session list + detail, transcript, event log, cost breakdown, recording playback, transfer outcome |

Module 3 is a **service module** — consumers, webhooks, provider adapters and a diagnostics page. It
ships no CRUD.

---

## The data model

Eleven models. `tenants.Tenant` and `tenants.Location`; `accounts.User` and `accounts.UserLocation`;
`agents.AgentSetting` (one row per location, carrying agent config, Twilio credentials and transfer
settings together); `scheduling.Contact`, `Service`, `Resource`, `Appointment` and `CallbackRequest`;
and `calls.CallSession`.

Three invariants govern it — **summarized here; the binding wording is
[`NavAIReceptionist-ERD.md`](NavAIReceptionist-ERD.md) §2**, which is what the review agents quote by number:

1. **One contact identity table.** Callers, bookers and attendees are `scheduling.Contact` rows.
2. **One call log.** A call is exactly one `calls.CallSession`; its transcript, event log, per-turn
   usage, analysis and transfer outcome are JSON columns on that row.
3. **Server owns identity; the model owns wording.** `tenant_id`, `location_id`, `contact_id` and
   `session_id` come from server-side session state and are never LLM tool parameters.

The full field lists are in **[`NavAIReceptionist-ERD.md`](NavAIReceptionist-ERD.md)**. That document
is **intent — the code is truth; grep before you FK.**

---

## Quickstart

Windows PowerShell. Note the `;` separator — `&&` is not valid PowerShell and will raise a
`ParserError`.

> **Run step 1 before your first Claude Code session in this repo.** `.claude/settings.json` wires its
> hooks to `venv\Scripts\python.exe`, which does not exist in a fresh checkout — until the virtual
> environment is created and the requirements installed, every hook fails to launch.

```powershell
# 1. Virtual environment — do this FIRST (the .claude hooks invoke venv\Scripts\python.exe)
python -m venv venv
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Environment file
Copy-Item .env.example .env
# then edit .env — at minimum SECRET_KEY, DB_*, and leave PROVIDER_MODE=fake

# 3. Database (MySQL/MariaDB, e.g. XAMPP — start it from the XAMPP control panel first)
C:\xampp\mysql\bin\mysql.exe -u root -e "CREATE DATABASE IF NOT EXISTS navai_receptionist CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 4. Migrate
venv\Scripts\python.exe manage.py check; venv\Scripts\python.exe manage.py migrate

# 5. Seed demo data — seed_accounts calls seed_tenants automatically if no business exists
venv\Scripts\python.exe manage.py seed_accounts
venv\Scripts\python.exe manage.py seed_agents
venv\Scripts\python.exe manage.py seed_scheduling
venv\Scripts\python.exe manage.py seed_calls

# 6. Run it (Daphne, never runserver)
venv\Scripts\python.exe -m daphne -b 127.0.0.1 -p 8000 config.asgi:application
```

Then open **http://127.0.0.1:8000/login/** and sign in with one of the demo accounts below.

Every seeder is **idempotent** — running one again prints `Data already exists. Use --flush to
re-seed.` and changes nothing. `--flush` on any of them rebuilds that seeder's demo rows from scratch.

> **Pipe a seeder to `tail`, never `head`.** `head` closes the pipe, the command dies on
> `BrokenPipeError`, and the `@transaction.atomic` seeder rolls back — which looks exactly like a real
> idempotency failure and is not one.

`seed_scheduling` creates 8 demo contacts, 9 services and 10 resources across the two businesses, shaped
to exercise the real edge cases: an anonymous caller with a number and no name, two people sharing one
household line, an email-only web enquiry, a deliberately unnormalised number that proves phone
normalisation runs on the seeder's writes too, a catalogue mixing all-location and site-pinned services,
the same room name at two different sites, and 14 appointments spanning every status across all four
locations. `seed_accounts` stamps working hours on every provider — without them the availability
engine correctly finds nothing, because unconfigured hours mean unavailable, not available-all-day.

`seed_calls` adds 11 synthetic call sessions across all four locations, covering all five statuses,
identified and unidentified callers, and every transfer outcome — with hand-authored transcript, event
log, cost and analysis JSON so the detail surfaces have something real to render. One Downtown call is
credited with creating an actual booking, so the call → contact → appointment trail is followable end to
end. **It contacts no provider under any `PROVIDER_MODE`; `apps/calls` has no adapter at all.**

> **Seeder order matters, and reversing it fails silently.** Run them in the order above —
> `seed_scheduling` before `seed_calls`. `seed_scheduling --flush` deletes and recreates the `Contact`
> rows, and `CallSession.contact` is `SET_NULL`, so flushing scheduling *after* calls nulls the contact on
> every session. Nothing errors and the pages still render; the demo just shows every caller as
> unidentified, which reads as a scoping bug rather than a stale seed. If you flush scheduling, re-run
> `seed_calls --flush` afterwards.

> **Database version.** This project is pinned to **Django 4.2 LTS** because Django 5.1+ requires
> MariaDB 10.5 or later, and XAMPP currently ships 10.4. If you see
> `NotSupportedError: MariaDB 10.5 or later is required`, your Django is too new for your database —
> either reinstall from `requirements.txt` or upgrade MariaDB. Note that 4.2 LTS support ends in
> **April 2026**, so the database upgrade belongs on the roadmap rather than deferred indefinitely.

> ⚠️ **`AUTH_USER_MODEL = 'accounts.User'` must be set in `config/settings.py` before the very first
> `makemigrations`.** The `accounts` app ships the custom user model (it carries a `tenant` FK), and other
> apps FK it back — `scheduling.Appointment.provider` — always via `settings.AUTH_USER_MODEL`, never a direct
> `from apps.accounts.models import User` (that is an import cycle, since `accounts.User` FKs `tenants.Tenant`).
> Django bakes the user model into every migration referencing it, so changing `AUTH_USER_MODEL` after the initial
> migrations exist requires a **destructive reset** — drop the database and regenerate every migration. Get it
> right on day one.

---

## Signing in for the first time

`seed_accounts` creates two demo businesses with two locations each, and four users. The login form at
**http://127.0.0.1:8000/login/** takes **three** fields — the Customer ID resolves the business
*before* any credential is checked, which is what lets the same email address exist in more than one
business.

**Password for every demo account: `navai-demo-2026`**

| Business | Customer ID | Email | Username | Role | Can switch into |
|---|---|---|---|---|---|
| Acme Dental Group | `ACME-1001` | `admin@acme.test` | `admin_acme` | Owner | Downtown + Uptown |
| Acme Dental Group | `ACME-1001` | `downtown.manager@acme.test` | `acme_downtown` | Manager | Downtown only |
| Globex Health | `GLBX-2002` | `admin@globex.test` | `admin_globex` | Owner | Lakeside + Riverside |
| Globex Health | `GLBX-2002` | `riverside.staff@globex.test` | `globex_riverside` | Staff | Riverside only |

**Start with `ACME-1001` / `admin@acme.test`.** The middle field accepts the email *or* the username
interchangeably, and both are case-insensitive, as is the Customer ID.

The seeder prints all of this at the end of its run, so `manage.py seed_accounts` is always the
authoritative source — read its output rather than trusting this table if the two ever disagree.

### Three things that look like bugs but are not

- **"Active location: Not selected"** on either Owner account. Both are assigned to two locations, and
  the switcher that lets a user choose between them is sub-module **0.4**, not built yet. A user with
  exactly one assignment auto-activates it — sign in as `downtown.manager@acme.test` to see an active
  location resolved.
- **Almost the entire sidebar is greyed out.** Only sub-module 0.1's Dashboard link is live; the other
  25 rows are roadmap placeholders. The sidebar is driven by the `LIVE_LINKS` ledger in
  `apps/accounts/navigation.py`, so it can only ever show what genuinely exists.
- **The superuser sees no data at all.** `admin@navai.local` (same password) signs in at **/admin/**
  with no Customer ID, because it deliberately has `tenant=None`. Every tenant-scoped view filters by
  `tenant=request.tenant`, so an empty result is correct behaviour, not a broken page. Use a tenant
  admin to see seeded data.

### Why login may fail

Every failure — wrong Customer ID, unknown user, wrong password, deactivated business, suspended
account — returns the **same** message on purpose, so the form cannot be used to discover which
accounts exist. If you are locked out, check the Customer ID first; it is the field people miss.

After 5 failed attempts within 15 minutes the account **and** your IP are throttled, and a *correct*
password will still be refused until the window expires. That is the throttle working. To clear it
during development, restart the server — the counters live in the local-memory cache.

---

## Running the server

```powershell
venv\Scripts\python.exe -m daphne -b 127.0.0.1 -p 8000 config.asgi:application
```

⚠️ **Two hazards, both of which cost hours if you hit them cold:**

1. **`manage.py runserver` cannot serve the websocket routes.** Under the WSGI path the media-stream
   endpoint does not exist, so calls connect and immediately die with no useful error. Use Daphne.
2. **Daphne has no autoreload.** Your edits are simply not picked up until you stop and restart it. If
   a change "has no effect", restart Daphne before you debug anything else.

---

## Local webhook testing

Twilio must reach your machine, so provider webhooks in development need a tunnel (ngrok or
equivalent) pointing at port 8000.

```powershell
ngrok http 8000
```

Then set the tunnel's public HTTPS URL as `TWILIO_WEBHOOK_BASE_URL` in `.env`, and configure the same
URL on the Twilio number.

⚠️ **The public URL must match `TWILIO_WEBHOOK_BASE_URL` exactly.** Twilio signs the request over the
full callback URL, and the app verifies `X-Twilio-Signature` against the URL it derives from that
setting. A trailing slash, `http` where Twilio sent `https`, a stale tunnel subdomain from the last
session, or a proxy that rewrites the host will all make signature verification fail and every webhook
return 403 — with nothing obviously wrong in the payload. When webhooks 403, check this first.

The signature is verified using the **per-location** credentials on the `agents.AgentSetting` row
resolved from the dialed number, not a platform-wide token.

---

## Provider modes

`PROVIDER_MODE` selects which implementation the telephony / STT / TTS / LLM adapters resolve to.

| Mode | Behaviour |
|---|---|
| `fake` | **The development default.** In-process fakes. No network, no cost, no real calls. Tests and seeders run against these so the adapter contract itself is exercised. |
| `sandbox` | Provider test credentials and test numbers. Real network, no billable production traffic. |
| `live` | Real carrier, real LLM/STT/TTS spend, real phone calls to real people. |

⚠️ **Never leave `PROVIDER_MODE=live` set in a development environment.** A seeder, a test, a stray
management command or a looping agent can then place real calls to real numbers — that is an unbounded
bill, not a bug. Keep `fake` in `.env`, and treat `live` as something you set deliberately, on a
deployed environment, and unset again.

---

## Testing

```powershell
venv\Scripts\python.exe -m pytest -q
venv\Scripts\python.exe -m pytest -q apps/calls
```

The suite runs against `config.settings_test` (SQLite in-memory, fast password hasher, locmem email,
`InMemoryChannelLayer`, and `PROVIDER_MODE = "fake"`). Async consumer tests use
`channels.testing.WebsocketCommunicator` against `config.asgi.application`. A test that can reach a
real provider is a failed test.

If the suite fails with a stale-schema error, drop the test database and re-run:

```powershell
mysql -u root -e "DROP DATABASE IF EXISTS test_navai_receptionist;"
```

---

## Project layout (planned)

```
config/                 settings, settings_test, urls, asgi (ProtocolTypeRouter), wsgi
apps/
  accounts/             users, roles, login, profile, the location switcher
  tenants/              the business record, locations, staff assignment, working hours
  agents/               per-location AgentSetting: agent config, Twilio creds, transfer settings
  runtime/              media-stream consumer, Twilio webhooks, tool dispatcher, provider adapters
  scheduling/           contacts, services, resources, appointments, callback requests
  calls/                CallSession list + detail, transcript, recording playback
templates/              base.html, partials/, then <app>/<submodule>/<entity>/<page>.html
static/css/theme.css    the Tailwick-derived blue/white design system class contract
NavAIReceptionist.md    module catalog — the scope authority
NavAIReceptionist-ERD.md  the eleven models, written out as intent
.env.example            every environment key with dummy values
```

Within each app, `models`, `forms`, `views`, `urls` and `consumers` are **Python packages** organized
one folder per sub-module then one file per entity — never flat monoliths. `routing.py`, `webhooks.py`,
`tasks.py`, `providers.py`, `admin.py` and `apps.py` stay flat at the app root. Templates mirror the
same shape. Both conventions, and the rules that keep them working, are specified in
`.claude/CLAUDE.md`.
