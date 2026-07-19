# Research — Sub-module 1.3: Staff & Location Assignment (Module 1 — Business & Locations, `tenants`)

## Repo state checked first

- **LIVE_LINKS in `apps/accounts/navigation.py`:** only `0.1`–`0.4` are built. **Nothing in Module 1 (`1.1`–`1.4`) has
  a `LIVE_LINKS` entry yet** — this research targets `1.3` directly because the invoking prompt named it by
  number, not because `1.1`/`1.2` are done. Concretely: **`apps/tenants` currently ships ONLY
  `models/`, `admin.py`, `apps.py`, `migrations/` and `seed_tenants.py`** — no `views/`, `forms/`, `urls/` or
  `templates/tenants/` package exists yet, and `tenants` is not even wired into the project `urls.py`/sidebar
  routing. Whoever builds `1.3` is, incidentally, standing up the app's view/url/template scaffolding for the
  first time. Flagging this so the build plan doesn't assume a Location list/detail page already exists to hang
  the location-side assignment UI off of (see *Recommended build scope*).
- **Models verified to exist** (grep evidence):
  - `accounts.UserLocation` — `apps/accounts/models/UserLocation.py`. `TenantOwned` (has `tenant`), FKs
    `user` (`settings.AUTH_USER_MODEL`, `related_name='user_locations'`) and `location` (`tenants.Location`,
    `related_name='user_assignments'`), `UniqueConstraint(user, location)`, index `(tenant, user)`, `clean()`
    refuses cross-tenant assignment. **Not itself location-scoped in the query sense** — it is the table that
    *defines* which locations are reachable.
  - `accounts.User.is_provider` — Boolean, already a real column (`apps/accounts/models/User.py` line 144),
    edited today only through `UserAdminForm` at sub-module 0.3 (owner/manager tier-gated).
  - `accounts.User.assigned_locations()` — `Location.objects.filter(tenant_id=self.tenant_id,
    user_assignments__user=self).distinct()` — the existing read helper; sub-module 0.4's switcher and 0.3's user
    detail page both already call it read-only.
  - `tenants.Tenant`, `tenants.Location` — both present and migrated (`apps/tenants/models/Tenant.py`,
    `Location.py`).
- **Models verified NOT to exist:** `apps/scheduling/` has **no directory at all** — `scheduling.Appointment`,
  `scheduling.Service`, `scheduling.Resource`, `scheduling.Contact` are all unbuilt (Module 4). The "orphan a
  future appointment" guard in the doc bullet must degrade to a no-op today (see *Unassignment Guard* below).
- **Starting backlog from sibling research files** (both explicitly deferred their `UserLocation`-writing features
  to `1.3`):
  - `research-accounts-0.3.md` line 88: *"Assignment Matrix (creating/editing `UserLocation` rows from either the
    user or the location side), the per-location bookable-target behavior of Provider Marking, Unassignment Guard
    → **1.3**"* — 0.3 only renders `assigned_locations()` read-only on `accounts/user/detail.html` and only sets
    the raw `is_provider` bit via `UserAdminForm`.
  - `research-accounts-0.4.md` lines 72–74: *"Creating/editing `UserLocation` rows ... → **1.3**"*, *"the
    'warns before removing an assignment that would leave a user with no location' guard → **1.3**"*, *"Provider
    marking ... → **1.3**"*.
  - These three lines ARE this sub-module's documented scope (`NavAIReceptionist.md` `### 1.3`) verbatim — no
    surprises, just confirmation the boundary was drawn consistently upstream.

## Leaders surveyed (with source links)

The competitor universe named for this task (Bland AI, Retell AI, Vapi, Synthflow, PolyAI, Goodcall, Smith.ai,
Ruby, Rosie, Dialpad AI) turned out to be **thin** on staff↔location assignment specifically — most of these
products route calls to a flat "team/employee directory" rather than modeling a location-scoped roster with
bookable-provider semantics. Confirmed by direct research (not assumed):

1. **Smith.ai** — AI + live-agent receptionist; team/department call routing, no per-location staff-assignment UI
   surfaced in its public docs — [smith.ai/all-features/what-we-do](https://smith.ai/all-features/what-we-do)
2. **Ruby Receptionists** — live/AI receptionist; a flat **employee directory**, bulk-edited via a downloadable
   spreadsheet re-uploaded to support staff rather than an in-product grid —
   [Updating Your Employee Directory](https://rubyhelpcenter.helpjuice.com/company-information/updating-your-employee-directory)
3. **Dialpad AI (Virtual Receptionist / Auto Attendant)** — the one AI-receptionist-adjacent product with a real
   assignment mechanic: **"Assign Operators to Departments"** — an admin bulk-assigns one operator to several
   departments (the closest analogue to locations) in a single action, and the same screen bulk-*removes* —
   [Assign Operators to Departments](https://help.dialpad.com/docs/assign-operators-to-departments),
   [Virtual Receptionist](https://www.dialpad.com/features/virtual-receptionist/)
4. **Goodcall** — multi-location AI voice agent; models "Directory contacts" as transfer targets who never log
   into the dashboard, distinct from dashboard team members — a Module 2.3 (Transfer Settings) concept, not a
   location-assignment one —
   [Goodcall](https://www.goodcall.com/), [Top AI Receptionist for Multi-Location](https://www.ilounge.com/articles/top-ai-receptionist-for-companies-with-multiple-locations)
5. **Square (Team Management + Appointments)** — the strongest reference for this sub-module even though it's a
   secondary source: a team member is **explicitly assigned to one or more locations**, and only sees/affects data
   for those locations; separately, **Square Appointments requires a staff member to be marked bookable AND
   assigned to a location** before they appear in that location's booking flow —
   [Add and manage team members](https://squareup.com/help/us/en/article/8356-add-and-manage-team-members),
   [Create and edit permission sets](https://squareup.com/help/us/en/article/5822-employee-permissions),
   [Manage bookable staff schedules](https://squareup.com/help/ca/en/article/8443-manage-staff-schedules-and-availability-with-square-appointments)
6. **Toast POS** — employees get a profile **per location** with location-level permission **overrides** on top of
   a group/job default (visually: grey = inherited, blue = overridden) —
   [Assign Employees to Multiple Locations](https://support.toasttab.com/en/article/Assigning-Employees-to-Multiple-Locations),
   [Assigning User Access Permissions](https://support.toasttab.com/en/article/Assigning-User-Access-Permissions)
7. **Mindbody** — **permission groups** assignable in bulk to many staff at once; a "restrict reports to my
   assigned location" toggle and a "let staff switch between locations while logged in" toggle model exactly the
   read-boundary `ActiveLocationMiddleware` already enforces here —
   [Staff Permissions explained](https://support.mindbodyonline.com/s/article/203253743-Staff-permissions-explained?language=en_US),
   [Permission groups](https://support.mindbodyonline.com/s/article/203253763-Permission-groups?language=en_US)

Bland AI, Retell AI, Vapi and Synthflow are single-agent/single-number developer platforms — they have no
multi-location staff-roster concept at all (a "location" there is just a phone number on an agent config, which is
Module 2's domain, not 1.3's). They are noted and excluded rather than stretched to fit.

## Feature catalog (this sub-module only)

### Assignment Matrix
- **Bidirectional bulk assignment (add/remove many `UserLocation` rows in one submit)** — one form action creates
  and deletes several `UserLocation` rows at once instead of one-row-at-a-time — · seen in: Square (multi-select
  locations per team member), Toast (assign employee to multiple locations from one dropdown), Dialpad (assign one
  operator to several departments/remove from several in one action) · priority: **table-stakes**
  · model: reuses `accounts.UserLocation` (create/delete only — tenant-scoped join row, not itself
  location-scoped) · realtime: post-call (back-office admin action, never reached from a live call)
  · tool-surface: pure UI — no LLM tool; identity of the acting manager is `request.user`/`request.tenant`, never
  a posted id · buildable now.
- **Single matrix/grid page as the one surface for "either side"** — because this product seeds **2 locations per
  tenant** and a handful of staff (`seed_tenants.py`, `seed_accounts.py`), a full rows-are-users ×
  columns-are-locations checkbox grid is genuinely legible at this scale — one page satisfies "from the user side"
  (toggle a row) and "from the location side" (toggle a column) at once, which is more elegant here than building
  two separate CRUD forms. This is a **product-specific synthesis**, not a literal pattern any surveyed product
  ships (Square/Toast/Dialpad all use per-record multi-select because their location counts are much larger) ·
  priority: **differentiator** (the underlying bulk-assign capability above is table-stakes; the single-grid
  *presentation* of it is this product's own call) · model: reuses `accounts.UserLocation` · realtime: post-call
  · tool-surface: pure UI · buildable now — **but see the build-scope note**: `1.2` (Location Directory) is
  unbuilt, so there is no Location list/detail page to link a location-scoped entry point from yet.
- **Per-user entry point** — from `accounts:user_detail` (0.3's existing page, which today only *renders*
  `assigned_locations()` read-only), add a "Manage locations" action that opens the matrix pre-filtered/scrolled
  to that user's row · seen in: Square's team-member profile carries its own location multi-select · priority:
  table-stakes · model: reuses `accounts.UserLocation` · realtime: post-call · tool-surface: pure UI · buildable
  now.
- **Per-location entry point** — the mirror image, opening the matrix pre-filtered to one location's column · seen
  in: Square's location roster, Mindbody's per-site staff list · priority: table-stakes (the doc bullet explicitly
  requires *"from either the user or the location side"*) · model: reuses `accounts.UserLocation` · realtime:
  post-call · tool-surface: pure UI · buildable now, contingent on at least a minimal Location page existing to
  link from (see build-scope note).
- **Spreadsheet export/bulk-import of assignments** — download the current roster, edit offline, re-upload · seen
  in: Ruby (download/re-upload workflow routed through human support staff, not self-service) · priority:
  differentiator · model: reuses `accounts.UserLocation`, no new table needed (a CSV parser writing/deleting rows
  through the same validated path) · realtime: post-call · tool-surface: pure UI · **deferred** — disproportionate
  surface area for a small tenant's staff count; the matrix already covers the same ground in one screen.

### Provider Marking
- **Bookable-roster intersection (is_provider ∧ assigned)** — a location's "bookable providers" are exactly the
  users where `is_provider=True` **and** a `UserLocation` row ties them to that location; this computed set is
  what Module 4's provider dropdown and Module 3's `book_appointment` tool will read later · seen in: Square
  Appointments (staff must be BOTH bookable-flagged and location-assigned to appear in that site's booking flow),
  Mindbody (staff profile capability × assigned location) · priority: **table-stakes** · model: reuses
  `accounts.User.is_provider` (existing column) + `accounts.UserLocation` (existing table) — no new field, this is
  a queryset, not a stored flag · realtime: post-call (this sub-module only computes/displays the set; the tool
  that reads it live is Module 3/4's job) · tool-surface: pure UI here — flag explicitly for the Module 4 `todo`
  agent that this is the queryset its provider-choice dropdown and its future booking tool must use · buildable
  now.
- **Provider badge + inline toggle on the roster** — show a "Provider" badge per row in the matrix/roster and let
  a manager flip `is_provider` right there (HTMX POST to a small toggle endpoint) instead of forcing a detour
  through `accounts:user_edit`'s full form · seen in: Square (mark-bookable is done in the same flow as location
  assignment, not a separate settings screen) · priority: **table-stakes** — this is literally the doc bullet's
  wording ("Flags a user as a provider ... at the locations they are assigned to") read as an in-context action,
  not just a read display · model: reuses `accounts.User.is_provider`, written through the *same* tier-gated path
  0.3 already validates (owner/manager only) — this sub-module adds a second write surface for the same field, so
  it must reuse `UserAdminForm`'s validation intent, not duplicate ad hoc `request.POST` handling · realtime:
  post-call · tool-surface: pure UI · buildable now.
- **Per-location or per-service bookable scope** — Square/Mindbody let a staff member be bookable for only some
  services or only some sites at a finer grain than "assigned or not" · priority: differentiator · model: would
  need a field on `UserLocation` (or a join to `scheduling.Service`) that does not exist and cannot be added this
  pass (zero-migration constraint) · **deferred** — flagged for a later pass once/if the product needs
  per-service staff scoping; today `is_provider` is a single tenant-wide flag and assignment is binary.

### Unassignment Guard
- **No-location-left warning** — before deleting a `UserLocation` row, check whether the user has *any other*
  assignment; if this is their last one, block (or require explicit confirmation) rather than silently leaving
  them locationless · seen in: implied by Square/Mindbody's own constraint that a team member must be assigned
  somewhere to do anything; mirrors this product's own existing idiom — `accounts/views/Users.py`'s
  `_is_last_owner()` guard on tier demotion/deactivation is the same "would this leave the business with zero of
  X" shape, just over locations instead of owners · priority: **table-stakes** (named directly in the doc bullet)
  · model: a queryset over the existing `accounts.UserLocation` table —
  `UserLocation.objects.filter(user=user).exclude(pk=this_row.pk).exists()` — no new field · realtime: post-call
  · tool-surface: pure UI, server-side re-check (never trust a `confirm()` dialog alone, per the CRUD-delete
  pattern already used at `user_delete_view`) · buildable now.
- **Orphan-future-appointment warning, degrading safely today** — before removing a `UserLocation` row (or before
  a manager unmarks `is_provider`), warn if `scheduling.Appointment` has a future row for that
  `(provider=user, location=location)` pair. **`scheduling.Appointment` does not exist yet** (grep confirmed
  no `apps/scheduling/` directory), so this must be a guard **helper** that returns `0`/no-op until Module 4
  lands, not a hard dependency:
  ```python
  # apps/tenants/views/_helpers.py
  def future_appointment_count(user, location):
      """0 when scheduling.Appointment is unbuilt (Module 4). Swap the body for a
      real filtered .count() once it ships — no caller changes."""
      try:
          from apps.scheduling.models import Appointment
      except ImportError:
          return 0
      return Appointment.objects.filter(
          provider=user, location=location,
          status__in=['scheduled', 'confirmed'],
          start_at__gte=timezone.now(),
      ).count()
  ```
  · priority: **table-stakes** (named directly in the doc bullet, and it is cheap to build the stub correctly
  now so Module 4 only has to fill in the body) · model: no new model; reads the future `scheduling.Appointment`
  via `Appointment.provider` + `Appointment.location` (both confirmed in `NavAIReceptionist-ERD.md` §3.3) once it
  exists · realtime: post-call · tool-surface: pure UI · buildable now as a safe stub / **integration-later** for
  the real count.
- **Guard messaging mirrors the deactivation idiom, not a hard block** — 0.3 already prefers "warn + let the
  manager confirm" over "silently forbid" (see `_is_last_owner()` producing a `messages.error` + redirect rather
  than deleting anyway). The doc bullet says *"Warns before removing"*, not *"prevents removing"* — so the
  no-location and orphan-appointment checks should render as an inline confirmation warning
  (`"Removing {user} from {location} will leave them with no assigned location and they'll be prompted to
  choose one at next login. Continue?"` / `"...has 2 upcoming appointments at this location that will lose their
  assigned provider. Continue?"`) rather than a hard 403 · priority: table-stakes · tool-surface: pure UI ·
  buildable now.

### Beyond the bullets
- **Search/filter on the roster/matrix** — filter the grid by tier, by provider flag, and search by name, mirrors
  the filter idiom already built for `accounts:user_list` (0.3) · seen in: Mindbody/Square staff lists all filter
  by role/status · priority: table-stakes (mandated by this project's own Filter Implementation Rules for any list
  surface, not just a competitor pattern) · model: reuses `accounts.User`/`accounts.UserLocation` querysets ·
  realtime: post-call · tool-surface: pure UI · buildable now.
- **Assignment-count summary** — "Assigned to 2 of 2 locations" / "0 of 2 — cannot be booked or seen in the call
  log" badges on the user list/detail and the matrix header · seen in: Square surfaces assigned-location counts on
  the team roster · priority: common · model: computed from `accounts.UserLocation`, no new field · realtime:
  post-call · tool-surface: pure UI · buildable now.
- **Empty-roster warning on a location** — a location with zero assigned staff (or zero *providers*) flagged with
  an empty-state banner, since that location's agent would have nobody to transfer to or book against · seen in:
  Mindbody warns on an empty/unstaffed location · priority: common · model: computed, no new field · realtime:
  post-call · tool-surface: pure UI · **this specific read-only rendering on the Location *detail* page itself
  belongs to `1.2`** (whose doc bullet already claims "shows ... assigned staff" on that page) — `1.3` should ship
  the underlying assign/remove actions and MAY surface the same warning on its own matrix/roster view, but should
  not be the one authoring `1.2`'s Location Detail template.
- **"Home"/primary location per staff member** — Square/Mindbody let a multi-location employee have one flagged
  default site · priority: differentiator · model: would need a new field (`UserLocation.is_primary` or similar)
  · **deferred** — no schema changes are in scope this pass; `0.4`'s `activate_sole_location()` already covers
  the single-assignment case, and a user with 2+ assignments is prompted to choose, which is an adequate substitute
  today.

## Compliance & provider constraints

- **No REQUIRED consent/HIPAA/GDPR trigger.** This sub-module never touches recording, transcripts, telephony
  provider calls, or the `Contact` PII table — it is entirely internal staff/location administration. None of the
  call-recording consent, two-party-consent announcement or retention/subject-rights obligations apply here; they
  belong to Modules 2 (`2.2`/`2.3`), 3 and 5.
  - **No provider-cost implication.** No Twilio/STT/TTS/LLM call is made by anything in this catalog, so nothing
    here appends to `calls.CallSession.usage`.
- **The one real constraint is the cross-location IDOR boundary named in the task brief, and it is a hard
  security rule, not a priority tier:**
  - Every dropdown/queryset the matrix, the per-user entry point and the per-location entry point offer MUST be
    narrowed to `tenant=request.tenant` before rendering — a `<select>` of users or locations built from
    `User.objects.all()` / `Location.objects.all()` is a cross-tenant leak even if the POST handler re-validates.
  - The POST handler that writes `UserLocation` rows must re-derive both the user and the location from
    tenant-scoped querysets keyed off the posted pks — never trust a posted `user_id`/`location_id` as already
    belonging to this tenant, exactly the pattern `UserLocation.clean()` already enforces at the model layer (its
    cross-tenant check is defense-in-depth, not the only control).
  - `UserLocation` rows are the table `ActiveLocationMiddleware` and `switch_location_view` (0.4) authorize
    against on every request — a bug here (creating a row for the wrong tenant's user or location) is not merely
    a display bug, it is a session hijack of the location-scoping boundary itself.

## Recommended build scope (this pass)

**CRUD sub-module — but ZERO new models.** `1.3` delivers its CRUD entirely as new **views/forms/urls/templates**
over the already-migrated `accounts.UserLocation` table and the already-migrated `accounts.User.is_provider`
column. No `makemigrations` output is expected from this sub-module.

- **No new model.** `accounts.UserLocation` (create/delete only, no new fields) — tenant-scoped, and it is the
  table that itself decides what "location-scoped" means for everything downstream. `accounts.User.is_provider`
  (existing Boolean) — tenant-scoped, written a second time through a new tier-gated surface.

**Where the code lives — a deliberate cross-app split, precedented by Module 3's "writes but doesn't own":**
`NavAIReceptionist.md`'s Module Index assigns "staff↔location assignment" to Module 1 (`tenants`), while the
`UserLocation` **model** is declared and migrated inside Module 0 (`accounts`), because `AUTH_USER_MODEL` had to
exist before anything else. So `1.3`'s views/forms/urls belong in `apps/tenants/`, importing
`from apps.accounts.models import User, UserLocation` (an ordinary absolute runtime import across apps — not a
model-to-model FK, so it does **not** trip the `AUTH_USER_MODEL` import-cycle rule that only applies to `models.py`
files). `tenants` is a foundation app (Modules 0–1), so per the Backend Package Structure rule its files stay
**flat** — no sub-module folder — e.g. `apps/tenants/views/UserLocation.py`, `apps/tenants/forms/UserLocation.py`,
alongside the (not-yet-written) `apps/tenants/views/Location.py` from `1.2`.

**Build-order note for the `todo`/orchestrator, not a research decision:** the location-side entry point and the
matrix's "column" needs *something* to link from on the Location side, and `1.2` (Location Directory) has not
been built yet — `apps/tenants` currently has no `views/`/`urls/`/`templates/tenants/` at all. Two honest options,
neither of which is this file's call to make: (a) build a minimal Location list/detail first as part of standing
up `1.3`'s scaffolding (narrow, read-mostly, not the full `1.2` feature set), or (b) sequence `1.2` ahead of `1.3`
despite the numeric order this run was given. Either way the matrix/roster views themselves need no new model.

**What ships:**
- A matrix/roster view (`tenants:staff_locations` or similar) — rows = tenant's active users, columns = tenant's
  active locations, checkbox cells create/delete `UserLocation` rows, one submit applies the whole diff; owner/
  manager tier-gated (reuse the existing `tier_required('owner', 'manager')` decorator from
  `apps/accounts/views/_helpers.py` — cross-app import, no new gate to invent). Optional `?user=<pk>` /
  `?location=<pk>` query params pre-filter/scroll to satisfy "from either side" without duplicating the view.
- An inline provider-toggle POST endpoint (`tenants:toggle_provider` or folded into the matrix's own POST) writing
  `User.is_provider`, tier-gated the same way `UserAdminForm` already is.
- The two guard helpers (`future_appointment_count`, and a "would this leave the user with zero locations" check)
  living in `apps/tenants/views/_helpers.py` since both the matrix and any future per-row remove action call them.
- Extending `accounts/user/detail.html`'s existing read-only "Assigned locations" card with a "Manage locations"
  action linking into the new matrix — this is the ONE template edit `1.3` makes outside its own app; everything
  else is new `templates/tenants/` files.
- A `LIVE_LINKS["1.3"]` entry in `apps/accounts/navigation.py` pointing at the new matrix view.

**Deferred from this pass (no schema change fits the zero-migration constraint):**
- Per-location role/title override (Toast-style inherited-vs-override permissions) — needs a field on
  `UserLocation` that isn't there.
- Per-service/per-skill bookable scoping — needs a join `UserLocation` doesn't have, and depends on
  `scheduling.Service` which doesn't exist yet.
- A "primary/home location" flag per staff member — needs a new field.
- CSV/spreadsheet bulk import — disproportionate for this tenant's staff scale; the matrix already covers it.

## Belongs to sibling sub-modules (parked, not scoped here)

- Location list/create/edit/deactivate, and the Location Detail page's own read-only "assigned staff" table
  render → **1.2** (Location Directory) — `1.3` only supplies the assign/unassign *actions*, not that page's
  primary CRUD or its read display.
- Per-location provider **working hours** (day/interval editor, overlap validation, timezone resolution) →
  **1.4** (Provider Working Hours) — a materially different feature from "is this person assigned/bookable here
  at all."
- `is_provider` as a plain field edit (not the location-assignment context) and the tier-gated
  `UserAdminForm`/`user_edit_view` it already lives on → **0.3** (already built).
- The read-only `assigned_locations()` display and the `my_locations`/switcher self-service flow → **0.4**
  (already built) — `1.3` never edits from the *signed-in user's own* side, only from a manager's.
- Provider-as-bookable-target inside an actual booking flow (the provider `<select>` on an appointment form, the
  `book_appointment` LLM tool's provider resolution) → **Module 4** (`scheduling`) and **Module 3** (`runtime`) —
  `1.3` only produces the queryset those will read.
- Transfer-target directory contacts (Goodcall's model of a person who receives transferred calls but never logs
  in) → **2.3** (Transfer Settings) — a different table's job (`AgentSetting`'s transfer destination numbers), not
  `UserLocation`.

## Out of scope for this product (outside the seven capabilities)

- Toast/Square-style granular per-location, per-resource permission *sets* (e.g., "can void a transaction," "can
  edit the menu at this site only") — this product has exactly one tenant-wide role field (`User.tier`:
  owner/manager/staff) by design; a permission-matrix engine is enterprise POS/scheduling scope this product does
  not carry.
- Payroll/scheduling/shift-clock features that Square and Toast bundle alongside location assignment (labor cost
  reporting, time clocks) — outside the seven capabilities entirely.

## Deferred (later passes / integrations)

- Per-location role/title override on `UserLocation` — needs a new field; explicitly out of this pass's
  zero-migration constraint.
- Per-service/per-skill staff scoping — depends on `scheduling.Service` (Module 4, unbuilt) and a join
  `UserLocation` does not have.
- "Primary/home location" flag — needs a new field.
- CSV/spreadsheet bulk import/export of assignments — the matrix already covers this tenant scale; revisit only if
  a tenant's headcount grows well past what a grid can show legibly.
- The real (non-stub) body of `future_appointment_count()` — lands automatically once Module 4 ships
  `scheduling.Appointment`; the call site in `1.3` does not change.
