# Research — Sub-module 4.1: Contact Directory (Module 4 — Calendar & Bookings, scheduling)

## Repo state checked first

- **LIVE_LINKS built so far in module 4:** none. `apps/accounts/navigation.py` has entries through `2.4` only
  (`0.1`–`0.4`, `1.1`–`1.4`, `2.1`–`2.4`). `4.1` is the lowest-numbered unbuilt sub-module of Module 4, and
  `apps/scheduling/` does not exist yet — this is the module's first pass.
- **Sibling models available to FK (verified by grep on `^class ` in `apps/*/models/`):**
  - `tenants.Tenant` — `apps/tenants/models/Tenant.py`
  - `tenants.Location` — `apps/tenants/models/Location.py`
  - `accounts.User` — `apps/accounts/models/User.py`
  - `accounts.UserLocation` — `apps/accounts/models/UserLocation.py`
  - `agents.AgentSetting` — `apps/agents/models/AgentConfiguration/AgentSettings.py`
- **NOT built (grep returned nothing):** `scheduling.Contact`, `scheduling.Service`, `scheduling.Resource`,
  `scheduling.Appointment`, `scheduling.CallbackRequest` (no `apps/scheduling/` directory at all), and
  `calls.CallSession` (no `apps/calls/` directory), and no `apps/runtime/`. Every "reuses X" claim below that
  points at a Module 4/5 sibling is therefore a **forward reference to the ERD's intent**, not a verified class,
  and is called out as such.
- **No prior `research-scheduling-*.md` file exists** — this is the first research pass for the `scheduling` app,
  so there is no earlier-deferred backlog to inherit.

## Leaders surveyed (with source links)

1. **Smith.ai** — human-backed AI receptionist that recognizes repeat callers and pushes contact/call data into a
   CRM — [CRM & Zapier integration](https://smith.ai/features/crm-zapier-integration), [AI receptionist](https://smith.ai/ai-receptionist)
2. **Ruby Receptionists** — live/AI receptionist with a CRM-lite Activity feed and Clio/HubSpot/Salesforce
   contact sync — [Integrations](https://www.ruby.com/solutions/integrations/)
3. **Dialpad AI (Ai Contact Center / Ai Receptionist)** — phone-number-to-contact matching with a sidebar
   showing single vs. multiple matches and manual search — [Contact Center AI](https://www.dialpad.com/features/contact-center-ai/), [CRM series](https://help.dialpad.com/docs/dialpad-crm-series)
4. **Goodcall** — small-business AI phone agent with a directory organized by department/contact, lead capture
   pushed to Sheets/CRM — [Goodcall](https://www.goodcall.com/)
5. **Rosie** — AI answering service with a unified inbox, caller-info summary copy, and a spam/robocall
   screening filter — [Rosie](https://heyrosie.com/)
6. **Retell AI** — realtime voice-agent platform; recent platform updates let agents recognize returning callers
   and resume context, and dynamic variables carry a pre-fetched caller record into the prompt — [Changelog](https://www.retellai.com/changelog), [Dynamic variables tutorial](https://community.retellai.com/t/lesson-18-inbound-outbound-calls/2936)
7. **Vapi** — dynamic-variable injection (`{{name}}` etc.) for personalizing a call from an externally resolved
   contact record — [Dynamic Variables](https://docs.vapi.ai/assistants/dynamic-variables)
8. **Bland AI / Synthflow / PolyAI** — enterprise voice-agent platforms; workflow builders that pull a caller
   record before the conversation starts and write outcomes back to a CRM — [Synthflow best voice AI agents](https://synthflow.ai/blog/best-voice-ai-agents-in-contact-centers)
9. **Acuity Scheduling** — appointment-booking product with an explicit client-directory merge-duplicates flow
   and CSV import/export — [Managing your client list](https://help.acuityscheduling.com/hc/en-us/articles/16676896712589-Managing-your-client-list-in-Acuity-Scheduling), [Importing](https://help.acuityscheduling.com/hc/en-us/articles/16676923391757-Importing-appointments-and-clients-to-Acuity-Scheduling), [Exporting](https://help.acuityscheduling.com/hc/en-us/articles/16676916553485-Exporting-Acuity-Scheduling-appointments-and-clients)
10. **Square Appointments / Mindbody** — multi-location booking products whose customer/client directory is
    explicitly business-wide rather than per-location — [Square multi-location](https://squareup.com/help/us/en/article/5834-square-appointments-for-multiple-locations), [Square Customer Directory](https://squareup.com/help/us/en/article/5612-customer-engagement-for-multiple-location-businesses), [Mindbody multi-location](https://www.mindbodyonline.com/business/multi-location-management)

## Feature catalog (this sub-module only)

### Phone-Keyed Contacts

- **ANI auto-match-or-create at call start** — resolves the inbound caller to an existing contact or creates one,
  before/at the top of the conversation · seen in: Retell AI (returning-caller recognition), Dialpad AI
  (phone-number contact matching), Smith.ai (recognizes repeat callers) · priority: table-stakes · model: reuses
  `scheduling.Contact` (tenant-scoped, **not** location-scoped) · realtime: live-call hot path · tool-surface:
  forward-looking `identify_contact()` tool for Module 3 — **zero args**, the ANI comes from server-held session
  state, never a model parameter; returns `{"ok": true, "data": {"contact_id": ..., "first_name": ..., "last_name":
  ..., "is_new": bool}, "error": null}`. This sub-module ships the model and the phone-indexed lookup the tool
  will call; the tool itself is Module 3's — integration/later.
- **E.164 normalization at write time** — every stored number is coerced to E.164 before the unique-ish index is
  used for lookup · seen in: Dialpad/Retell caller-matching depends on exact-format matching; Twilio numbers
  themselves are E.164 · priority: table-stakes · model: `Contact.phone_e164`, normalized in `clean()`/`save()`
  mirroring the pattern already used on `AgentSetting.inbound_phone_number` · realtime: supports the live-call hot
  path (the index must be an exact match) · tool-surface: none — model/form validation only · buildable now.
- **Shared-line disambiguation** — when one phone number maps to more than one contact (a household or shared
  office line), offer the caller-facing tool a candidate list instead of guessing · seen in: Dialpad AI's sidebar,
  which shows a single auto-match or lets staff pick manually among several · priority: common · model: reuses
  `Contact` — the ERD indexes `(tenant, phone_e164)` but does **not** make it unique, which is exactly what this
  case needs · realtime: live-call hot path (the `identify_contact` tool must return 0/1/many and let the model
  ask a clarifying question, e.g. name, when there is more than one) · tool-surface: `identify_contact` result
  carries `data.candidates: [...]` when count > 1 · buildable now (schema); the live disambiguation flow is Module
  3 integration/later.
- **Auto-create on first contact** — a never-seen number becomes a new `Contact` row rather than blocking the call
  · seen in: the same first-touch capture pattern across Retell/Dialpad/Ruby · priority: table-stakes · model:
  reuses `Contact`, `source='ai_phone'` · realtime: live-call hot path · tool-surface: forward-looking
  `create_contact(first_name, last_name, phone?, email?, date_of_birth?, notes?)` tool for Module 3; `tenant_id`
  from server state, never a model argument · buildable now (model); tool wiring integration/later.

### Contact List & Search

- **Multi-field search (name, phone, email)** — one search box across all three · seen in: Acuity's client list,
  Ruby's Activity search, Mindbody's "All Contacts" smart list · priority: table-stakes · model: reuses `Contact`
  · realtime: post-call (staff-facing page) · tool-surface: pure UI · buildable now.
- **Filter by source channel** (`ai_phone` / `manual` / `web`) — seen in: Smith.ai/Ruby distinguishing
  phone-originated vs. manually entered clients, Goodcall's channel-tagged lead capture · priority: common · model:
  reuses `Contact.source` · realtime: post-call · tool-surface: pure UI · buildable now.
- **Recently-active / last-touch sort** — surfacing repeat callers near the top · seen in: Mindbody's
  "recently visited" smart list, Smith.ai's repeat-caller recognition surfaced to staff · priority: differentiator
  · model: reuses `Contact.updated_at`/`created_at` now; a true "last call" or "last appointment" sort needs
  `calls.CallSession` / `scheduling.Appointment`, neither of which exists yet · realtime: post-call · tool-surface:
  pure UI · buildable now on the timestamp fields already in the ERD; the call/appointment-aware sort is deferred
  to when those sibling sub-modules ship.
- **Paginated list with a total count** — table-stakes list UI across every product surveyed · priority:
  table-stakes · model: reuses `Contact` · tool-surface: pure UI · buildable now.

### Contact Create, Edit & Detail

- **Core intake fields** (first name, last name, phone, email, date of birth, notes) · seen in: every product
  surveyed carries this minimum set · priority: table-stakes · model: reuses `Contact` fields exactly as specified
  in `NavAIReceptionist-ERD.md` (`first_name`, `last_name` Char(128) blank-allowed; `phone_e164` Char(16) indexed;
  `email` blank; `date_of_birth` nullable; `notes` Text blank) · realtime: post-call (CRUD form) · tool-surface:
  pure UI · buildable now.
- **Blank-tolerant identity** — an unknown or withheld-caller-ID contact has neither first nor last name, and the
  UI/tool layer must not choke on that · seen in: Rosie/Smith.ai handling anonymous or withheld-ID calls
  gracefully, Retell's "resume where the call left off" implying a partial profile is normal · priority:
  table-stakes · model: reuses `Contact` (`first_name`/`last_name` already `blank=True` per ERD) · realtime:
  live-call hot path — the forward-looking `create_contact` tool must accept a partial payload · tool-surface:
  prompt/tool-argument design note (Module 3) · buildable now.
- **Appointment history on the detail page** — explicit 4.1 bullet · seen in: Acuity's and Mindbody's client
  profile, Ruby's "linked client communications" in Clio · priority: table-stakes · model: reads
  `scheduling.Appointment`, which is **owned by sibling sub-module 4.3 and does not exist yet** · realtime:
  post-call · tool-surface: pure UI · **build now as an empty-state-guarded panel** ("No appointments yet") so the
  bullet is satisfied today; wire the real query when 4.3 ships — this is a forward dependency, not a deferral of
  the panel itself.
- **Merge / de-duplicate contact profiles** — seen in: Acuity's explicit "match names, keep one profile's contact
  info" merge flow, Dialpad's manual-match picker for ambiguous numbers · priority: common · model: reuses
  `Contact` — a merge action needs to re-point any FKs from the losing row to the winning row, but the only FKs
  that will ever point at `Contact` (`Appointment.contact`, `CallSession` linkage) belong to sibling sub-modules
  that don't exist yet · realtime: post-call (staff action) · tool-surface: pure UI · buildable now as a merge
  scaffold operating on `Contact` fields alone; full FK re-pointing is integration/later once 4.3 and Module 5
  exist.
- **Edit/Delete guarded by the `PROTECT` relationship** — a model-specific finding, not a marketing feature: the
  ERD declares `Appointment.contact` as `on_delete=PROTECT`. Once 4.3 ships, a hard delete of a `Contact` with any
  appointment history will raise `ProtectedError` · priority: table-stakes (CRUD Completeness Rules mandate a
  delete view) · model: `Contact` · tool-surface: pure UI · buildable now — the delete view must catch this today
  even though `Appointment` doesn't exist yet, so the pattern is right from the first commit rather than retrofit
  in 4.3.

### Business-Wide Identity

- **Tenant-wide contact record, no location filter on list/search/detail** — explicit 4.1 bullet, confirmed
  against real multi-location products: Square's Customer Directory is shared across a business's locations, and
  Mindbody's "datashare" "All Contacts" smart list spans locations · priority: table-stakes · model: `Contact`
  tenant-scoped only — **no `location` FK**, and the list/search view must never require or filter on
  `request.location` · realtime: post-call · tool-surface: pure UI · buildable now.
- **No location FK, not even an optional "primary location" convenience field** — Mindbody offers a *soft*
  "location visited most often" preference, which is tempting to copy, but adding any location field to `Contact`
  contradicts the bullet and blurs the identity/booking boundary (a contact's location history belongs on
  `Appointment`, which already carries `location`) · priority: differentiator avoided on purpose · model: do
  **not** add — call this out explicitly so a later pass doesn't reintroduce it · buildable now (i.e., ship
  without it).
- **Location-agnostic booking eligibility messaging** — surfacing "this contact can book at any of the business's
  locations" as UI copy on the detail page · seen in: Square/Mindbody's cross-location client model · priority:
  differentiator · model: pure UI copy, no schema · buildable now.

### Beyond the bullets

- **Consent / "don't call back" note for callback flows** · seen in: Rosie's spam/consent-oriented call screening,
  general CRM-lite do-not-contact toggles · priority: common (**not REQUIRED** — see Compliance section: this
  product has no outbound marketing capability in its seven-capability scope, so TCPA-style telemarketing
  opt-out enforcement does not attach to `Contact`) · model: reuses `Contact.notes` free text for this pass; do
  not add a dedicated boolean field yet · realtime: post-call · tool-surface: pure UI · buildable now, revisit only
  if 4.5's Callback Request Queue needs a structured flag.
- **CSV import / export of the contact list** · seen in: Acuity's explicit client import (batches of 500) and
  export-by-group flow · priority: common · model: reuses `Contact`, no schema change · realtime: post-call ·
  tool-surface: pure UI (bulk action) · buildable now — no external provider dependency, pure Django form + CSV
  module.
- **Tag / category chips beyond `source`** · seen in: Goodcall's department-organized directory, CRM-integration
  tagging referenced by Smith.ai/Synthflow · priority: differentiator · model: would require a new field (a
  `tags` CharField/JSONField) not present in the ERD baseline · realtime: post-call · tool-surface: pure UI ·
  **deferred** — out of the ERD's 8-field baseline; revisit only if the `todo` agent decides the product needs
  it, don't add it speculatively.
- **Push contact/call data into an external CRM** (Salesforce, HubSpot, Clio) · seen in: Smith.ai, Ruby, Dialpad,
  Synthflow, PolyAI — this is the single most common feature across the surveyed leaders · priority:
  differentiator among leaders, but **out of scope for this product** — see below.
- **GDPR/CCPA-style data-subject rights over Contact PII** — `Contact` stores name, phone, email, date of birth
  and free-text notes, all PII · priority: **REQUIRED** · model: `Contact` — implement a "forget this contact"
  admin action that **anonymizes fields in place rather than hard-deleting the row**, because
  `Appointment.contact` is `on_delete=PROTECT`: a hard delete is not always possible once a contact has
  appointment history, so the erasure path must degrade to redaction · realtime: post-call (admin action) ·
  tool-surface: pure UI · buildable now.

## Compliance & provider constraints

- **REQUIRED — PII subject rights on `Contact`.** Name, phone, email, DOB and notes are personal data. Ship a
  redaction/anonymize path for erasure requests (clear PII fields, keep the row for referential integrity against
  a `PROTECT`-constrained `Appointment.contact` once 4.3 exists) rather than relying on a hard delete that a live
  FK will refuse. This is the GDPR/CCPA obligation the project guardrails call out — never defer it.
- **Not REQUIRED here: TCPA do-not-call enforcement.** TCPA opt-out/DNC obligations attach to outbound
  telemarketing calls and texts. NavAIReceptionist's seven capabilities include no outbound marketing/SMS
  campaign feature — the only outbound contact is a human calling back a `CallbackRequest` the caller themselves
  asked for (module 4.5), which is not telemarketing. A DNC flag is therefore a `common`-priority convenience
  (staff note), not a legal mandate on this sub-module. Re-evaluate only if a future module adds outbound
  marketing.
- **Recording consent, two-party-consent announcements and HIPAA retention belong to Module 3 (recording) and
  Module 5 (playback/PII handling)**, not to the contact record itself — `Contact` does not store recordings or
  transcripts (Invariant 2), so those REQUIRED items are out of this file's scope; they are already tracked in
  the `agents`/`runtime`/`calls` research.
- **Provider/rate-limit implications: none directly.** This sub-module adds no Twilio/STT/TTS/LLM call and appends
  nothing to `calls.CallSession.usage` — it precedes the runtime module entirely. The one latency-relevant
  constraint to design for now: the `(tenant, phone_e164)` index is what the future `identify_contact` tool will
  hit on the live-call hot path, so it must stay a single indexed-equality lookup (no `LIKE`, no unbounded scan)
  to fit inside the project's ≤1.5s p50 / ≤3s p95 first-audio latency budget once Module 3 wires the tool.

## Recommended build scope (this pass)

**CRUD sub-module — 1 model:**

- **`scheduling.Contact`** — tenant-scoped, **not** location-scoped (Business-Wide Identity bullet, confirmed
  against Square/Mindbody's cross-location client directories) — fields justified by the researched features
  above: `tenant` FK (`tenants.Tenant`, verified), `first_name`/`last_name` (Char(128), blank — Blank-Tolerant
  Identity), `phone_e164` (Char(16), indexed — Phone-Keyed Contacts, ANI auto-match), `email` (Email, blank),
  `date_of_birth` (Date, null), `notes` (Text, blank), `source` (Char(16) choices `ai_phone`/`manual`/`web` —
  Filter by Source), `created_at`/`updated_at` (DateTime — Recently-Active Sort). Indexes: `(tenant, phone_e164)`,
  `(tenant, last_name, first_name)`, matching the ERD exactly. No second model — a tags table, a DNC table and a
  merge-audit table were all considered and rejected this pass (see Deferred); Invariant 1 forbids a second
  identity table outright.

**Deferred model additions considered and explicitly NOT built this pass:**
- A `tags`/`category` field or table — not in the ERD baseline, no strong leader consensus beyond Goodcall.
- A dedicated `do_not_contact` boolean — not legally required given this product's inbound-only scope; a notes
  entry covers the operational need for now.
- A contact-merge audit/log table — the merge action itself is buildable now; logging its history is a nice-to-have
  that can ride on `Contact.notes` or wait for a real audit-log feature elsewhere.

## Belongs to sibling sub-modules (parked, not scoped here)

- Appointment-history query wiring on the contact detail page (the panel ships now with an empty state) → 4.3
  Availability & Booking / 4.4 Calendar Views.
- Callback-request linkage and any structured do-not-contact flag → 4.5 Bookings List & Callback Requests.
- Call history / transcript link from a contact → 5.1 Call Log List, 5.2 Call Detail & Transcript.
- `identify_contact` / `create_contact` tool implementation, argument schema enforcement, and the tool dispatcher
  itself → 3.3 Tools & Dispatcher.
- Full merge with FK re-pointing across `Appointment.contact` and any `CallSession` contact linkage → activates
  once those sibling models exist (4.3 / Module 5).

## Out of scope for this product (outside the seven capabilities)

- **Push contact/call data to an external CRM** (Salesforce, HubSpot, Clio, Zapier) — every leader surveyed does
  this, but NavAIReceptionist's seven capabilities are login, password/email, calendar, bookings, agent setup +
  Twilio, call transfer and profile; there is no "integrations" capability. This product *is* the CRM-lite, not an
  integrator of one.
- **Outbound marketing campaigns / bulk SMS-email to contacts** — no outbound-marketing capability exists in the
  seven capabilities; also the reason TCPA DNC enforcement is not REQUIRED here (see Compliance).
- **Spam/robocall screening and blocklisting** (Rosie's "block calls before they connect") — this is call-routing
  behaviour that would live in Module 3 (Call Runtime) at most, and even there it is not one of the documented
  agent capabilities; not a contact-directory feature.
- **Loyalty programs, membership tiers, stored payment methods on a contact** (Square Loyalty, Mindbody
  memberships) — no payments/loyalty capability in this product.

## Deferred (later passes / integrations)

- Tag/category system on `Contact` — park until a real requirement (not just competitor parity) surfaces.
- "Last call" / "last appointment" aware sort on the contact list — needs `calls.CallSession` and
  `scheduling.Appointment`, neither built yet.
- Full merge-with-FK-repointing — needs the same sibling models.
- CSV import validation edge cases (duplicate detection on import) — buildable now in a basic form, but the
  Acuity-style "merge on match" logic during import can wait for the manual-merge feature to prove out first.
