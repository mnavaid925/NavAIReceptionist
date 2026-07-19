# Research — Sub-module 1.2: Location Directory (Module 1 — Business & Locations, tenants)

## Repo state checked first

- **LIVE_LINKS built so far in module 1:** none. `apps/accounts/navigation.py::LIVE_LINKS` has only `0.1`–`0.4`
  entries; `1.1`, `1.2`, `1.3`, `1.4` are all unbuilt. This run adds `LIVE_LINKS["1.2"]`.
- **Sibling models available to FK (verified):**
  - `tenants.Tenant` — `apps/tenants/models/Tenant.py` — `name`, `slug` (unique), `customer_id` (unique),
    `timezone`, `is_active`. Confirmed via `grep "^class Tenant"`.
  - `accounts.User` — `apps/accounts/models/User.py` — has `tier`, `status` (`STATUS_CHOICES`), `is_provider`,
    and `assigned_locations()` (see gap below).
  - `accounts.UserLocation` — `apps/accounts/models/UserLocation.py` — `tenant`, `user` FK
    (`settings.AUTH_USER_MODEL`), `location` FK (`'tenants.Location'`), unique `(user, location)`,
    `clean()` cross-tenant guard. This is the reverse relation the Location Detail "assigned staff" panel reads
    (`location.user_assignments.all()`).
- **Models verified NOT to exist:** `apps/agents/` is entirely absent from the repo (`Glob apps/agents/**` →
  no results). `agents.AgentSetting` is Module 2, unbuilt — not just the model but the whole app. The Location
  Detail page's "linked agent setting" panel must render defensively (a static/soft-checked "not configured yet"
  state), never a hard import of `apps.agents.models`.
- **`tenants.Location` — verified as-built** (`apps/tenants/models/Location.py`, migrated in
  `apps/tenants/migrations/0001_initial.py`): `tenant` FK, `name`, `slug`, `address_line1`, `address_line2`,
  `city`, `state`, `postal_code`, `country` (default `'US'`), `timezone` (IANA, default `'UTC'`), `phone`,
  `is_active` (default `True`), `created_at`/`updated_at` (via `TenantOwned`/`TimeStamped`). Plus a
  `full_address` property, a `tzinfo` property (degrades to UTC on a bad name), and `local_now()`. Constraints:
  unique `(tenant, slug)` (`uniq_location_tenant_slug`), index `(tenant, is_active)`. **No fields beyond this
  list exist** — confirmed by reading the file directly, not the ERD.
- **`apps/tenants` currently ships only** `models/`, `admin.py`, `apps.py`, `migrations/`, `seed_tenants.py`. No
  `views/`, `forms/`, `urls/`, `templates/tenants/` — this sub-module creates all four, following the flat
  foundation-app layout (Module 1 has no sub-module folder level, same as `accounts`).
- **Reusable toolkit confirmed present, not re-planned:** `TenantModelForm` (`apps/accounts/forms/_common.py`) —
  `Location` has no `location` FK, so its form subclasses **`TenantModelForm`**, not `TenantLocationModelForm`.
  `paginate()` (`apps/accounts/views/_common.py`), `tier_required(*tiers)` (`apps/accounts/views/_helpers.py`),
  the `crud(base, name)` factory (`apps/accounts/urls.py`), `templates/base.html`,
  `partials/_pagination.html`, `partials/_empty_state.html`.
- **Deactivate-not-delete precedent already in this codebase:** `user_delete_view`
  (`apps/accounts/views/Users.py:182`) is `@require_POST`, never calls `.delete()`, sets
  `obj.status = User.STATUS_INACTIVE; obj.save(update_fields=[...])`, and redirects to the detail/list page.
  There is no separate "reactivate" view — reactivation happens through the ordinary edit form. `Location`
  should mirror this exactly, with `is_active` (a plain boolean, not a choices field) as the toggle.
- **Gap found — required for Location Deactivation to be safe:** `User.assigned_locations()`
  (`apps/accounts/models/User.py:242`) does **not** filter `location__is_active`. `ActiveLocationMiddleware`
  (`apps/accounts/middleware.py`) validates the session's stored active-location id against exactly this
  queryset (`assigned.filter(pk=stored_id)`) and also uses it to auto-activate a user's sole assignment. As
  written today, deactivating a location does **not** make it fall out of a user's `assigned_locations()`, so a
  user whose active location gets deactivated keeps reaching it — a live violation of the middleware's own
  documented contract ("an id that no longer resolves to an assignment is discarded"). This is a one-line fix
  (`.filter(location__is_active=True)`-equivalent — the method queries `Location` directly, so
  `.filter(is_active=True)`), not a new model or migration. Flagged for the `todo` agent as a required
  cross-app fix that rides along with this sub-module.
- **Sibling research files:** `Glob .claude/tasks/research-*.md` found only `research-accounts-0.1.md` through
  `-0.4.md` (Module 0). No prior `research-tenants-*.md` exists — 1.2 is the first Module 1 research pass, so
  there is no earlier-file backlog to inherit.

## Leaders surveyed (with source links)

1. **Goodcall** — AI phone receptionist purpose-built for multi-location/franchise brands, with a dedicated
   multi-location management dashboard — [goodcall.com](https://www.goodcall.com/),
   [ilounge.com comparison](https://www.ilounge.com/articles/top-ai-receptionist-for-companies-with-multiple-locations)
2. **Dialpad AI** — business VoIP + AI receptionist where a physical "office" is the location primitive —
   [help.dialpad.com — Add and Manage Multiple Offices](https://help.dialpad.com/docs/add-and-manage-multiple-offices)
3. **Rosie** — AI answering service; multi-location businesses typically run one account per site, with
   custom pricing for multi-location — [heyrosie.com](https://heyrosie.com/),
   [Rosie vs Goodcall](https://heyrosie.com/blog/rosie-ai-vs-goodcall)
4. **PolyAI** — enterprise voice AI deployed across hundreds of locations for large restaurant/retail chains,
   distinct configuration per site/brand — [poly.ai](https://poly.ai/),
   [restauranttechnologynews.com](https://restauranttechnologynews.com/2024/09/polyai-joins-forces-with-opentable-to-offer-restaurants-voice-ai-enabled-phone-reservation-support/)
5. **Smith.ai** — hybrid AI + live-agent receptionist; call routing/escalation across a firm's locations rather
   than a location-directory UI — [smith.ai/features/live-virtual-receptionists](https://smith.ai/features/live-virtual-receptionists)
6. **Ruby Receptionists** — standard onboarding routes calls to any number a business supplies, no dedicated
   multi-site directory surface documented — [ruby.com/faqs](https://www.ruby.com/faqs/),
   [Ruby Quick Start Guide](https://rubyhelpcenter.helpjuice.com/en_US/getting-started/receptionist-service-quick-start-guide)
7. **Bland AI** — voice-agent builder; phone numbers attach to an *agent*, not a physical site — no
   location-directory concept — [comparison coverage](https://builts.ai/blog/vapi-vs-bland-ai-vs-retell-ai/)
8. **Retell AI** — same pattern as Bland: numbers/agents, no address/site record —
   [comparison coverage](https://futurepicker.com/en/retell-ai-vs-vapi-vs-synthflow-vs-bland-ai-voice-agent-2026/)
9. **Vapi** — developer-first agent platform; telephony numbers are pooled per agent/assistant, not per business
   site — [comparison coverage](https://tested.media/retell-vs-vapi-vs-bland-vs-synthflow/)
10. **Synthflow** — no-code agent builder with built-in phone infrastructure; still agent-centric, no
    address/site/business-hours record — [comparison coverage](https://synthflow.ai/blog/vapi-ai-alternatives)

**Finding confirmed across 7–10:** Bland AI, Retell AI, Vapi and Synthflow are conversational-agent *builder*
platforms. None of them model a physical business site with an address/timezone/business-hours record — they
bind a phone number to an agent config, which is squarely **Module 2's** domain (agent setup + Twilio), not
1.2's. The genuinely comparable products for a **site/location directory** are Goodcall, Dialpad, Rosie and
PolyAI (all of which operate real multi-site businesses), plus Smith.ai/Ruby for the routing angle. This
sub-module's catalog below draws its feature set from that narrower group.

## Feature catalog (this sub-module only)

### Location List
- **Search across name, slug, city, phone** — what it does: free-text filter over the directory · seen in:
  Dialpad (office list search), Goodcall (multi-location dashboard search) · priority: table-stakes · model:
  reuses `tenants.Location` (tenant-scoped) · realtime: post-call (back-office UI, not a runtime surface) ·
  tool-surface: pure UI · buildable now.
- **Active/Inactive filter + status badge** — what it does: narrows the list to active or deactivated sites ·
  seen in: Dialpad, Goodcall · priority: table-stakes · model: reuses `tenants.Location.is_active` · realtime:
  post-call · tool-surface: pure UI (`badge-green "Active"` / `badge-muted "Inactive"`, per the closed badge
  set — matches the generic `is_active` map already used on `user/list.html`) · buildable now.
- **Assigned-staff count per row** — what it does: shows how many people can work at each site at a glance ·
  seen in: Dialpad's office admin list (per-office user counts) · priority: common · model: reuses
  `accounts.UserLocation` (`location.user_assignments.count()`) · realtime: post-call · tool-surface: pure UI ·
  buildable now.
- **Agent-configured indicator per row** — what it does: flags whether a site has a live inbound agent yet ·
  seen in: Goodcall's per-site dashboard (configured vs. not-yet-configured state) · priority: common · model:
  stand-in — `agents.AgentSetting` doesn't exist yet, so this renders as a static "Not configured" placeholder
  for every row this pass · realtime: post-call · tool-surface: pure UI · integration/later — becomes real once
  Module 2 ships; do not hard-import `apps.agents` now.

### Location Create & Edit
- **Slug auto-suggest from name, per-tenant uniqueness enforced with a friendly error** — what it does: proposes
  a URL-safe site code from the name, with a clear message on a `(tenant, slug)` collision instead of a raw
  `IntegrityError` · seen in: generic multi-tenant SaaS UX pattern (not one specific competitor; Dialpad's
  per-office identifier is the closest analogue) · priority: table-stakes · model: reuses `tenants.Location` +
  the existing `uniq_location_tenant_slug` constraint, caught in `form.clean()` · realtime: post-call ·
  tool-surface: pure UI · buildable now.
- **Structured address fields (address_line1/2, city, state, postal_code, country)** — what it does: captures a
  full postal address as discrete fields rather than one free-text block · seen in: Dialpad's E911 physical
  address capture, Goodcall's address ingestion from a business listing · priority: table-stakes · model:
  reuses `tenants.Location` (all fields already exist) · realtime: post-call · tool-surface: pure UI ·
  buildable now.
- **IANA timezone selector, not free text** — what it does: a closed dropdown of real timezone names so
  `Location.tzinfo`/`local_now()` never has to degrade to UTC from a typo · seen in: Goodcall (adapts to
  "different time zones" per site), general telephony-platform practice (Dialpad) · priority: table-stakes ·
  model: reuses `tenants.Location.timezone` — needs a form-level choice list built from
  `zoneinfo.available_timezones()` (Python stdlib, no external dependency, no model change) · realtime:
  post-call · tool-surface: pure UI · buildable now.
- **Country as a constrained choice, not free text** — what it does: prevents "USA"/"United States"/"US"
  variants that would break formatting downstream · seen in: general multi-site SaaS practice · priority:
  common · model: reuses `tenants.Location.country` (stays a `CharField`; the form adds a compact ISO-3166
  `choices=` list — no model/migration change) · realtime: post-call · tool-surface: pure UI · buildable now.
- **Public phone number formatting/light validation** — what it does: normalizes the site's public-facing
  number as a display string · seen in: Dialpad's main-line number, Goodcall's listing number · priority:
  common · model: reuses `tenants.Location.phone` — this is explicitly **not** the Twilio inbound number (that
  lives on `AgentSetting`, Module 2), so E.164 strictness is not required here, just basic sanity · realtime:
  post-call · tool-surface: pure UI · buildable now.
- **Timezone/address auto-detect from a business-listing sync (e.g. Google Business Profile)** — what it does:
  pre-fills address, hours and timezone from an external listing · seen in: Goodcall (syncs a Google Business
  Profile to learn address/hours/timezone) · priority: differentiator · model: would need a geocoding/listing
  provider adapter · realtime: post-call · tool-surface: none (external integration, not a tool) · **out of
  scope for this product** — no directory-listing integration is among the seven documented capabilities;
  parked, not deferred, because there is no future module that owns it either.

### Location Detail
- **One-page summary: full address, timezone + current local time, public phone** — what it does: shows
  everything about the site in one view · seen in: Dialpad's office settings page, Goodcall's per-site config
  screen · priority: table-stakes · model: reuses `tenants.Location.full_address` / `.local_now()` (already
  implemented properties — no new code needed for the values, only the template) · realtime: post-call ·
  tool-surface: pure UI · buildable now.
- **Assigned staff roster (read-only)** — what it does: lists who can work at this site · seen in: Dialpad
  (office admin lists), Goodcall (per-site team) · priority: table-stakes · model: reuses
  `accounts.UserLocation` via `location.user_assignments.select_related('user')` · realtime: post-call ·
  tool-surface: pure UI (read-only here — assign/unassign actions are 1.3's Assignment Matrix, not 1.2) ·
  buildable now.
- **Linked agent-setting panel (enabled state, inbound number, voice mode)** — what it does: surfaces whether
  and how the location's AI receptionist is configured · seen in: Goodcall (per-site agent status), Dialpad
  (per-office line status) · priority: common · model: stand-in — `agents.AgentSetting` and the whole `agents`
  app do not exist yet, so this panel MUST NOT hard-import it; render a static "Agent not configured yet —
  available once Module 2 ships" panel, or guard with `django.apps.apps.is_installed('agents')` +
  `apps.get_model` so the panel activates automatically once Module 2 lands without another edit to `tenants`
  · realtime: post-call · tool-surface: pure UI · integration/later.
- **Recent activity feed (last N appointments / calls at this site)** — what it does: shows what's been
  happening at the location · seen in: Dialpad's office activity view · priority: differentiator · model: would
  read `scheduling.Appointment` / `calls.CallSession`, neither of which exists yet (Module 4/5, built after
  Module 1 in sequence) · realtime: post-call · tool-surface: pure UI · **belongs to a later cross-module pass**
  once 4.x/5.x exist — not buildable now, not part of this sub-module's documented bullets either.
- **Site status/audit timeline (who activated/deactivated the site and when)** — what it does: an audit trail
  of activation-state changes · seen in: larger multi-site telephony platforms generally (not a specific
  competitor feature page, but standard in enterprise office-management tooling like Dialpad's admin history) ·
  priority: differentiator · model: would need a new audit-log table — **violates the zero-new-model constraint
  for this pass** · realtime: post-call · tool-surface: pure UI · deferred.

### Location Deactivation
- **Deactivate-not-delete, single boolean toggle, POST-only** — what it does: flips `is_active=False` instead
  of removing the row, so historical appointments/call logs keep a valid FK target · seen in: this exact
  pattern already shipped in this codebase for `accounts.User` (`user_delete_view`); the documented bullet
  explicitly calls for the same shape for locations · priority: **REQUIRED** (the sub-module's own scope bullet,
  and the only way to satisfy CLAUDE.md's CRUD-completeness "Every model with a list page MUST have a delete
  view" without destroying FK-referenced history) · model: reuses `tenants.Location.is_active` — no new field ·
  realtime: post-call · tool-surface: pure UI, `@require_POST`, confirm dialog per the standard delete-button
  pattern · buildable now. **Reconciliation:** `location_delete_view` is the delete ROUTE required by the CRUD
  Completeness Rules, but its body sets `is_active=False` and redirects to the list — it never calls
  `.delete()`, mirroring `user_delete_view` exactly. Reactivation is not a separate view; it happens by editing
  the location and checking `is_active` again, same as `User`.
- **Guard: a deactivated location must stop being "reachable" through the active-location switcher** —
  what it does: the actual safety property "Location Deactivation" exists to provide · priority: **REQUIRED** —
  this is a direct consequence of CLAUDE.md's Multi-Tenancy & Location Rules ("`request.location`... validated
  against the user's `UserLocation` rows on every request... a user must never reach a location they are not
  assigned to") · model: fix `accounts.User.assigned_locations()` to filter `is_active=True` on the `Location`
  side (one-line change to an existing method — not a new model/migration; see the gap noted in "Repo state
  checked first") · realtime: post-call · tool-surface: none (backend guard) · buildable now, and it should
  ride along with this sub-module's commit set since it is what makes the sub-module's own headline feature
  correct.
- **Warn before deactivating a location that would leave an assigned user with zero locations** — what it does:
  a soft warning, not a hard block, before confirming deactivation · seen in: this codebase's own
  `_is_last_owner` guard pattern on `user_delete_view`, generalized to locations · priority: common · model:
  reuses `accounts.UserLocation` counts per assigned user · realtime: post-call · tool-surface: pure UI (a
  `messages.warning` or an inline confirm-page hint) · buildable now.
- **Deactivation never cascades to historical data** — what it does: past appointments/call logs at a
  deactivated site stay fully readable · priority: **REQUIRED** (this is the documented bullet's stated
  rationale) · model: this is a property of never hard-deleting `Location` — `scheduling.Appointment` and
  `calls.CallSession` (Module 4/5, not built yet) will simply keep a valid `location_id` FK; nothing to build in
  this pass beyond "never call `.delete()`" · realtime: post-call · tool-surface: none · buildable now (as an
  absence of a destructive action, not a feature to write).
- **Block new bookings / agent activity at a deactivated location** — what it does: stops downstream modules
  from creating new appointments or answering calls at an inactive site · priority: common · model: belongs to
  Module 2 (agent enable toggle should also check `location.is_active`) and Module 4 (booking-creation guard) —
  **park it**; 1.2 only flips the flag, it does not own the enforcement in modules that don't exist yet.

### Beyond the bullets
- **Location plan/limit messaging ("3 of 5 locations used")** — seen in: some multi-location SaaS billing UIs
  generally, not specifically in the surveyed 10 · priority: n/a · **out of scope for this product** — no
  billing/plan capability exists among the seven.
- **Bulk CSV import of locations** — seen in: large multi-site chain tooling (Dialpad-scale enterprises) ·
  priority: differentiator · model: reuses `tenants.Location`, no new model, but a bulk-upload flow is
  unnecessary complexity for a small application's first pass · deferred.
- **Per-location "type"/category tag (flagship, satellite, kiosk)** — seen in: multi-brand PolyAI-style
  enterprise deployments · priority: differentiator · model: would need an additive field on `Location` — not
  requested by any documented bullet · deferred, and only worth a migration if a future sub-module actually
  needs to branch behaviour on it.

## Compliance & provider constraints

- **No REQUIRED compliance trigger from the standard list applies to 1.2.** This sub-module carries no call
  content, no recording, no health/PII beyond a business's own public address and phone number (which the
  business itself controls and already intends to publish). Recording-consent basis, two-party-consent
  announcement, and HIPAA/GDPR retention/subject-rights do not attach to a location directory.
- **The one REQUIRED item here is an access-control correctness requirement, not a legal/provider one:**
  CLAUDE.md's Multi-Tenancy & Location Rules make it a hard rule that `request.location` is re-validated
  against `UserLocation` on every request and that a user must never reach a location they are not assigned
  to. "Location Deactivation" as documented is incomplete — and therefore not actually shippable as REQUIRED —
  unless `User.assigned_locations()` also excludes inactive locations, because that is the exact queryset
  `ActiveLocationMiddleware` trusts. See "Repo state checked first" and the Location Deactivation group above.
- **No provider cost lines.** 1.2 touches no Twilio/STT/TTS/LLM usage and appends nothing to
  `calls.CallSession.usage` — it is pure directory CRUD over an existing table, with no runtime surface.
  `agents.AgentSetting.inbound_phone_number` and Twilio credentials remain entirely Module 2's concern; 1.2's
  Location Detail page only renders a placeholder until that module exists.

## Recommended build scope (this pass)

**CRUD sub-module — ZERO new models** (the HARD CONSTRAINTS require this: `tenants.Location` already exists,
migrated, with exactly the field set below — no additive field, no migration this pass):

- **`tenants.Location`** — tenant-scoped (not location-scoped-of-itself; it *is* the location) — the CRUD
  surface (list / create / detail / edit / delete-as-deactivate) is built entirely against this existing model.
  Fields exposed on the create/edit form: `name`, `slug`, `address_line1`, `address_line2`, `city`, `state`,
  `postal_code`, `country`, `timezone`, `phone`, `is_active`. Form base: `TenantModelForm` (not
  `TenantLocationModelForm` — `Location` has no `location` FK). `tenant` is stamped server-side from
  `request.tenant`, never rendered. Justified by: Location List (search/filter), Location Create & Edit
  (structured address + IANA timezone selector + country choice + slug auto-suggest), Location Detail (address
  block, local-time readout, staff roster, defensive agent-setting placeholder), Location Deactivation
  (`is_active` toggle via POST-only delete route, never `.delete()`).

**Riding-along fix (not a new model):** `apps/accounts/models/User.py::assigned_locations()` gets a
`.filter(is_active=True)` clause on the `Location` side, so `ActiveLocationMiddleware` naturally drops a
deactivated location from any affected user's session on their next request. This is required for Location
Deactivation to be correct per CLAUDE.md's Multi-Tenancy & Location Rules; it is a one-line change to existing
code in a foundation app, not a model addition.

**Deferred — no field added this pass, nothing to build:**
- Per-site opening/closing hours (`business_hours`-style field) — not requested by any 1.2 bullet; conceptually
  closer to 1.4 (Provider Working Hours) or a later Module 2 greeting-variables pass. No field exists on
  `Location` for it and none is added here.
- Timezone/address geocoding auto-detect, directory-listing sync — needs an external provider adapter; out of
  scope for this product entirely (no listing-sync capability documented).
- Recent-activity feed on the location detail page — needs `scheduling.Appointment` / `calls.CallSession`,
  neither built yet.
- Site activation/deactivation audit trail — needs a new model, against this pass's zero-model constraint.
- Location "type"/category tag, bulk CSV import — optional enrichment, not requested by any bullet.

## Belongs to sibling sub-modules (parked, not scoped here)

- Assign/unassign staff to a location from either side, provider-flag toggle → 1.3 Staff & Location Assignment
- Per-provider weekly working-hours editor at this location → 1.4 Provider Working Hours
- Twilio inbound number, agent enable toggle, greeting, transfer settings shown for the location →
  2.1 Per-Location Agent Configuration / 2.2 / 2.3 Transfer Settings
- Booking/call activity feed for the location → 4.x Calendar & Bookings / 5.x Call Logs (once those modules
  exist)
- Business-level (tenant-level) name/slug/customer-id/default-timezone editing → 1.1 Business Settings
- Blocking new bookings/agent activity at a deactivated site → the enforcement lives in 2.x (agent enable
  check) and 4.x (booking-creation guard), once those exist; 1.2 only owns the flag

## Out of scope for this product (outside the seven capabilities)

- Location plan/billing limits — no billing capability among login / password-email / calendar / bookings /
  agent setup+Twilio / call transfer / user profile
- Google Business Profile / directory-listing sync to auto-fill address and hours — no listing-integration
  capability is documented anywhere in the product; there is no future module that would own it either

## Deferred (later passes / integrations)

- Timezone/address auto-detect from a geocoding or business-listing provider — needs a new provider adapter
  under `apps/runtime/providers/`, and even then only if a future module actually requires it
- Location recent-activity feed — blocked on Module 4/5 tables not existing yet at this point in the build
  order
- Site activation/deactivation audit log — needs a new model; deferred until there's a concrete requirement to
  justify the extra table
- Bulk CSV location import — unnecessary complexity for a small application's location count
- Per-location "type"/category tag — no current feature depends on branching by it
