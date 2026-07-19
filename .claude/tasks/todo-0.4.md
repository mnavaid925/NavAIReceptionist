# Sub-module 0.4 — Active Location Switcher (Module 0: Accounts & Access, `accounts`) — plan from research-accounts-0.4.md (2026-07-19)

*(Written to `.claude/tasks/todo-0.4.md` — a standalone file. `.claude/tasks/todo.md` holds 0.1's completed plan and
is being written to by sibling agents; this pass does not touch it.)*

## Shape: VIEW sub-module — ZERO new models, ZERO migrations

0.4 introduces no model. It reads `accounts.UserLocation` (via the already-built `User.assigned_locations()`) and
`tenants.Location`, and its one write is a mutation of **Django session state**, never a domain row — so the
CRUD-completeness "no create/edit/delete views" rule is satisfied trivially: there is no model here to create,
edit or delete. The bulk of the sub-module's own enforcement (`ActiveLocationMiddleware`'s per-request
revalidation, `set_active_location()`, `activate_sole_location()`, `assigned_locations()`, the context processor,
and the topbar's `.location-switcher` markup) was **already built in 0.1** and is confirmed read, not re-planned,
below. What genuinely remains is the interactive `POST` endpoint that mechanism has been waiting for, plus the
forced-choice UI for the one state the middleware deliberately leaves unresolved (2+ assignments, none chosen).

## Models

**NONE.** Tables read, none written beyond the session:
- `accounts.UserLocation` — via `request.user.assigned_locations()` (tenant-scoped join, already exists, already migrated)
- `tenants.Location` — display only (name, in the switcher `<select>` and the dashboard's "Your locations" table)
- `accounts.User` — the session owner; no field on `User` is written by this pass

No new migration. `makemigrations --check` must report "No changes detected" as part of Verify — that is the
proof this claim holds, not an assumption.

## Already built by 0.1 — confirmed by reading the files, NOT re-planned here

- [x] `apps/accounts/middleware.py` → `ActiveLocationMiddleware` — reads `ACTIVE_LOCATION_SESSION_KEY`
  (`'active_location_id'`) from the session, re-validates against `user.assigned_locations()` on **every**
  request, drops a stale/foreign id, auto-activates the sole assignment, degrades to `request.location = None`
  for 0 or 2+ assignments with none chosen. This IS the cross-location IDOR boundary; 0.4 adds a caller to it,
  not a replacement for it.
- [x] `apps/accounts/views/_helpers.py` → `set_active_location(request, location)` and
  `activate_sole_location(request, user)` — both already exist and are reused as-is.
- [x] `apps/accounts/models/User.py` → `assigned_locations()` — the authorization boundary every lookup below
  goes through; never `Location.objects.get(pk=...)` directly.
- [x] `apps/accounts/context_processors.py` → already supplies `user_locations`, `active_location`,
  `active_tenant`, and `nav_urls.switch_location` (resolves defensively via `_resolve()`, currently `None`
  because the url doesn't exist — 0.4 makes it resolve). **No change needed to this file.**
- [x] `templates/partials/_topbar.html` → the `.location-switcher` POST `<form>`/`<select>` markup already
  exists and already posts `location` to `nav_urls.switch_location`. **Genuinely needs two edits** (below): the
  outer guard, and a placeholder option + hidden `next` field.
- [x] `apps/accounts/urls.py` → FLAT module, `app_name='accounts'`, literal-routes-first convention already
  established by the 0.1 block.

## Backend (`apps/accounts/` — FLAT, no sub-module level, per Backend Package Structure rule 9)

- [ ] **`apps/accounts/views/_helpers.py`** — promote the redirect-safety helper currently private to
  `views/Auth.py` (`_safe_next`) up into this shared module, since it is now used by **two** sub-modules
  (0.1's `login_view` and 0.4's `switch_location_view`) — exactly the "used by more than one sub-module"
  threshold that puts a helper here rather than duplicating it. Rename (dropping the leading underscore to
  match this module's existing style — `get_client_ip`, `set_active_location`, `activate_sole_location` are
  none of them prefixed) to `safe_redirect_target(request, param='next', default='accounts:dashboard')`:
  reads `request.POST.get(param) or request.GET.get(param)`, validates with
  `django.utils.http.url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()},
  require_https=request.is_secure())`, returns the candidate or `default`. **Deliberately diverges from the
  research's "validate `HTTP_REFERER`" suggestion**: `Referer` can be stripped by the browser/a proxy or absent
  under HTTPS→HTTP navigation, and is materially harder to unit-test than a posted `next` field. Reusing the
  exact mechanic `login_view` already ships (a hidden `next` value run through
  `url_has_allowed_host_and_scheme`) is simpler, already proven, and directly satisfies "promote the helper for
  reuse rather than duplicating it."
- [ ] **`apps/accounts/views/Auth.py`** — delete the local `_safe_next(request)` function; import
  `safe_redirect_target` from `_helpers` instead; change `login_view`'s
  `return redirect(_safe_next(request))` to `return redirect(safe_redirect_target(request))`. One-line
  behavioural no-op — same validation, same default — but now shared.
- [ ] **`apps/accounts/views/LocationSwitcher.py`** — new file (naming mirrors `Auth.py`/`Dashboard.py`: a
  concern name, not a model name, since there is no model). `switch_location_view(request)`:
  - `@require_POST` + `@login_required` (GET must 405, not render a page — matches "GET on the switch route is
    refused").
  - Read `raw_id = (request.POST.get('location') or '').strip()`.
  - **Guard against the ORM `ValueError` trap** the way `paginate()` already does for `?page=`: only attempt the
    lookup when `raw_id.isdigit()` (an `AutoField` pk `.filter(pk='abc')` raises `ValueError` mid-query, not a
    clean empty queryset — `isdigit()` short-circuits that before it reaches the ORM).
  - `location = request.user.assigned_locations().filter(pk=raw_id).first() if raw_id.isdigit() else None` —
    **never** `Location.objects.get(pk=raw_id)`. This one line IS the sub-module's whole reason for existing:
    it re-derives the target from the authorization boundary instead of trusting the posted id, so a foreign
    tenant's location, a same-tenant-but-unassigned location, and a locations table that doesn't exist for this
    tenant all collapse to the same `None` — no special-casing per failure mode, no information leak between
    them.
  - On a hit: `set_active_location(request, location)`, `messages.success(request, f'Switched to
    {location.name}.')`.
  - On a miss (junk, foreign, unassigned, or empty): **no session write at all** — `request.location` for the
    *next* request is whatever `ActiveLocationMiddleware` already had it as; `messages.error(request, 'That
    location is not available to you.')`. Never a 403/404 response code — this is a same-page redirect-with-flash
    degrade, matching the project's existing "a junk value must degrade to no filter, never raise" filter rule
    applied to a switch instead of a filter.
  - `return redirect(safe_redirect_target(request))` — reads the hidden `next` field the topbar form now posts
    (see Templates below); falls back to `accounts:dashboard`.
  - No `ModelForm`, no plain `Form` class — the view parses the two POST fields directly, matching the
    lightweight style `paginate()` already uses for a similarly "degrade, don't validate-and-error" input.
- [ ] **`apps/accounts/views/__init__.py`** — add `switch_location_view` to the imports (`from
  apps.accounts.views.LocationSwitcher import switch_location_view`) and to `__all__`. Forgetting this is an
  `AttributeError` at URL-resolve time, not import time — it only surfaces the first time `accounts:switch_location`
  is reversed.
- [ ] **`apps/accounts/urls.py`** — one new literal route, in its own clearly-labelled block **after** the 0.1
  block and **before** the `# Later sub-modules append their crud() blocks here` comment (no `<int:pk>` route
  exists yet to collide with, but the block keeps the file's own "literals before member routes" convention for
  whoever adds 0.3's `crud('users', 'user')` next):
  ```python
  # -- 0.4 Active Location Switcher --------------------------------------- #
  path('locations/switch/', views.switch_location_view, name='switch_location'),
  ```
- [ ] `forms/`, `models/`, `admin.py`, migrations, `seed_accounts.py` — **no changes**. No new form (see above),
  no new model, nothing to register in `admin.py`, nothing to migrate. The existing demo data already covers
  every test scenario this pass needs (see Verify) — extending the seeder would be scope creep for a
  view-shaped sub-module with nothing new to seed.

## Realtime & agent surface

N/A. Confirmed by research's Compliance section: 0.4 touches no `calls.CallSession`, no LLM tool, no provider
adapter, no Channels consumer, no cost line. Its only "external" surface is the Django session, already in use.

## Wire-up

- [ ] **`apps/accounts/navigation.py`** — add exactly one entry:
  ```python
  LIVE_LINKS['0.4'] = {'Assigned-Location List': 'accounts:dashboard'}
  ```
  Reasoning: none of 0.4's four bullets (Assigned-Location List, Session Active Location, Assignment Validation,
  Location Context Header) is its own routable page — the switcher is topbar chrome, not a sidebar destination,
  same shape as 0.1's four pre-auth bullets. Of the four, **Assigned-Location List** maps most literally onto a
  page that already exists and already renders it: the dashboard's "Your locations" table (built in 0.1,
  `templates/accounts/dashboard.html`) IS that feature made visible, and after this pass it also carries the
  "Active" badge the switcher drives. Picking a bullet whose content is genuinely on the target page (rather than
  reusing 0.1's precedent of a paraphrased "Dashboard" label) keeps the mapping literal per the instruction to use
  exact `NavAIReceptionist.md` bullet text.
- [ ] `config/settings.py`, `config/urls.py`, `config/asgi.py` — **no change**. Not a brand-new-app run; `accounts`
  and its routing are already fully wired from 0.1.
- [ ] `AUTH_USER_MODEL` ordering item — **N/A**, already satisfied in 0.1 (not the first `makemigrations` run).

## Templates

- [ ] **`templates/partials/_topbar.html`** — two edits to the existing `.location-switcher` block:
  1. **Loosen the outer guard** from `{% if active_location %}` to `{% if user_locations %}`, so a user with 2+
     assignments and nothing chosen yet sees the control at all, instead of the current dead silence.
  2. **Inside it**, branch on whether the url resolves (unchanged defensive pattern) and, when it does, render a
     **placeholder option** when there is no active location yet, plus a **hidden `next` field** so the switch
     view can redirect back to wherever the user was:
     ```html
     {% if user_locations %}
       {% if nav_urls.switch_location %}
         <form class="location-switcher" method="post" action="{{ nav_urls.switch_location }}">
           {% csrf_token %}
           <input type="hidden" name="next" value="{{ request.path }}">
           <i data-lucide="map-pin" aria-hidden="true"></i>
           <label class="sr-only" for="active-location">Active location</label>
           <select class="form-select" id="active-location" name="location" onchange="this.form.submit()">
             {% if not active_location %}
               <option value="" selected disabled>Choose a location&hellip;</option>
             {% endif %}
             {% for location in user_locations %}
               <option value="{{ location.pk }}"
                 {% if active_location and location.pk == active_location.pk %}selected{% endif %}>
                 {{ location.name }}
               </option>
             {% endfor %}
           </select>
           <noscript><button type="submit" class="btn btn-outline">Switch</button></noscript>
         </form>
       {% elif active_location %}
         <span class="location-switcher">
           <i data-lucide="map-pin" aria-hidden="true"></i>
           <span class="text-muted">{{ active_location.name }}</span>
         </span>
       {% endif %}
     {% endif %}
     ```
     The `{% elif active_location %}` fallback keeps today's read-only-span behaviour as a defensive degrade for
     the (now purely historical, since 0.4 ships the url) case where the url briefly doesn't resolve.
- [ ] **`templates/partials/_choose_location_banner.html`** — new small partial, styled with the existing
  `.alert`/`.alert-info` classes `base.html`'s own messages block already uses (no new CSS). Renders only when
  `user.is_authenticated and user_locations and not active_location` — i.e. exactly the 2+-assignments-none-chosen
  state, never the 0-assignment state (that one is `templates/accounts/dashboard.html`'s existing
  `_empty_state.html` include, unchanged). Copy: an icon (`map-pin`) + "Pick a location from the switcher above to
  see this business's data — every page is scoped to one location at a time." No link needed; the switcher it
  refers to is already in the topbar directly above.
- [ ] **`templates/base.html`** — include the new banner partial once, globally, right after the existing
  `{% if messages %}` block and before `{% block content %}`. Deliberately **global, not dashboard-only**: every
  future location-scoped page (1.2 onward) would otherwise need to remember to include it itself, and a
  forgotten include is a silent empty-page bug, not a loud one. One `{% include "partials/_choose_location_banner.html" %}`
  line.
- [ ] **`templates/accounts/dashboard.html`** — small polish, not required but consistent: change the Session
  card's "Active location" `<dd>` fallback text from bare `Not selected` to `Not selected — choose one above`,
  since the global banner now explains why.

No `form.html` — there is no model, so there is no form to build. No `list.html`/`detail.html` beyond the existing
dashboard — a view sub-module's absence of CRUD templates is correct here, not a gap.

## Verify

- [ ] `makemigrations --check` → **"No changes detected"** — the concrete proof this pass added zero migrations.
- [ ] `manage.py check` — clean.
- [ ] assert `PROVIDER_MODE=fake` — trivially true (0.4 imports no provider adapter); confirm the env default is
  intact, matching every other pass.
- [ ] No `migrate` run needed (nothing new to apply); no `seed_accounts` re-run needed for new data — confirm the
  existing seeded rows already cover every scenario below:
  - `admin_acme` (Acme, owner tier) — assigned to **both** `downtown` and `uptown` → the 2-assignment,
    no-auto-select user. This is the primary switcher test subject.
  - `acme_downtown` (Acme, manager tier) — assigned to `downtown` **only** → auto-activates at login, and is the
    subject for "same-tenant, unassigned location" (POST `uptown`'s pk) refusal.
  - `admin_globex` / `globex_riverside` (Globex) — the source of a **cross-tenant** pk (`riverside`'s id) to POST
    while authenticated as an Acme user.
- [ ] `pytest -q apps/accounts` — create `apps/accounts/tests/__init__.py` if 0.1's test-writer step has not
  already created the `tests/` package (check first; do not overwrite an existing `__init__.py`), then
  `apps/accounts/tests/test_location_switcher.py` covering:
  - **Switch succeeds and persists** — logged in as `admin_acme`, POST `location=<uptown.pk>` →
    `request.location` becomes Uptown on this response's redirect target render, **and** a subsequent unrelated
    GET (e.g. to `accounts:dashboard`) still reflects Uptown as active — proves the session write survives
    `ActiveLocationMiddleware`'s next-request revalidation, not just the redirect response itself.
  - **Cross-tenant pk refused** — logged in as `admin_acme`, POST `location=<globex_riverside_location.pk>` →
    redirect (not 404/403 — this view degrades, it does not raise), `request.location` **unchanged** from
    whatever it was before the POST, an error message present, no session key overwritten with the foreign id.
  - **Same-tenant, unassigned location refused** — logged in as `acme_downtown` (assigned to `downtown` only),
    POST `location=<uptown.pk>` (a real Acme location, but not one this user is assigned to) → refused the same
    way; `request.location` stays `downtown`.
  - **Junk/absent pk degrades cleanly** — POST `location=abc`, POST `location=` (empty), POST with no `location`
    key at all → all three return a redirect (never a 500, never a `ValueError` traceback), `request.location`
    unchanged.
  - **GET is refused** — `GET accounts:switch_location` → `405`, no session mutation.
  - **Open-redirect refusal on `next`** — POST a valid `location` pk together with
    `next=http://evil.example.com/` → redirects to `accounts:dashboard`, never to the off-site URL (reuses the
    same `url_has_allowed_host_and_scheme` mechanic already tested for login's `next`, now via
    `safe_redirect_target`).
  - **Topbar renders the switcher for the no-active-location state** — render `dashboard.html` as `admin_acme`
    immediately after login (before any switch): assert the `<select id="active-location">` markup IS present
    (not the read-only `<span>`), the placeholder `<option value="" selected disabled>` is present, and the
    "choose a location" banner renders. Then switch, re-render, and assert the banner is gone and the chosen
    location's `<option>` carries `selected`.
  - **Single-assignment user never sees the switcher** — render as `acme_downtown` (or `globex_riverside`):
    assert no `<select id="active-location">` in the markup (unchanged 0.1 behaviour — the middleware already
    auto-selected the sole assignment, so there is nothing to choose).
- [ ] Twilio signature + idempotency — **N/A**, 0.4 has no webhook.
- [ ] websocket connect/reject — **N/A**, 0.4 has no Channels consumer.
- [ ] `temp/` smoke sweep as `admin_acme` (password printed by `seed_accounts` — read its own output, per Seed
  Command Rule 3, currently `navai-demo-2026` but confirm rather than assume): log in, confirm the dashboard shows
  the choose-location banner and the interactive switcher (not the read-only span); POST-switch into Downtown via
  the real form submission path; confirm the banner disappears and the "Your locations" table's Downtown row
  carries the Active badge; attempt the cross-tenant and same-tenant-unassigned POSTs via a raw `requests`/test
  client call (not reachable through the rendered UI, since the `<select>` only ever offers the user's own
  assigned locations — this is exactly why the server-side re-derivation matters) and confirm both are refused
  with `request.location` unchanged; confirm zero `{#`/`{% comment` leaks on every rendered page touched.
- [ ] sidebar shows `0.4` Live (the "Assigned-Location List" → Dashboard row resolves and is clickable).

## Close-out

- [ ] review agents (code-reviewer → explorer → frontend-reviewer → performance-reviewer → realtime-reviewer →
  qa-smoke-tester → security-reviewer → test-writer) — realtime-reviewer should again have nothing to flag (no
  realtime surface) but still runs per the mandatory sequence.
- [ ] **SKILL.md: NONE for this module**, matching 0.1's precedent — CLAUDE.md's Per-Module Skill section
  explicitly carves Module 0 out: *"Module 0 (`accounts`) is the foundation and is covered by the workflow skills
  (`next-module`, `frontend-design`, `voice-agent-runtime`). Modules 1–5 each get their own skill via this rule."*
  Do not author `.claude/skills/accounts/SKILL.md` in this pass.
- [ ] README — update only if it tracks build-state/module status; skip otherwise (same conditional as 0.1).

## Later passes / deferred

Carried over from research-accounts-0.4.md, nothing lost:

- **Signed-cookie "remembered last location" pre-select on login** — additive, zero-schema, but not required by
  the four documented bullets (the switcher already forces a choice, which is all they ask for). Build only if a
  later pass explicitly wants the convenience.
- **Read-only "all locations" aggregate/reporting view for an owner** — genuinely useful (Toast Now / Square
  reporting precedent) but carries real cross-location-leak risk if built carelessly. Deferred until a
  reporting-focused module explicitly scopes it, and even then `request.location` itself must never become
  non-singular — every location-scoped write still requires one concrete, assigned `location` id.
- **Per-location live-call badge in the switcher** (Dialpad's Centralized Office Management precedent) — depends
  on `calls.CallSession` (Module 5, not yet built) and, if made truly live, a Channels push. The topbar's existing
  `live_call_count` variable is already a hook, scoped to the *active* location only. Deferred entirely.
- **Per-page "scoped to `<Location>`" success-message convention** (e.g. "Booking created at **Downtown**") — a
  documentation/convention note for future sub-modules' `messages.*` calls, not a page 0.4 builds itself.
- **Excluding `is_active=False` locations from the switcher's options** — `assigned_locations()` does not filter
  on `Location.is_active` today, and Location deactivation UI does not exist yet (that's 1.2). Not a regression
  introduced by 0.4; revisit once 1.2 ships deactivation.
- **Admin-forced/default location assignment per staff member** (Mindbody's permission-gated "may this user
  switch at all") — the current model already achieves the tightest version of this for free: a 1-assignment
  user never sees a switcher. A separate "can switch" boolean would duplicate what having 1 vs 2+ `UserLocation`
  rows already expresses; not recommended even later unless a concrete gap appears.

Parked for sibling sub-modules (not 0.4's scope, not lost):

- Creating/editing `UserLocation` rows (the assignment matrix, from either the user or the location side) → **1.3**
- The "warns before removing an assignment that would leave a user with no location" guard → **1.3**
- Provider marking (`is_provider` flag surfaced in the assignment UI) → **1.3**
- Location list/detail/create/edit pages themselves (`tenants.Location` CRUD, including deactivation) → **1.2**
- Own-profile editing, user list/detail/create/edit, tier & status management → **0.3**
- Change password / change email → **0.2**

## Review notes

(filled in at the end of the build/review pass)
