---
# Sub-module 0.1 — Authentication & Session (Module 0: Accounts & Access, `accounts`) — plan from research-accounts-0.1.md (2026-07-19)

## Shape: CRUD (foundation variant) — no list/CRUD pages shipped this pass

0.1 genuinely introduces the two ERD-anchor models for the `accounts` app — `accounts.User`
(`AUTH_USER_MODEL`) and `accounts.UserLocation` — which makes it a CRUD-shaped sub-module by the "does new
tenant-scoped data get introduced" test. **But it ships zero list/create/detail/edit/delete pages this pass.**
Per the orchestrating task's explicit scope cut, User list/create/edit belongs to **0.3** and the
`UserLocation` assignment matrix belongs to **1.3** — 0.1 ships only the authentication-flow surface (login,
logout, forgot/reset password) plus the dashboard landing page as its observable surface, exactly like a
service sub-module's "diagnostics/settings page" stand-in. The CRUD Completeness Rule's mandatory
list→edit→delete chain is **not triggered** because neither model gets a list page in this pass — that
absence is correct here, not a gap; do not add list/edit/delete views for `User`/`UserLocation` in this
pass, and do not let a reviewer talk you into adding them early.

## Models (from research — 2, within the 1–3 ceiling)

- [ ] **`accounts.User`** (`AUTH_USER_MODEL`) — tenant-scoped only (not location-scoped; superuser is the
  documented `tenant=None` exception, CLAUDE.md Multi-Tenancy rule 1). Does **not** inherit `TenantOwned`
  (that base's `tenant` FK is non-nullable) — declare `tenant` manually:
  `models.ForeignKey('tenants.Tenant', null=True, blank=True, on_delete=models.CASCADE, related_name='users')`.
  Still inherits `TimeStamped` for `created_at`/`updated_at`. Fields per ERD §3.1, each justified by a
  researched feature:
  - `email` (Email) — **Customer-Scoped Login**: the identifier matched within the resolved tenant.
  - `username` (Char(150), `null=True`, blank) — **Email-or-username interchangeable identifier**.
  - `first_name`, `last_name` (Char(128), blank), `full_name` (Char(255), blank, auto-derived from
    first/last in `save()` when blank) — carried now because they're on the ERD row being created; **editing**
    them is 0.3's Own Profile feature, out of scope here.
  - `primary_phone` (Char(32), blank) — ERD field, unused by 0.1's own flows; 0.3's profile edits it.
  - `tier` (Char(16): `owner` / `manager` / `staff`) — ERD field; 0.1 does not build tier-gated UI (that's
    0.3), but the field must exist now since this is `User`'s one migration-defining pass.
  - `status` (Char(16), indexed: `active` / `inactive` / `suspended`) — **Failed-Attempt Throttling** /
    **Inactive-tenant gate**: login is refused (via the same uniform message) when `status != 'active'`.
    `suspended` is settable manually via `admin.py` in this pass; automatic auto-suspend-after-N-failures
    escalation is **not** built now (not a REQUIRED research bullet — the cache-based window throttle alone
    satisfies the Failed-Attempt Throttling bullet).
  - `password` (Char(128), via `AbstractBaseUser`) — **Forgot & Reset Password** / **Customer-Scoped Login**:
    Django hasher-backed, `set_password`/`check_password`.
  - `last_login_at` (DateTime, null) — **Customer-Scoped Login** completion signal. **Gotcha, resolve
    explicitly:** `AbstractBaseUser` contributes its own `last_login` field; to keep the ERD's exact field
    name, override it away with `last_login = None` (Django's documented "exclude an abstract-base field"
    pattern) and declare `last_login_at` instead. This has two required follow-on fixes (see Backend section):
    (a) `AccountsConfig.ready()` must disconnect the default `user_logged_in → update_last_login` receiver
    (it writes to `user.last_login` via `update_fields=['last_login']`, which no longer exists, and would
    raise `FieldDoesNotExist` on every login) and connect a local receiver that sets `last_login_at` instead;
    (b) the password-reset token generator must not use Django's stock `PasswordResetTokenGenerator`
    unmodified (it reads `user.last_login` in `_make_hash_value` — see Backend section for the subclass fix).
  - `is_provider` (Bool, default False), `provider_hours` (JSON, default dict) — ERD fields, unused by 0.1's
    own flows; consumed starting 1.4/4.x. Carried now for the same "one migration-defining pass" reason.
  - `inactivity_timeout` (PositiveInt, minutes, null=True/blank — falls back to
    `settings.DEFAULT_INACTIVITY_TIMEOUT_MINUTES`) — **Inactivity timeout, per user**: drives
    `SessionPolicyMiddleware`.
  - **Auth-plumbing addition beyond the ERD's domain fields** (not a domain field, needed so
    `createsuperuser` and `/admin/` work at all): `is_staff` (Bool, default False). No stored `is_active`
    column — expose it as a **property** (`return self.status == 'active'`) so Django's auth machinery has
    the attribute it expects without a second source of truth alongside `status`.
  - **Unique constraints:** `(tenant, email)` — enforced at the DB level (MySQL treats each NULL `tenant`
    as distinct, so multiple `tenant=None` superusers with different emails is fine). `(tenant, username)`
    where `username` is not null — **MySQL/MariaDB gotcha:** Django's `UniqueConstraint(condition=Q(...))`
    (a partial/filtered index) is **not supported on MySQL** — the migration will silently skip creating that
    DB-level constraint (no error, just unenforced). Do not rely on it. Enforce this rule at the application
    layer instead: override `User.clean()` / `validate_unique()` to raise when a non-null `username` collides
    with another row in the same tenant, and call it from `LoginForm`/wherever a username is ever written
    (nothing writes it in 0.1 itself, but the model-level guard must exist now since this is the one pass that
    defines the model).
  - `USERNAME_FIELD = 'email'` (used only by `createsuperuser` prompts / `get_username()` — actual login goes
    through `CustomerScopedBackend`, not Django's default `ModelBackend` natural-key lookup).
    `REQUIRED_FIELDS = []` (tenant is nullable for the superuser and can't be meaningfully prompted anyway).
  - `objects = UserManager()` — custom manager (same file) with `create_user(tenant, email, password=None,
    **extra)` and `create_superuser(email, password=None, **extra)` that forces `tenant=None`,
    `is_staff=True`, `is_superuser=True`, `tier='owner'`, `status='active'`.
  - `initials` property (two-letter, from `full_name`/`first_name`+`last_name`) and `display_name` property
    (`full_name` or `email`) — consumed directly by `templates/partials/_topbar.html`
    (`{{ user.initials }}`, `{{ user.display_name }}` — already wired, currently unresolved).
  - `assigned_locations()` method — `Location.objects.filter(pk__in=self.user_locations.values_list(
    'location_id', flat=True))` — consumed directly by `apps/accounts/context_processors.py`
    (`user.assigned_locations()` — already wired, currently unresolved) and by `ActiveLocationMiddleware`.
  - FK: `tenants.Tenant` (**verified** — `apps/tenants/models/Tenant.py`).

- [ ] **`accounts.UserLocation`** — tenant-scoped (inherits `TenantOwned`, gives `tenant` FK +
  `created_at`/`updated_at`); its own `location` FK is the **assignment target**, not an additional
  query-scoping constraint on this table (per ERD's scope table, `UserLocation` is classified "tenant only" —
  reads of this table filter by `tenant` alone, since it IS the table that defines which locations a user may
  reach). Fields: `user` (FK `settings.AUTH_USER_MODEL`, `related_name='user_locations'`, `on_delete=CASCADE`
  — per ERD naming exactly), `location` (FK `tenants.Location`, `related_name='user_assignments'`,
  `on_delete=CASCADE`). `UniqueConstraint(fields=['user', 'location'], name='uniq_userlocation_user_location')`
  (this one IS a plain two-column unique, fully supported on MySQL — no partial-index gotcha). Justified by:
  it is the table `ActiveLocationMiddleware`'s revalidation reads on every request, and the table the
  `assigned_locations()` method and the already-built topbar location switcher (`user_locations` context var)
  depend on. **0.1 ships zero CRUD and zero UI for this model** — no assignment matrix (1.3), no interactive
  switcher POST endpoint (0.4, `accounts:switch_location` — already referenced defensively by
  `context_processors.py` and `_topbar.html`, resolving to `None`/hidden until 0.4 builds it; **0.1 must NOT
  create that url**). `seed_accounts` (this pass) still writes real rows into it — seeding data is not the
  same as shipping UI, and without seeded rows `ActiveLocationMiddleware` has nothing to validate against.
  FK: `tenants.Location` (**verified**), `settings.AUTH_USER_MODEL`.

No third model — matches the research's "no third model justified" conclusion.

## Backend (apps/accounts/{models,forms,views}/ + urls.py — FLAT, no sub-module level, per rule 9/10)

- [ ] `models/User.py` — `User(AbstractBaseUser)` + `UserManager(BaseUserManager)` in the same file, per the
  field spec above. `last_login = None` override; `initials`/`display_name` properties;
  `assigned_locations()`; `save()` auto-derives `full_name`; `clean()`/`validate_unique()` app-layer guard for
  the `(tenant, username)` partial uniqueness MySQL can't enforce at the DB level.
- [ ] `models/UserLocation.py` — per the field spec above.
- [ ] `models/__init__.py` — **add** `User`, `UserManager`, `UserLocation` to the existing re-export block
  (keep the current `TimeStamped`/`TenantOwned`/`TenantLocationOwned`/`TenantNumbered` re-exports intact).
- [ ] `forms/_common.py` — **new package**, the cross-app home for `TenantModelForm` / `TenantLocationModelForm`
  (base `ModelForm` classes every other app's forms will inherit — they auto-exclude `tenant`/`location` from
  `Meta.fields` and narrow FK querysets to `request.tenant`/`request.location`), plus `ALLOWED_AUDIO_EXTENSIONS`
  / `MAX_RECORDING_BYTES` constants, plus widget-attrs helpers applying `.form-input`/`.form-select`/
  `.form-textarea`. **Not used by 0.1's own plain `Form` subclasses** (login/reset forms have no tenant/location
  FK to scope) — built now because it is explicitly the cross-app foundation and must exist before any later
  module's forms can subclass it.
- [ ] `forms/Auth.py` — `LoginForm` (plain `Form`: `customer_id`, `identifier`, `password`),
  `PasswordResetRequestForm` (plain `Form`: `email`), `SetNewPasswordForm` (plain `Form`: `new_password1`,
  `new_password2`, validated via `django.contrib.auth.password_validation.validate_password(user=user)`
  against the already-configured `AUTH_PASSWORD_VALIDATORS`).
- [ ] `forms/__init__.py` — re-export block: `TenantModelForm`, `TenantLocationModelForm`,
  `ALLOWED_AUDIO_EXTENSIONS`, `MAX_RECORDING_BYTES`, `LoginForm`, `PasswordResetRequestForm`,
  `SetNewPasswordForm`.
- [ ] `views/_common.py` — small shared view toolkit (message-level → alert-class mapping already lives in
  `base.html`; put render/context helpers used by ≥2 entity view modules here if any emerge).
- [ ] `views/_helpers.py` — cross-entity private helpers: `get_client_ip(request)` (throttle key input),
  `set_active_location(request, location)` (session write, used by `ActiveLocationMiddleware`'s
  auto-select-on-first-load path and reserved for 0.4's switcher view to call).
- [ ] `views/Auth.py` — `login_view` (GET form; POST: resolve `Tenant` by `customer_id`, reject uniformly if
  missing/`is_active=False`, throttle check, `authenticate()` via `CustomerScopedBackend`, uniform failure
  message on any mismatch, `login(request, user)`, auto-select the sole `UserLocation` if exactly one exists
  else leave `request.location=None` for 0.4 to resolve, redirect to `accounts:dashboard`);
  `logout_view` (POST-only, `django.contrib.auth.logout(request)` — this flushes the whole session, which
  clears `active_location_id` with it, satisfying "Explicit logout, session + active-location clear" for
  free); `password_reset_request_view` (GET form; POST: look up `User` by `email` across **all** tenants
  case-insensitively, for each match email a reset link built from `urlsafe_base64_encode(force_bytes(user.pk))`
  + a token from the custom token generator below — `user.pk` is a global surrogate key, so even when two
  tenants share an email each gets a link tied to its own row, resolving "Tenant-disambiguated reset" without
  asking for `customer_id` again; always show the same generic "if that account exists…" message regardless
  of 0/1/N matches; throttled the same cache-based way as login); `password_reset_confirm_view` (GET+POST:
  decode `uidb64` → `get_object_or_404(User, pk=uid)`, verify with `TenantPasswordResetTokenGenerator`, on
  GET show `SetNewPasswordForm`, on valid POST `set_password()` + save + send the post-reset confirmation
  email (a small **local** helper inside this file — NOT a shared cross-module notification helper; 0.2 owns
  designing that shared abstraction for its own Credential Change Notice, coordinate then, don't build it
  early) + redirect to login with a success message; on invalid/expired token show a friendly re-request
  prompt, never a 500).
- [ ] `views/Dashboard.py` — `dashboard_view` (`@login_required`, minimal landing content: welcome, active
  tenant/location summary, prompt to use the sidebar) — exists purely so `LOGIN_REDIRECT_URL` has somewhere
  real to land; full dashboard widgets are out of scope for 0.1's four bullets.
- [ ] `views/__init__.py` — re-export block: `login_view`, `logout_view`, `password_reset_request_view`,
  `password_reset_confirm_view`, `dashboard_view`.
- [ ] `urls.py` — **FLAT module, not a package** (CLAUDE.md Backend Package Structure rule 10). `app_name =
  'accounts'`. Define the compact `crud(base, name)` route-factory helper here now (used by **0.3**'s User
  CRUD and later flat-app entities) even though 0.1 issues zero calls to it — it's explicitly scoped to this
  pass by the orchestrating task. Routes this pass: `''` → `dashboard_view` (name=`dashboard`), `'login/'` →
  `login_view` (name=`login`), `'logout/'` → `logout_view` (name=`logout`), `'password-reset/'` →
  `password_reset_request_view` (name=`password_reset_request`), `'password-reset/<uidb64>/<token>/'` →
  `password_reset_confirm_view` (name=`password_reset_confirm`). Literal routes only this pass — no `<int:pk>`
  yet, so no ordering conflict, but note for 0.3: any future `crud()`-generated `<int:pk>` routes must sit
  after these literals in the concatenated `urlpatterns`.
- [ ] `backends.py` — `CustomerScopedBackend(BaseBackend)`: `authenticate(self, request, customer_id=None,
  identifier=None, password=None, **kwargs)` — resolve `Tenant` by `customer_id`, reject (return `None`) if
  missing/inactive; look up `User` in that tenant by `email__iexact=identifier` OR `username__iexact=identifier`
  where `status == 'active'`; cache-based throttle check **before** the password check (`LOGIN_ATTEMPT_LIMIT`
  / `LOGIN_ATTEMPT_WINDOW_SECONDS`, keyed on **both** `(customer_id, identifier)` and the client IP from
  `get_client_ip(request)` — increment the counter on every failed attempt **even for a nonexistent
  tenant/user combo**, so the "too many attempts" degradation looks identical whether or not the account is
  real); `check_password()`; `get_user(self, user_id)`. Also: `TenantPasswordResetTokenGenerator
  (PasswordResetTokenGenerator)` overriding `_make_hash_value(self, user, timestamp)` to read
  `user.last_login_at` instead of the stock implementation's `user.last_login` (which no longer exists on this
  model — see the User model note above; using the unmodified generator would raise `AttributeError` on every
  password-reset link).
- [ ] `middleware.py` — `TenantMiddleware` (`request.tenant = request.user.tenant if
  request.user.is_authenticated else None`, sits after `AuthenticationMiddleware` per the existing settings.py
  ordering); `ActiveLocationMiddleware` (reads `request.session.get('active_location_id')`, **re-validates it
  against `UserLocation.objects.filter(user=request.user, tenant=request.tenant, location_id=id).exists()`
  on every request** — the cross-location IDOR boundary; auto-selects the sole assignment when exactly one
  `UserLocation` row exists and none is set; degrades to `request.location = None` when zero or an invalid id
  — downstream tenant-scoped views then correctly return empty results rather than leaking a location the
  user isn't assigned to; **0.1 builds this middleware's contract only — the interactive switcher view/page
  that lets a user with 2+ assignments actively choose is 0.4's `accounts:switch_location`, out of scope
  here**); `SessionPolicyMiddleware` (compares `request.session.get('last_activity')` against `now`, using
  `request.user.inactivity_timeout or settings.DEFAULT_INACTIVITY_TIMEOUT_MINUTES`; force `logout(request)` +
  redirect to login when exceeded; otherwise bumps `request.session['last_activity']` every request).
- [ ] `apps.py` — extend `AccountsConfig.ready()`: disconnect
  `django.contrib.auth.signals.user_logged_in` → `django.contrib.auth.models.update_last_login` (it targets
  the now-removed `last_login` field and would raise `FieldDoesNotExist`), connect a local receiver that sets
  `user.last_login_at = timezone.now()` and `user.save(update_fields=['last_login_at'])`.
- [ ] `admin.py` — **new file**. `@admin.register(User)`: `list_display = ('email', 'username', 'tenant',
  'tier', 'status', 'is_staff')`, `list_filter = ('tier', 'status', 'is_staff')`,
  `search_fields = ('email', 'username', 'full_name')`. **WARNING, flag explicitly in the code:** exclude
  `password` from the admin form (`exclude = ('password',)` or `readonly_fields`) — Django's default
  `ModelAdmin` renders an unmanaged `CharField` as a plain text box, and an admin typing a new value into it
  would overwrite the hash with **unhashed plaintext**, silently breaking that account's login. Not building a
  full `UserAdmin`-style change-password subform in this pass (deferred convenience) — the exclusion is the
  minimum-safe default. `@admin.register(UserLocation)`: `list_display = ('user', 'location', 'tenant')`,
  `list_select_related = ('user', 'location', 'tenant')`.
- [ ] `management/__init__.py`, `management/commands/__init__.py` — new, per Seed Command Rule 4.
- [ ] `management/commands/seed_accounts.py` — idempotent (`get_or_create` on `(tenant, email)`). Creates: one
  Django superuser `admin` (`tenant=None`, `is_staff=True`, `is_superuser=True`); per demo tenant seeded by
  `seed_tenants` (acme, globex) an owner-tier admin (`admin_acme`, `admin_globex`) plus one manager/staff demo
  user assigned to **each** of that tenant's two locations via `UserLocation` rows (Seed Command Rule 6 — at
  least two locations per tenant must have real assignment data, not just exist). All demo accounts share one
  fixed dev password. Prints, per Seed Command Rule 3: each tenant admin's login (`customer_id` +
  email/username + the password), which locations each account can switch into, and the
  `"Superuser 'admin' has no tenant — data won't appear when logged in as admin"` warning.

## Realtime & agent surface

N/A this sub-module — confirmed by research's "Compliance & provider constraints": 0.1 touches no
`calls.CallSession`, no LLM tool, no provider adapter, no Channels consumer. No tool declaration, no prompt
variable, no `AgentSetting.variables` entry, no `CallSession.usage` cost line.

## Wire-up

- [ ] `apps/accounts/navigation.py` — `LIVE_LINKS["0.1"] = {"Customer-Scoped Login": "accounts:dashboard"}`.
  Reasoning: none of 0.1's four bullets (Customer-Scoped Login, Logout & Session Expiry, Forgot & Reset
  Password, Failed-Attempt Throttling) is itself a page an already-authenticated user would click from the
  sidebar — login/logout/reset are pre-auth surfaces, and logout already has its own topbar control. The
  Dashboard is the one concrete, reachable, "0.1 is live" proof point (you only ever land there via a
  successful customer-scoped login), so it is the sidebar's representative link, labeled with the first bullet.
- [ ] `config/settings.py` — add `SESSION_COOKIE_AGE = env_int('SESSION_COOKIE_AGE', 60 * 60 * 12)` (12h
  absolute session ceiling — "Absolute session lifetime ceiling" bullet; Django's own default is 2 weeks,
  which is too loose for this product). Everything else in settings.py (`AUTH_USER_MODEL`,
  `AUTHENTICATION_BACKENDS`, middleware stack, `LOGIN_URL`/`LOGIN_REDIRECT_URL`, `LOGIN_ATTEMPT_*`,
  `PASSWORD_RESET_TIMEOUT`, `DEFAULT_INACTIVITY_TIMEOUT_MINUTES`) is **already declared** — no action.
  `config/urls.py` already includes `apps.accounts.urls` at the site root — no action. This is not a
  brand-new-app run for settings/urls/asgi purposes (only the backing code was missing).
- [ ] **First run of all:** `AUTH_USER_MODEL = 'accounts.User'` is **already** declared in
  `config/settings.py`, ahead of this pass's first `makemigrations` — confirmed satisfied, no edit needed, but
  called out here per the mandatory ordering rule since this genuinely is the first `makemigrations` run for
  the whole project.

## Templates (templates/accounts/ — FLAT, no sub-module level, per Template Folder Structure rule 4)

- [ ] `templates/accounts/auth/login.html` — **standalone, does NOT `{% extends "base.html" %}`** (the sidebar
  shell has nowhere to point an unauthenticated request) — own minimal `<!DOCTYPE html>` using the existing
  `.auth-page` / `.auth-card` / `.auth-brand` theme.css classes. Fields: Customer ID, Email or username,
  Password. Renders the uniform failure message from one non-field error, never per-field. Link to
  password-reset request.
- [ ] `templates/accounts/auth/password_reset_request.html` — standalone (same shell-less pattern). Single
  `email` field; on submit always shows the generic "if that account exists, a reset link was sent" message
  regardless of match count.
- [ ] `templates/accounts/auth/password_reset_confirm.html` — standalone (same shell-less pattern).
  `new_password1`/`new_password2`; an invalid/expired token renders a friendly inline message with a link back
  to request a new one — never a 500, never a Django default error page.
- [ ] `templates/accounts/dashboard.html` — extends `base.html` (this is the one page in this pass that uses
  the full app shell), standalone page at the app root (no entity folder, per rule 6 — it isn't an entity's
  list/detail/form).

No `form.html`/`list.html`/`detail.html` for `User`/`UserLocation` this pass — their absence is correct (0.3
and 1.3 respectively).

## Verify

- [ ] `makemigrations` — the actual **first** migration run for the whole project; expect at minimum
  `tenants/0001_initial` (Tenant + Location, not yet migrated) and `accounts/0001_initial` (User +
  UserLocation). Per ERD §6, a base+follow-up split is possible if the autodetector reports a circular
  `AUTH_USER_MODEL` dependency — it is **not** expected here (nothing in `tenants` FKs `AUTH_USER_MODEL` yet),
  but if Django produces one anyway, that split is correct, not a bug — do not "fix" it by moving a model or
  dropping an FK. Run `git status` after and commit each generated migration file as its own commit.
- [ ] `migrate`
- [ ] `seed_tenants` then `seed_accounts` ×2 each (idempotent both times — second run reports "already exists")
- [ ] `manage.py check`
- [ ] assert `PROVIDER_MODE=fake` (trivially true — 0.1 never imports a provider adapter, but confirm the env
  default is intact)
- [ ] `pytest -q apps/accounts` covering: `CustomerScopedBackend` (valid login; wrong `customer_id`; wrong
  identifier; wrong password; inactive tenant; `status != 'active'` user — **all six produce the identical
  uniform message**); cache throttle (N+1th attempt within the window is blocked for both the
  `(customer_id, identifier)` key and the IP key; a nonexistent account throttles identically to a real one;
  the counter resets after the window); `TenantMiddleware`/`ActiveLocationMiddleware` (valid `UserLocation`
  row → `request.location` set; a location id belonging to **another tenant or another user** written directly
  into the session is rejected, not silently trusted — the actual cross-location IDOR check for this
  sub-module, since there is no CRUD model to IDOR against yet); `SessionPolicyMiddleware` (idle past
  `inactivity_timeout` forces logout on the next request); password reset (non-enumerating response identical
  for a matching and a non-matching email; a valid token succeeds once; the same token replayed after success
  fails via `TenantPasswordResetTokenGenerator`; an expired token — mock `PASSWORD_RESET_TIMEOUT` — fails
  cleanly); `User` model (`full_name` auto-derivation; `initials`/`display_name`; `assigned_locations()`;
  the application-layer `(tenant, username)` uniqueness guard, since MySQL won't enforce it at the DB level).
- [ ] Twilio signature / idempotency — **N/A**, 0.1 has no webhook.
- [ ] websocket connect/reject — **N/A**, 0.1 has no Channels consumer.
- [ ] `temp/` smoke sweep as `admin_acme` (password printed by `seed_accounts`, per Seed Command Rule 3 — read
  the command's own output, don't assume a value): `accounts:login` GET→200 (shell-less page, no sidebar
  markup), POST valid credentials→302 to `accounts:dashboard`, POST invalid→200 with the uniform error and no
  `{#`/`{% comment` leaks; `accounts:logout` POST→302 to `accounts:login`, session cookie/`active_location_id`
  gone; `accounts:dashboard` anonymous→302 to login, authenticated→200 with a page title and the active
  tenant/location visible; `accounts:password_reset_request` GET/POST→200 generic message both for
  `admin_acme`'s real email and a made-up one; `accounts:password_reset_confirm` with a deliberately mangled
  token→200 friendly re-request prompt, never 500; **cross-tenant check**: log in as `admin_acme`, confirm
  `request.tenant` is Acme and never resolves to Globex from any header/param tampering;
  **cross-location check**: log in as the Acme downtown-only demo user, POST-tamper the session's
  `active_location_id` to Acme uptown's id (a real location in the SAME tenant the user is NOT assigned to) —
  `ActiveLocationMiddleware` must reject it on the very next request, not trust it.
- [ ] sidebar shows `0.1` Live (the "Customer-Scoped Login" → Dashboard row resolves and is clickable).

## Close-out

- [ ] review agents (code-reviewer → explorer → frontend-reviewer → performance-reviewer → realtime-reviewer
  → qa-smoke-tester → security-reviewer → test-writer) — realtime-reviewer should have nothing to flag (no
  realtime surface) but still runs per the mandatory sequence.
- [ ] **SKILL.md: NONE for this module.** CLAUDE.md's Per-Module Skill section explicitly carves Module 0 out:
  *"Module 0 (`accounts`) is the foundation and is covered by the workflow skills (`next-module`,
  `frontend-design`, `voice-agent-runtime`). Modules 1–5 each get their own skill via this rule."* Do not
  author `.claude/skills/accounts/SKILL.md` in this pass or any later `accounts` sub-module pass — this
  overrides the generic "create or update SKILL.md" close-out step for this module only.
- [ ] README — update the root `README.md` if it tracks build state/module status; skip if it carries no such
  section yet.

## Later passes / deferred

Carried over from research-accounts-0.1.md, nothing lost:

- SSO / SAML / OIDC enterprise sign-in — needs a twelfth table (per-tenant IdP connection config) + external
  IdP dependency; not required by the four documented 0.1 bullets.
- TOTP multi-factor authentication — would start as extra fields on `accounts.User`, but recovery codes push
  toward a twelfth table; deferred until a security-hardening pass is explicitly scoped.
- Force logout / active-session & device management — needs session-to-user tracking beyond the two fixed
  models; deferred.
- Login audit trail — needs a new table with no home in the eleven-model set; deferred.
- CAPTCHA after repeated failures — third-party dependency (reCAPTCHA/hCaptcha); not required for the
  throttling bullet as documented.
- "Remember me" persistent login — not in the four bullets; safe to defer without loss.
- Shared/production cache backend for throttle counters — `LocMemCache` is fine for dev/tests; production
  needs Redis (already provisioned for Channels) so counts are correct across ASGI workers. Deployment-config
  item, not a code gap in this pass.
- Change Password / Change Email / Credential Change Notice → **0.2**.
- Own-profile editing, User list/detail/create/edit, tier & status management, `is_provider` flag,
  deactivation-instead-of-deletion → **0.3**.
- Assigned-location list UI, the interactive active-location switcher view (`accounts:switch_location`),
  assignment validation UI, location context header → **0.4**.
- Staff↔Location assignment matrix (creating/editing `UserLocation` rows through UI) → **1.3**.
- Tenant activation toggle UI (0.1 only *reads* `Tenant.is_active` at login) → **1.1**.

## Review notes

**Status: 0.1 code complete and verified. Steps 4-11 of the Module Creation Sequence (the eight review
agents + test-writer) have NOT yet run.**

### Deviations from this plan, and why

1. **`last_login` kept, `last_login_at` dropped.** The plan called for removing the inherited field and
   adding `last_login_at`, which requires disconnecting Django's `update_last_login` receiver and
   subclassing `PasswordResetTokenGenerator`. That is three pieces of permanent framework-fighting for a
   cosmetic field name, and it would have to be re-justified at every Django upgrade. The inherited field
   is used; `NavAIReceptionist-ERD.md` was updated in the same change to record it.
2. **No application-layer guard for `(tenant, username)`.** The plan flagged that MySQL cannot enforce a
   partial `UniqueConstraint(condition=...)`. Correct — but the conclusion was wrong. A **plain**
   `UniqueConstraint(fields=['tenant', 'username'])` already means "unique where username is not null",
   because every SQL engine treats NULLs as distinct inside a unique index. The real requirement was
   normalising `username` to `None` rather than `''`, which happens in both `clean()` and `save()`.
3. **`TenantPasswordResetTokenGenerator` not written.** Unnecessary once `last_login` is kept —
   `default_token_generator` works as-is, and single-use falls out of it for free since the token hashes
   the current password.
4. **`AccountsConfig.ready()` signal work not needed.** Same root cause as 1.

### Bugs found during verification (all fixed)

1. **`SessionPolicyMiddleware` 500'd on every idle logout** — it calls `messages.info()` but sat *before*
   `MessageMiddleware`, so `request._messages` did not exist. `MessageMiddleware` now precedes the three
   app middlewares in `MIDDLEWARE`.
2. **Every migration load crashed.** A manager with `use_in_migrations = True` is serialised by import
   path, and the mandated `<Entity>.py` layout makes `apps.accounts.models.User` resolve to the
   re-exported **class**, not the module — `type object 'User' has no attribute 'UserManager'`. Managers
   in this project keep `use_in_migrations = False`. **This trap applies to all eleven models**; recorded
   in the ERD.
3. **The entire design system 404'd under Daphne.** `get_asgi_application()` carries no staticfiles
   handler — serving `/static/` in development is a `runserver` convenience, and this project forbids
   `runserver` outright. `theme.css` and `layout.js` both returned 404 and every page rendered as unstyled
   HTML, silently. `config/asgi.py` now wraps the HTTP application in `ASGIStaticFilesHandler` when
   `DEBUG`. **This was invisible to the Django test client** — only a real browser against Daphne caught
   it, which is an argument for running the live check on every module.
4. **The admin add-user page would have failed on Django 4.2** — `usable_password` in `add_fieldsets` is
   5.1-only, and the stock `UserCreationForm` assumes a `username` login field. An explicit
   `AdminUserCreationForm` now backs it.

### Environment decision

XAMPP ships **MariaDB 10.4.14**; Django 5.1+ requires 10.5+. On the user's instruction the project is
pinned to **Django 4.2 LTS**, which supports MariaDB 10.4 and runs Channels 4.x unchanged. `requirements.txt`
and every doc that named Django 5.1 were updated. Revisit when the database server is upgraded — 4.2 LTS is
supported until April 2026.

### Verification evidence

- `manage.py check` — no issues (1 silenced: `auth.W004`, silenced by name with the multi-tenant reason).
- `makemigrations --check` — no changes detected.
- `migrate` against MySQL — clean, all apps applied.
- `seed_tenants` + `seed_accounts` — seeded; a second run of each is a no-op ("Data already exists").
- `temp/smoke_0_1.py` — **60/60 checks pass**, covering: uniform login failure across all six causes with
  identical rendered error text; throttling (including a nonexistent account throttling identically to a
  real one); open-redirect refusal; POST-only logout; non-enumerating password reset with single-use and
  expired-token handling; idle-session logout; template comment leaks; **cross-tenant isolation**; and
  **cross-location isolation** — a Downtown-only user writing Uptown's id, another tenant's id, and a junk
  id into their own session are all rejected without a 500.
- Live Daphne run — login → dashboard renders real seeded MySQL data; zero template-tag leaks in the
  served HTML; all four sidebar sizes, dark mode, brand sidebar, horizontal/detached layouts, RTL,
  localStorage persistence and reset all confirmed working; 25 Lucide icons render.

---

## Module 2 — Agent Setup & Telephony (2.1-2.4) — built and verified

Research in `research-agents-2.{1,2,3,4}.md`, plans in `todo-2-2.{1,2,3,4}.md`
(produced by a parallel research→plan workflow). Mounted at `/agent/`. Skill at
`.claude/skills/agents/SKILL.md`.

**One new model — `agents.AgentSetting`, the 5th of the eleven.** Only 2.1 added
it; 2.2, 2.3 and 2.4 edit different field groups of the same row and added no
migration.

### The two constraints that carry the module

`inbound_phone_number` is unique **globally, across every tenant** — an inbound
webhook has no session and resolves tenant + location from the dialled number, so
two businesses owning one DID would be a cross-tenant leak. The column is
**nullable rather than blank-defaulted**, because NULLs are distinct in a unique
index and empty strings are not.

`twilio_auth_token` is encrypted at rest and **absent from `Meta.fields`**. A
`ModelForm` binds every field it names to its current value, so listing it would
render a live credential into the edit page's `value=` attribute.

### Measured findings

* A 32-character token encrypts to **~147 characters**, so the ERD's `Char(128)`
  cannot hold the ciphertext. Column is 512; the deviation is recorded.
* `ENCRYPTION_KEY` in `.env.example` was **not a valid Fernet key** — the first
  credential save would have raised. Replaced, with a generation command and a
  rotation warning.
* `deconstruct` must NOT hide `max_length`: stripping it left the column width
  unpinned, so a later default change would alter the schema with no migration.

### Adopted from research rather than planned by me

**The test call takes no destination field at all.** The number is read
server-side from the signed-in user's own profile. An endpoint that dials a
client-supplied number is a toll-fraud gadget, and validating the number is not
sufficient — "valid E.164" and "safe to dial" are different questions.

### Bug found while building

`{% verbatim %}` inside `{% comment %}` breaks the template: verbatim is handled
by the **lexer**, so it swallows the `{% endcomment %}` and the comment never
closes. Caught by the edit hook; recorded in the skill.

### Verification evidence

`temp/smoke_module2.py` — **101/101**, including: the plaintext token never
present in the database column (raw SQL check); ciphertext fitting the column;
the mask hiding the secret; duplicate inbound numbers refused across locations
AND across tenants; an unset number stored as NULL; tenant-authored template
syntax not executed; `resolve_transfer_number` never returning a caller-supplied
value; the fake backend importing no provider SDK; the live backend refusing to
initialise; blank-token submit leaving the stored token alone; a cross-tenant
number collision message that does not disclose the other business; every one of
8 pages checked for the token; and a structural assertion that **no agents route
accepts a pk**.

Regressions: Module 1 **115/115**, Module 0 **61/61** and **156/156**. Live
Daphne run: all 8 pages render, zero template-tag leaks, no token leak.

### Still outstanding across Modules 0, 1 AND 2

Steps 4-11 have not run for ANY sub-module: `code-reviewer`, `explorer`,
`frontend-reviewer`, `performance-reviewer`, `realtime-reviewer`,
`qa-smoke-tester`, `security-reviewer`, `test-writer`. **There is still no
committed pytest suite** — no app has a `tests/` directory, and all 433 checks
live in gitignored `temp/` scripts.

---

## Module 1 — Business & Locations (1.1-1.4) — built and verified

Plans in `todo-1.1-1.2.md` and `todo-1.3-1.4.md`; research in
`research-tenants-1.{1,2,3,4}.md`. Mounted at `/manage/`. Skill authored at
`.claude/skills/tenants/SKILL.md` (Modules 1-5 require one; Module 0 is exempt).

**All four sub-modules shipped ZERO new models and ZERO migrations** —
`makemigrations --check` reports "No changes detected". `Tenant`, `Location`,
`UserLocation` and `User.provider_hours` all pre-existed, so Module 1 is entirely
forms, views and templates over existing tables.

### Security fix carried in

`accounts.User.assigned_locations()` did not filter `Location.is_active`. Without
that filter, deactivating a site left it switchable for everyone already assigned
and `ActiveLocationMiddleware` kept honouring a stored id pointing at it — so
"Location Deactivation" would have been cosmetic. Found by the 1.2 research agent
reading the as-built code, fixed with the regression test alongside.

### Decisions worth knowing

1. **1.1 has no pk in any URL.** One Tenant per business and `request.tenant` IS
   it, so a pk would be an invitation to request someone else's. `customer_id`,
   `slug` and `is_active` render but are never editable: editing the first locks
   every user out at login, and the third blocks the next login for everyone with
   nobody left able to undo it.
2. **Delete is deactivation everywhere**, and `location_delete_view` additionally
   refuses to deactivate the last active site — a business with no active location
   has nowhere to take a booking.
3. **The matrix treats posted pairs as filters, not identifiers.** Every
   `"<user_pk>:<location_pk>"` has BOTH halves intersected with the tenant's own
   querysets before writing, so a forged pair naming another business matches
   nothing. Removals use an OR of exact pairs — two `__in` filters would form a
   cross product and delete assignments nobody touched.
4. **Cross-module reads are import-guarded.** `apps.agents` (Module 2) and
   `apps.scheduling` (Module 4) do not exist. `_agent_setting_for()` and
   `future_appointment_count()` both `try/except ImportError` and return
   `None`/`0`, so THE CALL SITES DO NOT CHANGE when those modules land.
5. **`services.py` is the only writer of the `provider_hours` JSON**, and
   `get_provider_intervals(user, location, weekday=None)` is the named contract
   Module 4's availability search imports. "No configured hours" resolves to
   UNAVAILABLE, never "available all day".

### Verification evidence

`temp/smoke_module1.py` — **115/115**, covering: the tier gate across every
management view; spoofed `customer_id`/`slug`/`is_active` on the business form
having no effect; 9 junk filter and pagination values; slug auto-derivation and
per-tenant uniqueness; an invalid IANA timezone refused; cross-tenant IDOR to 404
on location detail/edit/delete, the provider toggle and both hours ids; a
deactivated location leaving `assigned_locations()` and the switcher; the
last-active-location guard; forged cross-tenant pairs in the matrix ignored; 5
junk pair payloads; the last-location warn-then-confirm round trip; interval
overlap, end-before-start and unassigned-location validation; malformed stored
JSON degrading rather than raising; and every `badge-*` checked against
`theme.css`.

Module 0 re-run after the `assigned_locations()` change: **61/61** and
**156/156**, so nothing regressed. Live Daphne run: all six `/manage/` pages
render with zero template-tag leaks, and a location was created end to end.

### Still outstanding across Modules 0 AND 1

Steps 4-11 have not run for ANY sub-module: `code-reviewer`, `explorer`,
`frontend-reviewer`, `performance-reviewer`, `realtime-reviewer`,
`qa-smoke-tester`, `security-reviewer`, `test-writer`. **There is still no
committed pytest suite** — `apps/accounts/` and `apps/tenants/` have no `tests/`,
and every `temp/smoke_*.py` is a gitignored throwaway.

---

## Sub-modules 0.2, 0.3 and 0.4 — built and verified

Plans live in `todo-0.2.md`, `todo-0.3.md`, `todo-0.4.md` (written to separate files so the three `todo`
agents could run in parallel without racing on this one). Research in `research-accounts-0.{2,3,4}.md`.

**All three ship ZERO new models and ZERO migrations** — `makemigrations --check` reports "No changes
detected", which is the empirical proof rather than an assertion. They are surfaces over the `User` and
`UserLocation` tables 0.1 created.

### What was built

* **0.2** — `ChangePasswordForm` / `ChangeEmailRequestForm`; `change_password_view`,
  `change_email_request_view`, `email_change_confirm_view`. The pending email change lives entirely in a
  `django.core.signing` token that embeds the CURRENT address, which is what makes it single-use with no
  server-side state to expire. `update_session_auth_hash` keeps the acting session alive while
  invalidating every other one. `_send_password_changed_email` was generalised into
  `send_credential_change_notice` in `views/_helpers.py` — one wording, two call sites, no drift.
* **0.3** — the user directory (`crud('users', 'user')` finally exercising the factory built in 0.1),
  plus the own-profile page. `tier_required('owner', 'manager')` is new. Delete is deactivation:
  `scheduling.Appointment.provider` will point at these rows, so removing one would either cascade away
  appointment history or orphan it.
* **0.4** — `switch_location_view`, the topbar guard change, and a global choose-a-location banner.

### Decisions worth knowing

1. **Two forms over one table is the privilege boundary.** `OwnProfileForm` omits `tier`, `status`,
   `is_provider` and `email`. A `ModelForm` only binds what `Meta.fields` names, so a POST body carrying
   `tier=owner` against the profile endpoint is inert — verified, not assumed.
2. **The switcher treats the posted id as a FILTER, never an identifier.**
   `request.user.assigned_locations().filter(pk=...)` — so another tenant's location, a same-tenant
   location the user has no `UserLocation` row for, and a junk string all fail identically. `.isdigit()`
   is checked first, because feeding a non-numeric string to a pk filter raises `ValueError` and would
   turn a junk POST into a 500.
3. **The email-change tripwire goes to the OLD address.** Sending only to the new one tells the attacker
   and nobody else, which is the entire failure the notice exists to prevent.
4. **New users are invited, never given a password.** `set_unusable_password()` plus the existing
   `accounts:password_reset_confirm` route — no second token scheme, no new url, and no password ever
   relayed out of band.
5. **The topbar guard was the actual 0.4 bug.** It was gated on `active_location`, so a user with two
   assignments and none active — precisely who needs the switcher — could not see it.

### Verification evidence

`temp/smoke_0_234.py` — **117/117 checks pass**, covering: wrong/mismatched/reused/weak passwords;
session survival across a password change; the same address being legal in a *different* business
(`(tenant, email)` is the unique pair, not `email`); the confirm link being unusable anonymously, by
another user's session, and on replay; the tier gate across all five management views; 13 junk filter
and pagination values; cross-tenant IDOR to 404 on detail/edit/delete; privilege escalation via a
spoofed profile POST; deactivation leaving the row intact with self and last-owner guards; the switcher
refusing unassigned, cross-tenant and junk ids; an off-site `next=`; template-tag leaks on eight pages;
and every `badge-*` modifier checked against the real `theme.css` inventory.

`temp/smoke_0_1.py` re-run: **60/60**, so refactoring `_safe_next` and the notice helper out of
`Auth.py` broke nothing. Live Daphne run confirms all five new pages render and the switcher moves the
active location and refuses a bogus id.

### Still outstanding for ALL of Module 0

Steps 4-11 of the Module Creation Sequence have **not** run for any sub-module: `code-reviewer`,
`explorer`, `frontend-reviewer`, `performance-reviewer`, `realtime-reviewer`, `qa-smoke-tester`,
`security-reviewer`, `test-writer`. In particular there is still **no pytest suite** — `apps/accounts/`
has no `tests/`, and the two `temp/smoke_*.py` files are gitignored throwaways, not the deliverable.
Step 12 stays a deliberate no-op: CLAUDE.md carves Module 0 out of the Per-Module Skill rule.

---

### Remaining for 0.1

Steps 4-11: `code-reviewer` -> `explorer` -> `frontend-reviewer` -> `performance-reviewer` ->
`realtime-reviewer` (expected to find nothing; 0.1 has no realtime surface) -> `qa-smoke-tester` ->
`security-reviewer` -> `test-writer` (the pytest suite under `apps/accounts/tests/` — `temp/smoke_0_1.py`
is a throwaway and is gitignored, so it is NOT the deliverable test suite). Step 12 is a deliberate no-op:
CLAUDE.md carves Module 0 out of the Per-Module Skill rule.

---

# Sub-module 4.1 — Contact Directory (Module 4: Calendar & Bookings, `scheduling`) — plan from research-scheduling-4.1.md (2026-07-19)

## Shape: CRUD (brand-new app — full CRUD ships this pass, no reduction)

`apps/scheduling/` does not exist yet (confirmed by directory glob and by the research agent's own repo-state
check) — this is Module 4's first sub-module and a brand-new-app run: the full app skeleton, `INSTALLED_APPS`
and root URL wiring are in scope alongside the one model. The sub-module genuinely introduces the tenant's
contact identity table, so it is CRUD-shaped by the "does new tenant-scoped data get introduced" test — it is
not a view sub-module, because `scheduling.Contact` does not exist anywhere yet for a view sub-module to merely
read.

## Models (from research — 1, within the 1–3 ceiling)

- [ ] **`scheduling.Contact`** — tenant-scoped **only**, deliberately **NOT** location-scoped (Business-Wide
  Identity bullet, `NavAIReceptionist.md` §4.1, confirmed against Square's Customer Directory / Mindbody's
  cross-location "All Contacts" smart list in research). **Do not add a `location` FK, not even an optional
  "primary location" convenience field — flag any reviewer suggestion to add one.** A caller belongs to the
  business and may book at any of its sites; per-visit location lives on `Appointment.location` (4.3), not here.
  Inherits `TenantOwned` (not `TenantLocationOwned`), mirroring `tenants.Location(TenantOwned)` — the one other
  model in the project that is tenant-only.
  - `tenant` — FK `tenants.Tenant` (verified: `apps/tenants/models/Tenant.py`), inherited from `TenantOwned`.
  - `first_name`, `last_name` — `CharField(max_length=128, blank=True)` — **Blank-Tolerant Identity** / Core
    intake fields: an unknown or withheld-caller-ID contact has neither.
  - `phone_e164` — `CharField(max_length=16, db_index=True, blank=True)`, **not unique** — **Phone-Keyed
    Contacts / ANI auto-match-or-create** and **Shared-line Disambiguation** (a household or shared office line
    legitimately maps to more than one contact — a `UniqueConstraint` here would break that case on purpose
    left open). Normalized in `clean()`/`save()` mirroring `AgentSetting.inbound_phone_number`'s pattern
    (`apps/agents/models/AgentConfiguration/AgentSettings.py`): strip whitespace on both; the form's
    `clean_phone_e164()` additionally rejects a non-blank value that doesn't match `^\+[1-9]\d{6,14}$`, so a
    malformed number becomes a field error the user can fix, not silently-uncalled-back data.
  - `email` — `EmailField(blank=True)` — Core intake fields.
  - `date_of_birth` — `DateField(null=True, blank=True)` — Core intake fields.
  - `notes` — `TextField(blank=True)` — Core intake fields; also carries the "common, not required" DNC/consent
    note per the research's Compliance section — no dedicated boolean field this pass.
  - `source` — `CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)` — **Filter by Source
    Channel**. Declare as class constants exactly like `AgentSetting.VOICE_PROVIDER_CHOICES`:
    `SOURCE_AI_PHONE = 'ai_phone'`, `SOURCE_MANUAL = 'manual'`, `SOURCE_WEB = 'web'`,
    `SOURCE_CHOICES = [(SOURCE_AI_PHONE, 'AI Phone'), (SOURCE_MANUAL, 'Manual'), (SOURCE_WEB, 'Web')]`.
    **Excluded from `ContactForm.Meta.fields`** — system-stamped, never user-chosen: a staff-created row gets
    the model's own `default='manual'` for free, because a `ModelForm` never touches a field absent from
    `Meta.fields`, on create OR edit. `'ai_phone'` is reserved for the future Module 3.3 `create_contact` tool
    and `'web'` for a future web widget — neither built yet. Never render a `source` `<select>` — a staff user
    hand-labelling their own entry as `ai_phone` would corrupt the Filter-by-Source feature's meaning.
  - `created_at`, `updated_at` — inherited from `TenantOwned`/`TimeStamped` — **Recently-Active / Last-Touch
    Sort** (buildable now on these two; a call/appointment-aware sort is deferred, see below).
  - `Meta.indexes`: `(tenant, phone_e164)` and `(tenant, last_name, first_name)`, exactly per
    `NavAIReceptionist-ERD.md` §3 `scheduling.Contact`. `Meta.ordering = ['last_name', 'first_name']`.
  - Form excludes: `tenant` (stamped by `TenantModelForm.save()`), `source` (system-stamped, see above),
    `created_at`/`updated_at` (auto). No `location` field exists to exclude — the callout above is the point.

No second model this pass. A tags table, a dedicated `do_not_contact` boolean/table and a merge-audit table
were all considered by the research and rejected; Invariant 1 forbids a second identity table outright
regardless of the researched features.

## Backend (apps/scheduling/{models,forms,views,urls}/ContactDirectory/ — brand-new app, full skeleton)

App skeleton (none of this exists yet):
- [ ] `apps/scheduling/__init__.py`
- [ ] `apps/scheduling/apps.py` — `SchedulingConfig(AppConfig)`, `default_auto_field =
  'django.db.models.BigAutoField'`, `name='apps.scheduling'`, `label='scheduling'`,
  `verbose_name='Calendar & Bookings'` (mirrors `apps/tenants/apps.py` / `apps/agents/apps.py`)
- [ ] `apps/scheduling/migrations/__init__.py`

Models:
- [ ] `apps/scheduling/models/_base.py` — re-exports `apps.accounts.models._base` (`TenantOwned`,
  `TenantLocationOwned`, `TimeStamped`, etc. via `import *`), mirroring `apps/tenants/models/_base.py` /
  `apps/agents/models/_base.py`
- [ ] `apps/scheduling/models/ContactDirectory/__init__.py`
- [ ] `apps/scheduling/models/ContactDirectory/Contacts.py` — the `Contact` model above, `SOURCE_*` constants
- [ ] `apps/scheduling/models/__init__.py` — `from apps.scheduling.models.ContactDirectory.Contacts import
  Contact` + `__all__ = ['Contact']` (the re-export block — its absence is an `ImportError` at runtime)

Forms:
- [ ] `apps/scheduling/forms/_common.py` — re-exports `apps.accounts.forms._common`
  (`TenantModelForm`/`TenantLocationModelForm`/`style_widgets`), mirroring `apps/tenants/forms/_common.py`
- [ ] `apps/scheduling/forms/ContactDirectory/__init__.py`
- [ ] `apps/scheduling/forms/ContactDirectory/Contacts.py` — `ContactForm(TenantModelForm)` with
  `Meta.fields = ('first_name', 'last_name', 'phone_e164', 'email', 'date_of_birth', 'notes')` and
  `clean_phone_e164()`; `ContactImportForm(forms.Form)` with one `csv_file = forms.FileField()`
- [ ] `apps/scheduling/forms/__init__.py` — re-export `ContactForm`, `ContactImportForm`

Views:
- [ ] `apps/scheduling/views/_common.py` — re-exports `apps.accounts.views._common` (`paginate`, decorators,
  shortcuts) + `tier_required`/`safe_redirect_target` from `apps.accounts.views._helpers` + a local
  `MANAGEMENT_TIERS = ('owner', 'manager')`, mirroring `apps/tenants/views/_common.py` exactly
- [ ] `apps/scheduling/views/ContactDirectory/__init__.py`
- [ ] `contact_list_view` — `@login_required` only (routine front-desk work, no tier gate); search `q` across
  `first_name`/`last_name`/`phone_e164`/`email` via `Q()`; `source` filter against `Contact.SOURCE_CHOICES`
  (a junk value degrades to no filter, never raises); `?sort=recent` toggles `-updated_at` vs. the default name
  ordering; `paginate()`; passes `source_choices` to the template context (Filter Implementation Rule 1)
- [ ] `contact_create_view` — `@login_required`; `ContactForm`; the new row gets `source='manual'` for free
  from the model default (see Models section — no explicit view code needed for this)
- [ ] `contact_detail_view` — `@login_required`; the appointment-history panel is **import-guarded**:
  `try: from apps.scheduling.models import Appointment` / `except ImportError: appointments = None` (the exact
  pattern `apps/tenants/views/Location.py`'s `_agent_setting_for()` already uses for a not-yet-built sibling),
  so the panel renders an empty state today and starts showing real rows the moment 4.3 lands with **zero code
  change at this call site**; also renders the "can book at any of the business's locations" copy (pure UI, no
  query)
- [ ] `contact_edit_view` — `@login_required`; same `ContactForm`; `source` is left untouched because it is
  absent from `Meta.fields`
- [ ] `contact_delete_view` — `@login_required` + `tier_required(*MANAGEMENT_TIERS)`, `@require_POST`; tries
  `obj.delete()`; catches `django.db.models.ProtectedError` and redirects to the detail page with a message
  pointing at "Forget This Contact" instead — **inert today** (no FK anywhere points at `Contact` yet) but
  written now per the research's explicit GDPR finding, so 4.3's `Appointment.contact`
  (`on_delete=PROTECT`) needs no retrofit here
- [ ] `contact_forget_view` — `@login_required` + `tier_required(*MANAGEMENT_TIERS)`, `@require_POST` — the
  **REQUIRED GDPR/CCPA erasure path**: blanks `first_name`, `email`, `phone_e164`, `date_of_birth`, `notes`,
  sets `last_name='(Erased)'`; keeps the row (and any future FKs into it) intact; logs the erasure server-side
  (never into `Contact.notes`, which was just cleared); no new field — `source` is left as-is (it is not PII)
- [ ] `contact_import_view` — `@login_required` + `tier_required(*MANAGEMENT_TIERS)` (bulk mutation is a
  privileged write); GET renders `ContactImportForm` with column instructions; POST parses `csv.DictReader`
  over `first_name,last_name,phone_e164,email,date_of_birth,notes`, caps at **500 rows** per upload (Acuity's
  cited batch size — a DoS/perf guard on one request), dedupes on `(tenant, phone_e164)` via `get_or_create`
  when `phone_e164` is present, reports created/skipped-duplicate/error counts back on the same template
- [ ] `contact_export_view` — `@login_required`; streams a `text/csv` response of the tenant's contacts,
  **re-applying the same `q`/`source` GET params as the list view** so "export what you're viewing" works; no
  template
- [ ] `apps/scheduling/views/__init__.py` — re-export all eight views above (the re-export block)

URLs (package form, matching the `calls`/`CallLogRecording` worked example in CLAUDE.md's Backend Package
Structure rule 1 — `scheduling` is headed for five entities across 4.1–4.5, so the package shape is adopted
from this first sub-module rather than retrofitted later, unlike `agents`' one-model flat `urls.py`):
- [ ] `apps/scheduling/urls/__init__.py` — `app_name = 'scheduling'`; concatenates
  `ContactDirectory.Contacts.urlpatterns`
- [ ] `apps/scheduling/urls/ContactDirectory/__init__.py`
- [ ] `apps/scheduling/urls/ContactDirectory/Contacts.py` — literal routes before the `<int:pk>` ones:
  `contacts/` → `contact_list`, `contacts/create/` → `contact_create`, `contacts/import/` → `contact_import`,
  `contacts/export/` → `contact_export`, `contacts/<int:pk>/` → `contact_detail`,
  `contacts/<int:pk>/edit/` → `contact_edit`, `contacts/<int:pk>/delete/` → `contact_delete`,
  `contacts/<int:pk>/forget/` → `contact_forget`

- [ ] `apps/scheduling/admin.py` — `ContactAdmin`: `list_display=('__str__', 'tenant', 'phone_e164', 'email',
  'source', 'created_at')`, `list_filter=('source', 'tenant')`,
  `search_fields=('first_name', 'last_name', 'phone_e164', 'email')`, `list_select_related=('tenant',)` — **no
  location filter**, correctly, since the model carries no `location` FK
- [ ] `makemigrations scheduling` → `0001_initial.py` (this sub-module actually creates a table — expect a real
  migration, not "No changes detected")
- [ ] `apps/scheduling/management/__init__.py`
- [ ] `apps/scheduling/management/commands/__init__.py`
- [ ] `apps/scheduling/management/commands/seed_scheduling.py` — idempotent; calls `seed_tenants` first when
  `Tenant.objects.filter(slug__in=('acme', 'globex')).exists()` is False (mirrors `seed_accounts`'s own
  dependency check); seeds ~8–10 `Contact` rows per tenant against the two demo tenants
  `apps/tenants/management/commands/seed_tenants.py` creates (`acme`, `globex`), with a mix of `source` values,
  at least one blank-name/withheld-caller-ID row per tenant to exercise Blank-Tolerant Identity, and at least
  one duplicate phone number within a tenant to exercise Shared-line Disambiguation; dedupes via
  `get_or_create(tenant=..., phone_e164=...)`; touches no provider; prints the demo tenant admin accounts
  (`admin_acme` / `admin_globex`, from `apps/accounts/management/commands/seed_accounts.py`) and reminds to
  browse Contacts under each

## Realtime & agent surface

No consumer, no `routing.py` entry and no live surface this pass — `scheduling` has no websocket route and
`config/asgi.py` is untouched. **No LLM tool is implemented in this sub-module.** `identify_contact` and
`create_contact` belong to sub-module **3.3 Tools & Dispatcher**, which does not exist yet (`apps/runtime/` was
confirmed absent by the research agent's repo-state check). What 4.1 ships for 3.3 to call later is the
**lookup shape**, documented here so the interface doesn't drift when 3.3 is planned:
`Contact.objects.filter(tenant=tenant, phone_e164=e164)` — 0 rows means "create", 1 row means "match", >1 row
means "candidates" (Shared-line Disambiguation, `data.candidates: [...]`). When 3.3 is built, its
`identify_contact()` tool takes **zero model-supplied args** (the ANI comes from server-held session state,
Invariant 3) and its `create_contact(first_name?, last_name?, phone?, email?, date_of_birth?, notes?)` tool
takes `tenant_id` from server state, never a model argument. Neither tool is implemented here; this section
exists so 3.3's `todo` plan has a verified contract to build against instead of re-deriving it.

## Prompt / variables

None. This sub-module adds no `agents.AgentSetting.variables` entry — a resolved contact's name reaching the
prompt as a `{{caller_name}}`-style variable is a Module 3 integration concern, out of scope here.

## Provider adapter

None. This sub-module makes no Twilio/STT/TTS/LLM call and adds nothing to `apps/runtime/providers/` — the
research's own Compliance section confirms "Provider/rate-limit implications: none directly."

## CallSession.usage cost lines

None. `calls.CallSession` does not exist yet (Module 5), and this sub-module precedes the runtime module
entirely — it appends nothing to any per-turn usage ledger.

## Wire-up

- [ ] `apps/accounts/navigation.py` — add **one** new entry to `LIVE_LINKS`:
  `'4.1': {'Contacts': 'scheduling:contact_list'}` (Module 4's icon, `calendar-days`, already exists in
  `MODULE_ICONS` — no change needed there)
- [ ] `config/settings.py` — `INSTALLED_APPS`: add `'apps.scheduling',` under a new
  `# Module 4 — Calendar & Bookings` comment, after `'apps.agents'` (brand-new-app wiring)
- [ ] `config/urls.py` — add `path('scheduling/', include('apps.scheduling.urls'))`, before the
  `apps.accounts.urls` catch-all include (which must stay last — it owns the site root)
- [ ] `config/asgi.py` — **untouched**, no websocket surface this pass
- [ ] `AUTH_USER_MODEL` — **N/A this pass**, already declared before Module 0's first `makemigrations`;
  nothing to do here

## Templates (templates/scheduling/directory/contact/)

Sub-module slug `directory` per CLAUDE.md's own worked example for `apps/scheduling`
(`calendar/ bookings/ directory/ catalog/ callbacks/`); `contact/` is the entity folder underneath it.

- [ ] `templates/scheduling/directory/contact/list.html` — filter bar reflecting `request.GET` (`q`, `source`
  dropdown from `source_choices`, `sort`), Actions column (view / edit / delete-POST+confirm+csrf, gated on
  `MANAGEMENT_TIERS` in the template same as the view), pagination with `has_previous`/`has_next` guards,
  empty-state ("No contacts yet — add one or import a CSV."), an Import button and an Export button
- [ ] `templates/scheduling/directory/contact/detail.html` — contact info panel; appointment-history panel
  rendering the empty state when `appointments is None`; the "can book at any of the business's locations"
  copy; Actions sidebar (Edit, Delete-POST+confirm, Forget-This-Contact-POST+confirm, Back to List) — Delete
  and Forget both hidden from non-management tiers in the template, matching the view gate
- [ ] `templates/scheduling/directory/contact/form.html` — shared create/edit template; fields
  `first_name`/`last_name`/`phone_e164`/`email`/`date_of_birth`/`notes` only — **no `source` field rendered**
- [ ] `templates/scheduling/directory/contact/import.html` — CSV upload form, expected-column instructions,
  the 500-row cap noted, and a results panel (created / skipped-duplicate / error rows) rendered after POST

## Verify

- [ ] `makemigrations scheduling` + `migrate` — expect one new migration (`0001_initial`), not "No changes
  detected" (this is the sub-module that actually creates a table)
- [ ] `seed_scheduling` ×2 — second run reports "Data already exists" (idempotent)
- [ ] `manage.py check` — no new issues
- [ ] `PROVIDER_MODE=fake` — asserted even though this sub-module makes no provider call, so the invariant is
  checked starting with the first sub-module of every module, not only the ones that need it
- [ ] `pytest` — model tests (`clean()`/normalization, both indexes exist, blank-name save succeeds, no
  `location` column exists on the table), view tests (list search/filter/sort/pagination,
  create/edit/detail/delete/forget, import dedup + 500-row cap, export CSV shape), all under
  `apps/scheduling/tests/` (arrives formally at step 11, `test-writer`)
- [ ] Twilio webhook signature + idempotency — **N/A**, this sub-module ships no webhook
- [ ] websocket connect/reject — **N/A**, this sub-module ships no consumer
- [ ] `temp/` smoke sweep as `admin_acme` (password from
  `apps/accounts/management/commands/seed_accounts.py` — `navai-demo-2026`) covering every new `scheduling:*`
  url: 200/302, no `{#`/`{% comment` leaks, page titles, a seeded record visible; **cross-tenant IDOR** —
  `admin_acme` requesting a `globex` contact's detail/edit/delete/forget by pk gets 404; **the deliberate
  absence of location scoping proven, not assumed** — switching `admin_acme`'s active location between
  Downtown and Uptown leaves the contact list **unchanged**, demonstrating `Contact` is correctly tenant-only
  rather than accidentally showing everything because a `location` filter was forgotten
- [ ] Sidebar shows `4.1` Live under Module 4, "Contacts" link resolves

## Close-out

- [ ] Review agents: `code-reviewer` → `explorer` → `frontend-reviewer` → `performance-reviewer` →
  `realtime-reviewer` (expected to find nothing — no realtime surface this pass) → `qa-smoke-tester` →
  `security-reviewer` (PII handling on `notes`/`date_of_birth`/`phone_e164`, the forget-flow, CSV upload
  validation) → `test-writer`
- [ ] Create `.claude/skills/scheduling/SKILL.md` — **author**, not update (brand-new app): models, routes,
  templates, seeder rows, the forward `identify_contact`/`create_contact` contract, and the explicit "no
  `location` FK on `Contact`" gotcha so a future sub-module's agent doesn't reintroduce it
- [ ] README — note the new `/scheduling/` mount if the project README enumerates mounted apps

## Later passes / deferred

- Tag/category system on `Contact` — not in the ERD's 8-field baseline; park until a real requirement surfaces.
- "Last call" / "last appointment" aware sort — needs `calls.CallSession` and `scheduling.Appointment`, neither
  built yet (Module 5, sub-module 4.3).
- Full contact merge with FK re-pointing — no strong requirement in the documented `NavAIReceptionist.md`
  bullets, and no FK exists yet to re-point; do not build a scaffold prematurely — revisit once 4.3/Module 5
  exist.
- CSV import duplicate-detection nuance beyond exact `(tenant, phone_e164)` match (Acuity-style fuzzy "merge on
  match") — the basic exact-dedupe import ships this pass; refine only once manual merge exists.
- Appointment-history query wiring on the detail page (ships now as an empty-state-guarded panel) → 4.3
  Availability & Booking / 4.4 Calendar Views.
- Callback-request linkage and any structured do-not-contact flag → 4.5 Bookings List & Callback Requests.
- Call history / transcript link from a contact → 5.1 Call Log List, 5.2 Call Detail & Transcript.
- `identify_contact` / `create_contact` tool implementation, argument-schema enforcement, and the tool
  dispatcher itself → 3.3 Tools & Dispatcher (contract documented above under Realtime & agent surface).
- Push contact/call data to an external CRM, outbound marketing/bulk SMS, spam/robocall screening, loyalty
  programs / stored payment methods on a contact — all out of scope for the product's seven capabilities, not
  merely deferred.

## Review notes

### Built

`scheduling` scaffolded as a brand-new app (four packages + `services.py` + `admin.py` + the management tree),
mounted at `/schedule/`, registered in `INSTALLED_APPS`, and lit up in the sidebar via `LIVE_LINKS['4.1']`.
One model — `scheduling.Contact`, tenant-scoped and deliberately not location-scoped. Six views: list (search +
source filter + pagination), create, detail, edit, delete, forget. 25 files, one commit each.

Verified by `temp/verify_4_1.py`: **70/70 checks green** — every page 200/302 as an Acme admin, no template
comment leaks, filters and search working (including national-format phone search matching a stored E.164 row),
junk `?source=`/`?page=` degrading rather than raising, cross-tenant IDOR to 404 on detail/edit/delete/forget,
delete POST-only (405 on GET), seeder idempotent across three consecutive runs, and
`makemigrations --check` clean.

### Deviations from this plan, and why

1. **CSV import/export not built** (planned at lines 727–734 and 814–825). The four documented feature bullets
   for 4.1 in `NavAIReceptionist.md` are phone-keyed contacts, list & search, create/edit/detail, and
   business-wide identity — import/export is none of them, and the research doc rates it `common`, not
   required. Deferred deliberately under "Simplicity First" to keep the fourteen-sub-module run tractable.
   It is a clean later addition: one view, one form, one `directory/contact/import.html`, and two buttons on
   the list page. **`code-reviewer` flagged this as an undocumented deviation — this note is the fix.**

2. **`contact_forget_view` was initially skipped and then built after review.** This was a genuine miss, not a
   judgement call: the research doc marks the GDPR/CCPA erasure path REQUIRED, and `code-reviewer` correctly
   caught that once 4.3 adds `Appointment.contact` with `on_delete=PROTECT`, a contact with any booking
   history becomes permanently unerasable — "delete my data" would be unanswerable for exactly the people who
   have used the business most. Now shipped as anonymize-in-place.

### Decisions worth carrying forward

* **`Contact.anonymized_at` is not in the ERD.** Added anyway — the ERD is intent and the code is truth, and
  erasure had no other durable marker; without one an erased contact is indistinguishable from a caller who
  simply never gave a name. Erasure blanks name/phone/email/DOB/notes and keeps the row and its pk.
* **`phone_e164` is indexed only through the composite `(tenant, phone_e164)`.** The single-column
  `db_index=True` was dropped on `performance-reviewer` routing from `code-reviewer`: every query in this app
  is tenant-scoped by Invariant, so the composite's leading column already covers it, and the bare index was
  a second index write serving no query.
* **`phone_e164` is deliberately NOT unique.** A household, a switchboard or a shared mobile legitimately maps
  to several people; a unique constraint would make the second one unsaveable. The duplicate path warns
  instead of blocking, and the detail page shows an "Also on this number" panel.
* **The initial migration was rebuilt rather than stacked with an `0002`**, since the app was one commit old
  and unpushed.

### Bugs found and fixed during the build

* **The seeder was not idempotent.** Its dedupe lookup compared the raw spec value while `Contact.save()`
  normalises on write, so the one deliberately-unnormalised seed row (`3125550188`) re-created itself on every
  run. Fixed by normalising inside the lookup. This is precisely the failure the idempotency rule exists to
  catch, and it only surfaced because the seed data includes an unnormalised number on purpose.
* **`normalize_e164` mishandled two inputs** (found by `code-reviewer`): `+00442079460958` kept its redundant
  `00` and stored a number that looks E.164 but rings nothing, and blind non-digit stripping spliced a
  trailing extension (`x205`) onto the end of the main number. Both fixed and covered in the verify script.
* **Two template partial includes passed the wrong context name** — `_appointment_status_badge.html` and
  `_call_status_badge.html` both take `obj=`, not `appointment=`/`session=`. Caught by reading the partials
  rather than assuming; would have rendered silently blank once 4.3 and Module 5 land.

### Note on verification method

An early idempotency check reported a false failure because the command was piped to `head`, which closed the
pipe, killed the process on `BrokenPipeError` and rolled back the `@transaction.atomic` seeder. **Pipe seed and
migrate commands to `tail`, never `head`.**
