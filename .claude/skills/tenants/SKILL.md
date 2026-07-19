---
name: tenants
description: Work on the Business & Locations module (the business record, location directory, staff-to-location assignment, provider working hours). Use when the user asks to add/change/debug anything under apps/tenants or templates/tenants, anything about Tenant or Location models, the assignment matrix, provider_hours, or invokes /tenants.
---

# Module 1 — Business & Locations (`apps/tenants`)

## Overview

Owns the two tenancy tables the whole product scopes against, plus the surfaces
that administer them. Mounted at **`/manage/`** in `config/urls.py`.

| Sub-module | Ships |
|---|---|
| 1.1 Business Settings | Read the business record; owner-only edit of name + timezone |
| 1.2 Location Directory | Full CRUD over sites, delete implemented as deactivation |
| 1.3 Staff & Location Assignment | One matrix over `accounts.UserLocation`, inline provider toggle |
| 1.4 Provider Working Hours | Interval editor over `User.provider_hours`, plus a tenant-wide report |

**All four sub-modules added ZERO models and ZERO migrations.** `Tenant`,
`Location`, `UserLocation` and `provider_hours` all pre-existed. `makemigrations
--check` must keep saying "No changes detected" — if a change here wants a
migration, stop and re-read `NavAIReceptionist-ERD.md` first.

## Models

Both owned models live in `apps/tenants/models/` (FLAT — foundation apps have no
`<SubModule>/` level).

**`tenants.Tenant`** — `name`, `slug` (unique), `customer_id` (unique),
`timezone`, `is_active`, `created_at`, `updated_at`. The isolation root: every
other model in the project FKs it. Carries no `tenant` FK itself.

**`tenants.Location`** — `tenant` FK, `name`, `slug`, `address_line1/2`, `city`,
`state`, `postal_code`, `country`, `timezone`, `phone`, `is_active`. Unique
`(tenant, slug)`; index `(tenant, is_active)`. Helpers: `full_address`,
`tzinfo` (degrades to UTC on an unknown name), `local_now()`.

**Reused, not owned:** `accounts.User` (`is_provider`, `provider_hours`,
`assigned_locations()`), `accounts.UserLocation`.

## URLs — `app_name = 'tenants'`, prefix `/manage/`

`urls.py` is a FLAT module with its own `crud(base, name)` factory.

| Name | Path |
|---|---|
| `business_settings` | `/manage/business/` |
| `business_settings_edit` | `/manage/business/edit/` |
| `staff_locations` | `/manage/staff/` |
| `toggle_provider` | `/manage/staff/<pk>/provider/` |
| `provider_hours_report` | `/manage/hours/` |
| `provider_hours` | `/manage/hours/<pk>/<location_pk>/` |
| `location_list` / `_create` / `_detail` / `_edit` / `_delete` | `/manage/locations/...` |

Literals are emitted BEFORE the `crud()` block — first-match-wins means a
`<int:pk>` route ahead of `locations/create/` would swallow it.

## Templates — `templates/tenants/<entity>/<page>.html`

Flat (foundation app). `business/{detail,form}.html`,
`location/{list,detail,form,_filters}.html`, `staff/matrix.html`,
`hours/{form,report}.html`. All extend `base.html` (blocks `title` and `content`
only) and reuse `partials/_pagination.html` + `partials/_empty_state.html`.

## Tools & prompt surface

**None.** This module registers no LLM tool and injects no prompt variable. It
does however own data the runtime will read: `Location.timezone` is what every
appointment and transfer window is evaluated in, and `provider_hours` is what
availability search filters against.

## Realtime surfaces

**This module has no realtime surface** — no consumer, no `routing.py` entry, no
webhook, no background task.

## Services — the Module 4 contract

`apps/tenants/services.py` is flat at the app root and is the ONLY writer of the
`provider_hours` JSON. Availability search (Module 4) must import from here
rather than reading the field:

```python
get_provider_intervals(user, location, weekday=None)  # -> [{start_time, end_time, days}]
is_provider_available(user, location, weekday, at_time)  # -> bool
validate_provider_hours(intervals, *, location_id, assigned_location_ids)  # -> [error, ...]
set_provider_hours(user, location_id, intervals, *, commit=True)
clear_provider_hours(user, location_id, *, commit=True)
has_configured_hours(user, location_id)
weekly_summary(user, location)
```

Storage shape, keyed by location id **as a string**:

```json
{"7": [{"start_time": "09:00", "end_time": "12:30", "days": ["mon", "tue"]}]}
```

* **Key absent** = never configured. **Key present, empty list** = explicitly not
  working here. Both yield zero intervals; the editor distinguishes them.
* **No configured hours means UNAVAILABLE**, never "available all day".
* Every reader degrades on malformed JSON rather than raising — this blob has
  been through migrations and hand edits.

## Seeder

`seed_tenants` creates two demo businesses (Acme `ACME-1001`, Globex
`GLBX-2002`), each with **two** locations in different timezones — a
single-location tenant hides every cross-location bug. `seed_accounts` (in
`accounts`) builds the users and `UserLocation` rows on top and calls
`seed_tenants` automatically when no business exists. Both are idempotent.

## Conventions & gotchas

1. **`Location` is tenant-scoped but NOT location-scoped** — it IS the location.
   Filter on `tenant=request.tenant` only; adding `location=request.location`
   would mean a site could only ever see itself.
2. **`assigned_locations()` filters `is_active=True`.** That is a security
   boundary, not presentation: without it a deactivated site stays switchable for
   everyone already assigned, and `ActiveLocationMiddleware` keeps honouring a
   stored id pointing at it.
3. **Deletion is deactivation everywhere.** Appointments, call sessions and
   callbacks FK `Location` with CASCADE, so a real delete takes the site's whole
   history with it. `location_delete_view` also refuses to deactivate the last
   active site.
4. **`UserLocation` is the cross-location IDOR boundary.** The matrix intersects
   BOTH halves of every submitted `"<user_pk>:<location_pk>"` pair with the
   tenant's own querysets before writing, so a forged pair matches nothing.
   Never `Location.objects.get(pk=posted_id)`.
5. **1.1 has no pk in any URL** — one Tenant per business, and `request.tenant`
   IS it. `customer_id`, `slug` and `is_active` are shown but never editable:
   editing the first locks every user out at login, and the third blocks the next
   login for everyone with nobody left able to undo it.
6. **Import-guarded cross-module reads.** `apps.agents` (Module 2) and
   `apps.scheduling` (Module 4) do not exist yet.
   `Location._agent_setting_for()` and `views/_helpers.future_appointment_count()`
   both `try/except ImportError` and return `None`/`0`, so THE CALL SITES NEVER
   CHANGE when those modules land.
7. **Portable strftime only** — `%-d` / `%-I` are a glibc extension the Windows
   runtime rejects. `services.format_hhmm` uses the padded form deliberately.
8. **`MANAGEMENT_TIERS`** lives in `views/_common.py` and MUST stay in its
   `__all__`, or `import *` silently omits it and every view module fails at
   import with `name 'MANAGEMENT_TIERS' is not defined`.

## Common tasks

**Add a field to `Location`** — this needs a migration, so confirm it against the
ERD first. Then: model → `LocationForm.Meta.fields` → `location/form.html` is
generic and needs nothing → add it to `location/detail.html` → extend
`seed_tenants` → `makemigrations tenants`.

**Add a filter to the location list** — pass the choice list from
`location_list_view`, add the `<select>` to `location/_filters.html` comparing
with `==` against the raw GET value, validate the value in the view so junk
degrades to no filter, and apply it BEFORE `paginate()`.

**Change the working-hours JSON shape** — change it in `services.py` only, keep
`get_provider_intervals`'s signature stable, and make the reader tolerate the old
shape. Module 4 will be calling it.

**Extend the seeder** — `seed_tenants` for businesses and sites,
`seed_accounts` for users and assignments. Both must stay idempotent; a second
run prints "Data already exists."

## Sidebar wiring

`apps/accounts/navigation.py`:

```python
'1.1': {'Business Settings': 'tenants:business_settings'},
'1.2': {'Locations': 'tenants:location_list'},
'1.3': {'Staff & Locations': 'tenants:staff_locations'},
'1.4': {'Working Hours': 'tenants:provider_hours_report'},
```

Module 1 DOES appear in the sidebar. Only Module 0 is excluded, via
`SIDEBAR_EXCLUDED_MODULES` — its surfaces live in the topbar user dropdown and
the account tab strip instead.
