# Research — Sub-module 1.4: Provider Working Hours (Module 1 — Business & Locations, tenants)

## Repo state checked first

- **LIVE_LINKS built so far in module 1:** none. `apps/accounts/navigation.py` only has
  `'0.1'`–`'0.4'` entries; `1.1`/`1.2`/`1.3`/`1.4` are all unbuilt sidebar placeholders today. This
  research targets `1.4` directly as instructed — it does not imply 1.1–1.3 have shipped their
  own CRUD pages yet, only that the **models** they'll eventually manage already exist and are
  migrated (verified below), so 1.4 can be built against them regardless of UI build order.
- **`apps/tenants` currently contains ONLY** `models/` (`Tenant.py`, `Location.py`, `_base.py`),
  `admin.py`, `apps.py`, `migrations/0001_initial.py`, `management/commands/seed_tenants.py`. No
  `forms/`, `views/`, or `urls/` package exists yet — confirmed via `Glob apps/tenants/**/*`.
- **Sibling models verified to exist (grep evidence), all already migrated:**
  - `apps\accounts\models\User.py` — `class User(AbstractBaseUser, PermissionsMixin, TimeStamped)`
    carries `is_provider = models.BooleanField(default=False)` and
    `provider_hours = models.JSONField(default=dict, blank=True)`, documented in-field as
    `{"<location_id>": [{"start_time": "09:00", "end_time": "17:00", "days": ["mon","tue"]}]}`.
    Also carries `assigned_locations()` — the authorization boundary (locations reachable via
    `UserLocation`).
  - `apps\tenants\models\Location.py` — `class Location(TenantOwned)` carries `timezone` (IANA
    string, default `'UTC'`), a `tzinfo` property (`ZoneInfo`, degrades to UTC on a bad/unknown
    name) and `local_now()`. This is the only correct timezone for interpreting an interval.
  - `apps\accounts\models\UserLocation.py` — `class UserLocation(TenantOwned)`, unique on
    `(user, location)`, `clean()` rejects cross-tenant assignment. This is the assignment table
    1.4 must check against before accepting an hours entry for a location.
  - `NavAIReceptionist-ERD.md` §User confirms the same JSON shape verbatim
    (`provider_hours` row, line 153) — the doc and the code agree, so no divergence to reconcile.
- **No `WorkingHours` / `ProviderSchedule` model exists anywhere in the repo** — confirmed by the
  `apps/tenants` file listing above and by the `User.py` grep; the eleven-model ERD ceiling has no
  room for one. This sub-module ships **zero new models and zero migrations** — the whole feature
  is a validated editor + a read helper over the existing `User.provider_hours` JSON column.
- Reusable, not re-planned: `accounts.forms._common.TenantModelForm` /
  `TenantLocationModelForm` (`apps\accounts\forms\_common.py:63,108`),
  `accounts.views._common.paginate()` (`apps\accounts\views\_common.py:42`),
  `accounts.views._helpers.tier_required()` (`apps\accounts\views\_helpers.py:155`), plus
  `base.html`, `_pagination.html`, `_empty_state.html`, theme.css badge modifiers.
- Sibling research files present: `research-accounts-0.1.md`, `-0.2.md`, `-0.3.md`, `-0.4.md`.
  None of them touch provider hours (0.3 is the user directory/tier CRUD, 0.4 is the location
  switcher) — nothing to avoid re-surveying, no deferred backlog handed to 1.4 from those files.

## Leaders surveyed (with source links)

1. **Smith.ai** — human-backed virtual receptionist with an explicit per-team-member work-schedule
   editor that drives call routing — [Availability and Work Schedule](https://docs.smith.ai/article/y2ep35f8tx-availability-and-work-schedule), [Appointment Scheduling](https://smith.ai/features/appointment-scheduling-service)
2. **Ruby Receptionists** — live receptionist service with business-hours + calendar-synced call
   handling — [Ruby's Business Hours and Availability](https://rubyhelpcenter.helpjuice.com/en_US/call-handling/ruby%E2%80%99s-business-hours-and-availability)
3. **Dialpad AI (Auto Attendant / AI Receptionist)** — business-hours-aware call routing with
   dedicated holiday overrides — [Manage Holidays & Routing Rules](https://help.dialpad.com/docs/set-holiday-hours-routing-rules), [Virtual Receptionist](https://www.dialpad.com/features/virtual-receptionist/)
4. **Goodcall** — AI phone agent with a business-hours toggle plus season/holiday exceptions,
   ingested from Google Business Profile — [AI Receptionist](https://www.goodcall.com/voice-ai/ai-receptionist)
5. **Rosie** — 24/7 AI answering service that auto-learns business hours at setup for
   after-hours-vs-default-instruction branching — [After Hours Answering Service](https://heyrosie.com/solutions/after-hours-answering-service)
6. **Retell AI / Vapi / Synthflow / Bland AI** — voice-agent platforms surveyed for whether they
   own a staff-hours editor themselves; they don't — they **delegate to a connected calendar**
   (Cal.com/Calendly) rather than model provider hours natively — [Retell vs Synthflow vs Bland comparison](https://www.retellai.com/blog/retell-vs-synthflow-vs-bland-vs-11x). Confirms the
   competitor universe's telephony platforms are not the right reference for the editor UX itself;
   Acuity/Calendly/Mindbody/Square (secondary references, as instructed) are.
7. **Acuity Scheduling** — per-calendar (per-staff) availability with multi-block/split-shift entry
   and date-specific overrides — [Managing availability and calendars](https://help.acuityscheduling.com/hc/en-us/articles/16676883635725-Managing-availability-and-calendars), [Setting repeating hours](https://help.acuityscheduling.com/hc/en-us/articles/16676880363277-Setting-repeating-hours-in-Acuity-Scheduling)
8. **Calendly** — named "Schedules": weekly list-view hours, one timezone per schedule, per-host
   custom-schedule override, apply-to-multiple-event-types — [How to manage availability for your users](https://calendly.com/help/how-to-manage-availability-for-your-users), [Time Zones overview](https://calendly.com/help/time-zones-overview)
9. **Square Appointments** — per-location staff schedules selected via a location dropdown; a
   location's own timezone seeds its calendar and staff-hours context — [Manage bookable staff schedules and availability](https://squareup.com/help/us/en/article/8443-manage-staff-schedules-and-availability-with-square-appointments), [Multi-Location Scheduling](https://squareup.com/au/en/appointments/features/multi-location)
10. **Mindbody** — multi-location staff management with per-location access control and a
    centralized staff-schedule view — [Multi-location Management](https://www.mindbodyonline.com/business/multi-location-management), [Staff Management Features](https://www.mindbodyonline.com/business/staff-management)

## Feature catalog (this sub-module only)

### Per-Location Hours
- **Location-keyed weekly schedule** — a provider's hours are a dict keyed by location id, not one
  flat weekly grid, so the same person can have Mon/Wed/Fri 9–5 at Location A and Tue/Thu 10–6 at
  Location B · seen in: Square Appointments, Mindbody, Smith.ai (per-team-member override of the
  business default) · priority: **table-stakes** · model: reuses `accounts.User.provider_hours`
  (already keyed by location id — no change) (tenant-scoped via `User.tenant`, the JSON value
  itself is per-location) · realtime: post-call (setup-time config, never touched mid-call) ·
  tool-surface: pure UI — no new tool, this sub-module is not on the call path itself · buildable
  now.
- **Location-scoped editor, not a global grid** — the edit form/page operates on one
  `(user, location)` pair at a time (a location selector + that location's interval list), mirroring
  Square's "select the Location dropdown" pattern · seen in: Square Appointments, Acuity
  (per-calendar availability) · priority: table-stakes · model: reuses `User.provider_hours[str(location.pk)]`
  · realtime: post-call · tool-surface: pure UI · buildable now.
- **Assignment guard — hours only at assigned locations** — reject (or strip) an hours entry keyed
  to a location the provider has no `UserLocation` row for; an admin editing a provider's schedule
  must not silently create a dead/stale entry for an unassigned site · seen in: implied by every
  leader's "select staff, then select their location" flow (Square, Mindbody) where the location
  picker is itself scoped to where the person works · priority: **REQUIRED** (data-integrity
  analogue of the product's location-scoping rule — an orphaned hours entry for a location the
  provider can't reach silently corrupts Module 4's availability search once it exists) · model:
  validated against `accounts.UserLocation` (verified model, `user=<provider>, location=<key>`)
  (tenant-scoped) · realtime: post-call · tool-surface: pure UI (server-side form validation) ·
  buildable now.

### Day & Interval Editor
- **Multiple time blocks per day (split shifts)** — a lunch-break-style gap (9–12, 1–5) is two
  interval entries, not one field with a break sub-type · seen in: Smith.ai ("two separate time
  blocks" for a lunch gap), Acuity (comma-separated start times / combined ranges) · priority:
  **table-stakes** · model: reuses the existing list-of-intervals shape — no schema change needed,
  since `days` already lets one interval apply to several weekdays and nothing stops two intervals
  sharing a day (tenant-scoped) · realtime: post-call · tool-surface: pure UI + server-side
  overlap validation (see below) · buildable now.
- **One interval, many weekdays** — an interval carries a `days` list so "Mon–Fri 9–5" is one row,
  not five · seen in: Calendly (weekly List view, one row per time block, applied across days),
  Acuity (repeating hours) · priority: table-stakes · model: reuses `days: ["mon", ...]` on the
  existing interval dict — already the as-built shape · realtime: post-call · tool-surface: pure UI
  · buildable now.
- **Overlap validation within a day** — reject a save where two intervals share a weekday and their
  `[start_time, end_time)` ranges intersect; reject `end_time <= start_time` · seen in: implied by
  every leader (none allow contradictory overlapping availability) · priority: **REQUIRED**
  (explicitly named in the sub-module's own bullet — "validating that intervals do not overlap" —
  and the wrong answer double-books or silently drops half a shift) · model: pure Python validator
  over the existing JSON list, no model needed · realtime: post-call · tool-surface: server-side
  form validation (`ValidationError`, not a tool) · buildable now.
- **"Copy to other days" shortcut** — after entering Monday's hours, one click applies them to
  Tue–Fri (or any subset) instead of re-typing four more rows · seen in: Calendly ("set the same
  hours for all hosts" / apply-across pattern), Acuity ("repeating hours"), common weekly-hours
  editors generally · priority: common · model: none — pure client-side convenience that still
  writes the same `days` list shape · realtime: post-call · tool-surface: pure UI (HTMX/JS,
  no new tool) · buildable now.
- **Copy hours to another location** — a provider who keeps identical hours at two sites can copy
  Location A's interval list into Location B rather than re-entering it · seen in: Square
  Appointments (multi-location shift view), implied by Mindbody's centralized staff view · priority:
  common · model: none — copies one JSON sub-list to another key in the same `provider_hours` dict
  · realtime: post-call · tool-surface: pure UI · buildable now.
- **Bulk day-select via checkboxes, not free text** — days are a fixed multi-select
  (Mon…Sun checkboxes), not a text field the admin types into, avoiding the parsing fragility of
  Acuity's "250-character comma-separated string" approach · seen in: Calendly, Smith.ai (structured
  form fields, not free text) · priority: table-stakes (this product already stores `days` as a
  JSON list, not a string — the UI should match) · model: reuses `days` list · realtime: post-call ·
  tool-surface: pure UI · buildable now.

### Availability Source of Truth
- **Read helper for Module 4's availability search** — a small, pure function that turns one
  provider's stored JSON into usable working intervals for a given location and weekday, so Module
  4 never re-parses the JSON shape itself · seen in: every leader's underlying architecture
  (a normalized "staff hours" query feeding the booking engine) — Square's and Acuity's booking
  flows both resolve to exactly this kind of per-staff/per-day interval lookup before an
  availability grid is drawn · priority: **REQUIRED** (the sub-module's own bullet says a slot must
  never be offered outside a provider's configured window — Module 4 cannot honor that without a
  stable read path) · model: reuses `accounts.User.provider_hours` — no new model, this is a
  service function, not a table · realtime: **the function itself is a plain, allocation-light,
  no-I/O parser (safe to call from a live-call hot path later); the sub-module 1.4 UI that produces
  the JSON it reads is post-call config-time** · tool-surface: not a tool in 1.4 — it is the utility
  Module 4's future `check_availability`-style tool will call internally; **name and signature
  below**, so Module 4 doesn't reinvent the parse.
- **No-hours-configured means unavailable, not "anytime"** — an empty or missing location key in
  `provider_hours` must resolve to zero working intervals, never to "no restriction" — this is the
  safe default named in the "never offer a slot outside a provider's configured window" bullet ·
  seen in: implied by Smith.ai/Dialpad's after-hours branching (absence of configured hours routes
  to the "not available" path, never to "always available") · priority: **REQUIRED** · model:
  encoded in the read helper's return contract (`[]` on missing/malformed data, never raises) ·
  realtime: the parser is hot-path-safe; the design decision itself is documented here for Module 4
  · tool-surface: pure logic, documented contract · buildable now.

### Timezone Resolution
- **Interval times are naive; the location supplies the timezone** — `provider_hours` stores plain
  `"HH:MM"` strings with no offset; the read helper returns naive `datetime.time` objects and the
  **caller** (Module 4, later) combines them with a calendar date and `Location.tzinfo` to get an
  aware boundary — 1.4 does no timezone math of its own beyond validating the strings parse as
  times · seen in: Calendly ("each schedule is tied to a single time zone... Calendly will
  automatically adjust and show the correct times"), Square (a location's own timezone seeds its
  calendar and staff hours) · priority: **REQUIRED** (the sub-module's own bullet: "never the
  browser's or the business default") · model: reuses `tenants.Location.timezone` /
  `Location.tzinfo` (verified property, degrades to UTC on a bad name) — no new field · realtime:
  post-call, but the contract matters for Module 4's later hot-path use · tool-surface: none — a
  documentation/contract concern, enforced by never accepting a timezone from the request in the
  1.4 form (the location picker selects a `Location` row; its `.timezone` is read-only display,
  never a form input on the hours editor) · buildable now.
- **Display the location's local time on the editor, not the admin's browser time** — when an
  owner in one timezone edits a provider's hours at a location in another, the editor must label
  "9:00 AM (America/Chicago)" using `Location.timezone`, never `Intl`/browser-local formatting ·
  seen in: Calendly ("you enter your availability based on the local time where you will be"),
  Square (location timezone drives the whole location context) · priority: table-stakes · model:
  reuses `Location.timezone` for display only · realtime: post-call · tool-surface: pure UI (server
  renders the label; **no client-side timezone conversion**, since the input values are already
  location-local `HH:MM` strings, nothing to convert) · buildable now.

### Beyond the bullets
- **Per-provider override of a location's default hours** — Smith.ai's model is "business default
  schedule, individually overridable per team member." This product has no location-level "default
  hours" concept to override (Location has no hours field, only `timezone`) — **out of scope for
  1.4**: there is nothing to override against; each provider's hours stand alone per location.
- **Date-specific / holiday overrides** (vacation days, one-off closures) — Smith.ai (holidays
  marked available/unavailable, automated pre-holiday reminder), Acuity (date-specific hours,
  temporary repeating hours that auto-revert), Dialpad (holiday routing overrides) · priority:
  differentiator · model: **would need a schema extension** beyond the current
  `{"<location_id>": [interval, ...]}` shape (e.g. a top-level `"exceptions"` key keyed by ISO
  date) — the hard constraint asks for a revised schema only if the researched UX needs one; this
  one does, but it is bigger than "weekly working hours" (the sub-module's actual bullet set) and
  has no natural home among the eleven models either. **Deferred**, not scoped here — see Deferred
  section.
- **Staff-schedule report / weekly grid view across all providers at a location** — Mindbody's
  "Staff Schedule report" — a read surface that shows every provider's hours at a location
  side-by-side · priority: common · model: reuses `provider_hours` across the location's assigned
  users, zero new storage · realtime: post-call · tool-surface: pure UI (a list/report page) ·
  buildable now — good candidate to include in this pass since it's a thin read view over data the
  edit form already produces.

## Compliance & provider constraints

- **No REQUIRED recording-consent / HIPAA / GDPR trigger here.** 1.4 is a business-hours config
  surface with no call audio, transcript or PII-in-motion — the product-wide compliance rules
  (two-party consent, retention) attach to Module 3/5, not this sub-module. Nothing to add here.
- **Labor/scheduling correctness is the closest thing to a compliance concern**: an incorrect
  timezone resolution could cause the (future) availability search to offer a slot when the
  provider is actually off duty, or cause a transfer/callback to reach staff outside their actual
  working hours. This is why Timezone Resolution is marked REQUIRED above, even though it isn't a
  legal mandate — it's the sub-module's own explicit bullet and a correctness invariant the rest of
  the product depends on.
- **No external provider dependency.** 1.4 touches no Twilio/STT/TTS/LLM call and appends nothing
  to `calls.CallSession.usage` — it is pure Django CRUD-over-JSON with zero adapter surface.

## Recommended build scope (this pass)

**ZERO new models, ZERO migrations** — mandated by the hard constraints and confirmed by the model
grep above; there is no `WorkingHours`/`ProviderSchedule` room in the eleven-model ERD, and the
storage (`accounts.User.provider_hours`, `accounts.User.is_provider`) already exists and is
migrated. This sub-module is an **edit-in-place JSON-field editor** over two already-existing,
already-migrated models, plus one read helper Module 4 will import later:

- **`accounts.User.provider_hours`** (existing JSONField, no change) — the field the whole
  sub-module edits. Fields/interactions justified by: Per-Location Hours (location-keyed dict),
  Day & Interval Editor (list of `{start_time, end_time, days}` per location key), Overlap
  validation. FK path: `User.tenant` (tenant-scoped) → the JSON's location keys are validated
  against `tenants.Location.pk` + `accounts.UserLocation` (assignment guard), never trusted as-is.
- **`tenants.Location.timezone` / `.tzinfo`** (existing field/property, no change) — read-only
  input to the editor's display and to the read helper's future timezone math. Justified by:
  Timezone Resolution.
- **`accounts.UserLocation`** (existing model, no change) — read-only authorization check: an
  hours entry may only target a location with a matching `UserLocation` row for that provider.
  Justified by: the Assignment Guard feature above.

**What ships, concretely (backend, all under `apps/tenants` per the module-ownership table — this
app is a foundation app, so no sub-module-level folder, per the flat-layout rule):**
- `apps/tenants/forms.py` (or a small `forms/` package if it grows) — a form/formset that renders
  and validates one location's interval list: per-interval `start_time`, `end_time`, `days`
  (multi-checkbox), plus the overlap/`end>start` validator and the assignment guard. Built on
  `TenantModelForm`'s pattern even though the underlying object is a JSON blob, not a normal model
  form field — `clean()` is where the interval-list validation lives.
- `apps/tenants/views.py` — a `provider_hours_view(request, user_pk)` (location-selector + editor
  for one provider, one location at a time) gated the same way `user_edit_view` is
  (`tier_required('owner', 'manager')`), reading/writing `User.objects.filter(tenant=request.tenant)`
  never `.all()`. Recommend also allowing a provider to self-edit their own hours (`is_self` check,
  mirroring `profile_view`'s pattern) since Calendly's model treats the calendar as the individual's
  own — flag this as a design choice for `todo` to confirm, defaulting to management-tier edit +
  self-service edit both allowed.
- `apps/tenants/services.py` — the read/write helpers below (module-level functions, not tied to
  any package the way Module 4 doesn't exist yet to own them):

  ```
  def get_provider_intervals(user, location, weekday=None):
      """Return (start: datetime.time, end: datetime.time) tuples for `user` at
      `location`, optionally filtered to one weekday code ('mon'..'sun').
      Never raises — malformed/missing JSON, a non-provider, or an unassigned
      location all resolve to []. Pure parsing, no queries inside: caller passes
      already-fetched User/Location instances so this stays safe to call from a
      hot path later (Module 4's availability search)."""

  def validate_provider_hours(intervals, *, assigned_location_ids):
      """Validate one location's proposed interval list before save: HH:MM
      parses, end > start per interval, no two intervals share a day with
      overlapping ranges, and (via the caller) the location id itself is in
      assigned_location_ids. Raises django.core.exceptions.ValidationError with
      a field-level message; used by the form's clean()."""
  ```
  `get_provider_intervals(user, location, weekday=None)` is the named contract Module 4 imports
  later — `from apps.tenants.services import get_provider_intervals`.
- **Staff-schedule report page** (the Mindbody-style read view, Beyond-the-bullets) — a thin list
  view over `UserLocation`/`User.provider_hours` for the active location, no new storage.
- **Templates** (flat, foundation-app layout): `templates/tenants/user/hours.html` (the
  location-scoped editor) and `templates/tenants/user/hours_report.html` (the read-only
  cross-provider view), following the existing `templates/accounts/user/*` visual pattern.
- **`LIVE_LINKS["1.4"]`** entry pointing at the hours editor/report page.
- Tests: overlap rejection, `end<=start` rejection, unassigned-location rejection, timezone-label
  correctness (uses `Location.timezone`, not request locale), idempotent re-save, and
  `get_provider_intervals` unit tests (empty/malformed JSON → `[]`, weekday filter correctness,
  multi-interval split-shift correctness).
- Seeder: extend `seed_tenants.py` (or wherever provider seeding already lives) to populate
  `provider_hours` for at least one provider across two locations with different weekly patterns,
  including one split-shift day — through no external provider (this sub-module has none anyway).

## Belongs to sibling sub-modules (parked, not scoped here)

- Location list/create/edit/detail, location deactivation → **1.2 Location Directory**
- The staff↔location assignment matrix itself (creating/removing `UserLocation` rows), the
  unassignment guard warning → **1.3 Staff & Location Assignment** (1.4 only *reads* `UserLocation`
  to validate, never writes it)
- The business record's own default timezone → **1.1 Business Settings** (irrelevant here — per
  the sub-module's own bullet, the business default timezone must NOT be used for interval
  interpretation)
- `is_provider` flag creation/toggling in the user form → **0.3 User Directory & Roles** (already
  built; 1.4 only reads the flag, doesn't add it)
- Actually consuming these hours to compute bookable slots, the availability grid, the booking flow
  itself → **Module 4 (`scheduling`)**, not yet built. 1.4 ships only the storage-adjacent editor
  and the `get_provider_intervals()` contract Module 4 will call.
- Transfer-hours restriction (`AgentSetting.transfer_working_hours`, a *separate* JSON field for
  when a human transfer is allowed) → **2.3 Transfer Settings**. Do not conflate with
  `provider_hours` — they are two different JSON columns on two different models serving two
  different purposes (bookable slots vs. transfer eligibility).

## Out of scope for this product (outside the seven capabilities)

- Shift-swap / substitute-teacher automation (Mindbody's "Quick Teacher Substitution") — this
  product has no class/instructor-substitution workflow; providers are simply bookable or not.
- IP-restricted per-location login (Mindbody) — a login/access-control feature, not a working-hours
  feature; would belong to 0.1/0.4 if ever pursued, and isn't researched here.
- Payroll/time-clock integration implied by some "staff schedule" tooling (outside all seven
  capabilities — this product tracks bookable availability, not attendance/payroll).

## Deferred (later passes / integrations)

- **Date-specific overrides / holiday exceptions / temporary repeating hours** (Smith.ai, Acuity,
  Dialpad) — needs a schema extension (`"exceptions"` keyed by date) beyond the current
  `{"<location_id>": [interval,...]}` shape and has no natural model home in the eleven-model ERD;
  revisit only if a future pass explicitly re-opens `User.provider_hours`'s shape.
  Recommend NOT bundling into this pass — it changes the JSON contract Module 4 will build against,
  and should ship once, deliberately, not as a 1.4 afterthought.
- **Overnight/multi-day intervals** (Acuity's cross-midnight support) — no evidence any leader in
  the *inbound receptionist* space needs this for staff hours (it's a niche Acuity booking-type
  feature); skip unless a real use case appears.
- **Self-service vs. admin-only editing** — flagged above as a design choice for `todo`/build time
  rather than settled here; both are cheap to support (same form, different `tier_required` vs.
  `is_self` gate) so this is a low-cost decision to defer to implementation.
- **Module 4 availability search itself** — explicitly out of scope per the task's own
  instructions; 1.4 ships only the read contract (`get_provider_intervals`) it will consume.
