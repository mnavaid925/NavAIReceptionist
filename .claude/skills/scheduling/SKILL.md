---
name: scheduling
description: Work on the Calendar & Bookings module (contacts, services, resources, availability, appointments, calendar views, callback requests). Use when the user asks to add/change/debug anything under apps/scheduling or templates/scheduling, anything about the Contact identity table, phone/E.164 normalisation, contact erasure, service catalogue, resources, availability search, appointments, the calendar, callback requests, or invokes /scheduling.
---

# scheduling — Calendar & Bookings (Module 4)

App path `apps/scheduling`, templates `templates/scheduling/`, mounted at **`/schedule/`**,
`app_name = 'scheduling'`.

This is the module the voice agent books into. Module 3's tools read `Contact`, `Service` and `Resource`
and write `Appointment`, `CallbackRequest` and `Contact` — so a change here has a realtime blast radius even
though this module itself has **no realtime surface**.

## Build state

| Sub-module | Status | Adds |
|---|---|---|
| 4.1 Contact Directory | **BUILT** | `Contact` |
| 4.2 Services & Resources | **BUILT** | `Service`, `Resource` |
| 4.3 Availability & Booking | not built | `Appointment` |
| 4.4 Calendar Views | not built | none — a **view** sub-module |
| 4.5 Bookings List & Callback Requests | not built | `CallbackRequest` |

> **Update this file, never re-author it.** Each sub-module run appends its models / routes / templates /
> seeder rows. Rewriting the file clobbers the previous sub-module's documentation.

## Models

### `Contact` — 4.1 · `models/ContactDirectory/Contacts.py`

**Invariant 1: this is THE one contact identity table.** Callers, bookers and attendees are all rows here.
Never add a `Lead`, `Caller`, `Patient` or `Attendee` model.

Base `TenantOwned` — **tenant-scoped, deliberately NOT location-scoped.** A caller belongs to the business
and may book at any of its sites. This is the one model in Module 4 without a `location` FK; the absence is
correct and is documented in the model docstring, the view module docstring and the list template so nobody
"fixes" it.

| Field | Notes |
|---|---|
| `first_name`, `last_name` | Char(128), **blank-tolerant** — the agent creates a row the instant an unknown number rings, before it has asked anyone's name |
| `phone_e164` | Char(16), **not unique**. Indexed via the composite only |
| `email` | blank |
| `date_of_birth` | null |
| `notes` | blank; **caller-dictated, so untrusted** |
| `source` | `ai_phone` / `manual` / `web`, `db_index=True`. Server-stamped, never a form field |
| `anonymized_at` | null. **Not in the ERD** — added because erasure had no other durable marker |

Indexes: `idx_contact_tenant_phone` on `(tenant, phone_e164)` — the inbound-call ANI hot path — and
`idx_contact_tenant_name` on `(tenant, last_name, first_name)`. Ordering
`['last_name', 'first_name', '-created_at']`.

Members: `save()` (normalises `phone_e164` on **every** write), `display_name`, `has_name`,
`is_anonymized`, `anonymize()`.

### `Service` — 4.2 · `models/ServicesResources/Services.py`

Base `TenantOwned`, but with a **hand-declared NULLABLE `location` FK** — the one shape in the project no
abstract base expresses. `location=None` means offered at every site; a set location means that site only.
`TenantOwned` alone would lose the per-site case; `TenantLocationOwned` would force a duplicate row per
location for a service every branch offers.

Fields: `name`, `description` (what the agent says aloud), `duration_minutes`, `buffer_minutes` (held
**after** the appointment), `requires_resource`, `is_active`, `display_order`.
Index `idx_service_tenant_loc_active` on `(tenant, location, is_active)`. Ordering `['display_order', 'name']`.

Members: `is_all_locations`, `location_label`, `total_minutes` (duration + buffer — **this**, not
`duration_minutes`, is what 4.3 must subtract from a working window), `is_offered_at(location)`.

### `Resource` — 4.2 · `models/ServicesResources/Resources.py`

Base `TenantLocationOwned` — fully location-scoped. A room is at one site by definition.

Fields: `name`, `resource_number`, `description`, `is_active`, `display_order`.
Unique constraint `uniq_resource_location_name` on **`(location, name)`** — Downtown and Uptown may each have
a "Surgery 1". Index on `(tenant, location, is_active)`. Member: `display_label`.

Deliberately **no `capacity`** (a room is exclusive; there is no group-class or attendee model) and
**no FK to the user model** (the provider is a separate concern from the room — merging them would make
"room 2 is busy" and "Dr Chen is busy" the same constraint when they are independent).

## Routes

`urls/` is a **package** (not the flat module `tenants`/`accounts` use), because this app is headed for five
entities. `urls/__init__.py` sets `app_name` and concatenates each sub-module's list. Order is behaviour
across the **whole concatenated list** — check any new greedy route against all of it.

**4.1** — `urls/ContactDirectory/Contacts.py`:
`contact_list` · `contact_create` · `contact_detail` · `contact_edit` · `contact_delete` (POST) ·
`contact_forget` (POST)

**4.2** — `urls/ServicesResources/{Services,Resources}.py`:
`service_list` · `service_create` · `service_detail` · `service_edit` · `service_delete` (POST) ·
`resource_list` · `resource_create` · `resource_detail` · `resource_edit` · `resource_delete` (POST)

## Templates

`templates/scheduling/directory/contact/` — `list.html`, `detail.html`, `form.html`, `_filters.html`.
`templates/scheduling/catalog/service/` and `templates/scheduling/catalog/resource/` — same four each.
Shared partials used: `partials/_pagination.html`, `_empty_state.html`, and (once 4.3 / Module 5 land)
`_appointment_status_badge.html` / `_call_status_badge.html` — **both take `obj=`**, not
`appointment=`/`session=`.

**Each list header says something different, on purpose, because each model is scoped differently:**
contacts → the business name and "all locations" (not location-scoped); services → the business name plus
which site you are working at (nullable location); resources → the **active location name** (fully
location-scoped, so the rows change on a switch and nothing else on screen would explain why).

## Tools & prompt surface

**This module registers no LLM tools.** Module 3.3 owns the dispatcher and will call into this module's
models. When it does:

* `identify_contact` resolves a caller by ANI against `Contact.phone_e164`. **The match can return more than
  one row** — `(tenant, phone_e164)` is deliberately non-unique. It must NOT silently `.first()`; that
  attaches the call, and anything booked on it, to the wrong person's history. It needs an explicit N>1
  policy: treat as unidentified and ask who is calling.
* `tenant_id`, `location_id`, `contact_id` and `session_id` come from **server-side session state** and are
  never tool parameters (Invariant 3). The resolved `contact_id` is never handed back to the model to echo.
* `normalize_e164` is pure CPU with no I/O and no catastrophic backtracking — safe to call inline on the
  event loop. `Contact.save()` is a single ORM write with no `select_for_update` and no signal receivers, so
  one `database_sync_to_async` wrapper is sufficient.

## Realtime surfaces

**This module has no realtime surface** — no `consumers/`, no `routing.py`, no `async def`, no websocket
route, no provider adapter. `config/asgi.py`'s `websocket_urlpatterns` is untouched by it.

## Seeder

`manage.py seed_scheduling` (`--flush` to rebuild). Idempotent; runs on top of `seed_tenants` +
`seed_accounts` and looks tenants up by slug rather than creating them.

**4.1 seeds 8 contacts** across `acme` (5) and `globex` (3), shaped to exercise real edge cases rather than
to look tidy: an anonymous caller with a number and no name, **two people sharing one household line**
(`+13125550101`), an email-only web enquiry with no number, a deliberately **unnormalised** number
(`3125550188`) that proves `save()` normalises the seeder's writes too, and all three `source` values.

**4.2 seeds 9 services and 10 resources.** The services mix all-location and site-pinned entries, include an
inactive one and a `requires_resource=False` phone consultation. The resources cover **all four** demo
locations, with "Surgery 1" deliberately duplicated across Downtown and Uptown to prove the unique
constraint is location-scoped. Services key on `(tenant, location, name)`; resources on `(location, name)` —
the same tuples their forms validate.

> **The dedupe lookup must normalise before comparing.** `Contact.save()` normalises on write, so keying on
> the raw spec value re-creates the unnormalised row on every run. That bug shipped once and was caught by
> the second-run check.

## Conventions & gotchas

* **THE nullable-location trap (4.2).** `Service.location` may be `NULL`. Anywhere you filter services by
  location, the filter must be **ADDITIVE** —
  `Q(location=here) | Q(location__isnull=True)` — never a plain `filter(location=here)`, which silently
  hides every business-wide service, i.e. most of a typical catalogue. `_bookable_here()` in
  `views/ServicesResources/Services.py` is the canonical implementation; reuse it rather than rewriting it.
* **Site-pinned services: business-wide READ, location-gated WRITE.** The catalogue is readable from any
  site, but `service_edit_view` and `service_delete_view` refuse when the user is not assigned to a pinned
  service's `location` — those fields decide what the agent offers and books there. An all-locations
  service stays editable by anyone.
* **`ServiceForm` renders `location`; it is the ONLY form in the project that does.** Justified because it
  is a real product choice, not an identity field. Two things keep it safe: the queryset is narrowed to
  `user.assigned_locations()`, and the instance's **current** location is UNIONed in — without that union
  an unassigned editor's select renders with no option selected, the browser falls back to the blank
  "All locations", and an unrelated edit silently widens the service to every site.
* **Excluding a field from a form silences Django's `UniqueConstraint` check.** `ResourceForm` excludes
  `location`, so Django cannot build the `(location, name)` tuple and skips validation entirely — a
  duplicate would 500 with a raw `IntegrityError`. `ResourceForm.clean_name` enforces it by hand. Any
  future form that excludes part of a constraint needs the same treatment.
* **`.isdecimal()`, never `.isdigit()`, before `int()`.** `isdigit()` is `True` for `'²'` and fullwidth
  `'１'`, which `int()` then refuses — turning a query-string filter into a 500.
* **`save_or_report_conflict` (`views/_helpers.py`)** wraps `form.save()` for every form with a hand-rolled
  uniqueness check, converting a lost race into a form error instead of a 500. Use it in 4.3/4.5 too.
* **Access tier (module-wide, confirmed with the user).** list/detail/create/edit are open to **any signed-in
  tenant user** — taking bookings is front-desk work. Only **delete and forget** are
  `@tier_required(*MANAGEMENT_TIERS)`. This deliberately differs from `tenants`/`agents`, where every CRUD
  view is management-gated. 4.2/4.3/4.5 follow this same pattern.
* **Location scoping cuts both ways.** The `Contact` row is business-wide, but anything location-scoped
  hanging off it is not. `_appointments_for` / `_call_sessions_for` filter by
  `request.user.assigned_locations()` — without that, a receptionist assigned to one site reads another
  site's booking times and call history off the contact page.
* **Delete vs erase.** `Contact` really is deleted, unlike `Location` (which deactivates). Once 4.3 adds
  `Appointment.contact` with `on_delete=PROTECT`, a contact with bookings raises `ProtectedError` and the
  view redirects to the **erasure** path instead. `anonymize()` blanks every identifying field and keeps the
  row so the calendar does not grow holes. There is no un-erase; editing an erased contact is refused.
* **PII discipline.** Never log a name, number, email or note body. Every `logger.info` here carries primary
  keys only — especially in `contact_forget_view`, where logging the details would defeat the erasure.
  `notes` renders with `|linebreaksbr`, **never `|safe`**.
* **Piping.** Pipe `manage.py` commands to `tail`, **never `head`** — a closed pipe kills the process on
  `BrokenPipeError` and rolls back the `@transaction.atomic` seeder, which looks exactly like a real failure.
* **The ERD field is `start_at`, singular** (not `starts_at`). An import guard covers the import, not a field
  reference, so a wrong name surfaces only when the model lands.

## Common tasks

**Add a field to an existing model** — edit `models/<SubModule>/<Entity>.py`, add it to the form's
`Meta.fields` *only if a user should set it* (server-owned facts like `source` and `anonymized_at` stay out),
render it in `form.html` and `detail.html`, then `makemigrations scheduling` + `migrate`.

**Add a new model + CRUD** — create `<SubModule>/<Entity>.py` in each of `models/ forms/ views/ urls/`, add
the re-export block to **every** touched `__init__.py` (a missing re-export is an `ImportError` at URL-table
build time), wire the urlpatterns into `urls/__init__.py`, register in `admin.py`, extend `seed_scheduling`
idempotently, add `templates/scheduling/<submodule>/<entity>/{list,detail,form}.html`, and add one
`LIVE_LINKS["N.M"]` entry.

**Add a filter** — parse it in the view **before** pagination, degrade a junk value to "no filter" rather
than raising, pass the choices/queryset the `<select>` needs into the context, and compare with `==` for a
string choice or `|stringformat:"d"` for a pk.

**Extend the seeder** — reuse existing tenants/locations/contacts by lookup; never invent duplicates. Guard
every row with an existence check on its real identifying key, and re-run the command twice to prove zero new
rows.

## Sidebar wiring

`apps/accounts/navigation.py` → `LIVE_LINKS`:

```python
'4.1': {'Contacts': 'scheduling:contact_list'},
'4.2': {'Services': 'scheduling:service_list',
        'Resources': 'scheduling:resource_list'},
```

## Tests

`apps/scheduling/tests/` — 4.1: `test_models.py`, `test_services.py`, `test_forms.py`, `test_views.py`,
`test_security.py`; 4.2: `test_catalog_models.py`, `test_catalog_forms.py`, `test_catalog_views.py`,
`test_catalog_security.py`. **224 passing.** Run with
`venv\Scripts\python.exe -m pytest -q apps/scheduling`. Fixtures live in the repo-root `conftest.py` (two
tenants, three locations, owner/manager/staff users, and client fixtures that activate a location through the
real `accounts:switch_location` endpoint rather than poking the session).

`test_views.py` carries a `TODO(4.3 / Module 5)` marker on the regression guard that asserts the appointment
and call panels return `None` today — **replace it with the real cross-location assertion** when those models
land.
