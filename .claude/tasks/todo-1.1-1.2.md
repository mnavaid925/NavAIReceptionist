---
# Sub-modules 1.1 + 1.2 — Business Settings & Location Directory (Module 1: Business & Locations, `tenants`) — plan from research-tenants-1.1.md + research-tenants-1.2.md (2026-07-19)

*(Written to `.claude/tasks/todo-1.1-1.2.md` — a standalone file. `.claude/tasks/todo.md` and any `todo-0.*.md` are
untouched. A sibling agent is writing `.claude/tasks/todo-1.3-1.4.md` concurrently over the same `apps/tenants/`
tree — this plan only touches the files listed below and leaves 1.3/1.4's models (`UserLocation` assignment UI,
`User.provider_hours` editor) alone.)*

## Overview

Both sub-modules ship against **models that already exist and are already migrated** —
`apps/tenants/models/Tenant.py` and `apps/tenants/models/Location.py`, confirmed by direct read (not the ERD) with
**no drift** from `NavAIReceptionist-ERD.md` §3.1/§3.2. `apps/tenants/` today has only `models/`, `admin.py`,
`apps.py`, `migrations/0001_initial.py`, `management/commands/seed_tenants.py` — **no `forms/`, `views/` or
`urls.py`**. This pass creates all three from scratch, wires `apps.tenants.urls` into `config/urls.py`, adds two
`LIVE_LINKS` entries, and — because this is the first sub-module to give `tenants` a reachable page — **authors**
`.claude/skills/tenants/SKILL.md` (no `.claude/skills/tenants/` directory exists yet, confirmed by glob).

## Shape

- **1.1 Business Settings — CRUD sub-module, singleton-row shape.** `ZERO new models, ZERO migrations.` There is
  exactly one `Tenant` row per business and `request.tenant` IS it, so this ships **no list page, no create view,
  no delete view, and no pk in the URL** — one read-only overview + one owner-gated edit form, both over the
  existing `tenants.Tenant` row.
- **1.2 Location Directory — CRUD sub-module, standard shape.** `ZERO new models, ZERO migrations.` Full
  list/create/detail/edit/delete-as-deactivate over the existing `tenants.Location` table.

## Models

**NONE new. Both existing, migrated, field sets confirmed by reading the files directly:**

- [x] `tenants.Tenant` (`apps/tenants/models/Tenant.py`) — tenant-scoped by definition (it IS the tenant, no
  `tenant` FK): `name`, `slug` (unique), `customer_id` (unique), `timezone` (IANA, default `UTC`), `is_active`,
  `created_at`/`updated_at`. 1.1's form touches only `name` + `timezone` (drivers: Business Record / Business
  Profile Editing — the two fields that reach a caller's ear); `customer_id`, `slug`, `is_active` are **read-only
  display** (drivers: Business Profile Editing's "locked/support-only identifiers" finding + Tenant Activation
  State's "suspension is a platform action, not tenant self-service" finding) — none of the three is ever in
  `Meta.fields`.
- [x] `tenants.Location` (`apps/tenants/models/Location.py`) — tenant-scoped, **not** location-scoped-of-itself (it
  IS the location): `tenant`, `name`, `slug`, `address_line1/2`, `city`, `state`, `postal_code`, `country`
  (default `US`), `timezone` (IANA, default `UTC`), `phone`, `is_active`, plus `full_address` / `tzinfo` /
  `local_now()` properties (already implemented, template-only reuse — no new code needed for the values).
  Constraint `uniq_location_tenant_slug` on `(tenant, slug)` already exists — 1.2's form catches the collision with
  a friendly error instead of letting it surface as a raw `IntegrityError`. 1.2's form exposes **all eleven**
  domain fields (drivers: Location Create & Edit — structured address + IANA timezone selector + country choice +
  slug uniqueness; Location Deactivation — `is_active` as an editable checkbox is what makes reactivation "edit and
  re-check the box", mirroring `user_delete_view`/edit precedent, not a separate reactivate view). `tenant` is
  excluded from `Meta.fields` — stamped server-side from `request.tenant` by `TenantModelForm.save()`.
- No FK added to either model. The location-count stat on 1.1's overview reads `tenants.Location` read-only,
  read-through, no write path.

`makemigrations --check` must report **"No changes detected"** in Verify — that is the proof this claim holds, not
an assumption.

## App scaffolding (`apps/tenants/{forms,views}` created as packages; `apps/tenants/urls.py` as a flat module — Backend Package Structure rules 9 & 10, foundation app, no `<SubModule>/` level)

- [ ] `apps/tenants/forms/__init__.py` — new package init. Re-exports `BusinessSettingsForm`, `LocationForm`.
- [ ] `apps/tenants/forms/_common.py` — new, **local to `tenants`** (distinct from
  `apps.accounts.forms._common`, the cross-app home for `TenantModelForm`/`TenantLocationModelForm`, which this
  app's forms import directly, not redefine). Holds the toolkit shared by **both** of this app's forms:
  ```python
  from zoneinfo import available_timezones
  from django import forms  # noqa: F401
  from apps.accounts.forms._common import style_widgets  # noqa: F401

  __all__ = ['forms', 'style_widgets', 'COUNTRY_CHOICES', 'timezone_choices']

  COUNTRY_CHOICES = (
      ('US', 'United States'), ('CA', 'Canada'), ('GB', 'United Kingdom'),
      ('AU', 'Australia'), ('IE', 'Ireland'), ('NZ', 'New Zealand'),
      ('DE', 'Germany'), ('FR', 'France'), ('ES', 'Spain'), ('IT', 'Italy'),
      ('NL', 'Netherlands'), ('MX', 'Mexico'), ('IN', 'India'), ('SG', 'Singapore'),
      ('AE', 'United Arab Emirates'), ('ZA', 'South Africa'), ('BR', 'Brazil'),
      ('PH', 'Philippines'), ('JP', 'Japan'), ('SE', 'Sweden'), ('CH', 'Switzerland'),
  )

  def timezone_choices():
      """(tz, tz) pairs for every IANA zone the stdlib knows, sorted. Built fresh
      per call — cheap (~600 strings), and never goes stale against the running
      interpreter's own tzdata."""
      return [(name, name) for name in sorted(available_timezones())]
  ```
  Justifies research's "IANA timezone selector, not free text" (1.2) and "Country as a constrained choice" (1.2);
  reused as-is by 1.1's `timezone` field (see below) rather than duplicating the helper — same technique, one
  fewer typo surface on the tenant-wide default.
- [ ] `apps/tenants/views/__init__.py` — new package init. Re-exports all seven views (see Backend sections below).
- [ ] `apps/tenants/urls.py` — **new, flat module** (not a package — CLAUDE.md Backend Package Structure rule 10:
  `accounts/urls.py` and `tenants/urls.py` stay flat modules with a copied `crud()` factory, not per-entity
  `urlpatterns` lists). Copy the exact factory shape from `apps/accounts/urls.py` (`crud(base, name, view_module,
  extra=())`, looked up as `views.<name>_<suffix>_view`), parameterized against `apps.tenants.views`:
  ```python
  from django.urls import path
  from apps.tenants import views

  app_name = 'tenants'

  def crud(base, name, view_module=views, extra=()):
      ...  # identical shape to apps/accounts/urls.py's crud()

  urlpatterns = [
      # -- 1.1 Business Settings --------------------------------------------- #
      path('business/', views.business_settings_view, name='business_settings'),
      path('business/edit/', views.business_settings_edit_view, name='business_settings_edit'),
  ]

  # crud() emits its own literals (locations/create/) before its <int:pk> member
  # routes — first-match-wins, same rule as apps/accounts/urls.py.
  urlpatterns += crud('locations', 'location')   # 1.2 Location Directory
  ```
  Produces `locations/`, `locations/create/`, `locations/<int:pk>/`, `locations/<int:pk>/edit/`,
  `locations/<int:pk>/delete/` — matches the CRUD Completeness delete-URL pattern exactly.
- [ ] `apps/tenants/admin.py` — **no change**. `TenantAdmin`/`LocationAdmin` already exist and already cover the
  superuser-only surface; this pass builds the separate owner/tenant-facing equivalent, not a replacement.
- [ ] `apps/tenants/management/commands/seed_tenants.py` — **no change**. No new field on either model to seed;
  the existing two-tenant, two-location-each dataset already exercises every scenario this pass's Verify needs.
- [ ] `apps/tenants/tests/__init__.py` — new test package (none exists yet).

## 1.1 Business Settings — Backend (`apps/tenants/forms/Tenant.py`, `apps/tenants/views/BusinessSettings.py`)

- [ ] `apps/tenants/forms/Tenant.py` — `BusinessSettingsForm`. **Plain `django.forms.ModelForm`, NOT a
  `TenantModelForm` subclass** — per research, `Tenant` carries no `tenant` FK (it IS the tenant), so there is
  nothing for `TenantModelForm` to pop/stamp; using it here would be reaching for the wrong base for the wrong
  reason.
  ```python
  from django import forms
  from apps.accounts.forms._common import style_widgets
  from apps.tenants.forms._common import timezone_choices
  from apps.tenants.models import Tenant

  class BusinessSettingsForm(forms.ModelForm):
      class Meta:
          model = Tenant
          fields = ['name', 'timezone']   # customer_id, slug, is_active NEVER here

      def __init__(self, *args, **kwargs):
          super().__init__(*args, **kwargs)
          self.fields['timezone'] = forms.ChoiceField(
              choices=timezone_choices(), initial=self.instance.timezone,
          )
          style_widgets(self)
  ```
- [ ] `apps/tenants/views/BusinessSettings.py`:
  - `business_settings_view(request)` — `@login_required` only (no tier gate — research: the read is not
    owner-restricted, only the edit is). Guards `request.tenant is None` (the platform superuser) with a
    `messages.error` + redirect to `accounts:dashboard`, never a 500 on `None.name`. Context: `obj=request.tenant`,
    `location_count=Location.objects.filter(tenant=request.tenant).count()` (drivers: "Read-only account snapshot"
    finding — location count only; agent count omitted per research, not stubbed, until 2.1 ships). Renders
    `tenants/business/detail.html` — `customer_id`, `slug`, `is_active` shown **read-only**, `created_at` shown.
  - `business_settings_edit_view(request)` — `@login_required` + `@tier_required('owner')` +
    `@require_http_methods(['GET', 'POST'])`. Same `request.tenant is None` guard. `instance=request.tenant`,
    `form = BusinessSettingsForm(request.POST or None, instance=request.tenant)`. On valid POST: `form.save()`,
    `messages.success`, redirect to `tenants:business_settings`. No `business_settings_delete_view` — deleting the
    single business record is out of scope for a tenant owner (research: platform-operator/billing action, not
    this sub-module's).
- [ ] `apps/tenants/forms/__init__.py` / `apps/tenants/views/__init__.py` — add `BusinessSettingsForm` /
  `business_settings_view`, `business_settings_edit_view` to the re-export blocks.

## 1.2 Location Directory — Backend (`apps/tenants/forms/Location.py`, `apps/tenants/views/Locations.py`)

- [ ] `apps/tenants/forms/Location.py` — `LocationForm(TenantModelForm)`:
  ```python
  from django import forms
  from apps.accounts.forms._common import TenantModelForm, ValidationError, style_widgets
  from apps.tenants.forms._common import COUNTRY_CHOICES, timezone_choices
  from apps.tenants.models import Location

  class LocationForm(TenantModelForm):
      class Meta:
          model = Location
          fields = ['name', 'slug', 'address_line1', 'address_line2', 'city', 'state',
                     'postal_code', 'country', 'timezone', 'phone', 'is_active']
          # tenant is NEVER here — TenantModelForm pops it and stamps request.tenant in save()

      def __init__(self, *args, **kwargs):
          super().__init__(*args, **kwargs)
          self.fields['country'] = forms.ChoiceField(
              choices=COUNTRY_CHOICES, initial=self.instance.country or 'US',
          )
          self.fields['timezone'] = forms.ChoiceField(
              choices=timezone_choices(), initial=self.instance.timezone,
          )
          style_widgets(self)

      def clean_slug(self):
          slug = self.cleaned_data['slug']
          qs = Location.objects.filter(tenant=self.tenant, slug=slug)
          if self.instance.pk:
              qs = qs.exclude(pk=self.instance.pk)
          if qs.exists():
              raise ValidationError(
                  'A location with this slug already exists for this business. '
                  'Choose a different one.'
              )
          return slug
  ```
  Realizes: slug auto-suggest/friendly-collision-error, structured address, IANA timezone selector, constrained
  country choice, `is_active` toggle doubling as the reactivation control.
- [ ] `apps/tenants/views/Locations.py`:
  - `_tenant_locations(request)` helper — `Location.objects.filter(tenant=request.tenant)`. **No `location=` filter
    anywhere in this file** — `Location` is not location-scoped-of-itself (CLAUDE.md's explicit exception), so a
    location's own detail/edit page is reachable regardless of which location is currently active in the switcher,
    only which tenant the row belongs to.
  - **Tier decision (stated explicitly, not left implicit):** all five views — list, create, detail, edit,
    delete — are gated `@tier_required('owner', 'manager')`, matching `apps/accounts/views/Users.py`'s
    `MANAGEMENT_TIERS` precedent exactly, rather than opening list/detail to every tier. Research does not call
    for a specific tier split here; picking the codebase's existing convention (rather than inventing a new,
    narrower-than-precedent policy for one entity) is the safer, more consistent choice.
  - `location_list_view(request)` — search (`q` on `name`, `slug`, `city`, `phone` via `Q(...)`, junk-safe:
    `request.GET.get('q', '').strip()`), status filter (`request.GET.get('status', '')` mapped
    `'active'`→`is_active=True`, `'inactive'`→`is_active=False`, anything else → no filter, never raises).
    `.annotate(staff_count=Count('user_assignments', distinct=True))` (drivers: "Assigned-staff count per row").
    `agents_installed = django_apps.is_installed('apps.agents')` passed to context — **always `False` this pass**
    (agents app not yet in `INSTALLED_APPS`), so the "Agent-configured indicator per row" renders as a static
    "Not configured" badge on every row; this flag is the hook that lets a future Module 2 pass wire in the real
    per-location check without another edit to `tenants` itself. Filters applied **before** `paginate()`.
    `total_count = queryset.count()`. Renders `tenants/location/list.html`.
  - `location_create_view(request)` — `LocationForm(request.POST or None, request=request)`. On valid POST:
    `form.save()` (stamps `tenant=request.tenant`), `messages.success`, redirect to `tenants:location_detail`.
  - `location_detail_view(request, pk)` — `get_object_or_404(_tenant_locations(request), pk=pk)`. Context:
    `obj`, `assigned_staff = obj.user_assignments.select_related('user').order_by('user__full_name')` (drivers:
    "Assigned staff roster (read-only)" — read-only here, assign/unassign is 1.3's job), and the **defensive**
    agent-setting panel:
    ```python
    from django.apps import apps as django_apps
    agent_setting = None
    if django_apps.is_installed('apps.agents'):
        AgentSetting = django_apps.get_model('agents', 'AgentSetting')
        agent_setting = AgentSetting.objects.filter(location=obj).first()
    ```
    **Never** a hard `from apps.agents.models import AgentSetting` — that import does not exist yet and would
    crash every location detail render until Module 2 ships. Renders `tenants/location/detail.html`.
  - `location_edit_view(request, pk)` — `get_object_or_404(_tenant_locations(request), pk=pk)`,
    `LocationForm(request.POST or None, instance=obj, request=request)`. This is also how a deactivated location
    is **reactivated** (check `is_active` again) — no separate reactivate view, mirroring `user_edit_view`.
  - `location_delete_view(request, pk)` — `@require_POST`. **Deactivates, never deletes**, mirroring
    `user_delete_view` exactly:
    ```python
    obj = get_object_or_404(_tenant_locations(request), pk=pk)
    # Compute the warning BEFORE flipping the flag, while assigned_locations()
    # still (correctly, post-fix) reflects this location as active for them.
    affected = [
        u for u in User.objects.filter(tenant=request.tenant, user_locations__location=obj)
        if list(u.assigned_locations()) == [obj]
    ]
    obj.is_active = False
    obj.save(update_fields=['is_active', 'updated_at'])
    messages.success(request, f'{obj.name} has been deactivated. Past appointments and call logs are unchanged.')
    for u in affected:
        messages.warning(request, f'{u.display_name} now has no active location assigned.')
    return redirect('tenants:location_list')
    ```
    Realizes: "Deactivate-not-delete, single boolean toggle, POST-only" (REQUIRED), "Warn before deactivating a
    location that would leave an assigned user with zero locations" (soft warning, not a hard block — matches the
    `_is_last_owner` precedent's shape of "guard exists, action still proceeds unless it's the harder invariant"),
    "Deactivation never cascades to historical data" (satisfied by construction — `.delete()` is never called).
- [ ] `apps/tenants/forms/__init__.py` / `apps/tenants/views/__init__.py` — add `LocationForm` /
  `location_list_view`, `location_create_view`, `location_detail_view`, `location_edit_view`,
  `location_delete_view` to the re-export blocks. **Forgetting this is an `ImportError`/`AttributeError` at
  runtime**, not at file-save time.

## Riding-along fix (required for 1.2's own headline feature to be correct — not a new model)

- [ ] **`apps/accounts/models/User.py::assigned_locations()`** (currently ~line 242) — add `is_active=True` to the
  `Location` filter:
  ```python
  return Location.objects.filter(
      tenant_id=self.tenant_id,
      user_assignments__user=self,
      is_active=True,
  ).distinct()
  ```
  **Why this rides along with 1.2, not a separate pass:** `ActiveLocationMiddleware._resolve()`
  (`apps/accounts/middleware.py`) trusts this exact queryset to re-validate the session's stored active-location id
  on **every** request and to auto-activate a user's sole assignment. Without the fix, deactivating a location via
  the new `location_delete_view` would not make it fall out of `assigned_locations()` — a live violation of the
  middleware's own documented contract and of CLAUDE.md's Multi-Tenancy Rule 2 ("a user must never reach a
  location they are not assigned to"). "Location Deactivation" is not actually shippable as REQUIRED without this
  one-line change to an existing method in the foundation app.
- [ ] **Consequence to verify, not additional code:** with the fix in place, the very next request after a user's
  *active* location is deactivated re-runs `ActiveLocationMiddleware._resolve()`: the stored id no longer appears
  in the (now correctly filtered) `assigned_locations()`, so it is dropped, and the existing "auto-activate the
  sole remaining assignment" branch runs — a user with exactly one other active location is silently switched to
  it; a user with zero or two-or-more remaining active locations gets `request.location = None` and sees the
  existing choose-location banner (built in 0.4). No new banner/UI copy needed — 0.4's mechanism already handles
  this state; 1.2 only makes the input to it correct.
- [ ] `apps/tenants/tests/test_location_deactivation.py` regression test (see Verify) proves both halves: the
  queryset drop AND the request-level re-resolution, using the seeded `acme_downtown` (manager, assigned **only**
  to `downtown` — exactly the "left with zero locations" subject) and `admin_acme` (assigned to **both** — the
  "auto-switches to the remaining one" subject, once `uptown` or `downtown` is deactivated for them specifically —
  see the two seeded users' distinct assignment shapes in `seed_accounts.py`).

## Wire-up

- [ ] `apps/accounts/navigation.py` — add exactly two new top-level keys, touching no other:
  ```python
  LIVE_LINKS['1.1'] = {'Business Record': 'tenants:business_settings'}
  LIVE_LINKS['1.2'] = {'Location List': 'tenants:location_list'}
  ```
  One label each, matching the 0.3/0.4 precedent of pointing at the one real page a bullet group fans out from
  (Create/Edit/Detail/Delete are reached from the list itself, not separate sidebar rows — exactly how `0.3` lists
  only "Users", not "Add User"/"Edit User"). Module 1 **is** in the sidebar (`SIDEBAR_EXCLUDED_MODULES = {'0'}`
  only), so both rows render under "Business & Locations" once these keys exist.
- [ ] `config/urls.py` — **new-app-level wiring, done once**: add one line after the existing `accounts` include.
  **Prefix chosen: `tenants/`** — so Business Settings resolves at `/tenants/business/` and the Location Directory
  at `/tenants/locations/`, matching the app-slug-prefixed convention every later module (`agents/`,
  `scheduling/`, `calls/`) will also follow (Module 0 alone owns the site root):
  ```python
  path('tenants/', include('apps.tenants.urls')),
  ```
- [ ] `config/settings.py` — **no change**. `'apps.tenants'` is already in `INSTALLED_APPS` (confirmed by grep);
  this is not a brand-new-app run at the Python-package level, only at the "has routes" level.
- [ ] `config/asgi.py` — **no change**. `tenants` has no realtime surface (see below).
- [ ] `AUTH_USER_MODEL` ordering item — **N/A**, already satisfied before Module 0's first `makemigrations`.

## Realtime & agent surface

**N/A for both sub-modules.** Confirmed by both research files' Compliance sections: neither touches
`calls.CallSession`, an LLM tool, a provider adapter, a Channels consumer, or any cost line. `tenants` has no
`consumers/` and no `routing.py` entry after this pass.

## Templates (`templates/tenants/<entity>/<page>.html` — flat, foundation app, no sub-module level)

Neither page set includes `partials/_account_tabs.html` — that strip is Module 0's own account-area chrome
(`ACCOUNT_TABS` in `navigation.py`); Module 1 pages are reached from the **sidebar**, not the account tabs, so
copying that include here would be a wrong-precedent mistake, not a harmless extra.

**1.1 — `templates/tenants/business/`:**
- [ ] `detail.html` — page header "Business Settings", breadcrumb NavAIReceptionist ▸ Business ▸ Settings. Card 1:
  `name`, `customer_id` (labelled "Customer ID (read-only)"), `slug` (labelled "read-only"), `timezone`,
  `is_active` badge (`badge-green "Active"` / `badge-muted "Inactive"`), `created_at`. Card 2 (or a stat block):
  location count. Actions sidebar/aside: "Edit business settings" button → `tenants:business_settings_edit`,
  **visible only when `request.user.tier == 'owner'`** (hidden, not the only enforcement — the view re-gates with
  `tier_required('owner')`).
- [ ] `form.html` — one form over `name` + `timezone` only, same field-loop pattern as
  `templates/accounts/user/form.html`. Cancel → `tenants:business_settings`. No password-style fields, no
  `customer_id`/`slug`/`is_active` inputs anywhere in the markup (not hidden — **absent**, so there is nothing to
  tamper with even via a crafted POST body; the form's `Meta.fields` already enforces this server-side, the
  template omission is defense in depth).

**1.2 — `templates/tenants/location/`:**
- [ ] `_filters.html` — search input (`q`, placeholder "Name, slug, city or phone") + status `<select>` with
  hardcoded `All statuses` / `Active` / `Inactive` options (not a model `CHOICES` — `is_active` is a plain
  boolean, so no `status_choices` context var is needed, unlike `user/_filters.html`'s tier/status pair) + Filter
  / Reset buttons, same `card card-body flex flex-wrap` shape as `accounts/user/_filters.html`.
- [ ] `list.html` — page header "Locations" + "Add location" button (tier-gated in the view already; template
  still checks `request.user.tier in ('owner','manager')` before rendering the button, matching the User list's
  pattern of hiding what the view would reject anyway). Table columns: Name, City/State, Timezone, Staff (from
  `staff_count`), Agent (static `badge-muted "Not configured"` per row, per the `agents_installed` flag), Status
  (`badge-green "Active"` / `badge-muted "Inactive"`), Actions (view/edit always; deactivate `{% if obj.is_active
  %}` guard, `onclick="return confirm(...)"` + `{% csrf_token %}`, mirroring `user/list.html`'s deactivate button
  exactly). Empty state via `partials/_empty_state.html` (`icon="map-pin"`, action → `tenants:location_create`).
  Pagination via `partials/_pagination.html`.
- [ ] `detail.html` — Card 1: `full_address`, `timezone` + `local_now()` readout, `phone`, `is_active` badge. Card
  2: assigned staff roster table (name, role/tier, provider flag) from `assigned_staff`, empty-state fallback if
  none. Card 3: agent-setting panel — `{% if agent_setting %}` real fields **or** `{% else %}` a static "Agent not
  configured yet — available once Module 2 ships" message; **never** a template reference to a field on
  `agent_setting` without that guard. Actions sidebar: Edit (always) → `tenants:location_edit`; Deactivate
  `{% if obj.is_active %}` → POST `tenants:location_delete` with confirm; Back to list.
- [ ] `form.html` — same field-loop shape as `user/form.html`, all eleven `LocationForm` fields render
  (`is_active` as a checkbox — visible on **both** create and edit, so the same template serves reactivation with
  no branch needed). Cancel → detail (edit) or list (create).

## Verify

- [ ] `makemigrations --check` → **"No changes detected"** — the concrete proof both sub-modules added zero
  migrations, not an assumption.
- [ ] `manage.py check` — clean.
- [ ] assert `PROVIDER_MODE=fake` — trivially true, neither sub-module imports a provider adapter; confirm the env
  default is intact.
- [ ] `seed_tenants` ×2 (already idempotent, `get_or_create`-based — re-run to confirm no regression from this
  pass, no new fields to seed).
- [ ] `pytest -q apps/tenants`:
  - `apps/tenants/tests/test_business_settings.py` — GET overview as any authenticated tenant user (200, shows
    `name`/`customer_id`/`slug`/`timezone`/status badge/location count); GET/POST edit as **owner** (200/302,
    `name`+`timezone` update); GET/POST edit as **manager or staff** tier → redirected with an error message, no
    row mutated (tier-gate proof); **tamper attempt** — POST `customer_id`, `slug` and `is_active` alongside valid
    `name`/`timezone` as owner → all three remain unchanged after save (proves `Meta.fields` exclusion holds even
    against a crafted POST body, not just an absent template field); superuser (`tenant=None`) hitting either view
    → redirected to dashboard, never a 500.
  - `apps/tenants/tests/test_location.py` — list search (`q`) across name/slug/city/phone; status filter
    active/inactive; **junk `?status=xyz` degrades to no filter, never raises** (per Filter Implementation Rule 3);
    create (owner/manager succeed, staff redirected); detail shows assigned-staff roster and the defensive "not
    configured" agent panel with **no import of `apps.agents`** anywhere in the request path; edit incl. the
    `(tenant, slug)` collision producing a friendly form error, not an `IntegrityError` 500; delete-as-deactivate —
    `is_active` flips to `False`, `Location.objects.filter(pk=pk).exists()` is **still `True`** afterward
    (`.delete()` never called), redirects to list; **cross-tenant IDOR → 404** — `admin_acme` (Acme) requesting
    Globex's `riverside` location's detail/edit/delete-POST all 404 (not 403, not a redirect — `get_object_or_404`
    against a tenant-filtered queryset). *(No cross-**location** IDOR case applies to `Location` itself — it is
    the location, not scoped by one — noted explicitly so its absence here isn't mistaken for an oversight.)*
  - `apps/tenants/tests/test_location_deactivation.py` — the riding-along-fix regression, using seeded data:
    logged in as `admin_acme`, POST-deactivate `downtown` (the location `acme_downtown`, a **manager**, is
    assigned to **only**) → assert `acme_downtown.assigned_locations()` no longer includes `downtown`; assert a
    subsequent request as `acme_downtown` with `downtown` as their stored active-location session value has
    `request.location` become `None` (their sole assignment is gone) and the existing choose-location banner
    condition is met; separately, deactivate `uptown` while `admin_acme` (assigned to both) has `uptown` active →
    assert their **next** request auto-switches `request.location` to `downtown` (the remaining active
    assignment), matching `ActiveLocationMiddleware`'s existing "auto-activate the sole remaining assignment"
    branch; assert the deactivation view's response carries the `messages.warning` naming `acme_downtown` in the
    first scenario.
- [ ] Twilio signature + idempotency — **N/A**, neither sub-module has a webhook.
- [ ] websocket connect/reject — **N/A**, neither sub-module has a Channels consumer.
- [ ] `temp/` smoke sweep as `admin_acme` (password `navai-demo-2026`, confirmed by reading
  `apps/accounts/management/commands/seed_accounts.py::DEMO_PASSWORD` directly, not assumed): log in; GET
  `/tenants/business/` (200, shows "Acme Dental Group", Customer ID `ACME-1001`, timezone, Active badge, location
  count 2); GET `/tenants/business/edit/` (200, form pre-filled); POST a name change, confirm it persists and
  reflects on the overview and in the topbar's `active_tenant.name`; GET `/tenants/locations/` (200, both Acme
  locations listed, staff counts correct); filter `?q=downtown` and `?status=active`/`?status=junk` (junk degrades
  cleanly); GET `/tenants/locations/<downtown.pk>/` (200, address/timezone/local-time/staff roster/defensive agent
  panel all render); create a third location, edit it, then deactivate it via the real confirm-dialog POST path
  and confirm it drops off the default (unfiltered-status-but-still-shown, since there's no default status filter)
  list with an `Inactive` badge and reappears correctly under `?status=inactive`; attempt
  `/tenants/locations/<globex_location.pk>/` as `admin_acme` → 404; confirm zero `{#`/`{% comment` leaks on every
  page touched; confirm page titles are set (`Business Settings`, `Locations`, per-location name).
- [ ] sidebar shows **1.1** and **1.2** Live (both rows resolve and are clickable — "Business & Locations" module
  row lights up as live).

## Close-out

- [ ] review agents, in the mandated order: code-reviewer → explorer → frontend-reviewer → performance-reviewer →
  realtime-reviewer (expect nothing to flag — no realtime surface, still runs per the mandatory sequence) →
  qa-smoke-tester → security-reviewer → test-writer.
- [ ] **`.claude/skills/tenants/SKILL.md` — AUTHOR (not update).** No `.claude/skills/tenants/` directory exists
  yet (confirmed by glob), and this is the first sub-module pass that gives the `tenants` app any reachable
  route/template/form — unlike Module 0, CLAUDE.md's Per-Module Skill rule does **not** exempt Module 1
  ("Modules 1–5 each get their own skill via this rule"). Cover: Overview; Models (`Tenant`, `Location` — both
  pre-existing, this pass's actual contribution is the CRUD surface over them); URLs (`tenants:business_settings`,
  `tenants:business_settings_edit`, `tenants:location_list/_create/_detail/_edit/_delete`); Templates
  (`templates/tenants/business/`, `templates/tenants/location/`); Tools & prompt surface ("this module has no
  tool/prompt surface"); Realtime surfaces ("this module has no realtime surface"); Seeder (`seed_tenants`,
  unchanged by this pass); Conventions & gotchas (`Location` is tenant-scoped only, never `location=` filtered;
  the `assigned_locations()` fix and why it matters; the `agents_installed` defensive-guard pattern for the
  not-yet-built agent panel); Common tasks ("add a field to Location", "add a filter", "extend the seeder"); Sidebar
  wiring (`LIVE_LINKS['1.1']`, `LIVE_LINKS['1.2']`). **Leave room in the doc structure for 1.3/1.4 to UPDATE it
  next** (they add `UserLocation` assignment CRUD and the provider-hours editor to this same skill file) —
  do not word it as if `tenants` is "done" after this pass.
- [ ] README — update only if it tracks build-state/module status; skip otherwise (same conditional as prior
  sub-modules).
- [ ] One-file-per-commit applies during the "write the module code" step that follows this plan, PowerShell-safe
  (`;` separator, never `&&`) — not a planning-time item, restated here only so the main session doesn't lose it
  between reading this plan and starting to build.

## Later passes / deferred

Carried over from `research-tenants-1.1.md`, nothing lost:

- **`Tenant.description` (Text, blank) and `Tenant.website` (URLField, blank)** — real, researched,
  spoken-to-caller fields (Ruby's "company description", Goodcall/Rosie's business summary). Needs an additive
  migration, which this pass explicitly must not ship. If added later: tenant-wide, new prompt-variable inputs for
  Module 2, not new tool-surface.
- **`Tenant.default_language` / locale** — same additive-migration reasoning; deferred until a multi-language
  prompt/voice feature exists to justify it.
- **Self-service "regenerate customer ID" flow with re-confirmation** — deferred; `customer_id` stays
  Django-admin-only.
- **Tenant-level "danger zone"** (self-deactivate, export data, delete business) — deferred indefinitely, no
  workflow to hang it off yet.

Carried over from `research-tenants-1.2.md`, nothing lost:

- **Timezone/address auto-detect from a geocoding or business-listing provider** (Goodcall's Google Business
  Profile sync) — needs a new provider adapter under `apps/runtime/providers/`; out of scope for this product
  entirely, no listing-sync capability documented anywhere.
- **Location recent-activity feed** (last N appointments/calls at the site) — blocked on `scheduling.Appointment` /
  `calls.CallSession`, neither built yet (Module 4/5).
- **Site activation/deactivation audit log** — needs a new model; deferred, would break this pass's
  zero-model constraint, only worth building if a concrete requirement appears later.
- **Bulk CSV location import** — unnecessary complexity for this product's location count.
- **Per-location "type"/category tag** (flagship/satellite/kiosk) — no current feature branches on it.
- **Wiring the list/detail agent-configured indicator to a real per-location `AgentSetting` lookup** — this pass
  ships only the `agents_installed`/defensive-guard placeholder; Module 2 (or a later `tenants` touch-up) replaces
  the static badge with a real query once `agents.AgentSetting` exists.
- **Blocking new bookings/agent activity at a deactivated location** — enforcement lives in Module 2 (agent-enable
  check should also test `location.is_active`) and Module 4 (booking-creation guard); 1.2 only owns the flag.

## Belongs to sibling sub-modules (parked, not scoped here, not lost)

- Assign/unassign staff to a location from either side, provider-flag toggle, the "would leave a user with zero
  locations" pre-confirm assignment-matrix guard → **1.3 Staff & Location Assignment**
- Per-provider weekly working-hours editor at a location → **1.4 Provider Working Hours**
- Twilio inbound number, agent enable toggle, greeting, transfer settings shown for a location →
  **2.1/2.2/2.3 Agent Setup & Telephony**
- Booking/call activity feed for a location → **4.x Calendar & Bookings / 5.x Call Logs**, once those exist

## Review notes

(filled in at the end of the build/review pass)
