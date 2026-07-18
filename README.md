# NavAIReceptionist

**A multi-tenant Django app where a business with multiple locations gives each location its own Twilio
number and AI voice agent.**

The agent answers inbound calls, books appointments into the location's calendar, transfers to a human
when the caller asks, and logs the call in detail. Seven capabilities, nothing more: login, change
password or email, calendar, bookings, agent setup + Twilio, call transfer, user profile.

**Multi-tenant means multi-location.** A business (tenant) adds locations, and Twilio numbers, agent
setup, calendar and staff are configured **per location**.

> **This repository is greenfield.** Nothing is built yet — there is no `apps/` directory. The module
> catalog and the project layout below describe the **planned** structure that the build sequence will
> produce, one sub-module at a time. Do not read any path in this file as a claim that the code exists.

---

## Architecture — all-Django

One codebase, one deployment. There is **no separate microservice**.

| Layer | Choice |
|---|---|
| Framework | Django 5.1 |
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

# 3. Database (MySQL/MariaDB, e.g. XAMPP)
mysql -u root -e "CREATE DATABASE navai_receptionist CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# Steps 4-6 apply once the Module 0/1 foundation exists (see the greenfield note above) —
# there is no manage.py and no apps/ in a fresh checkout, so they cannot run yet.

# 4. Migrate
venv\Scripts\python.exe manage.py check; venv\Scripts\python.exe manage.py migrate

# 5. Seed demo data (foundation first, then any built module's seed_<slug>)
venv\Scripts\python.exe manage.py seed_tenants; venv\Scripts\python.exe manage.py seed_accounts

# 6. Platform superuser
venv\Scripts\python.exe manage.py createsuperuser
```

> ⚠️ **`AUTH_USER_MODEL = 'accounts.User'` must be set in `config/settings.py` before the very first
> `makemigrations`.** The `accounts` app ships the custom user model (it carries a `tenant` FK), and other
> apps FK it back — `scheduling.Appointment.provider` — always via `settings.AUTH_USER_MODEL`, never a direct
> `from apps.accounts.models import User` (that is an import cycle, since `accounts.User` FKs `tenants.Tenant`).
> Django bakes the user model into every migration referencing it, so changing `AUTH_USER_MODEL` after the initial
> migrations exist requires a **destructive reset** — drop the database and regenerate every migration. Get it
> right on day one.

> **The superuser has no tenant.** Every tenant-scoped view filters by `tenant=request.tenant`, so
> logging in as the superuser shows empty lists by design. To see seeded data, log in as a tenant
> admin created by the seeder (for example `admin_acme`), which also has an active location.

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
