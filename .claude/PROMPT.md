# NavAIReceptionist — Build Prompt

## Goal

1. Build **NavAIReceptionist**, a multi-tenant **AI voice agent** SaaS for inbound and outbound phone calls (24/7 answering, new-lead follow-up, prospect qualification, SMS, automated appointment booking) — Django + **Django Channels/ASGI** (realtime telephony media streams) + Tailwind CSS + HTMX. **All-Django, one codebase, no separate microservice.**
2. Create a clean, intuitive, fully responsive, unique dashboard design with a **blue and white** theme.
3. Multi-tenant application (tenant-scoped data; `tenant=request.tenant` on every query).
4. Create login, registration, and forgot-password pages.
5. Create user management, user invite, and user profile (IAM/RBAC — Module 0).
6. Proper migrations for all tables.
7. Seed fake/demo data via idempotent seeders.
8. Create a `.env` file for the MySQL (XAMPP) database connection — DB name **`navai_receptionist`**.
9. Serve over ASGI (Daphne/Uvicorn) — `daphne -b 127.0.0.1 -p 8000 config.asgi:application`. Realtime telephony media and the live-call UI run on Django Channels websocket consumers; never use `manage.py runserver` for anything touching websockets.
10. Abstract every external provider (telephony, STT, TTS, LLM) behind an adapter in `apps/core/providers/` — **Module 0 owns the adapter interfaces, the fakes and `PROVIDER_MODE` resolution; Module 4 owns the realtime orchestration that calls them.** `PROVIDER_MODE` ∈ `fake | sandbox | live`, and **`fake` is the default** for dev, tests and seeders. When the mode is not `live`, adapters resolve to the fake/sandbox implementation and must never reach a real provider — no real call placed, no real SMS sent, no billable API call. The **live** adapter refuses to initialize unless `PROVIDER_MODE == 'live'`, and live mode additionally requires real credentials to be present — missing credentials in live mode is the hard failure.
11. Extend `.env` with provider credentials and the webhook base URL (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WEBHOOK_BASE_URL`, LLM/STT/TTS keys, `PROVIDER_MODE`), and document every key with a dummy value in a committed `.env.example` (the real `.env` stays gitignored).
12. Always keep `README.md` up to date.
13. **`NavAIReceptionist.md`** is the master module catalog (modules 0–13) for planning; **`NavAIReceptionist-ERD.md`** is the unified core data model (the `Contact` + two-ledger spine every module reuses).
14. The sidebar menu mirrors the `NavAIReceptionist.md` modules and sub-modules; the design follows the attached reference image.

## Architecture (read `NavAIReceptionist-ERD.md` first)

- **Unified core, no duplication.** Leads/prospects/customers/callers/attendees/staff are `ContactRole`s on a single `Contact`; a reachable phone or email endpoint is a `ContactChannel`, and a provisioned DID is a `PhoneNumber`. Services/resources/locations/business hours/currencies/voices/rate cards are shared masters. Every call, SMS and email is one `Interaction` with append-only `InteractionEvent` rows (transcript turns, tool calls, provider events — one log, not three); every billable unit is an append-only `UsageEvent`. Call minutes, spend, credit balances, answer rates and agent utilization are **derived**, never stored editable. An `AgentVersion` is immutable once published — you publish a new one — so every call is traceable to the exact prompt that ran it. Every outbound call, SMS or voicemail drop passes through the single gate `apps/core/compliance.check_outbound_allowed(contact, channel, now)` — there is no second DNC list.
- **Module 0 — System Admin & Security** is the cross-cutting foundation: build it first as the apps `core` (Tenant, TenantMiddleware, navigation (`parse_catalog()` building the module 0–13 catalog from `NavAIReceptionist.md`, plus `MODULE_ICONS` and `LIVE_LINKS` keyed `"N.M"`), AuditLog, decorators, the unified-core masters + the interaction and usage ledgers, the ASGI/Channels routing and consumer base, the provider adapters, and the telephony webhook ingress), `accounts` (User/Role/Permission/UserInvite + email-or-username auth + IAM/RBAC — **`AUTH_USER_MODEL = 'accounts.User'` MUST be declared in `config/settings.py` before the very first `makemigrations`**; every spine FK to the user model (`core.AuditLog.actor`, `core.Contact.owner`, `core.AgentVersion.published_by`, `core.CallbackRequest.assigned_to`) uses `settings.AUTH_USER_MODEL` and `migrations.swappable_dependency(settings.AUTH_USER_MODEL)`, **never** `from apps.accounts.models import User` — that is an import cycle, because `accounts.User` FKs `core.Tenant` while `core` FKs the user model back. Django bakes the user model into every migration that references it, so getting this wrong later requires a **destructive migration reset** (drop the database, delete and regenerate every migration) — it must be right on day one), `tenants` (subscription/plans/billing/branding/encryption keys/health), and `dashboard` (KPI aggregation). Modules 1–13 are domain apps built on top via the `/next-module` skill.

## Realtime & Compliance Constraints

- **First audio is deterministic** — the greeting is rendered server-side from the published `AgentVersion` and costs **0 LLM tokens**; nothing about the opener waits on a model.
- **Turn latency budget** — ≤1.5 s p50 and ≤3 s p95 from end-of-user-speech to first agent audio; count the serial hops (STT → LLM → tool → LLM → TTS) and add none without justification.
- **Tool-iteration cap 4** per turn, with a spoken fallback when the cap is hit — a looping model must never produce dead air.
- **No-audio idle timeout 45 s**; **hard max call duration** tenant-configurable, default 15 minutes; per-tenant spend caps and concurrency ceilings are enforced at call-accept time.
- **Audio chain** — μ-law 8 kHz on the carrier leg ⇄ PCM 16 kHz in / 24 kHz out on the model leg; **barge-in flushes the outbound audio buffer immediately**.
- **Recording consent basis is recorded per recording**, announced before recording where the tenant's jurisdiction requires two-party consent, and expired by a retention job.
- **Outbound quiet hours are evaluated in the contact's timezone**, alongside consent, suppression and A2P/10DLC registration state — all through the single compliance gate.
- **Transport-mutating tools** (transfer, hang-up) set a deferred signal on session state; the transport acts only after the turn's audio completes.

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

- **Palette:** primary accent medium blue (~Tailwind `blue-500/600`); white cards on a very light gray page (`~#f6f7f9`); muted gray secondary text; soft `rounded-xl` corners, hairline borders + subtle shadows; roomy padding. Status colors: green = active/ok, red = inactive/critical, amber = warning, purple/indigo = info.
- **Left sidebar (~250px, fixed, collapsible):** white; brand logo + "NavAIReceptionist" wordmark on top; grouped nav with small uppercase section labels. Active item = light-blue pill with blue icon/text; Lucide line icons. The sidebar mirrors the **NavAIReceptionist module catalog** (Dashboard + Modules 0–13 and their sub-modules from `NavAIReceptionist.md`) — NOT the Tailwick demo apps. Support the layout variants in §Dashboard Requirements (default / compact / small-icon / icon-hovered; light/colored; vertical/horizontal/detached).
- **Topbar:** sidebar-collapse toggle, large search ("Search… ⌘K"), a **live-call count chip** (pulsing dot + N calls in progress), a **minutes-remaining / credit chip**, language/flag, dark-mode toggle, notifications bell (with dot), settings, user avatar.
- **Page header:** page title (left) + breadcrumb (right, e.g. `NavAIReceptionist › Calls › Call Log`).
- **Content blocks (provide as reusable components):**
  - **Stat cards** — soft-tinted icon tile (green/orange/purple/blue) + big metric + label + faint sparkline.
  - **Charts (Chart.js):** treemap-style category tiles, smooth line/area, vertical bars with value labels, radar, half-doughnut gauge with center %, floating-bar/"candlestick" comparison, dual-line trend, donut distribution with legend, and horizontal progress bars.
  - **Data table** — card with title + search + Export button; sortable columns; row checkbox; **status pill badges** (green "Completed" / red "Missed" / blue "In Progress" with a leading dot); footer "Showing X of Y" + numbered pagination (active page = blue).
  - **List widgets** — icon + label + value + colored % delta rows (e.g. call outcomes, top intents, agent utilization).
  - **Live-call monitor** — a card listing calls in progress with a pulsing status dot, caller, agent, elapsed timer and a listen/barge control, driven by a websocket consumer (not an unbounded poll).
  - **Transcript turn list** — alternating caller/agent turns with speaker label, timestamp and a visually distinct style for partial/interim turns; scrolls inside its own container.
  - **Audio player** — a plain `<audio controls>` partial against a short-lived signed URL, showing the recording's retention date and consent basis.
  - **Waveform** — a lightweight amplitude strip used under the live monitor and the recording player.
- **Footer:** `© <year> NavAIReceptionist` left; build credit right.
- **theme.css component classes** to expose (so every module + the frontend-reviewer agent stay consistent): `.page-header/.page-title/.breadcrumb`, `.card/.card-header/.card-body`, `.stat-card`, `.btn/.btn-primary/.btn-outline/.btn-danger/.btn-icon`, `.badge` (+ green/red/amber/muted/slate variants), `.table-wrap/.table/.table-actions`, `.form-group/.form-label/.form-input/.form-select/.form-textarea/.form-error`, `.empty-state`, `.pagination`, `.avatar-initial`, `.progress/.progress-bar`, `.call-status-dot`, `.transcript-turn` (+ `.transcript-turn.agent`/`.transcript-turn.user`), `.waveform`, `.live-badge`.

## NavAIReceptionist module catalog (see `NavAIReceptionist.md` for full sub-modules)

The first module to implement is **Module 0 — System Admin & Security** (the foundation above). Its 0.1 sub-module:

## 0. System Admin & Security

### 0.1 Tenant & Workspace Management
- **Tenant Provisioning** — Creates an isolated tenant with slug, timezone, locale and default admin, seeding baseline config so the workspace is usable immediately.
- **Business & Location Records** — Stores legal/trading name, industry, address, service area and timezone, with per-location overrides for multi-site and franchise tenants.
- **Agency & Sub-Account Hierarchy** — Lets an agency workspace own many client tenants with strict data isolation and cross-tenant roll-up reporting.
- **White-Label Branding** — Applies per-tenant logo, colours, sender names and custom domain so the dashboard and notifications carry the agency's brand.
- **Tenant Lifecycle States** — Moves a tenant through trial, active, past-due, suspended and closed, with defined behaviour for live calls in each state.
- **Data Residency & Isolation Policy** — Records the tenant's storage region and enforces tenant-FK scoping as a queryset-level default across every app.

After Module 0, build modules 1–13 (Telephony & Number Management, Voice Agent Studio, Knowledge Base & Business Facts, Realtime Conversation Runtime, Inbound Call Handling & Routing, Compliance/Consent & Trust, Contacts/Leads & Qualification, Outbound Calling & Campaigns, Messaging & Missed-Opportunity Recovery, Appointments & Scheduling, Call Records/Transcripts & Post-Call Intelligence, Testing/QA & Analytics, Integrations/API & Onboarding) one at a time with the `/next-module` skill — each as a Django app under `apps/<slug>` reusing the unified core. Compliance ships at Module 6, ahead of outbound and messaging, because A2P 10DLC registration, TCPA consent and recording consent are hard gates those modules cannot legally clear without.
