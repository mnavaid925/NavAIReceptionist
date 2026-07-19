# NavAIReceptionist — Module Catalog

NavAIReceptionist is a multi-tenant AI voice receptionist. A business signs in, adds its **locations**, and configures a **Twilio number and an AI voice agent per location**. The agent answers inbound calls, books appointments into the location's calendar, transfers the caller to a human when asked, and writes a detailed call log.

**Stack.** All-Django: Django 4.2 LTS + Channels/ASGI for the realtime Twilio media-stream websocket, Tailwind + HTMX + Lucide for the UI, MySQL for storage, `AUTH_USER_MODEL = accounts.User`. There is no separate microservice. Each module is a Django app under `apps/<slug>`, and anything touching websockets is served over ASGI (`daphne … config.asgi:application`), never `manage.py runserver`.

**Multi-tenant means multi-location.** A tenant is the business; a `Location` is a site. Twilio credentials, the inbound number, the agent prompt, resources, appointments and call logs are all **per location**. Every queryset carries `tenant=request.tenant`, and location-scoped models additionally carry `location=request.location` — reaching another location's data is a bug, not a feature.

**How to use this catalog.** It is the master build sequence and the scope authority. Modules are numbered `N`, sub-modules `N.M`; the build runs **one sub-module at a time** through the mandated `research → todo → code → review-agents → skill` sequence, each step ending in its own commit. **Modules 0 and 1 are the foundation and are built first** — accounts, tenants and locations are what every later module scopes against. The data model's intended shape is written out in `NavAIReceptionist-ERD.md`; read it before adding any model or foreign key.

## Module Index

| # | Module | App slug | Owns | Reads |
|---|---|---|---|---|
| 0 | Accounts & Access | `accounts` | `User`, `UserLocation` — login, logout, password reset, password and email change, user profile, tier-based access, the active-location switcher. | `Tenant`, `Location` |
| 1 | Business & Locations | `tenants` | `Tenant`, `Location` — business settings, location records, staff↔location assignment, per-location provider working hours. | `User`, `UserLocation` |
| 2 | Agent Setup & Telephony | `agents` | `AgentSetting` — per-location agent config, Twilio credentials and inbound number, transfer settings, test call. | `Tenant`, `Location`, `User` |
| 3 | Call Runtime | `runtime` | No tables. The Twilio webhooks, signature verification, the media-stream consumer, the turn loop, the LLM tool dispatcher, transfer execution and recording capture. Writes `CallSession`, `Appointment`, `Contact`, `CallbackRequest`; owns none of them. | `AgentSetting`, `Location`, `Service`, `Resource`, `User` |
| 4 | Calendar & Bookings | `scheduling` | `Contact`, `Service`, `Resource`, `Appointment`, `CallbackRequest` — availability search, calendar views, booking CRUD. | `Location`, `User`, `CallSession` |
| 5 | Call Logs | `calls` | `CallSession` — the call list and detail page, transcript, event log, cost breakdown, recording playback, transfer outcome. | `Location`, `Contact`, `Appointment` |

---

## 0. Accounts & Access

### 0.1 Authentication & Session
- **Customer-Scoped Login** — Signs a user in with customer id plus email-or-username and password, resolving the tenant from the customer id before authenticating.
- **Logout & Session Expiry** — Ends the session on logout and after the user's configured inactivity timeout, clearing the active location with it.
- **Forgot & Reset Password** — Issues a single-use, short-TTL reset link by email and invalidates it once used or expired.
- **Failed-Attempt Throttling** — Rate-limits repeated failed logins per account and per IP without revealing whether the account exists.

### 0.2 Credential Management
- **Change Password** — Requires the current password, enforces Django's validators, and re-authenticates the session so the user is not logged out.
- **Change Email** — Confirms the new address by emailed token before it replaces the old one, keeping `(tenant, email)` unique.
- **Credential Change Notice** — Emails the previous address whenever the password or email changes, as the account-takeover tripwire.

### 0.3 User Profile & Directory
- **Own Profile** — Edits first name, last name, full name and primary phone for the signed-in user.
- **User List & Detail** — Lists tenant users with search and filters on tier and status, linking through to a read-only detail page.
- **User Create & Edit** — Creates and edits users with tier (`owner`, `manager`, `staff`), status and the `is_provider` flag that makes them bookable.
- **Deactivation Instead of Deletion** — Sets status to `inactive` rather than deleting, so historical appointments keep a valid provider reference.

### 0.4 Active Location Switcher
- **Assigned-Location List** — Reads the user's `UserLocation` rows to build the set of locations the user may work in.
- **Session Active Location** — Holds exactly one active location per session and exposes it to every view as `request.location`.
- **Assignment Validation** — Rejects any switch to a location the user has no `UserLocation` row for, since the switcher is the boundary a cross-location IDOR would cross.
- **Location Context Header** — Shows the active location in the shell and forces a choice when the user's first assignment loads.

---

## 1. Business & Locations

### 1.1 Business Settings
- **Business Record** — Stores the tenant's name, slug, customer id and default timezone as the single business record.
- **Business Profile Editing** — Lets an owner edit the business details that appear in agent prompts and confirmations.
- **Tenant Activation State** — Marks a tenant active or inactive, with inactive tenants blocked at login rather than mid-call.

### 1.2 Location Directory
- **Location List** — Lists the business's locations with search and an active/inactive filter.
- **Location Create & Edit** — Captures name, slug, full address, country, timezone and a public phone number, unique on `(tenant, slug)`.
- **Location Detail** — Shows one location's address, timezone, assigned staff and linked agent setting in one view.
- **Location Deactivation** — Deactivates a location instead of deleting it, so its past appointments and call logs stay readable.

### 1.3 Staff & Location Assignment
- **Assignment Matrix** — Assigns users to locations as `UserLocation` rows from either the user or the location side.
- **Provider Marking** — Flags a user as a provider so they appear as a bookable target at the locations they are assigned to.
- **Unassignment Guard** — Warns before removing an assignment that would leave a user with no location or orphan a future appointment.

### 1.4 Provider Working Hours
- **Per-Location Hours** — Stores each provider's weekly working hours keyed by location id, because the same person can work different days at different sites.
- **Day & Interval Editor** — Edits start time, end time and weekdays per interval, validating that intervals do not overlap.
- **Availability Source of Truth** — Feeds these hours into availability search, so a slot is never offered outside a provider's configured window.
- **Timezone Resolution** — Interprets every interval in the location's timezone, never the browser's or the business default.

---

## 2. Agent Setup & Telephony

### 2.1 Per-Location Agent Configuration
- **One Setting per Location** — Keeps exactly one `AgentSetting` row per `(tenant, location)`, so a location's agent is unambiguous.
- **Enable Toggle & Voice Mode** — Enables the agent for the location and selects the voice provider mode (`live`, `google`, `gemini`).
- **Deterministic Greeting** — Stores the opening line the agent speaks with no LLM round trip, so the first audio lands immediately.
- **Prompt Authoring** — Edits the system prompt for this location, with a rendered preview before saving.
- **Prompt Variables** — Defines a `{{variable}}` map merged with server-computed values at call setup, rejecting unknown placeholders at save time.

### 2.2 Twilio Connection
- **Per-Location Credentials** — Stores the location's own Twilio account SID and auth token, since each site may run its own Twilio subaccount.
- **Write-Only Auth Token** — Accepts the auth token as a write-only field, encrypted at rest, and never renders, logs or returns it in a message.
- **Inbound Number Binding** — Binds one E.164 inbound number to the location, globally unique across all tenants because it is what resolves an inbound webhook.
- **Webhook URL Display** — Shows the exact voice-webhook and media-stream URLs to paste into the Twilio console for this number.
- **Connection Check** — Verifies the credentials and number ownership against Twilio and reports the result without placing a call.

### 2.3 Transfer Settings
- **Transfer Enable & Targets** — Enables human transfer for the location and stores a primary and secondary destination number.
- **Transfer Working Hours** — Defines per-weekday transfer windows in a configurable timezone, so the agent only offers a human when one is there.
- **Transfer Keywords** — Lists the phrases that make the agent offer a handoff, replacing hardcoded escalation logic.
- **Off-Hours Behaviour** — Defines what the agent says and does when a caller asks for a human outside the transfer window.

### 2.4 Test Call
- **Placed Test Call** — Places a call from the configured number to a verified destination so the tenant hears the agent before going live.
- **Fake-Mode Test** — Runs the whole test path against the fake provider when `PROVIDER_MODE` is not `live`, never touching Twilio.
- **Setup Readiness Check** — Flags a missing greeting, prompt, inbound number or transfer target before the tenant tries a real call.

---

## 3. Call Runtime

Module 3 is a **service module**: consumers, webhook handlers, provider adapters and a diagnostics page. It ships **no CRUD** — no list, detail or form pages, and no tables of its own. It writes rows that modules 4 and 5 own.

### 3.1 Inbound Webhook & Call Resolution
- **Twilio Voice Webhook** — Answers Twilio's inbound request and returns the media-stream connect instruction with the per-call parameters.
- **Signature Verification** — Validates `X-Twilio-Signature` against the raw body and exact public URL using the resolving location's own auth token, before any side effect.
- **Dialed-Number Resolution** — Resolves tenant and location from the dialed number via `AgentSetting.inbound_phone_number`, never from a query-string or body parameter.
- **Idempotent Handling** — Keys on the provider call SID so a redelivered webhook cannot create a second session or double-book an appointment.
- **Unmapped-Number Handling** — Plays a defined out-of-service message and hangs up cleanly rather than dropping the caller into silence.

### 3.2 Media Stream & Turn Loop
- **ASGI Media Consumer** — Terminates Twilio's bidirectional media websocket in a Channels consumer holding all per-call state, authorised in `connect()`.
- **Audio Codec Chain** — Transcodes μ-law 8 kHz to PCM and back with persistent resampler state, so no artefact appears at frame boundaries.
- **VAD & Barge-In** — Detects utterance boundaries by energy threshold and interrupts agent playback only after sustained caller speech.
- **Off-Loop Work** — Runs every ORM call, SDK call and file write off the event loop, because a blocking call freezes audio for every concurrent call on the worker.
- **Bounded Provider Calls** — Applies an explicit timeout and bounded retry to every STT, TTS and LLM call, degrading to a spoken fallback rather than dead air.

### 3.3 Tools & Dispatcher
- **Transport-Agnostic Dispatcher** — Applies every tool through a single `apply_tool_call(state, name, args)` so behaviour cannot drift between paths.
- **Server-Side Identity Injection** — Injects `tenant_id`, `location_id`, `contact_id` and `session_id` from server-held session state; they are never tool parameters.
- **Built-In Tool Set** — Ships identify contact, create contact, get business info, get availability, book, reschedule, cancel, callback request, transfer and end call.
- **Opaque Signed Slot Tokens** — Returns one signed short-TTL `slot_token` per offered slot, so a slot cannot be mangled, invented or replayed from another session.
- **Standard Result Envelope** — Returns every tool result as `{"ok": bool, "data": {...}, "error": {"code": "...", "message": "..."} | null}`, with `code` always lower_snake_case.
- **Per-Turn Iteration Cap** — Caps tool calls per turn and always emits a spoken fallback, so a looping model never produces silence.

### 3.4 Transfer Execution
- **Deferred Transfer Signal** — Sets a pending-transfer flag the transport executes only after the acknowledgement audio has fully played.
- **Hours & Target Gating** — Checks the location's transfer window and target numbers before promising a handoff, falling back to a callback request when closed.
- **Single-Fire Guard** — Marks the transfer initiated before any await, so concurrent turns cannot double-execute the bridge.
- **Outcome Capture** — Records reason, destination and result — connected, no-answer, off-hours or failed — onto the session's transfer JSON.

### 3.5 Recording, Teardown & Diagnostics
- **Consent-Gated Recording** — Starts the recorder only once the location's consent basis is satisfied, storing the announcement that was played.
- **Guaranteed Teardown** — Finalises the recording, flushes the transcript and closes the session even on abnormal termination.
- **Waveform & Cost Capture** — Writes caller/agent waveform peaks and the per-turn cost breakdown onto the session as the call proceeds.
- **Runtime Diagnostics Page** — Shows active sessions, per-stage latency, ended-reason codes and recent runtime errors for the active location.
- **Fake Provider Path** — Runs the entire call path against fake telephony, STT, TTS and LLM adapters under `PROVIDER_MODE=fake`, so no dev or seed run ever places a real call.

---

## 4. Calendar & Bookings

### 4.1 Contact Directory
- **Phone-Keyed Contacts** — Creates a contact on first contact keyed on a normalised E.164 number, deduplicating repeat callers.
- **Contact List & Search** — Lists contacts with search across name, phone and email, filtered by source.
- **Contact Create, Edit & Detail** — Manages first name, last name, phone, email, date of birth and notes, with the contact's appointment history on the detail page.
- **Business-Wide Identity** — Keeps contacts tenant-scoped but not location-scoped, since one caller may book at any of the business's sites.

### 4.2 Services & Resources
- **Service Catalogue** — Defines bookable services with duration, buffer and display order, optionally scoped to a single location.
- **Resource Records** — Defines the bookable rooms, chairs or bays at a location with a number, description and ordering, unique on `(location, name)`.
- **Active-Only Offering** — Excludes inactive services and resources from availability search without removing them from history.

### 4.3 Availability & Booking
- **Availability Search** — Finds open slots from provider working hours, resource capacity, service duration and existing appointments within a date range.
- **Server-Capped Slot Set** — Returns a small pre-ranked set of slots so the agent offers a manageable choice, enforced server-side.
- **Booking with Slot Locking** — Books against a slot token and locks the slot between offer and write, so two concurrent calls cannot double-book it.
- **Reschedule & Cancel** — Moves or cancels an appointment with a reason and timestamp, authorised against tenant, location and the identified contact.
- **Booking Provenance** — Links each appointment to its source and, for AI bookings, to the `CallSession` that created it.

### 4.4 Calendar Views
- **Day & Week Grid** — Renders the active location's appointments as a day or week grid in the location's timezone.
- **By Resource and By Provider** — Switches the grid's columns between resources and providers without changing the underlying query.
- **Slot Click-Through** — Opens the appointment form pre-filled from the clicked time, resource and provider.
- **Status Colouring** — Colours each block by status — scheduled, confirmed, completed, cancelled, no-show — using the shared badge contract.

### 4.5 Bookings List & Callback Requests
- **Booking List** — Lists appointments with filters on date range, status, provider, resource and service, plus search by contact.
- **Appointment Detail** — Shows one appointment with its contact, service, resource, provider, notes and originating call.
- **Callback Request Queue** — Records callers the agent could not fully serve, with name, phone, reason and a `pending`/`contacted`/`closed` status.
- **Callback Resolution** — Works a callback to closed with notes, so an unhandled request is visible rather than lost.

---

## 5. Call Logs

### 5.1 Call Log List
- **Session List** — Lists `CallSession` rows for the active location, newest first, with duration, from/to numbers, contact and status.
- **Filters** — Filters by date range, status, mode and outcome, and searches by caller number or contact name.
- **Status Badges** — Renders `in_progress`, `completed`, `abandoned`, `transferred` and `failed` through the shared badge map.
- **Contact & Booking Links** — Links each row to the contact it identified and to any appointment it created.

### 5.2 Call Detail & Transcript
- **Session Header** — Shows numbers, contact, location, mode, status, start and end times and total duration in one header.
- **Speaker-Attributed Transcript** — Renders the session's transcript JSON as timestamped, speaker-labelled turns, with no separate transcript table.
- **Analysis Panel** — Displays the stored summary, success evaluation and extracted data, rendered defensively since an abandoned call has none.
- **Transcript Print View** — Provides a clean printable transcript for records and disputes.

### 5.3 Event Log & Cost
- **Structured Event Log** — Renders the session's log JSON as levelled, categorised entries with their raw payload expandable inline.
- **Tool-Call Trace** — Surfaces tool invocations in that same event stream with arguments, result and duration, with sensitive argument values redacted.
- **Per-Turn Cost Breakdown** — Shows the stored per-turn cost lines and their total, so a slow or expensive call can be traced to its turn.
- **Runtime Error Surface** — Shows call-level runtime errors on the detail page rather than only in the server log.

### 5.4 Recording & Transfer Outcome
- **Waveform Player** — Plays the stored recording with a caller/agent waveform synced to the transcript position.
- **Signed Media Access** — Serves recordings through short-lived signed URLs, never a public or guessable path.
- **Transfer Outcome Panel** — Shows the transfer reason, destination, timing and result for any call that attempted a handoff.
- **PII Handling** — Treats transcripts, recordings and caller numbers as PII, never logging their contents at INFO.
