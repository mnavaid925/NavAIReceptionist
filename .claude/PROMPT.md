# NavAIReceptionist — Build Prompt

## Goal

1. Build **NavAIReceptionist**, a multi-tenant **AI voice agent** SaaS for **inbound** phone calls. A business (tenant) adds **multiple locations**; each location has its own Twilio number and its own agent configuration. The agent answers the call, books appointments into that location's calendar, transfers to a human when asked, and logs the call in detail. Django + **Django Channels/ASGI** (the Twilio media stream) + Tailwind CSS + HTMX. **All-Django, one codebase, no separate microservice.**
2. Create a clean, intuitive, fully responsive, unique dashboard design with a **blue and white** theme.
3. Multi-tenant **and multi-location** (`tenant=request.tenant` on every query; `location=request.location` on every location-scoped query).
4. Create login (email-or-username + customer id + password), forgot/reset password, change password and change email pages.
5. Create user management, user profile, roles, and the **active-location switcher** (Module 0).
6. Proper migrations for all tables.
7. Seed fake/demo data via idempotent seeders — at least two locations per demo tenant.
8. Create a `.env` file for the MySQL (XAMPP) database connection — DB name **`navai_receptionist`**.
9. Serve over ASGI (Daphne/Uvicorn) — `daphne -b 127.0.0.1 -p 8000 config.asgi:application`. The Twilio media stream and the live-call UI run on Django Channels websocket consumers; never use `manage.py runserver` for anything touching websockets.
10. Abstract every external provider (telephony, STT, TTS, LLM) behind an adapter in `apps/runtime/providers/` — **Module 3 owns the adapter interfaces, the fakes, `PROVIDER_MODE` resolution and the realtime orchestration that calls them.** `PROVIDER_MODE` ∈ `fake | sandbox | live`, and **`fake` is the default** for dev, tests and seeders. When the mode is not `live`, adapters resolve to the fake/sandbox implementation and must never reach a real provider — no real call, no billable API call. The **live** adapter refuses to initialize unless `PROVIDER_MODE == 'live'`, and live mode additionally requires real credentials to be present — missing credentials in live mode is the hard failure.
11. **Twilio credentials are per-location, in the database** (`agents.AgentSetting.twilio_account_sid` / `twilio_auth_token`, encrypted at rest, write-only in forms) — **not** in `.env`. `.env` keeps only platform defaults: the webhook base URL (`TWILIO_WEBHOOK_BASE_URL`), LLM/STT/TTS keys and `PROVIDER_MODE`. Document every key with a dummy value in a committed `.env.example` (the real `.env` stays gitignored).
12. Always keep `README.md` up to date.
13. **`NavAIReceptionist.md`** is the master module catalog (modules 0–5) for planning; **`NavAIReceptionist-ERD.md`** is the data model (11 models).
14. The sidebar menu mirrors the `NavAIReceptionist.md` modules and sub-modules; the design follows the attached reference image.

## Architecture (read `NavAIReceptionist-ERD.md` first)

- **Eleven models, no duplication.** Callers, bookers and attendees are one `scheduling.Contact`. A call is exactly **one** `calls.CallSession` row whose transcript, event log, per-turn usage, analysis, waveform and transfer outcome are **JSON columns on that row** — not three normalized tables. A location's agent config, Twilio credentials and transfer settings all live in one `agents.AgentSetting` row, unique per `(tenant, location)`; its `inbound_phone_number` is globally unique because that is how an inbound webhook resolves tenant + location. `accounts.UserLocation` decides which locations a user may switch into, and exactly one is active per session.
- **Modules 0 and 1 are the foundation — build them first:** `accounts` (User/UserLocation, roles, email-or-username auth, profile, password/email change, the location switcher — **`AUTH_USER_MODEL = 'accounts.User'` MUST be declared in `config/settings.py` before the very first `makemigrations`**; every FK to the user model uses `settings.AUTH_USER_MODEL` and `migrations.swappable_dependency(settings.AUTH_USER_MODEL)`, **never** `from apps.accounts.models import User` — that is an import cycle, because `accounts.User` FKs `tenants.Tenant`. Django bakes the user model into every migration that references it, so getting this wrong later requires a **destructive migration reset** — it must be right on day one) and `tenants` (Tenant, Location, TenantMiddleware + LocationMiddleware, navigation (`parse_catalog()` building the module 0–5 catalog from `NavAIReceptionist.md`, plus `MODULE_ICONS` and `LIVE_LINKS` keyed `"N.M"`), staff↔location assignment, provider working hours). Modules 2–5 are domain apps built on top via the `/next-module` skill.

## Realtime Constraints

- **First audio is deterministic** — the greeting is rendered server-side from `AgentSetting.greeting` and costs **0 LLM tokens**; nothing about the opener waits on a model.
- **Turn latency budget** — ≤1.5 s p50 and ≤3 s p95 from end-of-user-speech to first agent audio; count the serial hops (STT → LLM → tool → LLM → TTS) and add none without justification.
- **Tool-iteration cap 4** per turn, with a spoken fallback when the cap is hit — a looping model must never produce dead air.
- **No-audio idle timeout 45 s**; **hard max call duration** configurable, default 15 minutes.
- **Audio chain** — μ-law 8 kHz on the Twilio leg ⇄ PCM 16 kHz in / 24 kHz out on the model leg; **barge-in flushes the outbound audio buffer immediately**.
- **Recording consent basis is recorded per recording**, announced before recording where the location's jurisdiction requires two-party consent, and expired by a retention job.
- **Transport-mutating tools** (transfer, hang-up) set a deferred signal on session state; the transport acts only after the turn's audio completes.
- **Tenant AND location are resolved from the dialed number** (`AgentSetting.inbound_phone_number`), never from a websocket URL or body parameter; the Twilio signature is verified with that row's own credentials before any side effect.

## Dashboard Requirements

Layout Features:

-  Clean, Intuitive and Fully Responsive Unique Design
-    Vertical, Horizontal & Detached
-    Light & Dark Modes
-    Fluid & Boxed Width
-    Fixed & Scrollable Positions
-    Light & Dark Topbars
-    Default, Compact, Small Icon & Icon Hovered Sidebars
-    Light & Colored Sidebars
-    LTR & RTL supported
-    Preloader option

Browser Compatibility:

-    Chrome (Windows, Mac, Linux)
-    Firefox (Windows, Mac, Linux)
-    Safari (Mac)
-    Microsoft Edge
-    And other WebKit browsers

## Design Reference (the attached image)

The UI mirrors the **"Tailwick"** admin theme in the reference image — clean, airy, blue-and-white — re-branded to **NavAIReceptionist**. Build the design system in `static/css/theme.css` to match:

- **Palette:** primary accent medium blue (~Tailwind `blue-500/600`); white cards on a very light gray page (`~#f6f7f9`); muted gray secondary text; soft `rounded-xl` corners, hairline borders + subtle shadows; roomy padding. Status colors: green = active/ok, red = inactive/critical, amber = warning, blue = info.
- **Left sidebar (~250px, fixed, collapsible):** white; brand logo + "NavAIReceptionist" wordmark on top; grouped nav with small uppercase section labels. Active item = light-blue pill with blue icon/text; Lucide line icons. The sidebar mirrors the **NavAIReceptionist module catalog** (Dashboard + Modules 0–5 and their sub-modules from `NavAIReceptionist.md`) — NOT the Tailwick demo apps. Support the layout variants in §Dashboard Requirements (default / compact / small-icon / icon-hovered; light/colored; vertical/horizontal/detached).
- **Topbar:** sidebar-collapse toggle, large search ("Search… ⌘K"), the **active-location switcher** (current location name + a dropdown of the user's assigned locations only), a **live-call count chip** (pulsing dot + N calls in progress), language/flag, dark-mode toggle, notifications bell (with dot), settings, user avatar.
- **Page header:** page title (left) + breadcrumb (right, e.g. `NavAIReceptionist › Calls › Call Log`).
- **Content blocks (provide as reusable components):**
  - **Stat cards** — soft-tinted icon tile (green/amber/blue) + big metric + label + faint sparkline.
  - **Calendar** — day and week grids, columned by resource and by provider, with drag-free click-to-create; appointment blocks carry the status badge colour.
  - **Booking form** — contact lookup/create, service, provider, resource, start time from the availability slots, plus reschedule and cancel actions with a reason.
  - **Agent setup form** — enable toggle, voice, greeting, prompt textarea with a `{{variable}}` helper, the Twilio connection panel (account sid, **write-only** auth token, inbound number) and the transfer panel (enable, numbers, timezone, working hours grid, keywords), with a **test call** button.
  - **Data table** — card with title + search + Export button; sortable columns; row checkbox; **status pill badges** (green "Completed" / blue "In Progress" / muted "Abandoned" with a leading dot); footer "Showing X of Y" + numbered pagination (active page = blue).
  - **List widgets** — icon + label + value + colored % delta rows (e.g. call outcomes, booking sources).
  - **Live-call monitor** — a card listing calls in progress with a pulsing status dot, caller, location, elapsed timer and a listen control, driven by a websocket consumer (not an unbounded poll).
  - **Transcript turn list** — alternating caller/agent turns with speaker label, timestamp and a visually distinct style for partial/interim turns; scrolls inside its own container.
  - **Event log** — the call's `logs` JSON rendered as level/category/title rows with an expandable raw-JSON payload.
  - **Cost breakdown** — the call's per-turn `usage` JSON as a small table with a total.
  - **Audio player** — a plain `<audio controls>` partial against a short-lived signed URL, showing the recording's retention date and consent basis.
  - **Waveform** — a lightweight amplitude strip used under the live monitor and the recording player.
- **Footer:** `© <year> NavAIReceptionist` left; build credit right.
- **theme.css component classes** to expose (so every module + the frontend-reviewer agent stay consistent): `.page-header/.page-title/.breadcrumb`, `.card/.card-header/.card-body`, `.stat-card`, `.btn/.btn-primary/.btn-outline/.btn-danger/.btn-icon`, `.badge` (+ green/red/amber/info/muted/slate variants), `.table-wrap/.table/.table-actions`, `.form-group/.form-label/.form-input/.form-select/.form-textarea/.form-error`, `.empty-state`, `.pagination`, `.avatar-initial`, `.progress/.progress-bar`, `.call-status-dot`, `.transcript-turn` (+ `.transcript-turn.agent`/`.transcript-turn.user`), `.waveform`, `.live-badge`, `.calendar-grid/.calendar-slot/.appointment-block`, `.location-switcher`.

## NavAIReceptionist module catalog (see `NavAIReceptionist.md` for full sub-modules)

The first module to implement is **Module 0 — Accounts & Access** (the foundation above). Its 0.1 sub-module:

## 0. Accounts & Access

### 0.1 Authentication & Session
- **Login** — Email-or-username + password, with the tenant resolved by `customer_id`, so the same address can exist in more than one business.
- **Password Reset** — Forgot-password request and tokenised reset, rate-limited, with no account-existence disclosure.
- **Change Password** — Post-login change requiring the current password, invalidating other sessions.
- **Change Email** — Post-login email change confirmed by a link sent to the new address before it takes effect.
- **Active-Location Switcher** — Sets the session's active location from the user's `UserLocation` rows and re-validates it on every request, so a user can never reach a location they are not assigned to.
- **Session Policy** — Applies the user's `inactivity_timeout`, logging out idle sessions.

After Module 0, build modules 1–5 (Business & Locations, Agent Setup & Telephony, Call Runtime, Calendar & Bookings, Call Logs) one at a time with the `/next-module` skill — each as a Django app under `apps/<slug>`. Module 1 completes the foundation. **Module 3 is a service module** — consumers, Twilio webhooks, provider adapters and a diagnostics page; it ships no CRUD.
