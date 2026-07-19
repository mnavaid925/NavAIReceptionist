# Research — Sub-module 4.2: Services & Resources (Module 4 — Calendar & Bookings, scheduling)

## Repo state checked first

- **LIVE_LINKS built so far:** `0.1`–`0.4`, `1.1`–`1.4`, `2.1`–`2.4`, `4.1` (`apps/accounts/navigation.py`).
  `4.2` is the lowest-numbered unbuilt sub-module of Module 4.
- **Models verified to EXIST** (grep on `^class ` in `apps/*/models/`):
  - `tenants.Tenant` — `apps/tenants/models/Tenant.py`
  - `tenants.Location` — `apps/tenants/models/Location.py`
  - `accounts.User` (`AUTH_USER_MODEL`) — `apps/accounts/models/User.py`
  - `accounts.UserLocation` — `apps/accounts/models/UserLocation.py`
  - `agents.AgentSetting` — `apps/agents/models/AgentConfiguration/AgentSettings.py`, `TenantLocationOwned`
  - `scheduling.Contact` — `apps/scheduling/models/ContactDirectory/Contacts.py`, `TenantOwned` (built in 4.1)
- **Models verified NOT to exist** (grep returned nothing): `scheduling.Service`, `scheduling.Resource`,
  `scheduling.Appointment`, `scheduling.CallbackRequest` (4.2/4.3/4.5 unbuilt), and `calls.CallSession`
  (`apps/calls/` does not exist — Module 5 unbuilt). Every "reuses X" claim below pointing at `Appointment` or
  `CallSession` is therefore a **forward reference to the ERD's intent**, called out as such.
- **Abstract bases confirmed** in `apps/scheduling/models/_base.py` (re-exports
  `apps/accounts/models/_base.py`): `TenantOwned` (tenant FK only), `TenantLocationOwned` (tenant + location FK).
  `_base.py`'s own docstring already states the exact split this sub-module must follow: *"`Service` is
  tenant-scoped with a NULLABLE location, which no abstract base expresses — it declares its own FK."* `Resource`
  takes `TenantLocationOwned` unmodified.
- **Sibling research file** `research-scheduling-4.1.md` shipped `Contact` only and explicitly parked nothing
  onto 4.2 — no inherited backlog. It did note (as a forward dependency, not yet actionable) that the contact
  detail page's appointment-history panel and any service/resource-aware sort wait on 4.3, which is unaffected
  by this sub-module.

## Leaders surveyed (with source links)

1. **Acuity Scheduling** — appointment-booking platform with explicit per-appointment-type padding
   (buffer before/after) and ordering — [Adding padding](https://help.acuityscheduling.com/hc/en-us/articles/16676926857101-Adding-padding-between-appointments), [Creating appointment types](https://help.acuityscheduling.com/hc/en-us/articles/16676922487949-Creating-and-editing-appointment-types)
2. **Square Appointments** — service catalogue with a "Require a resource" toggle per service, resources
   assignable to one or many locations, and services whose location is derived from staff assignment —
   [Resource management](https://squareup.com/help/us/en/article/7065-square-appointments-resource-management), [Create and manage services](https://squareup.com/help/us/en/article/6487-create-a-service-from-the-square-appointments-app), [Multi-location](https://squareup.com/au/en/appointments/features/multi-location)
3. **Cal.com** — event-type model with per-event buffers, an optional multiple-duration picker, and multiple
   selectable locations per event type — [Event buffers](https://cal.com/help/event-types/event-buffer), [Event type configuration](https://deepwiki.com/calcom/cal.com/2.1-event-type-configuration)
4. **Mindbody** — class/room capacity model (multi-attendee rooms, waitlists) and a rooms-and-resources
   scheduling surface shared with teacher/staff assignment — [Rooms and resources](https://support.mindbodyonline.com/s/article/203254103-Rooms-and-resources), [Scheduling](https://www.mindbodyonline.com/business/scheduling)
5. **NexHealth** (dental/medical scheduling API — the direct domain ancestor of this ERD's `Operatory`→`Resource`
   rename) — appointment types carry duration; operatories are the **capacity-1, exclusive-booking** resource;
   providers and operatories are explicitly separate booking axes — [Operatories](https://docs.nexhealth.com/v2.2.2/reference/operatories-1), [Appointment Types](https://docs.nexhealth.com/reference/appointment-types), [Appointment Slots](https://docs.nexhealth.com/reference/appointment-slots)
6. **Setmore** — multi-service booking per visit, staff-owned booking pages, one account per location with
   independent service/resource sets per site — [Booking multiple services](https://support.setmore.com/en/articles/490980-booking-multiple-services), [Manage multiple locations](https://support.setmore.com/en/articles/12608591-manage-multiple-locations)
7. **Goodcall** (AI phone receptionist) — the agent answers service/pricing/hours questions from a connected
   knowledge source and books using synced calendar data — the pattern this sub-module's data must support even
   though the tool itself is Module 3.3's — [Schedule appointments with your AI agent](https://help.goodcall.com/en/articles/8007538-schedule-appointments-with-your-ai-agent), [AI voice agent for appointment booking](https://www.goodcall.com/voice-ai/ai-voice-agent-for-appointment-booking)
8. **Retell AI / Vapi** (voice-agent infrastructure, already the confirmed comparator set for Module 3) —
   neither product models services/resources as first-class entities; both rely on a **knowledge base** /
   **dynamic-variable injection** pattern to hand business facts to the model — confirms this product's own
   design of a `get_business_info` **tool** (already named in `research-agents-2.1.md`) as the correct integration
   point rather than baking service data into the static prompt — [Retell pricing/knowledge bases](https://www.retellai.com/pricing), [Vapi dynamic variables](https://docs.vapi.ai/assistants/dynamic-variables) *(confirmed in 4.1's research; re-cited here for the tool-surface finding)*

## Feature catalog (this sub-module only)

### Service Catalogue

- **Duration per service (minutes)** — the core bookable unit · seen in: Acuity, Square, Cal.com, NexHealth
  (all model appointment length per type) · priority: table-stakes · model: new `scheduling.Service.duration_minutes`
  (PositiveInt) (tenant-scoped, **nullable** location) · realtime: post-call (staff-authored CRUD); the stored
  value is read on the **live-call hot path** once 4.3's availability-search tool exists · tool-surface: none in
  this pass — feeds the forward-looking `get_availability` tool's slot math (3.3/4.3) · buildable now.
- **Buffer/padding, applied after the appointment** — blocks turnover/cleanup time so the next booking can't start
  immediately · seen in: Acuity's padding (also allows padding **before**), Cal.com's event buffers, dental/medical
  operatory turnover implicit in NexHealth's operatory-exclusivity model · priority: table-stakes · model:
  `Service.buffer_minutes` (PositiveInt, default 0) — **kept as the ERD's single field, semantics fixed to "applied
  after `end_at`, before the next slot at that resource/provider can open"** rather than adding separate
  before/after fields (see Deferred: Acuity/Cal.com's split-buffer feature was researched and explicitly not
  copied) · realtime: post-call to author; consumed on the live-call hot path by 4.3's slot computation
  (`next_open >= end_at + buffer_minutes`) · tool-surface: none this pass; this is the semantic contract 4.3 must
  read off the field, stated here so it lands unambiguously · buildable now.
- **Display order for the service menu** — the order staff want their offerings presented, including to a caller
  · seen in: Acuity's appointment-type ordering (ERD already models this) · priority: table-stakes · model:
  `Service.display_order` (Int, default 0), `Meta.ordering = ['display_order', 'name']` · realtime: post-call ·
  tool-surface: the forward-looking `get_business_info` tool must read services in this same order, so a spoken
  list matches what staff configured · buildable now.
- **Per-location vs. all-locations scoping (nullable `location` FK)** — one service definition can either belong
  to a single site or be offered everywhere · seen in: Cal.com's multi-location event types, Square's
  service-location-via-staff-assignment (a different mechanism, same outcome) · priority: table-stakes · model:
  `Service.location` FK `tenants.Location`, **null=True, blank=True** — null means "all locations", exactly as the
  ERD states; this is the one field the shared `TenantLocationOwned` base cannot express, so `Service` declares its
  own FK rather than inheriting it (confirmed against `apps/scheduling/models/_base.py`'s own docstring) ·
  realtime: post-call; filtered on the live-call hot path once 4.3's tool resolves `location_id` from server state
  and matches `Q(location=location_id) | Q(location__isnull=True)` · tool-surface: none this pass · buildable now.
- **Service description, spoken-explanation field** — **added beyond the ERD's strict 6-field baseline**, because
  the explicit research question for this sub-module is *how the voice agent describes services to a caller*, and
  every comparator that answers that question needs a text field to answer from: Acuity/Square/Cal.com/Setmore all
  carry a description on the appointment type/service, and Goodcall's answer to "what does X cost/involve" comes
  from a connected knowledge source, not the bare service name · priority: table-stakes for this product's domain
  specifically (an AI phone agent that can only say a service's name, with no explanation, fails the core "explain
  what you do" caller intent) · model: **new field** `Service.description` (Text, blank) · realtime: authored
  post-call; read on the **live-call hot path** by the forward-looking `get_business_info` tool · tool-surface:
  `get_business_info` (Module 3.3, already named in `research-agents-2.1.md`) returns
  `data.services: [{"name": ..., "description": ..., "duration_minutes": ...}]` — a pure read, no argument beyond
  server-held `tenant_id`/`location_id` · buildable now (field); tool wiring is integration/later (3.3).
- **`requires_resource` flag** — **added beyond the ERD baseline** — marks a service as needing a bookable
  room/chair/bay, distinct from one that only needs a provider (e.g. a phone consult) · seen in: Square's explicit
  per-service "Require a resource" toggle · priority: common · model: **new field** `Service.requires_resource`
  (Bool, default `False`) · realtime: authored post-call; consumed on the live-call hot path by 4.3's availability
  search to decide whether resource capacity gates the slot set · tool-surface: none this pass — the field is the
  input 4.3's `get_availability` tool will branch on · buildable now.
- **Active-only offering** — see its own group below (shared with Resource).

### Resource Records

- **Bookable physical resource per location (room/chair/bay), with a number, description and display order** ·
  seen in: NexHealth's Operatory (the direct ancestor — a chair/column/room where a provider services someone),
  Square's rooms/stations/equipment/chairs, Mindbody's rooms-and-resources · priority: table-stakes · model: new
  `scheduling.Resource`, `TenantLocationOwned` (confirmed base class, no deviation needed) — `name` (Char128),
  `resource_number` (PositiveInt, null), `description` (Char255, blank), `display_order` (Int, default 0),
  `is_active` (Bool, default True) · realtime: post-call · tool-surface: none this pass — feeds 4.3's availability
  search and 4.4's "by resource" calendar column · buildable now.
- **Unique `(location, name)`** — prevents two rooms at the same site sharing a name, which would make the
  spoken/visual disambiguation ("Room 2" vs "Room 2") ambiguous · seen in: every comparator enforces unique
  resource naming per site implicitly through their UI; NexHealth and Square both scope a resource strictly to one
  location · priority: table-stakes · model: `Resource.Meta.unique_together = [('location', 'name')]` (per ERD) ·
  realtime: post-call (form validation) · buildable now.
- **Resource exclusivity — capacity is implicitly 1, no `capacity` field** — a resource can host exactly one
  appointment at a time · seen in: NexHealth states this explicitly — *"operatories cannot have more than one
  appointment booked in them at the same time"* — while Mindbody's opposite case (a room capacity of 20+ for a
  group class) does **not** apply here, because `scheduling.Appointment` (4.3) is one `contact` per row with no
  attendee count or M2M — there is no group-class capability in this product's seven capabilities · priority:
  table-stakes (as a *design decision*, not a field) · model: **explicitly no `capacity` field on `Resource`** —
  recorded here so a later pass does not add one by analogy to Mindbody · realtime: enforced on the live-call hot
  path by 4.3's slot computation treating any resource with a conflicting `Appointment` as fully booked · buildable
  now (i.e., ship without the field).
- **Resource is a physical thing, never a person — kept decoupled from `provider`** — the single most important
  correctness point for 4.3 to land cleanly. NexHealth explicitly separates providers from operatories (a provider
  *uses* an operatory; the operatory does not represent the provider), and Square explicitly separates staff from
  resources · seen in: NexHealth (operatories vs. providers), Square (resources vs. staff) · priority: table-stakes
  · model: `Resource` carries **no** FK to `settings.AUTH_USER_MODEL`, and the forward-looking `Appointment` (4.3)
  keeps `resource` and `provider` as two **independent** nullable FKs exactly as the ERD specifies — a service
  needing "a provider AND a room" sets both, a phone-only consult sets neither · realtime: n/a (schema-level) ·
  tool-surface: none · buildable now — stated explicitly so 4.3 doesn't try to fold them into one FK.
- **Active-only offering** — see below.

### Active-Only Offering

- **Exclude inactive services/resources from booking/availability, keep them for history** — universal pattern:
  Acuity archives appointment types rather than deleting, Square/Mindbody deactivate rather than remove a resource
  that has appointment history · priority: table-stakes · model: `Service.is_active` / `Resource.is_active` (both
  Bool, default `True`, already in the ERD) · realtime: post-call to toggle; enforced on the **live-call hot path**
  once 4.3's `get_availability` filters `is_active=True` on both tables — this sub-module's own CRUD forms must
  also **not** hard-delete a `Service`/`Resource` that already has appointment history once 4.3 lands (the ERD's
  `Appointment.resource`/`Appointment.service` are `on_delete=SET_NULL`, so a hard delete is technically survivable
  today, but a deactivate-first UX matches every comparator and avoids surprising a past-appointment's display) ·
  tool-surface: none · buildable now.

### Beyond the bullets

- **`get_business_info` tool consumes this sub-module's data — forward reference, name confirmed against
  `research-agents-2.1.md`** · seen in: Goodcall/Retell/Vapi's "connected knowledge source" / dynamic-variable
  pattern for answering caller questions about offerings · priority: table-stakes for the AI-receptionist domain ·
  model: reads `Service` (active, location-scoped-or-null) and `Resource` (active, location-scoped) · realtime:
  live-call hot path (Module 3.3) · tool-surface: **integration/later** — 4.2 ships the queryable data; the tool
  itself, its argument-free schema and its `{"ok": true, "data": {"services": [...], "resources": [...]}, "error":
  null}` envelope belong to 3.3.
- **Resource display order feeds the calendar's "by resource" column ordering** · seen in: no single comparator
  names this explicitly, but it follows directly from 4.4's own bullet ("By Resource and By Provider — switches
  the grid's columns... without changing the underlying query") · priority: differentiator · model: reuses
  `Resource.display_order` — no new field · realtime: post-call · tool-surface: pure UI · buildable now, consumed
  by 4.4 later.
- **Service/Resource CRUD access tier matches 4.1's confirmed pattern** · not a market-leader feature, a repo
  convention: per `.claude/skills/scheduling/SKILL.md`, list/detail/create/edit are open to **any signed-in tenant
  user** (front-desk work); only **delete** is gated to `@tier_required(*MANAGEMENT_TIERS)` · priority: n/a
  (convention, not researched) · model: n/a · tool-surface: pure UI/view-decorator · buildable now — 4.2 follows
  4.1's already-confirmed tier split rather than re-deciding it.

## Compliance & provider constraints

- **No REQUIRED item is directly triggered by this sub-module.** `Service` and `Resource` carry no PII (no name,
  phone, health data — those live only on `Contact` and, once built, `CallSession`), so neither the recording-consent
  basis, the two-party-consent announcement, nor HIPAA/GDPR subject-rights obligations attach to these two tables.
  Those REQUIRED items are already tracked against `agents`/`runtime`/`calls` (2.x, 3.5, 5.x research) and are not
  re-triggered here — this mirrors 4.1's own finding for `Contact`'s non-recording fields.
- **No provider call, no cost line.** This sub-module makes no Twilio/STT/TTS/LLM call and appends nothing to the
  future `calls.CallSession.usage` — it is pure CRUD that precedes the runtime module.
- **Latency-relevant design constraint for the future hot path.** Once 3.3 wires `get_business_info` and
  `get_availability`, both will query `Service`/`Resource` filtered by `tenant`, `location` (or
  `location__isnull=True` for Service) and `is_active` inside the ≤1.5 s p50 / ≤3 s p95 first-audio budget. That
  means: keep the active-service/resource lists small and indexed by the existing `TenantOwned`/`TenantLocationOwned`
  `tenant`/`(tenant, location)` FKs (no full-table scan, no `LIKE` query) — the two tables recommended below need no
  extra index beyond the FK indexes Django already creates, because per-location service/resource counts in this
  product's target market (single-site to few-dozen-site SMBs) are small enough that `Meta.ordering` alone keeps
  the query cheap.

## Recommended build scope (this pass)

**CRUD sub-module — 2 models** (exactly the two named in the task and in 4.4's build-state table):

- **`scheduling.Service`** — tenant-scoped with a **nullable** `location` FK (declares its own FK; no abstract base
  expresses "tenant + optional location" — confirmed against `apps/scheduling/models/_base.py`'s own docstring).
  Fields, each justified by a researched feature above:
  - `tenant` — FK `tenants.Tenant` (verified), `on_delete=CASCADE`
  - `location` — FK `tenants.Location` (verified), **null=True, blank=True** — Per-Location Scoping
  - `name` — Char(255) — Service Catalogue baseline
  - `description` — Text, blank — **new field**, Service Description (spoken-explanation) research finding
  - `duration_minutes` — PositiveInt — Duration per Service
  - `buffer_minutes` — PositiveInt, default 0 — Buffer, applied-after semantics
  - `requires_resource` — Bool, default `False` — **new field**, Service-to-Resource Requirement research finding
  - `is_active` — Bool, default `True` — Active-Only Offering
  - `display_order` — Int, default 0 — Display Order
  - `Meta.ordering = ['display_order', 'name']`
- **`scheduling.Resource`** — `TenantLocationOwned` (tenant + location, both required — verified base class, no
  deviation). Fields, each justified by a researched feature above:
  - `tenant` / `location` — inherited from `TenantLocationOwned`
  - `name` — Char(128) — Bookable Resource baseline
  - `resource_number` — PositiveInt, null — matches NexHealth/Square's numbered room/chair pattern
  - `description` — Char(255), blank — per ERD
  - `display_order` — Int, default 0 — feeds 4.4's future "by resource" column ordering
  - `is_active` — Bool, default `True` — Active-Only Offering
  - **No `capacity` field** (Resource Exclusivity finding) — **no FK to `settings.AUTH_USER_MODEL`**
    (Resource-vs-Provider Decoupling finding)
  - `Meta.unique_together = [('location', 'name')]`, `Meta.ordering = ['display_order', 'name']`

Package layout (per the mandated `<layer>/<SubModule>/<Entity>.py` shape, mirroring 4.1's `ContactDirectory/`):
`apps/scheduling/models/ServicesResources/Services.py`, `.../Resources.py`, with matching `forms/`, `views/`,
`urls/` packages, and template folder `templates/scheduling/catalog/service/` /
`templates/scheduling/catalog/resource/` (the `catalog` slug is the one CLAUDE.md's own template-structure section
already names for this sub-module).

**Explicitly NOT built this pass** (see Deferred): `price`/`price_cents`, split `buffer_before_minutes` /
`buffer_after_minutes`, multiple-duration variants per service, a `resource_type` category field, and a
`Service`↔`Resource` eligibility M2M (which would be a third model).

## Belongs to sibling sub-modules (parked, not scoped here)

- Availability-search slot computation reading `duration_minutes`, `buffer_minutes`, `requires_resource`,
  `is_active` → **4.3 Availability & Booking**.
- `Appointment.service` / `Appointment.resource` FK wiring (`on_delete=SET_NULL`, per ERD) → **4.3**.
- The calendar's "By Resource and By Provider" column toggle consuming `Resource.display_order` → **4.4 Calendar
  Views**.
- `get_business_info` / `get_availability` LLM tool implementation, argument schema and result envelope →
  **3.3 Tools & Dispatcher** (Module 3).
- Booking-list filters by service/resource (4.5's "Booking List" bullet) → **4.5 Bookings List & Callback
  Requests**.

## Out of scope for this product (outside the seven capabilities)

- **Price/payment capture, deposits, cancellation fees on a service** — every booking-platform comparator surveyed
  (Acuity, Square, Cal.com) displays or charges a price; this product has no payments capability among its seven
  (login, password/email, calendar, bookings, agent setup + Twilio, call transfer, profile) — bookings here are
  informational scheduling, not commerce.
- **Group-class capacity / multi-attendee bookings** (Mindbody's room-capacity classes) — `scheduling.Appointment`
  is one `contact` per row with no attendee list; adding class capacity would require a new attendee-set concept
  the ERD does not define and no bullet requests.
- **Public self-serve online booking page** where a customer picks service + resource directly (Acuity/Cal.com/Setmore
  booking pages) — this product's only inbound intake surfaces are the phone agent and internal staff CRUD; there
  is no customer-facing booking widget in the seven capabilities.
- **Resource rental/monetization** (Mindbody's "Resource Rentals" — renting a room to a third party) — not a
  capability of this product.

## Deferred (later passes / integrations)

- **`price`/`price_cents` field on `Service`** — common among leaders, but no payments capability exists in this
  product to attach it to; revisit only if a billing/payments capability is ever added to the seven.
- **Split `buffer_before_minutes` / `buffer_after_minutes`** — researched (Acuity, Cal.com both offer it), but the
  ERD's single `buffer_minutes` field, fixed to "applied after," is sufficient for this product's target
  single-service-at-a-time booking flow; revisit only if a real before-appointment prep-time need surfaces.
- **Multiple duration variants per service** (Cal.com's `multipleDuration`) — workaround for now is to create a
  separate `Service` row per duration (e.g. "30-min Massage" / "60-min Massage"), matching how many small
  businesses on Acuity/Square already model it; a durations array/table is unwarranted complexity at this size.
- **`resource_type`/category field** (room vs. chair vs. equipment) — free-text `name`/`description` already
  covers this; no comparator enforces it as a hard-typed field either.
- **`Service` ↔ `Resource` eligibility matrix (M2M)** — Square's "assign resource(s) to service" is the real
  precedent, but it is a third table and this pass's build-scope constraint is exactly two models; the simpler
  `Service.requires_resource` boolean plus 4.3's location-scoped resource search covers the common case. Revisit
  only if a business genuinely needs to restrict a service to a resource subset within one location.
- **`capacity` field on `Resource`** — deliberately rejected, not merely postponed (see Resource Exclusivity
  above); would require attendee-count support on `Appointment` that does not exist and is not requested.
