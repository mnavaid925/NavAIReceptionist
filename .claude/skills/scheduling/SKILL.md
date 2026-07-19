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
| 4.2 Services & Resources | not built | `Service`, `Resource` |
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

## Routes

`urls/` is a **package** (not the flat module `tenants`/`accounts` use), because this app is headed for five
entities. `urls/__init__.py` sets `app_name` and concatenates each sub-module's list. Order is behaviour
across the **whole concatenated list** — check any new greedy route against all of it.

**4.1** — `urls/ContactDirectory/Contacts.py`:
`contact_list` · `contact_create` · `contact_detail` · `contact_edit` · `contact_delete` (POST) ·
`contact_forget` (POST)

## Templates

`templates/scheduling/directory/contact/` — `list.html`, `detail.html`, `form.html`, `_filters.html`.
Shared partials used: `partials/_pagination.html`, `_empty_state.html`, and (once 4.3 / Module 5 land)
`_appointment_status_badge.html` / `_call_status_badge.html` — **both take `obj=`**, not
`appointment=`/`session=`.

The list header shows the **business name and "all locations"**, not an active-location indicator, because
Contact is not location-scoped. Showing one would imply a filter that does not exist.

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

> **The dedupe lookup must normalise before comparing.** `Contact.save()` normalises on write, so keying on
> the raw spec value re-creates the unnormalised row on every run. That bug shipped once and was caught by
> the second-run check.

## Conventions & gotchas

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
```

## Tests

`apps/scheduling/tests/` — `test_models.py`, `test_services.py`, `test_forms.py`, `test_views.py`,
`test_security.py`. **89 passing.** Run with
`venv\Scripts\python.exe -m pytest -q apps/scheduling`. Fixtures live in the repo-root `conftest.py` (two
tenants, three locations, owner/manager/staff users, and client fixtures that activate a location through the
real `accounts:switch_location` endpoint rather than poking the session).

`test_views.py` carries a `TODO(4.3 / Module 5)` marker on the regression guard that asserts the appointment
and call panels return `None` today — **replace it with the real cross-location assertion** when those models
land.
