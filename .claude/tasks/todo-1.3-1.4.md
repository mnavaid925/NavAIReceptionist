---
# Sub-modules 1.3 + 1.4 — Staff & Location Assignment + Provider Working Hours (Module 1: Business & Locations, `tenants`) — combined plan from research-tenants-1.3.md + research-tenants-1.4.md  (2026-07-19)

**Both sub-modules ship ZERO new models and ZERO migrations.** They are new `apps/tenants/{forms,views,urls}` +
`templates/tenants/` surfaces over three already-migrated tables/fields: `accounts.UserLocation` (create/delete),
`accounts.User.is_provider` (update), `accounts.User.provider_hours` (update, JSON). No `makemigrations` output is
expected from either.

**Repo state this plan is written against** (re-verified, do not re-grep before starting):
- `apps/tenants/` today has only `models/`, `admin.py`, `apps.py`, `migrations/`, `management/commands/seed_tenants.py`.
  A sibling pass (1.1 Business Settings / 1.2 Location Directory, tracked in `.claude/tasks/todo-1.1-1.2.md`) is
  standing up `apps/tenants/forms/`, `apps/tenants/views/`, `apps/tenants/urls.py`, `apps/tenants/views/_common.py`
  and `templates/tenants/location/*` concurrently. **This plan assumes those packages exist by build time** and
  adds 1.3/1.4's entity files into them. If `apps/tenants/urls.py` / `views/__init__.py` / `forms/__init__.py`
  don't exist yet when this plan is executed, create them minimally first (flat modules, no sub-module folder —
  foundation-app rule) rather than blocking.
- `accounts.UserLocation` (`apps/accounts/models/UserLocation.py`): `TenantOwned`, FKs `user`
  (`settings.AUTH_USER_MODEL`, `related_name='user_locations'`) and `location` (`tenants.Location`,
  `related_name='user_assignments'`), `UniqueConstraint(user, location)`, index `(tenant, user)`, `clean()` blocks
  cross-tenant assignment. Confirmed NOT location-scoped in the query sense (it's the table that *defines*
  reachability) — no `location=request.location` filter belongs on reads of it here.
- `accounts.User` (`apps/accounts/models/User.py`): `is_provider` (bool, line 144), `provider_hours` (JSONField,
  default `dict`, line 149, keyed `{"<location_id>": [{"start_time":"HH:MM","end_time":"HH:MM","days":["mon",...]}]}`),
  `assigned_locations()` (line 242), `TIER_CHOICES`, `STATUS_CHOICES`, `display_name`, `initials`. Also confirmed
  NOT location-scoped (tenant-scoped only, per the Multi-Tenancy rules' explicit list) — the staff/location
  admin surfaces built here are **tenant-wide**, not filtered to `request.location`, exactly like the existing
  `accounts:user_list` (0.3) precedent.
- `tenants.Location` (`apps/tenants/models/Location.py`): `timezone` (IANA, default `'UTC'`), `tzinfo` property
  (degrades to UTC on bad name), `local_now()`, `is_active`.
- Reused, not rebuilt: `TenantModelForm` / `style_widgets` (`apps/accounts/forms/_common.py`), `paginate()`
  (`apps/accounts/views/_common.py`), `tier_required(*tiers)` / `safe_redirect_target()`
  (`apps/accounts/views/_helpers.py`), `templates/base.html` (blocks `title`/`content` only),
  `partials/_pagination.html`, `partials/_empty_state.html`. `_is_last_owner()` in `apps/accounts/views/Users.py`
  is the direct precedent for 1.3's "would this leave the business with zero of X" guard shape.
- Demo data available today (`seed_accounts.py`, password `navai-demo-2026`): tenant `acme` (Customer ID
  `ACME-1001`) has `admin_acme` (owner, **2 locations**: downtown+uptown, `is_provider=False`) and
  `acme_downtown` (manager, **1 location** only: downtown, `is_provider=True`) — the single-location provider is
  the exact fixture the "last location" and "self-service hours edit" tests need. Tenant `globex` mirrors this
  with `admin_globex` / `globex_riverside`. **No currently-seeded provider has 2 locations** — 1.4's seeder
  extension adds one (see Backend, 1.4).
- theme.css badge modifiers are colour-named and CLOSED: `badge-green/red/amber/info/muted/slate`. No
  `badge-purple`, no semantic `-success/-danger` names.
- Sidebar: exactly one `LIVE_LINKS["1.3"]` key and one `LIVE_LINKS["1.4"]` key in `apps/accounts/navigation.py`.

---

## Sub-module 1.3 — Staff & Location Assignment

### Shape: CRUD (zero-migration) — one bulk create/delete surface over `accounts.UserLocation`, plus a second
write surface for `accounts.User.is_provider`. No new table.

### Models — NONE new. Tables written:
- [ ] `accounts.UserLocation` — tenant-scoped, NOT location-scoped — create/delete only, no new fields. Written by
      the assignment matrix's single bulk-diff submit (this is the researched "Bidirectional bulk assignment"
      feature — one form action creates AND deletes several rows at once — **not** five per-row CRUD pages; that
      is a deliberate, researched product-specific synthesis for this tenant's small staff/location scale, not a
      gap). FKs: `user` → `settings.AUTH_USER_MODEL` (verified), `location` → `tenants.Location` (verified).
- [ ] `accounts.User.is_provider` — tenant-scoped — updated by a second, in-context write surface (the matrix's
      inline toggle), reusing the same tier gate `UserAdminForm`/`user_edit_view` (0.3) already enforces —
      driver: **Provider Marking**.
- [ ] **CRUD-completeness note for reviewers**: `UserLocation` deliberately has no `list_view`/`create_view`/
      `edit_view`/`delete_view` quintet. Its "list" IS the matrix; its "create+delete" IS the matrix's diff apply.
      This is the researched shape (Assignment Matrix, priority: differentiator over a table-stakes bulk-assign
      capability) — do not add a separate `userlocation_list.html`.

### Backend (`apps/tenants/{forms,views,urls}` — flat, foundation app, no sub-module folder)
- [ ] `apps/tenants/views/_helpers.py` (NEW file, mirrors `apps/accounts/views/_helpers.py`) —
      ```python
      def future_appointment_count(user, location):
          """0 until scheduling.Appointment ships (Module 4) — try/except ImportError,
          never a hard dependency. Call site does not change when Module 4 lands."""
          try:
              from apps.scheduling.models import Appointment
          except ImportError:
              return 0
          return Appointment.objects.filter(
              provider=user, location=location,
              status__in=['scheduled', 'confirmed'],
              start_at__gte=timezone.now(),
          ).count()

      def remaining_assignment_count(user, excluding_location_ids):
          """How many locations `user` would still be assigned to after removing
          `excluding_location_ids` in one diff. 0 means the removal would leave them
          locationless."""
          from apps.accounts.models import UserLocation
          return UserLocation.objects.filter(user=user).exclude(
              location_id__in=excluding_location_ids
          ).count()
      ```
      Also re-export `from apps.accounts.views._helpers import tier_required` so entity views import one path.
- [ ] `apps/tenants/forms/UserLocation.py` — no ModelForm (the matrix is a bulk toggle, not a single-object
      form); houses the POST-parsing/validation helpers instead:
      - `parse_assignment_pairs(post_data)` — parses `request.POST.getlist('assign')` (values `"<user_pk>:<location_pk>"`),
        returns a set of `(int, int)` tuples, silently dropping any value that doesn't parse as `int:int` (a junk
        payload degrades to "no pair", never a 500).
      - `ProviderFlagForm(forms.Form)` — single `is_provider = forms.BooleanField(required=False)`, used by the
        inline toggle endpoint so the write goes through form validation like every other write surface.
- [ ] `apps/tenants/views/UserLocation.py`:
      - `staff_locations_view(request)` — `@login_required @tier_required('owner','manager')`. GET renders the
        matrix: rows = `User.objects.filter(tenant=request.tenant).order_by('full_name','email')` (search `q`,
        `tier`, `provider` filters — same param names/semantics as `user_list_view` in 0.3 — plus a `status`
        filter defaulting to `active`); columns = `Location.objects.filter(tenant=request.tenant, is_active=True)`
        (a `?show_inactive_locations=1` toggle includes inactive ones). Optional `?user=<pk>` / `?location=<pk>`
        pre-highlights/scrolls to that row/column — it does NOT filter the grid, so "from either side" is one
        view, not two (see research: "single grid page" is the differentiator here).
        POST applies the whole diff in one submit:
        1. Re-derive `desired = parse_assignment_pairs(request.POST)`, intersected against tenant-scoped user pks
           and tenant-scoped location pks (`User.objects.filter(tenant=request.tenant).values_list('pk', flat=True)`,
           same for `Location`) — **never trust a posted pk as already belonging to this tenant**, exactly the
           defense-in-depth `UserLocation.clean()` already applies at the model layer.
        2. `existing = set(UserLocation.objects.filter(tenant=request.tenant).values_list('user_id','location_id'))`.
        3. `to_create = desired - existing`, `to_delete = existing - desired`.
        4. For each `(user_id, location_id)` in `to_delete`, group by `user_id` and check
           `remaining_assignment_count(user, [loc ids being removed for that user in this diff])`. If it would hit
           `0`, or `future_appointment_count(user, location) > 0`, the pair is **risky**.
        5. If any risky pair exists AND `request.POST.get('confirm') != '1'`: apply nothing, re-render the matrix
           with the posted (unsaved) checkbox state preserved and a warning banner per risky pair using the
           research's own wording — `"Removing {user} from {location} will leave them with no assigned location."`
           / `"{user} has {n} upcoming appointment(s) at {location} that will lose their assigned provider."` —
           plus a "Confirm and apply anyway" button that resubmits the same POST with a hidden `confirm=1`.
        6. Otherwise apply: `bulk_create` the `to_create` pairs (each row still runs `full_clean()` via
           `UserLocation.clean()` for the cross-tenant belt-and-braces check — do not bypass validation with a
           raw `bulk_create` that skips `save()`/`clean()`; loop + `save()` or call `full_clean()` per instance
           before a `bulk_create`), delete the confirmed `to_delete` rows, `messages.success(...)`.
        Template: `templates/tenants/staff_locations.html`.
      - `toggle_provider_view(request, pk)` — `@login_required @tier_required('owner','manager') @require_POST`.
        `obj = get_object_or_404(User.objects.filter(tenant=request.tenant), pk=pk)`. Also checks
        `future_appointment_count` across `obj.assigned_locations()` when flipping `is_provider` **off**, and adds
        a `messages.warning` (not a block) if any are found — mirrors the "warn, don't hard-block" idiom. Redirects
        via `safe_redirect_target(request, default='tenants:staff_locations')` so it returns to the same
        `?user=`/`?location=` context it was toggled from.
- [ ] `apps/tenants/forms/__init__.py` — re-export `parse_assignment_pairs`, `ProviderFlagForm`.
- [ ] `apps/tenants/views/__init__.py` — re-export `staff_locations_view`, `toggle_provider_view`.
- [ ] `apps/tenants/urls.py` (flat module, append after 1.1/1.2's routes — literal routes before any `<int:pk>`,
      checked against the WHOLE concatenated list, not just this block):
      ```python
      path('staff-locations/', views.staff_locations_view, name='staff_locations'),
      path('staff-locations/toggle-provider/<int:pk>/', views.toggle_provider_view, name='toggle_provider'),
      ```
- [ ] No `admin.py` change needed (`UserLocation` is registered, if at all, under `accounts/admin.py` — not this
      pass's concern).
- [ ] No migration — `makemigrations tenants --check` must report "No changes detected."

### Template edit outside `apps/tenants` (the ONE cross-app edit this sub-module makes)
- [ ] `templates/accounts/user/detail.html` — extend the existing "Assigned locations" card (around the block at
      lines 90–112) with a "Manage locations" action linking to `{% url 'tenants:staff_locations' %}?user={{ obj.pk }}`.

### Wire-up
- [ ] `apps/accounts/navigation.py` — add `'1.3': {'Staff & Locations': 'tenants:staff_locations'}` to
      `LIVE_LINKS`.
- [ ] No `settings.py` / `config/urls.py` / `config/asgi.py` change — `tenants` app wiring is 1.1/1.2's job
      (first sub-module to land in this pass).

### Templates (`templates/tenants/` — flat, foundation app, standalone page per Template Folder Structure rule 6)
- [ ] `templates/tenants/staff_locations.html` — filter bar reflecting `request.GET` (`q`, `tier`, `provider`,
      `status`, `show_inactive_locations`) using `status_choices`/`tier_choices` passed from the view (Filter
      Rules #1); the grid itself (rows=users, columns=locations, checkbox cells, one submit button at the
      bottom); a per-row "Provider" badge (`badge-green` = yes / `badge-slate` = no) with its own small toggle
      form/button next to it; a per-row "Assigned to N of M" badge (`badge-green` at full count, `badge-amber`
      partial, `badge-red` at zero — research's "0 of 2 — cannot be booked or seen in the call log" wording as
      the zero-state tooltip/help text); the risky-removal confirmation banner + hidden `confirm=1` resubmit;
      pagination on the user rows (`partials/_pagination.html`, `has_previous`/`has_next` guarded) since the
      roster can grow past one page even though locations (columns) stay few; `partials/_empty_state.html` when
      the tenant has zero locations (nothing to assign into) or zero users.

---

## Sub-module 1.4 — Provider Working Hours

### Shape: CRUD (zero-migration) — an edit-in-place JSON-field editor over `accounts.User.provider_hours`, plus
one pure read helper (`get_provider_intervals`) Module 4 will import later. No new table.

### Models — NONE new. Tables read/written:
- [ ] `accounts.User.provider_hours` — tenant-scoped — the field the whole sub-module edits, one `(user,
      location)` pair at a time. Shape justified by: Per-Location Hours (location-keyed dict), Day & Interval
      Editor (list of `{start_time,end_time,days}` per key). Location keys are validated against
      `tenants.Location.pk` **and** `accounts.UserLocation` (Assignment Guard) before save — never trusted as-is.
- [ ] `tenants.Location.timezone` / `.tzinfo` — read-only input to the editor's display label and to
      `get_provider_intervals`'s future timezone math. Never a form field on this editor (driver: Timezone
      Resolution — "never the browser's or the business default").
- [ ] `accounts.UserLocation` — read-only authorization check: an hours entry may only target a location the
      provider actually has a `UserLocation` row for (driver: Assignment Guard, REQUIRED priority).

### Backend
- [ ] `apps/tenants/services.py` (NEW, flat module per Backend rule 8 — `services.py` stays flat, never a
      package):
      ```python
      WEEKDAY_CHOICES = [
          ('mon', 'Mon'), ('tue', 'Tue'), ('wed', 'Wed'), ('thu', 'Thu'),
          ('fri', 'Fri'), ('sat', 'Sat'), ('sun', 'Sun'),
      ]

      def get_provider_intervals(user, location, weekday=None):
          """Return [(start: datetime.time, end: datetime.time), ...] for `user` at
          `location`, optionally filtered to one weekday code. NEVER raises: a
          missing location key, a malformed entry, or a non-dict provider_hours all
          resolve to []. Pure parsing, no queries — caller passes already-fetched
          User/Location instances so this stays safe to call from Module 4's future
          hot-path availability search. This IS the named contract Module 4 imports:
          `from apps.tenants.services import get_provider_intervals`."""

      def validate_provider_hours(intervals, *, location_id, assigned_location_ids):
          """Validate ONE location's proposed interval list before save:
            - location_id not in assigned_location_ids -> ValidationError (Assignment Guard)
            - a start_time/end_time that doesn't parse as HH:MM -> ValidationError
            - end_time <= start_time on any interval -> ValidationError
            - two intervals sharing a weekday with overlapping [start,end) ranges -> ValidationError
          Raises django.core.exceptions.ValidationError with field-level messages;
          called from ProviderHoursForm.clean(). Returns the cleaned interval list
          unchanged when valid; never mutates provider_hours itself.
          NOTE: this signature adds an explicit `location_id` param the research left
          as 'via the caller' — resolved here for an unambiguous contract."""
      ```
      Times are stored and compared as `%H:%M` (24-hour, zero-padded) throughout — **`%-I`/`%-d` strftime
      directives are unsupported on this Windows host**; any Python-side formatting uses `%H:%M` (portable) or
      `f'{t.hour:02d}:{t.minute:02d}'`, and all admin-facing display formatting uses Django's own template
      filters (`{{ t|time:"g:i A" }}`) which are OS-independent, never Python `strftime` dash-flags.
- [ ] `apps/tenants/forms/ProviderHours.py`:
      - `IntervalForm(forms.Form)` — `start_time = forms.TimeField(input_formats=['%H:%M'])`,
        `end_time = forms.TimeField(input_formats=['%H:%M'])`,
        `days = forms.MultipleChoiceField(choices=WEEKDAY_CHOICES, widget=forms.CheckboxSelectMultiple, required=True)`.
      - `IntervalFormSet = forms.formset_factory(IntervalForm, extra=1, can_delete=True)`.
      - `ProviderHoursForm(forms.Form)` — one field, `mark_closed = forms.BooleanField(required=False,
        label='Not working at this location')`. **This is the "no hours configured" vs "explicitly closed"
        distinguisher**: on save, a location key with 1+ interval rows → `provider_hours[loc_id] = [intervals]`;
        zero interval rows AND `mark_closed` checked → `provider_hours[loc_id] = []` (an explicit, intentional
        "not working here" — the key IS present, distinguishing it from a location never touched, whose key is
        simply absent from the dict); zero interval rows AND `mark_closed` unchecked → form error
        ("Add at least one working interval, or check 'Not working at this location'.") — the save is refused
        rather than silently writing an ambiguous empty list. (Functionally `get_provider_intervals` treats a
        missing key and an explicit `[]` identically — both mean zero bookable intervals — the distinction is an
        editor/audit-trail concern, not an availability-search one.)
      - `clean()` on `IntervalFormSet`/the combined save path calls `services.validate_provider_hours(...)`,
        attaching its `ValidationError` as a formset `non_form_errors`.
- [ ] `apps/tenants/views/ProviderHours.py`:
      - `provider_hours_view(request, user_pk)` — `@login_required`, then an inline gate (NOT the
        `tier_required` decorator, since self-service is allowed): `provider = get_object_or_404(User.objects.filter(
        tenant=request.tenant), pk=user_pk)`; `if request.user.pk != provider.pk and request.user.tier not in
        ('owner','manager'): messages.error(...); return redirect('accounts:dashboard')`. Resolves
        `assigned_location_ids = list(provider.assigned_locations().values_list('pk', flat=True))` — empty →
        render an empty-state pointing at `tenants:staff_locations?user={{ provider.pk }}` ("Assign this provider
        to a location first"). Resolves the active editor location from `?location=<pk>` (defaulting to the
        first assigned one), re-validated against `assigned_location_ids` on EVERY load (a `?location=` for an
        unassigned/other-tenant location falls back to the default rather than 404ing the whole page — softer
        than a hard 404 because it's a same-page query param, not a resource fetch, but it never renders an
        unauthorized location's data). If `provider.is_provider` is `False`, render a banner:
        "This user is not marked as a provider — configured hours have no effect until Provider Marking (1.3) is
        enabled" with a link to `tenants:staff_locations?user={{ provider.pk }}`, but still allow editing (so an
        admin can pre-configure hours before flipping the flag).
        GET: builds `IntervalFormSet(initial=[{...} for each interval in get_provider_intervals(...)])` and
        `ProviderHoursForm(initial={'mark_closed': str(location.pk) in provider.provider_hours and not
        provider.provider_hours[str(location.pk)]})`.
        POST: re-derives `location_id` from a hidden POST field, re-validates membership in
        `assigned_location_ids` server-side (never trust the posted id, even though it echoes the GET-selected
        one — defense in depth, same posture as the matrix). Validates both forms, calls
        `services.validate_provider_hours`, then writes `provider.provider_hours[str(location.pk)] = [...]` (or
        `[]`) and `provider.save(update_fields=['provider_hours', 'updated_at'])`.
        Template: `templates/tenants/provider_hours.html`.
      - `provider_hours_report_view(request)` — `@login_required @tier_required('owner','manager')`. Tenant-wide
        read-only table: `User.objects.filter(tenant=request.tenant, is_provider=True)`, optional `?location=<pk>`
        filter (tenant-scoped queryset, never trusted blind), each row rendering a compact weekly summary built
        from `services.get_provider_intervals(provider, location, weekday=day)` per day. No create/edit/delete —
        this is the researched "Staff-schedule report", a thin read view over data the editor above already
        produces. Template: `templates/tenants/provider_hours_report.html`.
- [ ] `apps/tenants/forms/__init__.py` — re-export `IntervalForm`, `IntervalFormSet`, `ProviderHoursForm`.
- [ ] `apps/tenants/views/__init__.py` — re-export `provider_hours_view`, `provider_hours_report_view`.
- [ ] `apps/tenants/urls.py` — append (literal `providers/hours/report/` listed before the `<int:user_pk>`
      route even though `'hours'` can never match the `<int:...>` int converter, to keep the file consistent with
      the project's own literal-before-pk convention):
      ```python
      path('providers/hours/report/', views.provider_hours_report_view, name='provider_hours_report'),
      path('providers/<int:user_pk>/hours/', views.provider_hours_view, name='provider_hours'),
      ```
- [ ] No `admin.py` change, no migration — `makemigrations tenants --check` must report "No changes detected."

### Seeder (extends `apps/accounts/management/commands/seed_accounts.py`, NOT `seed_tenants.py`)
- [ ] Rationale (state this in the commit message): `provider_hours`/`is_provider`/`UserLocation` are all
      `accounts` fields/tables, and `seed_accounts.py` already creates them idempotently — a second seeding entry
      point in `apps/tenants` would split one idempotency check across two files. Extend `seed_accounts.py`
      instead.
- [ ] Add a THIRD Acme demo user to `DEMO_USERS['acme']['users']` — a provider assigned to **both** Acme
      locations (today's seed has no 2-location provider): `email='provider@acme.test'`,
      `username='acme_provider'`, `first_name='Lena'`, `last_name='Chen'`, `tier=User.TIER_STAFF`,
      `is_provider=True`, `primary_phone='+13125550103'`, `locations=['downtown','uptown']`.
- [ ] After the existing per-user `UserLocation` loop, add an idempotent `provider_hours` backfill keyed by
      username (`get_or_create`-safe — only write if `user.provider_hours` is still `{}`, so a second run doesn't
      clobber anything a human edited via the UI): `acme_provider` gets a **split shift at downtown**
      (`09:00–12:00` + `13:00–17:00`, `days=['mon','tue','wed','thu','fri']`) and a **straight shift at uptown**
      (`10:00–14:00`, `days=['sat']`) — satisfies the research's "different weekly patterns... including one
      split-shift day, across two locations" requirement. Also give the existing single-location provider
      `acme_downtown` one simple interval so the self-service edit test has an existing row to load
      (`09:00–17:00`, `days=['mon','tue','wed','thu','fri']`).
- [ ] `_report()` — add one printed line per seeded provider showing which locations have configured hours, so
      the smoke sweep script doesn't have to guess.

### Wire-up
- [ ] `apps/accounts/navigation.py` — add `'1.4': {'Provider Hours': 'tenants:provider_hours_report'}` to
      `LIVE_LINKS` (the report is the tenant-wide landing surface; the per-provider editor is reached from it and
      from `accounts/user/detail.html`).
- [ ] `templates/accounts/user/detail.html` — same edit pass as 1.3 (one more line in the same card, or an
      adjacent "Actions" block): when `obj.is_provider`, add an "Edit working hours" link to
      `{% url 'tenants:provider_hours' user_pk=obj.pk %}`. **Combine with 1.3's edit into ONE commit for this
      file** — do not touch `accounts/user/detail.html` twice across the two sub-modules; land both link
      additions together since they're the same file (one-file-per-commit still applies: one commit, both lines).

### Templates (`templates/tenants/` — flat, standalone pages)
- [ ] `templates/tenants/provider_hours.html` — location selector (a `<select>` over `assigned_location_ids`,
      `onchange="this.form.submit()"`, method GET, preserving `user_pk` in the URL) rendered ABOVE the interval
      editor; a location-timezone label computed server-side from `location.local_now()` /
      `{{ location.timezone }}` via Django's `time`/`date` template filters (never client-side `Intl`/JS
      timezone conversion — the stored `HH:MM` values are already location-local, nothing to convert); the
      `IntervalFormSet` as a table of rows (start time, end time, day checkboxes, a delete checkbox per row, an
      "Add another block" JS-only client-side row-add — no server round-trip); the `mark_closed` checkbox; a
      "Copy to other days" **client-side JS convenience only** (fills the day checkboxes of a new row from an
      existing one — no backend endpoint, still writes the same `days` list shape on submit); a "Copy from
      another location" link that does a plain GET reload with `?location=<target>&copy_from=<source>`, which
      pre-fills the formset's initial values from the source location's stored intervals without persisting
      anything until the admin explicitly saves (no separate POST endpoint for this — kept to the read side).
- [ ] `templates/tenants/provider_hours_report.html` — filter bar (`?location=`, `?q=` on provider name), one row
      per provider × the report's per-day summary, `partials/_pagination.html`, `partials/_empty_state.html` when
      the tenant has no providers yet (linking to `tenants:staff_locations` to mark one).

---

## Verify (covers both 1.3 and 1.4)

- [ ] `venv\Scripts\python.exe manage.py makemigrations tenants --check` → "No changes detected." (both
      sub-modules are zero-migration; a stray migration here is a bug, not progress)
- [ ] `venv\Scripts\python.exe manage.py check`
- [ ] `venv\Scripts\python.exe manage.py seed_tenants` then `seed_accounts` ×2 each — idempotent, no duplicate
      rows/errors on the second run; confirms `acme_provider`'s `UserLocation` rows and `provider_hours` backfill
      land and stay stable
- [ ] `pytest -q apps/tenants` — new tests under `apps/tenants/tests/`:
      - `test_services.py` — `get_provider_intervals`: empty/missing key → `[]`; malformed JSON entry → skipped,
        never raises; weekday filter correctness; split-shift (two intervals, same days) returns both.
        `validate_provider_hours`: location not in `assigned_location_ids` → `ValidationError`; `end_time <=
        start_time` → `ValidationError`; two intervals sharing a weekday with overlapping ranges → `ValidationError`;
        a valid non-overlapping multi-block list passes.
      - `test_staff_locations.py` — matrix POST creates/deletes the diff correctly; a diff that would leave
        `acme_downtown` with zero locations is blocked without `confirm=1` and applied with it;
        `future_appointment_count` stub returns `0` today (import-guarded); `toggle_provider_view` flips the
        flag and is tier-gated (a `staff`-tier user gets redirected, not a 500).
      - `test_provider_hours.py` — self-service: `acme_downtown` (a provider, non-management tier) can GET/POST
        their OWN hours but a 403/redirect on someone else's; a management-tier user can edit anyone's; saving
        zero intervals without `mark_closed` is a form error, not a silent empty-list write; saving with
        `mark_closed` writes `[]` and is distinguishable in the stored dict from an untouched location (key
        absent) via a direct DB read in the test.
- [ ] Cross-tenant IDOR: as `admin_globex`, POST a `staff-locations` diff containing an Acme user pk / Acme
      location pk → the pair is silently dropped (not created), zero side effects. As `admin_globex`, GET
      `tenants:provider_hours` with an Acme user's `user_pk` → 404.
- [ ] Cross-location / unassigned-location IDOR: POST `tenants:provider_hours` for `acme_downtown` with a
      `location_id` for Acme Uptown (a location they are NOT assigned to) → rejected server-side
      (`validate_provider_hours`'s Assignment Guard fires) even though the attacker also controls the GET
      `?location=` param that would otherwise have silently fallen back.
- [ ] Last-location guard: attempt to remove `acme_downtown`'s only assignment (downtown) via the matrix without
      `confirm=1` → blocked, warning shown, `UserLocation` row still present; resubmit with `confirm=1` → row
      removed, `request.location` degrades to `None` on their next request (`ActiveLocationMiddleware`'s
      documented behaviour) rather than erroring.
- [ ] Overlap validation: two intervals both covering `mon` with overlapping `[start,end)` → rejected;
      `end_time == start_time` and `end_time < start_time` both rejected; two intervals covering DIFFERENT days
      with the same clock times → accepted (no overlap).
- [ ] Unassigned-location hours rejected: attempt to save hours for `acme_provider` at a THIRD (non-existent /
      not-assigned) location id via a hand-crafted POST → `ValidationError`, no write.
- [ ] Junk POST payloads degrade, never 500: non-integer `assign` values, a missing `location_id`, an `HH:MM`
      string that doesn't parse (`"25:99"`), an empty `days` list on a submitted interval row.
- [ ] `temp/` smoke sweep as `admin_acme` (password `navai-demo-2026`, printed by `seed_accounts`): `GET
      /staff-locations/`, `/staff-locations/?user=<pk>`, `/staff-locations/?location=<pk>`, `/providers/<pk>/hours/`,
      `/providers/hours/report/` all 200; content assertions (no `{#`/`{% comment` leaks, correct page titles, the
      seeded `acme_provider` row visible on both the matrix and the report); POST `toggle-provider` 302 back to
      the matrix.
- [ ] Sidebar: Module 1 shows `1.3` and `1.4` as Live with working links.

## Close-out (covers both 1.3 and 1.4)

- [ ] Review agents, in order: `code-reviewer` → `explorer` → `frontend-reviewer` → `performance-reviewer` →
      `realtime-reviewer` (expected to report "no realtime surface" for both — fine, note it, no empty commit
      required) → `qa-smoke-tester` → `security-reviewer` → `test-writer`.
- [ ] **`.claude/skills/tenants/SKILL.md`** — Module 1 DOES require this skill (per the mandatory Per-Module
      Skill rule, `tenants` is a brand-new module getting its Django views/forms/urls for the first time across
      this pass and the sibling 1.1/1.2 pass). **Check existence before deciding create vs. update** — if the
      1.1/1.2 pass (`todo-1.1-1.2.md`) lands first and already authored `.claude/skills/tenants/SKILL.md`, this
      pass must **UPDATE** it in place (add the Assignment Matrix / Provider Hours models-reused, routes,
      templates, `services.py` contract, and the `seed_accounts.py` extension) rather than re-authoring it — that
      would clobber 1.1/1.2's documentation. If somehow this pass lands FIRST, author the skill fresh, covering
      all four of 1.1–1.4's as-built surfaces that exist at that point.
- [ ] README — update if the project root README enumerates built sub-modules.

## Later passes / deferred (carried over from both research files)

- Per-location role/title override on `UserLocation` (Toast-style inherited-vs-override permissions) — needs a
  field that isn't there; zero-migration constraint this pass.
- Per-service/per-skill bookable scoping — needs a join `UserLocation` doesn't have; depends on
  `scheduling.Service` (Module 4, unbuilt).
- "Primary/home location" flag per staff member — needs a new field.
- CSV/spreadsheet bulk import/export of assignments — the matrix already covers this tenant's scale; revisit only
  if headcount grows past what a grid shows legibly.
- The real (non-stub) body of `future_appointment_count()` — lands automatically once Module 4 ships
  `scheduling.Appointment`; the call sites in `apps/tenants/views/UserLocation.py` do not change.
- Date-specific overrides / holiday exceptions / temporary repeating hours on `provider_hours` — needs a schema
  extension (a top-level `"exceptions"` key keyed by ISO date) beyond the current
  `{"<location_id>": [interval,...]}` shape; deliberately not bundled into this pass since it changes the JSON
  contract Module 4 will build against.
- Overnight/multi-day intervals — no evidence any leader in the inbound-receptionist space needs this for staff
  hours; skip unless a real use case appears.
- Module 4's availability search itself — out of scope; it will consume `get_provider_intervals` as its read
  contract, not reinvent the parse.
- Per-provider override of a location-level "default hours" — out of scope entirely; `Location` has no hours
  field to override, by design (only `timezone`).

## Review notes
(filled in at the end)
