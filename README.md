# NavAIReceptionist

**A multi-tenant SaaS AI voice agent for inbound and outbound phone calls, running 24/7/365.**

It answers every inbound call within seconds, follows up with new leads by voice and SMS, qualifies
prospects against tenant-defined criteria, sends SMS, and books appointments directly into live
calendars — so no opportunity is missed. Every tenant configures its own agents, phone numbers,
knowledge, business hours, transfer targets and compliance policy; the platform meters, audits and
isolates all of it.

> **This repository is greenfield.** Nothing is built yet — there is no `apps/` directory. The module
> catalog and the project layout below describe the **planned** structure that the build sequence will
> produce, one sub-module at a time. Do not read any path in this file as a claim that the code exists.

---

## Architecture — all-Django

One codebase, one deployment. There is **no separate microservice**.

| Layer | Choice |
|---|---|
| Framework | Django 5.1 |
| Realtime | Django Channels / ASGI (telephony media-stream websockets, live-call UI) |
| UI | Tailwind CSS + HTMX + Lucide icons |
| Database | MySQL (`navai_receptionist`; test database `test_navai_receptionist`) |
| Server | ASGI via Daphne — `config.asgi:application` |
| Telephony | Twilio (Programmable Voice + Media Streams + Programmable Messaging), behind a provider adapter |
| Tenancy | Multi-tenant — a `tenant` FK on every model, `tenant=request.tenant` on every queryset |

### Why Channels/ASGI is required, not optional

The carrier does not hand us an audio file after the call. It opens a **bidirectional websocket** and
streams μ-law frames while the caller is still talking, and expects agent audio streamed back on the
same socket in real time. That media session is where the whole product lives: voice activity
detection, barge-in, the turn loop, tool calls, deferred transfer and hangup signals, and the
per-turn usage metering all happen inside a long-lived consumer holding per-call state.

WSGI has no way to hold that socket. So the realtime path is a Channels consumer, the app is served
over ASGI, and two rules follow from it:

- **`manage.py runserver` cannot serve the websocket routes at all.** Use Daphne for anything that
  touches a call.
- **No blocking work on the event loop.** A synchronous ORM query or a blocking SDK call inside an
  `async def` consumer freezes audio for *every* concurrent call on that worker. Use
  `database_sync_to_async` / `sync_to_async(thread_sensitive=False)`.

---

## Module catalog

Fourteen modules, `0`–`13`. Module 0 is the cross-cutting foundation and is built first; modules 1–13
are ordered so each depends only on what precedes it. Full feature bullets live in
**[`NavAIReceptionist.md`](NavAIReceptionist.md)** — that file is the scope authority.

| # | Module | Planned app slug |
|---|---|---|
| 0 | System Admin & Security | `core` + `accounts` + `tenants` + `dashboard` |
| 1 | Telephony & Number Management | `telephony` |
| 2 | Voice Agent Studio | `agents` |
| 3 | Knowledge Base & Business Facts | `knowledge` |
| 4 | Realtime Conversation Runtime | `runtime` |
| 5 | Inbound Call Handling & Routing | `inbound` |
| 6 | Compliance, Consent & Trust | `compliance` |
| 7 | Contacts, Leads & Qualification | `contacts` |
| 8 | Outbound Calling & Campaigns | `campaigns` |
| 9 | Messaging & Missed-Opportunity Recovery | `messaging` |
| 10 | Appointments & Scheduling | `scheduling` |
| 11 | Call Records, Transcripts & Post-Call Intelligence | `calls` |
| 12 | Testing, QA & Analytics | `analytics` |
| 13 | Integrations, API & Onboarding | `integrations` |

Two orderings are deliberate. **Compliance (6) ships before outbound (8) and messaging (9)**, because
A2P 10DLC registration, TCPA consent and recording consent are hard gates those modules cannot legally
clear without. And an **agent configuration is a versioned, publishable artifact** — draft → version →
publish → compare → rollback — decided in 2.1 and never retrofitted.

---

## The core spine

`apps/core` (Module 0) will own the entire shared spine, and modules 1–13 own their domain tables and
the UI over it — never a spine table of their own. The spine is three ideas: **one identity table**
(`core.Contact` plus `core.ContactRole` rows — leads, callers, customers and staff are roles, not
separate tables), **two append-only ledgers** (`core.Interaction` + `core.InteractionEvent` for every
call, SMS and email; `core.UsageEvent` for every billable unit), and **derived state, never stored
editable** (minutes used, spend, credit balance, answer rate and containment are `aggregate()` results,
so a stored `minutes_used` field is a bug). On top of those sit the outcome documents
(`core.Appointment`, `core.Recording`, `core.CallbackRequest`) and one outbound compliance gate,
`apps/core/compliance.py::check_outbound_allowed(...)`, that every dial, SMS and voicemail drop
must pass through.

The full field lists, the six spine invariants and the derived-not-stored table are in
**[`NavAIReceptionist-ERD.md`](NavAIReceptionist-ERD.md)**. That document is **intent — the code is
truth; grep before you FK.**

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

# Steps 4-6 apply once the Module 0 foundation exists (see the greenfield note above) —
# there is no manage.py and no apps/ in a fresh checkout, so they cannot run yet.

# 4. Migrate
venv\Scripts\python.exe manage.py check; venv\Scripts\python.exe manage.py migrate

# 5. Seed demo data (foundation first, then any built module's seed_<slug>)
venv\Scripts\python.exe manage.py seed_core; venv\Scripts\python.exe manage.py seed_accounts; venv\Scripts\python.exe manage.py seed_tenants

# 6. Platform superuser
venv\Scripts\python.exe manage.py createsuperuser
```

> ⚠️ **`AUTH_USER_MODEL = 'accounts.User'` must be set in `config/settings.py` before the very first
> `makemigrations`.** The `accounts` app ships the custom user model (it carries a `tenant` FK), and the spine FKs
> it back — `core.AuditLog.actor`, `core.Contact.owner`, `core.AgentVersion.published_by`,
> `core.CallbackRequest.assigned_to` — always via `settings.AUTH_USER_MODEL`, never a direct
> `from apps.accounts.models import User` (that is an import cycle, since `accounts.User` FKs `core.Tenant`).
> Django bakes the user model into every migration referencing it, so changing `AUTH_USER_MODEL` after the initial
> migrations exist requires a **destructive reset** — drop the database and regenerate every migration. Get it
> right on day one.

> **The superuser has no tenant.** Every tenant-scoped view filters by `tenant=request.tenant`, so
> logging in as the superuser shows empty lists by design. To see seeded data, log in as a tenant
> admin created by the seeder (for example `admin_acme`).

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

---

## Provider modes

`PROVIDER_MODE` selects which implementation the telephony / STT / TTS / LLM adapters resolve to.

| Mode | Behaviour |
|---|---|
| `fake` | **The development default.** In-process fakes. No network, no cost, no real calls or SMS. Tests and seeders run against these so the adapter contract itself is exercised. |
| `sandbox` | Provider test credentials and test numbers. Real network, no billable production traffic. |
| `live` | Real carrier, real LLM/STT/TTS spend, real phone calls to real people. |

⚠️ **Never leave `PROVIDER_MODE=live` set in a development environment.** A seeder, a test, a stray
management command or a looping agent can then place real calls and send real SMS to real numbers —
that is a compliance incident and an unbounded bill, not a bug. Keep `fake` in `.env`, and treat
`live` as something you set deliberately, on a deployed environment, and unset again.

---

## Testing

```powershell
venv\Scripts\python.exe -m pytest -q
venv\Scripts\python.exe -m pytest -q apps/core
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
  core/                 the entire spine: Contact, Interaction, InteractionEvent, UsageEvent,
                        PhoneNumber, Agent/AgentVersion, Appointment, Recording, consent
                        + providers/ (adapters + fakes), agent/ (prompt, state, tool dispatcher),
                          compliance.py (the single outbound gate), navigation.py (LIVE_LINKS)
  accounts/             users, roles, RBAC, MFA, sessions
  tenants/              tenant records, plans, subscriptions, invoices, spend caps
  dashboard/            tenant home KPIs
  <module slug>/        one Django app per module 1–13 (see the catalog table above)
templates/              base.html, partials/, then <app>/<submodule>/<entity>/<page>.html
static/css/theme.css    the Tailwick-derived blue/white design system class contract
NavAIReceptionist.md    module catalog — the scope authority
NavAIReceptionist-ERD.md  the core spine, written out as intent
.env.example            every environment key with dummy values
```

Within each app, `models`, `forms`, `views`, `urls` and `consumers` are **Python packages** organized
one folder per sub-module then one file per entity — never flat monoliths. `routing.py`, `webhooks.py`,
`tasks.py`, `providers.py`, `admin.py` and `apps.py` stay flat at the app root. Templates mirror the
same shape. Both conventions, and the rules that keep them working, are specified in
`.claude/CLAUDE.md`.
