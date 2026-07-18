---
name: next-module
description: Build the next NavAIReceptionist SUB-module end-to-end — ONE sub-module ("N.M") per run, NOT a whole module. Extend the module's Django app under apps/<slug> with that sub-module's tenant- and location-scoped models, full CRUD views/forms/urls/admin, Tailwind+HTMX templates, any Channels consumers / LLM tools / provider-adapter methods it needs, an idempotent seeder, navigation wiring (a LIVE_LINKS "N.M" entry), and migrations. Use when the user says "new", "next", "next sub-module", "build/create the next sub-module", "continue the modules", or invokes /next-module. Takes an optional argument — a specific sub-module "N.M" (e.g. "/next-module 4.2"), a sub-module name (e.g. "availability", "transfer settings"), or a whole module number/name (build its next unbuilt sub-module). With no argument, auto-detect and build the next unbuilt sub-module of the module currently in progress.
---

# next-module — NavAIReceptionist module builder

When this skill is invoked, you build **one NavAIReceptionist sub-module** (`N.M`) end-to-end — the **next unbuilt
sub-module of the module currently in progress**, NOT the whole module in one pass. Each module has 3–5
sub-modules; each "next"/`/next-module` run delivers exactly **one** sub-module's slice, then stops. If the
module's app already exists under `apps/<slug>`, you **extend** it (add that sub-module's models + pages + a
`LIVE_LINKS["N.M"]` entry) — you do NOT re-scaffold the app.

The product is small and deliberately so: a multi-tenant Django app where a business with **multiple locations**
configures a Twilio number and an AI voice agent **per location**. The agent answers inbound calls, books
appointments into a calendar, transfers to a human when asked, and logs the call in detail. Seven capabilities
only — login, change password/email, calendar, bookings, agent setup + Twilio, call transfer, user profile.

**`scope-v2.md` is the binding design.** Modules 0 and 1 (`accounts` + `tenants`) are the foundation and are built
first; once they exist they are the **canonical reference implementation** for a tenant- and location-scoped CRUD
module. Read them whenever you are unsure how something should look.

## Triggers
- User says: **"new"**, **"next"**, "next sub-module", "build/create the next sub-module", "continue the modules". **"new"/"next" mean the next *sub-module*, one per run — never the whole module.**
- User invokes **`/next-module`** (optionally with a sub-module `N.M` like `4.2`, a sub-module name like `availability`/`transfer settings`, or a whole module number `0`–`5` / module name — in which case you build that module's *next unbuilt* sub-module).

## When NOT to use
- User wants the design-system / template pattern reference → `/frontend-design`.
- User wants the realtime + tool-dispatcher contract → `/voice-agent-runtime`.
- User wants tests for a module → run the `test-writer` agent; for a render sweep run `qa-smoke-tester`.
- User wants to fix a specific bug → just fix it.

---

## Project conventions

- **Stack:** Django 5.1, **Django Channels/ASGI** for the realtime Twilio media-stream websocket (**all-Django, one
  codebase, no separate microservice**), **function-based views** with `@login_required`, **Tailwind CSS (Play CDN)
  + HTMX + Lucide**, MySQL/MariaDB (XAMPP) via PyMySQL. DB is **`navai_receptionist`**. `AUTH_USER_MODEL =
  'accounts.User'`. Run Python through the venv: `venv\Scripts\python.exe manage.py ...` (PowerShell) — Django is
  not on system Python. The dev server is **Daphne**, never `runserver`, for anything touching websockets:
  `venv\Scripts\python.exe -m daphne -b 127.0.0.1 -p 8000 config.asgi:application`. Twilio webhooks in dev need a
  tunnel whose public URL matches `TWILIO_WEBHOOK_BASE_URL` **exactly**, or signature verification fails. Tests run
  under `config.settings_test` (SQLite in-memory, `InMemoryChannelLayer`, `PROVIDER_MODE = "fake"`) with pytest +
  pytest-django + pytest-asyncio.
- **The three invariants** (the wording must be identical in every file that carries them):
  1. **One contact identity table.** Callers, bookers and attendees are `scheduling.Contact` rows. **Flag any new standalone `Lead`, `Caller`, `Patient` or `Attendee` model.**
  2. **One call log.** A call is exactly one `calls.CallSession`; its transcript, event log, per-turn usage, analysis and transfer outcome are **JSON columns on that row**. **Flag a second transcript, turn, tool-call or call-event table.**
  3. **Server owns identity; the model owns wording.** The tool dispatcher is `apply_tool_call(state, name, args)`. `tenant_id`, `location_id`, `contact_id` and `session_id` come from server-side session state and are **never tool parameters**. Any id the model does supply (`appointment_id`, `slot_token`) is authorized server-side against tenant, location **and** the identified contact.

  Two supporting rules, kept: **opaque signed slot tokens** (the availability tool returns one signed short-TTL
  `slot_token` per slot, not semantic fields the model must echo back), and **one tool-result envelope**
  (`{"ok": bool, "data": {...}, "error": {"code": "...", "message": "..."} | null}`, `code` always
  lower_snake_case).

  FK across apps **by string** (e.g. `models.ForeignKey('scheduling.Contact', ...)`). **Before FK'ing anything,
  verify it exists** (`grep -rn "^class <Name>" apps/*/models/` — `models` is a **package** in every app, so the
  grep must be recursive and target directories, never a nonexistent `models.py`).
- **App layout:** `apps/<slug>/`, AppConfig `name = 'apps.<slug>'`. Register in `config/settings.py`
  `INSTALLED_APPS` and add `path('<slug>/', include('apps.<slug>.urls'))` to `config/urls.py`. If the module has a
  websocket surface, add its `routing.py` patterns to the `ProtocolTypeRouter` in `config/asgi.py`.
- **Backend packages (MANDATORY):** `models/`, `forms/`, `views/`, `urls/` (and `consumers/` when the sub-module has
  a realtime surface) are **packages**, never flat `.py` files — **one folder per sub-module, then one file per
  entity** (`apps/<slug>/models/<SubModule>/<Entity>.py`), exactly mirroring the template rule. Each package's
  `__init__.py` re-exports everything it owns; imports inside them are **absolute**. See §2a. **The foundation apps
  `accounts` and `tenants` are FLAT** — the entity file sits at the package root
  (`apps/tenants/models/Location.py`), no `<SubModule>/` level.
- **Templates:** project-level `templates/<slug>/<submodule>/<entity>/<page>.html` (**one folder per sub-module,
  then one folder per entity, with a bare `list/detail/form.html` page filename — MANDATORY**, see
  CLAUDE.md "Template Folder Structure"; landing page stays at `templates/<slug>/` root; the foundation apps are
  flat: `templates/accounts/user/form.html`), **extend `templates/base.html`**, use the design-system classes from
  `static/css/theme.css`: `.page-header .page-title .breadcrumb .page-actions`, `.card .card-header .card-body`,
  `.btn .btn-primary .btn-outline .btn-danger .btn-icon`,
  `.badge .badge-green/.badge-red/.badge-amber/.badge-info/.badge-muted/.badge-slate` (**colour-named ONLY —
  semantic `-success/-warning/-danger` variants do NOT exist and render unstyled**), `.table-wrap .table
  .table-actions`, `.form-group .form-label .form-input .form-select .form-textarea .form-error`, `.stat-card`
  (stat-icon colours: `blue/green/orange/purple/slate` only), `.empty-state`, `.pagination`, `.avatar-initial`,
  `.progress .progress-bar`, the calendar/booking components `.calendar-grid`, `.calendar-slot`, `.booking-card`,
  and the voice components `.call-status-dot`, `.transcript-turn` (+ `.agent`/`.user`), `.live-badge`, `.waveform`.
  Before using ANY theme.css modifier class, confirm it exists
  (`grep -oE '\.(badge-[a-z]+|stat-icon(\.[a-z]+)?|text-[a-z]+)' static/css/theme.css | sort -u`) or copy a
  sibling template's badge line verbatim. Canonical call-status badge map: `in_progress`→`badge-info`,
  `completed`→`badge-green`, `abandoned`→`badge-muted`, `transferred`→`badge-info`, `failed`→`badge-red`. Five
  statuses share four badge classes; `badge-info` is intentionally used twice. There is no `badge-purple`. Always
  pair the map with an `{% else %}` fallback to `{{ obj.get_status_display }}`. Icons:
  `<i data-lucide="NAME"></i>` (list actions: eye / pencil / trash-2).
- **Tenant AND location scoping (mandatory):** every model has `tenant = models.ForeignKey('tenants.Tenant',
  on_delete=models.CASCADE, related_name='<unique>')`. Location-scoped models — `AgentSetting`, `Resource`,
  `Appointment`, `CallSession`, `CallbackRequest`, and `Service` (nullable) — additionally carry a `location` FK.
  Every view filters `Model.objects.filter(tenant=request.tenant)` — never `.all()` — and, for a location-scoped
  model, `location=request.location` as well. `request.tenant` / `request.location` are set by
  `apps.accounts.middleware`; `request.location` is the session's **active location**, validated against the user's
  `accounts.UserLocation` rows. **Cross-location access is a real bug class** — a user must never reach a location
  they are not assigned to, and an IDOR across locations is as serious as one across tenants.
  **Channels consumers, background tasks and Twilio webhooks have no `request`** — there tenant **and** location
  are resolved from the **dialed number** (`AgentSetting.objects.get(inbound_phone_number=<To>)`), never from a URL
  or body parameter the caller controls. That is exactly why `inbound_phone_number` is globally unique across all
  tenants.
- **CRUD completeness (mandatory for any model with a list page):** **list (search + filters + pagination),
  detail, create, edit, delete (POST-only + confirm + csrf)**. List templates have an Actions column
  (view/edit/delete). See CLAUDE.md "CRUD Completeness Rules" + "Filter Implementation Rules".
- **Filters:** parse `request.GET` and apply BEFORE pagination. Pass `status_choices` + any FK querysets the
  template's filter dropdowns need (locations, services, resources, providers, contacts). pk filters compare with
  `|stringformat:"d"`.
- **Seeders:** idempotent (guard `if Model.objects.filter(tenant=tenant).exists()`), `get_or_create`,
  existence-check auto-numbers. Create both `management/__init__.py` and `management/commands/__init__.py`. A seeder
  must never reach a live provider — it runs against the fake adapters under `PROVIDER_MODE=fake`.
- **Auto-numbers:** human-readable per-tenant numbers like `CALL-00001` / `APPT-00001` / `CB-00001` where it fits —
  use the app's abstract `TenantNumbered` base in `apps/<slug>/models/_base.py`.
- **Git:** at the end, output a **PowerShell-safe one-file-per-commit** snippet (`git add 'f'; git commit -m '...'`).
  One file per commit, to `main`; do NOT `git push` — the user pushes.
- **Security:** flag vulnerabilities with a `# WARNING:` comment + secure alternative. The per-location
  `AgentSetting.twilio_auth_token` is **encrypted at rest and write-only in forms** — never in `Meta.fields` as a
  readable value, never rendered, never logged, never in `messages.*`.

Reference files to read before building: **`scope-v2.md`** (the binding design — read this first), and — once the
foundation exists — `apps/accounts/navigation.py`, `apps/accounts/middleware.py`, `apps/accounts/models/`,
`apps/tenants/models/`, `apps/runtime/providers/` (telephony/STT/TTS/LLM adapters + their fakes),
`apps/runtime/agent/` (prompt rendering, session state, tool declarations, the `apply_tool_call` dispatcher),
`config/asgi.py` + `config/settings.py` (`ASGI_APPLICATION`, `CHANNEL_LAYERS`). For foundation-style CRUD/auth
patterns read `apps/tenants/models/`, `apps/tenants/views/`, `apps/tenants/forms/` (packages with entity files at
the root, no sub-module level), `templates/tenants/<entity>/<page>.html`, `static/css/theme.css`, and the
foundation seeders `seed_accounts` and `seed_tenants`. **Never point at or FK a file you have not confirmed
exists.**

> ⚠️ **Build ONE sub-module per run.** Each `/next-module` run (and each "next"/"new") builds exactly ONE
> sub-module (`N.M`) — its models (usually 1–3), fully CRUD + tenant/location-scoped + wired
> (`LIVE_LINKS["N.M"]`) + seeded + verified, then STOP. Do NOT build the rest of the module's sub-modules in the
> same run. (The first run for a brand-new module also scaffolds the app skeleton — see Step 1 + Step 2.)

---

## Step 0 — Is the foundation built? (greenfield check)

**This repository is greenfield: there is no `apps/` directory. Never claim anything is built.** Before any domain
module exists, the **foundation (modules 0 + 1)** must be built:

- **`accounts`** — `User` (email-or-username + password, tenant resolved by `customer_id`), `UserLocation`, login /
  logout / password reset / change password / change email / profile, roles by `User.tier`, the **active-location
  switcher**, `middleware.py` (sets `request.tenant` + `request.location`), and `navigation.py`
  (`MODULE_ICONS` + `LIVE_LINKS`, the module 0–5 catalog).
- **`tenants`** — `Tenant`, `Location`, business settings, location CRUD, staff↔location assignment, provider
  working hours.

Plus `config/` (including `asgi.py` + `CHANNEL_LAYERS`), `templates/base.html`, `static/css/theme.css`, `.env`
(platform defaults + `PROVIDER_MODE` only — **Twilio credentials are per-location in the database, not env**), and
the seeders. If `apps/accounts` / `config/settings.py` do not exist yet, build the foundation first (enter plan
mode, follow `scope-v2.md`) — it is the reference every later module clones.

## Step 1 — Decide which SUB-MODULE to build

> **You always resolve to exactly ONE sub-module `N.M`.** **How "built" is tracked:** a sub-module is BUILT iff it
> has a `LIVE_LINKS["N.M"]` entry in `apps/accounts/navigation.py` (the sidebar lights it up). Read that dict to
> know the order and what's done. **Always read the *real* current `LIVE_LINKS` keys at run time** — the built set
> changes every run, so never assume it from memory or from this doc.

1. **If the user passed an argument, resolve it to exactly one sub-module** (case-insensitive, punctuation/`&`/`and`
   ignored):
   - **Sub-module number `N.M`** — e.g. `4.2`, `2.1`, `module 4.2`, `#4.2` → exactly that sub-module.
   - **Sub-module name** — e.g. `availability`, `transfer settings`, `location switcher`, `transcript` → match it
     against the module's sub-module headings and resolve to that one `N.M`.
   - **Whole module number `0`–`5`, app slug, or module name** — e.g. `4`, `scheduling`, `"Calendar & Bookings"`,
     `calls` → resolve to that module, then pick its **next unbuilt sub-module** = the lowest-numbered `N.M` with
     **no** `LIVE_LINKS["N.M"]` entry.
   - If the text matches **more than one** sub-module/module → ask the user to pick via `AskUserQuestion`. If it
     matches **none** → tell the user and show the relevant sub-module list.

   Examples: `/next-module 4.3` → Scheduling's third sub-module. `/next-module transfer` → Agents' transfer-settings
   sub-module. `/next-module calls` → Call Logs' next unbuilt sub-module.

2. **If no argument**, **auto-detect the next unbuilt sub-module** of the module currently in progress:
   1. **Active module** = the **highest-numbered** module `N` (0–5) whose app slug already exists under `apps/` —
      that's the module under construction. (If NO app exists yet, the active module is **Module 0 = `accounts`**,
      and this run scaffolds it + builds `0.1`.)
   2. **Next sub-module** within the active module = the **lowest-numbered `N.M`** that has **no**
      `LIVE_LINKS["N.M"]` entry. *(Illustration of the rule only, NOT live state: if a module has entries for
      `X.1, X.2, X.4`, the lowest `N.M` with no entry is **X.3**, so "next" → X.3.)*
   3. **Module rollover:** if the active module has a `LIVE_LINKS` entry for **every** one of its sub-modules,
      advance to the **next module** = the lowest `0..5` whose app does NOT exist, scaffold its app, and build its
      **first** sub-module (`N.1`).

3. **State the one sub-module you resolved** (`N.M <name>`) and which models it adds, then proceed: enter plan mode
   per CLAUDE.md, present the short model/page spec for **that sub-module only**, then build it and STOP. Lean
   toward building, don't over-deliberate.

### Module → app-slug → models (the complete map — eleven models, nothing else)

| # | Module | app slug | Models it owns |
|---|--------|----------|----------------|
| 0 | Accounts & Access | `accounts` | `User`, `UserLocation` |
| 1 | Business & Locations | `tenants` | `Tenant`, `Location` |
| 2 | Agent Setup & Telephony | `agents` | `AgentSetting` |
| 3 | Call Runtime | `runtime` | **none — service module** (consumers, webhooks, provider adapters, the agent package, a diagnostics page) |
| 4 | Calendar & Bookings | `scheduling` | `Contact`, `Service`, `Resource`, `Appointment`, `CallbackRequest` |
| 5 | Call Logs | `calls` | `CallSession` |

Field-level definitions live in **`scope-v2.md` §S4** — read them there rather than re-deriving. The shapes that
matter most:

- **`agents.AgentSetting`** is one row per `(tenant, location)` and carries agent config, Twilio credentials **and**
  transfer settings together — `enabled`, `voice_provider`, `greeting`, `prompt_text`, `variables`,
  `inbound_phone_number` (**globally unique across all tenants** — it is how an inbound webhook resolves
  tenant+location), `twilio_account_sid`, `twilio_auth_token` (**encrypted, write-only**), `transfer_enabled`,
  `transfer_phone_number`, `transfer_secondary_number`, `transfer_timezone`, `transfer_working_hours`,
  `transfer_keywords`.
- **`calls.CallSession`** is **one table with JSON columns** — `transcript`, `logs`, `analysis`, `usage`,
  `transfer`, `waveform_peaks`, `metadata` — **not** a normalized event log. A call session is written once by one
  process and read as a whole on one detail page; nothing queries across turns. A second transcript / turn /
  tool-call / call-event table is an **Invariant 2** violation.
- **`scheduling.Contact`** is the single identity table for callers and bookers. It is **not** location-scoped — a
  caller belongs to the business and may book at any location.

Aim for **1–3 models** per sub-module pass. **This is a ceiling for CRUD sub-modules only — it defers to the shape
branches in Step 2.** A **service** sub-module may add zero models; a **view** sub-module adds **ZERO** models and
zero migrations. *Inventing a model to satisfy the target is the bug the view branch exists to prevent. If the data
already lives in `CallSession`'s JSON columns or in a foundation table, the sub-module is a view — ship the pages,
not a table.* Decide the shape (CRUD / service / view) BEFORE you pick any models.

---

## Step 2 — Build the sub-module (prefer a parallel agent Workflow for speed)

**Existing module vs. new module.** First check whether `apps/<slug>/` already exists:
- **App exists (the common case — you're adding a sub-module):** you **extend** it by **adding a new
  `<SubModule>/` folder to each of the four packages** (`models/`, `forms/`, `views/`, `urls/` — plus `consumers/`
  if it has a realtime surface) with one `<Entity>.py` per model — then **add that sub-module's re-export block to
  each package's `__init__.py`** (and wire the new url module into `urls/__init__.py`, the new websocket patterns
  into `routing.py`). Register the models in `admin.py` and extend the existing `seed_<slug>.py`. **Skip** the
  `apps.py`/`__init__.py` scaffolding and the `config/settings.py` + `config/urls.py` wire-up — already done. The
  only navigation change is **one new `LIVE_LINKS["N.M"]` entry**. `makemigrations <slug>` produces a new
  incremental migration (e.g. `0002_…`).
  - If you are extending an **entity that already exists** (a new field, an extra child model), edit that entity's
    existing `<Entity>.py` in each layer rather than creating a parallel file.
  - **Legacy flat apps:** if a non-foundation app somehow starts flat (`models.py` etc.), convert it to the package
    layout as part of the run — do **not** append to the monolith and do **not** add a `*_advanced.py` sidecar.
- **App does NOT exist (first run for a brand-new module):** scaffold the full app skeleton below (`apps.py`,
  `__init__.py`, `migrations/__init__.py`, the four **packages** with their `__init__.py` + `_base.py`/`_common.py`,
  the `management/commands` tree) AND do the `config/settings.py` + `config/urls.py` wire-up (plus `config/asgi.py`
  if it has websocket routes) — then build that module's first sub-module (`N.1`).

**Service sub-module variant (Module 3 `runtime`, and the Twilio-connection parts of Module 2).** Some sub-modules
produce **consumers, services, provider adapters and diagnostics**, not list/detail/form CRUD. When the resolved
`N.M` is one of these, say so up front and follow this branch instead:
- It **MAY ship zero CRUD templates.** The mandatory CRUD/filter rules apply only to sub-modules that introduce a
  model with a list page.
- It **MUST still ship**: tenant **and location** scoping on every query (resolved from the dialed number in
  non-HTTP paths), a `LIVE_LINKS["N.M"]` entry pointing at its diagnostics or settings page, migrations if it adds
  models, tests, an idempotent seeder if it adds data, and a **fake provider implementation so the whole path runs
  with `PROVIDER_MODE=fake`**.
- It **MUST ship at least one observable surface** — a diagnostics page (`templates/runtime/diagnostics.html`), a
  settings form, or a management command — so `qa-smoke-tester` has something to assert against. A sub-module with
  no observable surface is not done.

**View sub-module variant.** Some sub-modules add **no data of their own** — they are the reading surface over
tables that already exist. A **view sub-module** ships **ZERO new models and ZERO migrations**: it is pages,
filters, search, detail views, exports and a `LIVE_LINKS["N.M"]` entry over data it only **READS**. When the
resolved `N.M` is one of these, say so up front and follow this branch instead:
- *Inventing a model to satisfy the model target is the bug this branch exists to prevent.* Concretely, the
  **transcript and tool-call trace sub-module in Module 5 is the view over `calls.CallSession.transcript` and
  `.logs`** — a `Transcript`, `TranscriptTurn` or `ToolCall` table there is an **Invariant 2** violation that
  `code-reviewer` will reject. The same is true of the cost breakdown (it reads `CallSession.usage`) and the
  transfer outcome (it reads `CallSession.transfer`).
- It **MAY ship zero new models, zero forms, zero migrations** and no create/edit/delete views — their absence is
  correct here. The backend layers it does touch (`views/<SubModule>/<Entity>.py`,
  `urls/<SubModule>/<Entity>.py`) still follow §2a, re-exports included.
- It **MUST still ship**: **tenant + location scoping on every query**, the **`LIVE_LINKS["N.M"]` entry**, its
  **templates** under `templates/<slug>/<submodule>/<entity>/` (list + detail, filter bar, pagination,
  empty-state), **tests**, and **seeded demo data reachable through the pages — seeded into the existing tables,
  never into a new one** (extend the existing `seed_<slug>` idempotently).

The user prefers fanning work out across agents. For one sub-module a small **2–3 agent Workflow** works well:
keep **backend + migrations + seed** as one solo agent (single DB writer), then **templates** as 1–2 agents.
You may also build it inline if it's quick. Produce ALL of the following **for the one sub-module** (for an existing
app, "create" means "append to the existing file"):

### 2a. Backend (`apps/<slug>/`) — **models / forms / views / urls are PACKAGES, never flat .py files**

**MANDATORY — Backend Package Structure.** Exactly like the template rule, the backend layers are organized
**one folder per sub-module, then one file per entity**.

```
apps/<slug>/
  models/     __init__.py (re-exports EVERY model)   _base.py  (shared imports + abstract Tenant* base)
  forms/      __init__.py (re-exports EVERY form)    _common.py (shared imports)
  views/      __init__.py (re-exports EVERY view)    _common.py (shared imports) [+ _helpers.py]
  urls/       __init__.py (app_name + concatenates each entity module's urlpatterns)
  consumers/  __init__.py (re-exports EVERY consumer)  [realtime sub-modules only]
  routing.py  (flat — websocket URLPatterns for this app)
     +-- <SubModule>/          # PascalCase sub-module title, e.g. CallLogRecording, TranscriptTrace
           __init__.py
           <Entity>.py         # PascalCase entity, e.g. CallSessions.py, Appointments.py
```

The layers **line up one-to-one**: `models/CallLogRecording/CallSessions.py` ↔
`forms/CallLogRecording/CallSessions.py` ↔ `views/CallLogRecording/CallSessions.py` ↔
`urls/CallLogRecording/CallSessions.py` (↔ `consumers/CallLogRecording/CallSessions.py`). Folder = the sub-module
title in PascalCase — worked examples: Module 5 (`apps/calls`) `Call Log & Recording` → `CallLogRecording/`, full
path `apps/calls/models/CallLogRecording/CallSessions.py`; Module 4 (`apps/scheduling`) `Calendar & Availability`
→ `CalendarAvailability/`, `Bookings` → `Bookings/`; Module 2 (`apps/agents`) `Transfer & Escalation` →
`TransferEscalation/`. An entity file holds the primary model **plus its children**.

**The foundation apps `accounts` and `tenants` have NO sub-module level** — the entity file sits FLAT at the
package root: `apps/tenants/models/Location.py`, `apps/accounts/views/User.py`.

**Non-negotiable rules:**
1. **Every package `__init__.py` re-exports everything** it owns (`from .<SubModule>.<Entity> import (A, B)`).
   This is what keeps `from apps.<slug>.models import X`, `views.<name>` in the URLconf, and
   `include('apps.<slug>.urls')` working. **If you add a model/form/view/consumer and forget the re-export block, it breaks.**
2. **Imports inside these packages MUST be ABSOLUTE** — `from apps.<slug>.models import X`. A relative
   `from .models import X` resolves to the wrong package one level deeper and will `ImportError`/silently misbehave.
   Entity modules pull the shared toolkit via `from apps.<slug>.models._base import *` (resp. `forms._common`,
   `views._common`).
3. **`urls/__init__.py`** sets `app_name = '<slug>'` and concatenates each entity module's `urlpatterns`. Django is
   **first-match-wins**, so order is behaviour: keep literal routes before `<int:pk>` ones, and check any new greedy
   `<str:token>` route against the whole list. **`routing.py` is the same rule for websockets** — a greedy
   `<str:token>` media-stream route must be checked against the whole concatenated `URLRouter` list.
4. **Shared private helpers** used by MORE THAN ONE sub-module go in `views/_helpers.py`. Helpers used by one entity
   stay in that entity's module.
5. **NEVER create `models_advanced.py` / `views_advanced.py` / a second flat file for "advanced" features** — a later
   sub-module's models just get their own `<SubModule>/<Entity>.py`.

**What each layer contains** (unchanged rules, new locations):
- `models/<SubModule>/<Entity>.py` — this sub-module's models. Each: `tenant` FK, a `location` FK when the model is
  location-scoped, timestamps, `STATUS_CHOICES` class attrs where relevant, `__str__`, `class Meta: ordering`. FK
  across apps **by string** (`models.ForeignKey('scheduling.Contact', ...)`). Auto-number in `save()` with an
  existence guard. Models sit deeper than the app root, but Django still derives `app_label` from the app config —
  **migrations are unaffected**.
- `forms/<SubModule>/<Entity>.py` — ModelForms; **exclude** `tenant`, `location` (it comes from
  `request.location`), auto-`number`, and provider-supplied fields (`provider_call_sid`, `from_number`,
  `to_number`, `transcript`, `usage`). `twilio_auth_token` is **write-only**.
- `views/<SubModule>/<Entity>.py` — function-based, `@login_required`, tenant- **and location**-scoped, full CRUD +
  search + filters + pagination.
- `urls/<SubModule>/<Entity>.py` — `urlpatterns = [...]` with names
  `<entity>_list/_detail/_create/_edit/_delete`; imports views absolutely (`from apps.<slug> import views`).
- `consumers/<SubModule>/<Entity>.py` + `routing.py` — Module 3 only; see **2e**.
- `webhooks.py` — flat at the app root (Module 3); Twilio ingress with **signature verification before any side
  effect**, using the resolved `AgentSetting`'s credentials, and an idempotency key on `provider_call_sid`.
- `admin.py` — stays a flat file; register the new model(s).
- `apps.py` / `__init__.py` — **new-app run only** (skip if the app exists).
- `migrations/` — `makemigrations <slug>` yields `0001_initial.py` for a new app, or the next incremental migration.
- `management/commands/seed_<slug>.py` — for a new app create the `management/__init__.py` +
  `management/commands/__init__.py` tree + the command; for an existing app **extend the existing `seed_<slug>.py`**
  with this sub-module's demo rows (idempotent per-tenant guard; reuse existing Tenant/Location/Contact rows rather
  than inventing duplicates). Seed **at least two locations per demo tenant** — a single-location seed hides every
  cross-location scoping bug.

### 2b. Wire-up
- `config/settings.py` — add `'apps.<slug>'` to `INSTALLED_APPS` **only for a brand-new app**.
- `config/urls.py` — add `path('<slug>/', include('apps.<slug>.urls'))` **only for a brand-new app**.
- `config/asgi.py` — add the app's `routing.websocket_urlpatterns` to the `ProtocolTypeRouter`/`URLRouter` **only
  when this sub-module introduces the app's first websocket route** (in practice, Module 3's first run).
- `apps/accounts/navigation.py` — add **one `LIVE_LINKS["N.M"]` entry** for the sub-module you built, mapping its
  feature names → `'<slug>:<entity>_list'` (or the most relevant live page; for a service sub-module, its
  diagnostics or settings page). After this the sidebar shows that sub-module as **Live** instead of the roadmap
  placeholder. Do NOT touch other sub-modules' `LIVE_LINKS` entries.

### 2c. Frontend (`templates/<slug>/<submodule>/<entity>/<page>.html`)
- **One folder per sub-module, then one folder per entity, with a bare `list/detail/form.html` page filename
  (MANDATORY — see CLAUDE.md "Template Folder Structure").** The view's `render()` uses that full path (e.g.
  `"calls/calllog/callsession/detail.html"`). Worked paths:
  `templates/calls/calllog/callsession/{list,detail,form}.html`,
  `templates/scheduling/bookings/appointment/list.html`,
  `templates/agents/setup/agentsetting/form.html`; the banned flat form is `callsession_detail.html`. The
  foundation apps are flat — `templates/tenants/location/list.html`, `templates/accounts/user/form.html`. The
  module landing/overview page stays at the app root (`templates/<slug>/overview.html`); standalone pages —
  the calendar (`scheduling/calendar.html`), the transcript print page
  (`calls/transcript/transcript_print.html`), the runtime diagnostics page (`runtime/diagnostics.html`) — stay at
  the sub-module or app level with no entity folder.
- For each new model, an entity folder under the sub-module with `list.html`, `detail.html`, `form.html`
  (shared create/edit). For a single-entity sub-module the sub-module folder doubles as the entity folder — keep
  `setup/form.html`, NOT `setup/setup/list.html`.
- Extend `base.html`; use the design-system classes; list pages get a GET filter form (search `q` + status/FK
  selects reflecting `request.GET`), an Actions column (view/edit/delete POST+confirm+csrf), pagination, and an
  `.empty-state`. Badges use the model's exact choice values + `{{ obj.get_<field>_display }}` fallback.
  Caller-controlled text (transcript turns, tool-call payloads, contact names) is **never** `|safe`. Recordings
  play through a plain `<audio controls>` against a short-lived signed URL. **A location selector or a visible
  active-location indicator belongs on every location-scoped list page** — a user must always know which
  location's data they are looking at.

### 2d. Migrate + seed + verify (venv python)
```
venv\Scripts\python.exe manage.py makemigrations <slug>
venv\Scripts\python.exe manage.py migrate
venv\Scripts\python.exe manage.py seed_<slug>
venv\Scripts\python.exe manage.py seed_<slug>   # 2nd run must be idempotent
venv\Scripts\python.exe manage.py check
```
For a **view** sub-module `makemigrations` must report **"No changes detected"** — a new migration here means you
added a table you should not have.

### 2e. Realtime & agent surface — **Module 3 (`runtime`) only**
Skip this step entirely for every other module. Module 3 owns the whole live-call path: the Twilio webhooks, the
media-stream consumer, the turn loop, the LLM tools and transfer execution. When you are building one of its
sub-modules, ship **all** of:
- **Consumer + route.** `consumers/<SubModule>/<Entity>.py` plus the `routing.py` entry. The consumer **authorizes
  in `connect()`** (`@login_required` does not apply to consumers) and closes with a code rather than
  accepting-then-checking; it resolves tenant **and location** from the verified stream token or the dialed
  number's `AgentSetting`, never from the websocket URL. Group names are **tenant-namespaced** —
  `t{tenant_id}:call:{session_id}`. No synchronous ORM, provider SDK, `requests`/`httpx.Client`, file I/O or
  `time.sleep` inside an `async def`; use `database_sync_to_async` / `sync_to_async(thread_sensitive=False)` /
  `asyncio.to_thread`. `disconnect()` finalizes the `CallSession` and flushes buffered transcript/log entries; an
  exception on one frame must not kill the call.
- **Tool declaration + dispatcher branch.** Declarations are **plain provider-agnostic dicts** (`name`,
  `description`, `parameters`) in `apps/runtime/agent/tools.py`. The dispatcher signature is
  **`apply_tool_call(state, name, args)` and is transport-agnostic**. Identity args (`tenant_id`, `location_id`,
  `contact_id`, `session_id`) come from server-side session state and are **never tool parameters**; any
  model-supplied ID (`appointment_id`, `slot_token`) is authorized server-side against tenant, location **and** the
  identified contact. Every tool returns the one envelope
  `{"ok": bool, "data": {...}, "error": {"code": ..., "message": ...} | null}` — never prose, never a bare
  `{"id": …}`. A per-turn tool-iteration cap (default **4**) with a spoken fallback, so a looping model never
  produces dead air.
- **Prompt & variables.** Add any new runtime variable to the variable set and recompute time-sensitive ones per
  turn. **The prompt names no tool and no tool parameter.** The greeting is rendered from
  `AgentSetting.greeting` with `{{variable}}` substitution, is deterministic and never waits on an LLM.
- **Provider adapter + fake.** The interfaces, the fakes and `PROVIDER_MODE` resolution live in
  `apps/runtime/providers/`. Any new external call gets an adapter method there **and its fake implementation in
  the same pass**, with an explicit timeout and a bounded retry. `PROVIDER_MODE` ∈ `fake | sandbox | live` and
  **`fake` is the default** for dev, tests and seeders. When the mode is not `live`, the adapter resolves to the
  fake/sandbox implementation and **must never reach a real provider**. The **live** adapter refuses to initialize
  unless `PROVIDER_MODE == "live"`, and live mode additionally requires real credentials — missing credentials in
  live mode is the hard failure. A test, seed or dev path must never place a real call.
- **Per-turn cost.** Append the turn's cost breakdown to `CallSession.usage` as a delta —
  `{turn_sequence, cost_breakdown, cost_usd}` — never re-aggregate the whole call each turn.
- **Deferred transport actions.** Transfer and hangup set a pending signal on state; the transport acts only after
  the turn's audio has finished playing, and a single-fire guard is set before any `await`. The transfer
  destination is **always** the configured `AgentSetting.transfer_phone_number` /
  `transfer_secondary_number` — never anything derived from caller speech.

Full contract: `/voice-agent-runtime`.

---

## Step 3 — Verify (don't mark done until proven)

Render every new page as a tenant admin against seeded data and assert no errors / no leaks. Use a throwaway
script in `temp/` (gitignored):

- **First, assert `PROVIDER_MODE` is `fake`** and that `apps/runtime/providers` resolves to the fake adapters. A
  verify run must never place a real call or hit a paid LLM endpoint.
- Log in via Django test client `force_login(User.objects.get(email='admin@acme.test'))` (set
  `settings.ALLOWED_HOSTS=['testserver',...]`), then GET every `<slug>:*` url (use `reverse`, sample a pk per
  model) and assert status in `(200, 302)`.
- Fetch one list page's HTML and assert **no** `'{#'` / `'{% comment'` leak markers (Django `{# #}` comments are
  single-line only — use `{% comment %}` for multi-line notes), and that the page title + a seeded record appear.
- **Cross-tenant IDOR:** as the Acme admin, request a Globex record's pk → expect **404**.
- **Cross-LOCATION IDOR:** as a user assigned only to Location A, request a Location B record's pk → expect
  **404**, and confirm the location switcher refuses to activate Location B for that user. This is a real bug
  class in this product; test it on every location-scoped model.
- **If the sub-module has a websocket surface:** `channels.testing.WebsocketCommunicator` against
  `config.asgi.application` — connect with a valid stream token → accepted; connect without auth or with another
  tenant's session id → **rejected**; send a synthetic audio frame → the consumer responds without raising.
- **If it has a webhook:** valid signature → 200 + the expected body; absent/invalid signature → 403 with **zero**
  side effects; the same valid payload twice → exactly one `CallSession` row.
- Fix anything that isn't 200/302 (usual culprit: a wrong reverse-accessor name or a context-variable
  mismatch — read the view to confirm the exact name).

Credentials: the tenant admins the foundation seeder creates. Read
`apps/accounts/management/commands/seed_accounts.py` for the current values rather than assuming them. The
superuser has no tenant and sees no module data (by design).

---

## Step 4 — Document + commit snippet
1. Update `README.md` (mark **this sub-module** complete in the roadmap; ensure `seed_<slug>` is in the seeding section).
2. Update `.claude/tasks/todo.md` with a short review of the sub-module just built.
3. Output the **one-file-per-commit** PowerShell snippet for every created/changed file — with the package layout
   this is one commit per entity module per layer, e.g.
   `git add 'apps/scheduling/models/Bookings/Appointments.py'; git commit -m 'feat(scheduling): 4.2 Appointment model (location-scoped, slot-token booking)'`
   then the same for `forms/`, `views/`, `urls/`, `consumers/`, **and the touched `__init__.py` re-export blocks** —
   plus the edits to `apps/accounts/navigation.py` (the new `LIVE_LINKS["N.M"]` entry) and `README.md` — and, **on a
   brand-new-app run only**, `config/settings.py` + `config/urls.py` (+ `config/asgi.py` for a first websocket
   route). One `git add` + one `git commit` per file — never bundle. Use PowerShell `;`, never `&&`. Commit to
   `main`; do NOT `git push`.
   Note that a single `makemigrations` run can author files in more than one app — `git status` after every run and
   commit each generated migration separately.

---

## Step 5 — Close with the specialist review agents (CLAUDE.md "Module Creation Sequence")
The full sequence is **twelve steps**, run **one at a time, in order**, each ending with `git add` + `git commit`
(one file per commit, PowerShell-safe `;`) and **never** a `git push`:
`research` → `todo` → **write the module code** → `code-reviewer` → `explorer` → `frontend-reviewer` →
`performance-reviewer` → **`realtime-reviewer`** → `qa-smoke-tester` → `security-reviewer` → `test-writer` →
**create or update the module's Claude Code skill**. Steps 1–3 happen before and during the build (Steps 1–4 above);
after the build verifies, run the eight review agents scoped to the sub-module's new files, applying each one's
findings and committing between steps. This is the quality bar, not optional. Then step 12: **create or update the
module's Claude Code skill** (`.claude/skills/<slug>/SKILL.md`) — **author** it only on a brand-new-app run;
otherwise **UPDATE** the existing one with this sub-module's models / routes / templates / seeder rows. Never
re-author an existing skill: a second sub-module run that rewrites the file clobbers the previous sub-module's
documentation. Commit the skill on its own.

---

## Continue / repeat
If the user says "next" again after a sub-module is done, repeat Step 1 — auto-detect now returns **the next
unbuilt sub-module** (the lowest `N.M` without a `LIVE_LINKS["N.M"]` entry in the active module), and you build that
ONE. Keep going **sub-module by sub-module** within a module; only roll over to the next module (building its `N.1`)
once every sub-module of the current one is wired.

## Quality bar
A delivered sub-module must: live in the **backend package layout** (§2a — a `<SubModule>/` folder with one
`<Entity>.py` per model in each of `models/ forms/ views/ urls/` (+ `consumers/`), **plus the re-export block added
to every touched `__init__.py`**, absolute imports throughout, and **no flat `models.py`/`*_advanced.py`** — except
the flat foundation apps `accounts` and `tenants`); migrate cleanly to `navai_receptionist`; seed idempotently;
pass `manage.py check`; have every new list page rendering 200 with working search/filters/pagination + Actions
(or, for a service sub-module, at least one observable diagnostics/settings surface; or, for a **view** sub-module,
its list/detail pages rendering 200 with **no new table**); appear as **Live** in the sidebar via its new
`LIVE_LINKS["N.M"]` entry; honour the three invariants — one contact identity table, one call log, server owns
identity — instead of duplicating contacts or transcripts; run entirely on the fake providers under
`PROVIDER_MODE=fake`; match the blue/white Tailwind design system; and isolate data **per tenant AND per location**
in HTTP, websocket and webhook paths alike. The run builds **exactly one sub-module** — if you find yourself adding
a second sub-module's models, stop. Would a staff engineer approve it? If a piece feels hacky, redo it the elegant
way before presenting.
