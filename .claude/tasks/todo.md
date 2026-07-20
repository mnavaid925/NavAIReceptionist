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

### Carried forward — things later sub-modules MUST handle

* **4.3 (Appointments): the field is `start_at`, singular.** `explorer` caught `_appointments_for` and the
  contact detail template using `starts_at`; both are fixed. The import guard only covers the *import*, so a
  wrong field name would have raised `FieldError` at request time (view) and rendered a silently blank column
  (template) the moment 4.3 landed.
* **3.3 (`identify_contact`): an ANI lookup can match MORE THAN ONE contact.** `(tenant, phone_e164)` is
  deliberately non-unique — a household, a switchboard or a shared mobile maps to several people, and the 4.1
  detail page already surfaces that with its "Also on this number" panel. `identify_contact` must NOT silently
  `.first()`: that would attach the call, and any appointment booked on it, to the wrong person's history.
  It needs an explicit N>1 policy — treat as unidentified and ask who is calling. Whatever it does, the
  resolved `contact_id` lands in server-side session state (Invariant 3) and is never handed to the model to
  echo back as a tool argument.
* **3.3 (`create_contact`): `tenant` comes from session state**, established at `connect()` from
  `AgentSetting.objects.get(inbound_phone_number=<To>)` — never from a tool parameter.
* **Module 5: `_call_status_badge.html` branches on `transferred` and `failed`**, but the ERD defines only
  `in_progress`/`completed`/`abandoned` for `CallSession.status`. Module 5 must either add those two statuses
  or trim the dead branches. Pre-existing, not introduced by 4.1.
* **`normalize_e164` and `Contact.save()` are both realtime-safe** (pure CPU regex work; a single ORM write
  with no `select_for_update` and no signal receivers), so 3.3 can wrap `Contact.save()` in a single
  `database_sync_to_async` with nothing hidden inside it. Confirmed by `realtime-reviewer`.

### Access-tier convention for Module 4 (confirmed with the user)

Contacts — and, going forward, appointments and callbacks — are open to **any signed-in user** for
list/view/create/edit; only owner/manager can delete or erase. This deliberately differs from `tenants` and
`agents`, where every CRUD view is `@tier_required(owner, manager)`. The reason: taking bookings IS the front
desk's job, and gating contact creation to management would make the product unusable for its primary user,
whereas a Location or a Twilio credential is admin config. `explorer` flagged the divergence; the user
confirmed the front-desk-open reading. **4.2, 4.3 and 4.5 follow this same pattern.**

### Note on verification method

An early idempotency check reported a false failure because the command was piped to `head`, which closed the
pipe, killed the process on `BrokenPipeError` and rolled back the `@transaction.atomic` seeder. **Pipe seed and
migrate commands to `tail`, never `head`.**

---

# Sub-module 4.2 — Services & Resources (Module 4: Calendar & Bookings, `scheduling`) — plan from research-scheduling-4.2.md (2026-07-19)

## Shape: CRUD (EXTEND run — `apps/scheduling` already exists from 4.1, no scaffolding)

Two genuinely new tenant-scoped tables — `scheduling.Service` and `scheduling.Resource` — neither of which
exists anywhere in the repo (confirmed absent by `research-scheduling-4.2.md`'s own `grep -rn "^class "` sweep
of `apps/*/models/`), so this is CRUD-shaped, not a view sub-module. **This is an EXTEND run, not a
scaffold run**: `apps/scheduling/apps.py`, `INSTALLED_APPS`, `config/urls.py`'s `scheduling/` include and
`config/asgi.py` are all already in place from 4.1 and are untouched here. The only new package-level
artifacts are one new `ServicesResources/` sub-folder in each of `models/ forms/ views/ urls/`, one new
migration (`0002_…`, stacked on `0001_initial`), and an extension of the existing `seed_scheduling.py` — every
`__init__.py` touched gets an **appended** re-export block, never a rewrite.

## Models (from research — 2, within the 1–3 ceiling)

- [ ] **`scheduling.Service`** — tenant-scoped **with a NULLABLE `location` FK** (null = offered at all
  locations). No abstract base expresses this shape — `apps/scheduling/models/_base.py`'s own docstring already
  flags it: *"`Service` is tenant-scoped with a NULLABLE location, which no abstract base expresses — it
  declares its own FK."* Inherits `TenantOwned` directly (not `TenantLocationOwned`) and adds `location` itself.
  - `tenant` — FK `tenants.Tenant` (verified), inherited from `TenantOwned`, `on_delete=CASCADE`.
  - `location` — FK `tenants.Location` (verified: `apps/tenants/models/Location.py`), **`null=True, blank=True,
    on_delete=CASCADE, related_name='services'`** — Per-Location vs. All-Locations Scoping. `on_delete=CASCADE`
    (not `SET_NULL`) because a deleted `Location` genuinely takes its own site-specific services with it; a
    service with `location=None` (all-locations) is naturally unaffected by any single location's deletion since
    no FK points at it. **This is the one FK in this sub-module Django doesn't already narrow for us**, so the
    view/form work below must do it by hand (see Backend section).
  - `name` — `CharField(max_length=255)` — Service Catalogue baseline (Bookable Service).
  - `description` — `TextField(blank=True)` — **new field, beyond the ERD's 6-field baseline** — Service
    Description / spoken-explanation research finding: the explicit research question for this sub-module is
    *how the voice agent describes services to a caller*, and every comparator surveyed (Acuity/Square/Cal.com/
    Setmore) carries a description field for exactly that reason. Read later by 3.3's `get_business_info` tool.
  - `duration_minutes` — `PositiveIntegerField()` — Duration per Service (the core bookable unit; feeds 4.3's
    slot math, `next_open >= end_at`).
  - `buffer_minutes` — `PositiveIntegerField(default=0)` — Buffer/padding, **applied-after semantics fixed per
    research** (`next_open >= end_at + buffer_minutes`) — the ERD's single field, not Acuity/Cal.com's
    before-and-after split (see Deferred).
  - `requires_resource` — `BooleanField(default=False)` — **new field, beyond the ERD's 6-field baseline** —
    Square's explicit per-service "Require a resource" toggle; the input 4.3's availability search will branch
    on to decide whether resource capacity gates a slot.
  - `is_active` — `BooleanField(default=True)` — Active-Only Offering (excluded from booking/availability once
    4.3 lands, kept for history — never hard-deleted for this reason alone).
  - `display_order` — `PositiveIntegerField(default=0)` — Display Order for the service menu, including what the
    agent reads back to a caller (feeds 3.3's `get_business_info` ordering).
  - `Meta.ordering = ['display_order', 'name']`. **No `Meta.indexes` beyond the FK indexes Django creates
    automatically** — the research's own Compliance section confirms per-tenant service counts at this product's
    target size (single-site to few-dozen-site SMBs) keep `Meta.ordering` alone cheap; do not add one by
    reflex.
  - Form: `location` is **rendered**, `required=False`, `empty_label='All locations (offered everywhere)'`,
    narrowed to `request.tenant`'s own locations via `TenantModelForm.tenant_scoped_fields = ('location',)` —
    **the one documented exception in this sub-module to "location is never a form field"**, because unlike
    every other location-scoped model, `Service.location` is a genuine business decision the user makes
    (this-site-only vs. every-site), not an identity fact the server should silently stamp from
    `request.location`. Form excludes: `tenant` (stamped by `TenantModelForm.save()`), `created_at`/`updated_at`
    (auto). `is_active`, `display_order`, `requires_resource`, `duration_minutes`, `buffer_minutes`, `name`,
    `description` are all ordinary rendered fields.

- [ ] **`scheduling.Resource`** — `TenantLocationOwned` (tenant **and** location, both required — verified base
  class in `apps/scheduling/models/_base.py`, no deviation). A resource is a physical thing at exactly one site.
  - `tenant` / `location` — inherited from `TenantLocationOwned` (`on_delete=CASCADE` on both, per the base
    class).
  - `name` — `CharField(max_length=128)` — Bookable Resource baseline (NexHealth's Operatory, Square's rooms/
    stations/equipment/chairs, Mindbody's rooms-and-resources).
  - `resource_number` — `PositiveIntegerField(null=True, blank=True)` — matches NexHealth/Square's numbered
    room/chair pattern.
  - `description` — `CharField(max_length=255, blank=True)` — per ERD.
  - `display_order` — `PositiveIntegerField(default=0)` — feeds 4.4's future "By Resource" calendar column
    ordering (no new field there — 4.4 reuses this one).
  - `is_active` — `BooleanField(default=True)` — Active-Only Offering.
  - **No `capacity` field** — Resource Exclusivity finding: a resource hosts exactly one appointment at a time,
    recorded here as a **deliberate omission**, not an oversight, so a later pass does not add one by analogy to
    Mindbody's group-class rooms (this product has no attendee-count concept on `Appointment`). **No FK to
    `settings.AUTH_USER_MODEL`** — Resource-vs-Provider Decoupling finding: NexHealth and Square both keep the
    physical resource and the person serving from it as two independent axes; 4.3's `Appointment` will carry
    `resource` and `provider` as two separate nullable FKs, never folded into one.
  - `Meta.unique_together = [('location', 'name')]` — per ERD, prevents two same-named rooms at one site.
  - `Meta.ordering = ['display_order', 'name']`. No additional indexes beyond the inherited `(tenant, location)`
    FK indexes.
  - Form: standard `TenantLocationModelForm` — `location` **excluded**, stamped from `request.location` exactly
    like every other fully location-scoped model in the project. Form excludes: `tenant`, `location`,
    `created_at`/`updated_at`. **Gotcha to plan for explicitly**: because `location` is absent from
    `ResourceForm.Meta.fields`, Django's automatic `Meta.unique_together` validation during `full_clean()`
    silently **excludes** it too (a field outside `self.fields` is excluded from validation by default) — the
    `(location, name)` uniqueness would surface as a raw `IntegrityError`/500 on a duplicate submission instead
    of a friendly field error. `ResourceForm` must override `clean_name()` (or `clean()`) to check
    `Resource.objects.filter(tenant=self.tenant, location=self.location,
    name=name).exclude(pk=self.instance.pk).exists()` itself and raise `ValidationError` — this is new code, not
    inherited free from the base class.

### FK intent for 4.3's `Appointment` — stated now, not built here

`Appointment.service` and `Appointment.resource` will be **`on_delete=SET_NULL, null=True`** — this is what
`NavAIReceptionist-ERD.md`'s `Appointment` table actually specifies for both fields, confirmed verbatim by the
research doc's own Compliance section, and it is **not** `PROTECT` (unlike `Appointment.contact`, which the ERD
does give `on_delete=PROTECT` — the two are different by design, not by omission). Practical consequence: a hard
delete of a `Service`/`Resource` with appointment history will be survivable at the DB level once 4.3 lands (the
appointment keeps its row, just loses the reference), so this sub-module cannot rely on a `ProtectedError` catch
the way 4.1's `contact_delete_view` does. Instead:
- [ ] Both delete views implement the same **forward-looking, import-guarded check** 4.1's `_appointments_for`
  established (`try: from apps.scheduling.models import Appointment / except ImportError: … `): if the row has
  any related `Appointment`, block the hard delete and redirect with a message pointing at the `is_active`
  toggle instead ("Deactivate it so it drops out of booking without losing history"); if it has none (true
  today, since `Appointment` doesn't exist yet, and true later for a genuinely unused row), the hard delete
  proceeds. This produces the same practical safety net a `PROTECT` FK would, implemented in the view layer
  because the ERD's chosen `on_delete` is `SET_NULL`, not `PROTECT` — deliberately corrected here from a loose
  paraphrase rather than silently mis-declaring the forward FK.
- [ ] Both list/detail templates show `is_active` as the primary lifecycle control (a toggle-style edit, not a
  separate view) — Active-Only Offering's "deactivate rather than remove" pattern, universal across every
  comparator surveyed (Acuity archives, Square/Mindbody deactivate).

## Backend (apps/scheduling/{models,forms,views,urls}/ServicesResources/ — EXTEND, append re-exports)

Models:
- [ ] `apps/scheduling/models/ServicesResources/__init__.py`
- [ ] `apps/scheduling/models/ServicesResources/Services.py` — the `Service` model above
- [ ] `apps/scheduling/models/ServicesResources/Resources.py` — the `Resource` model above
- [ ] **APPEND** to `apps/scheduling/models/__init__.py` (do not rewrite): add
  `from apps.scheduling.models.ServicesResources.Services import Service` and
  `from apps.scheduling.models.ServicesResources.Resources import Resource`, extend `__all__` to
  `['Contact', 'Service', 'Resource']`, and extend the module docstring's sub-module-folder list with
  `* ServicesResources/  — 4.2  Service, Resource`

Forms:
- [ ] `apps/scheduling/forms/ServicesResources/__init__.py`
- [ ] `apps/scheduling/forms/ServicesResources/Services.py` — `ServiceForm(TenantModelForm)`,
  `tenant_scoped_fields = ('location',)`, `Meta.fields = ('location', 'name', 'description',
  'duration_minutes', 'buffer_minutes', 'requires_resource', 'is_active', 'display_order')`, `__init__` sets
  `self.fields['location'].required = False` and a friendly `empty_label`
- [ ] `apps/scheduling/forms/ServicesResources/Resources.py` — `ResourceForm(TenantLocationModelForm)`,
  `Meta.fields = ('name', 'resource_number', 'description', 'display_order', 'is_active')`, plus the manual
  `clean_name()` uniqueness check described above
- [ ] **APPEND** to `apps/scheduling/forms/__init__.py`: import both forms, extend `__all__` to
  `['ContactForm', 'ServiceForm', 'ResourceForm']`

Views:
- [ ] `apps/scheduling/views/ServicesResources/__init__.py`
- [ ] `apps/scheduling/views/ServicesResources/Services.py`:
  - [ ] `_tenant_services(request)` — `Service.objects.filter(tenant=request.tenant).select_related('location')`
  - [ ] `service_list_view` — `@login_required` only (front-desk convention, confirmed module-wide in
    `.claude/skills/scheduling/SKILL.md`). Filters, applied before pagination: `q` search across
    `name`/`description` via `Q()`; `location` GET param — `''` (default) shows every service tenant-wide,
    a specific location pk **additively** includes that location's own rows **and** `location__isnull=True`
    rows (`Q(location_id=loc) | Q(location__isnull=True)`, exactly the query 4.3's hot path will run) so
    picking a location filter **never hides all-locations services** per the task's explicit requirement, and
    a literal `all_locations` sentinel value shows only the `location__isnull=True` rows; `status` GET param
    (`active`/`inactive`) maps to `is_active=True/False`, a junk value degrades to no filter. Passes
    `location_choices=request.tenant.locations.all()` to the template (Filter Implementation Rule 1 — FK
    dropdown data must come from the view, never assumed by the template).
  - [ ] `service_create_view` / `service_edit_view` — `@login_required`; `ServiceForm(request.POST or None,
    instance=obj, request=request)`
  - [ ] `service_detail_view` — `@login_required`; shows the resolved location ("All locations" vs. the named
    site) and an import-guarded appointment count exactly like 4.1's `_appointments_for` pattern (`None` today)
  - [ ] `service_delete_view` — `@login_required` + `tier_required(*MANAGEMENT_TIERS)`, `@require_POST`; the
    import-guarded appointment check from the Models section above
- [ ] `apps/scheduling/views/ServicesResources/Resources.py`:
  - [ ] `_location_resources(request)` — `Resource.objects.filter(tenant=request.tenant,
    location=request.location)` — **both** filters always, never tenant alone (the task's explicit instruction:
    Resource is fully location-scoped, unlike Contact). Guard `request.location is None` the same way
    `apps/agents/views/_helpers.py:get_setting_for_active_location` does for create/edit/delete (redirect to
    `accounts:my_locations` with a message); the list view instead degrades to an empty queryset so the global
    `partials/_choose_location_banner.html` explains the empty state, matching how every other location-scoped
    list in the project already behaves.
  - [ ] `resource_list_view` — `@login_required`; `q` search across `name`/`description`/`resource_number`;
    `status` (`active`/`inactive`) filter; passes `active_location=request.location` explicitly to the template
    for the **visible active-location indicator** the task calls for (Resource's list header states which site
    it is showing, deliberately the opposite of Contact's "all locations" header)
  - [ ] `resource_create_view` / `resource_edit_view` — `@login_required`; `ResourceForm`
  - [ ] `resource_detail_view` — `@login_required`; import-guarded appointment count (`None` today)
  - [ ] `resource_delete_view` — `@login_required` + `tier_required(*MANAGEMENT_TIERS)`, `@require_POST`; same
    import-guarded appointment check
- [ ] **APPEND** to `apps/scheduling/views/__init__.py`: import all ten new views, extend `__all__`

URLs:
- [ ] `apps/scheduling/urls/ServicesResources/__init__.py`
- [ ] `apps/scheduling/urls/ServicesResources/Services.py` — literal before `<int:pk>`: `services/` →
  `service_list`, `services/create/` → `service_create`, `services/<int:pk>/` → `service_detail`,
  `services/<int:pk>/edit/` → `service_edit`, `services/<int:pk>/delete/` → `service_delete`
- [ ] `apps/scheduling/urls/ServicesResources/Resources.py` — `resources/` → `resource_list`,
  `resources/create/` → `resource_create`, `resources/<int:pk>/` → `resource_detail`,
  `resources/<int:pk>/edit/` → `resource_edit`, `resources/<int:pk>/delete/` → `resource_delete`
- [ ] **APPEND** to `apps/scheduling/urls/__init__.py` (do not rewrite): import both new `urlpatterns` lists and
  concatenate them onto the existing `urlpatterns = list(contact_directory_urlpatterns) + …` — check the new
  `services/`/`resources/` literals against the **whole** concatenated list, not just this file, per the
  first-match-wins rule (no collision expected: `contacts/`, `services/`, `resources/` are disjoint prefixes)

- [ ] `apps/scheduling/admin.py` — **APPEND** `ServiceAdmin` (`list_display=('name', 'tenant', 'location',
  'duration_minutes', 'requires_resource', 'is_active', 'display_order')`, `list_filter=('tenant', 'location',
  'is_active', 'requires_resource')`, `search_fields=('name', 'description')`,
  `list_select_related=('tenant', 'location')`) and `ResourceAdmin` (`list_display=('name', 'tenant', 'location',
  'resource_number', 'is_active', 'display_order')`, `list_filter=('tenant', 'location', 'is_active')`,
  `search_fields=('name', 'description')`, `list_select_related=('tenant', 'location')`) — do not touch
  `ContactAdmin`
- [ ] `makemigrations scheduling` → expect `0002_…` (an incremental migration stacked on `0001_initial`, per the
  brief — **not** a rebuilt `0001_initial`, unlike 4.1 which was still one commit old and unpushed)
- [ ] **EXTEND** `apps/scheduling/management/commands/seed_scheduling.py` idempotently — do not create a new
  seeder file. Add `DEMO_SERVICES` and `DEMO_RESOURCES` dicts keyed by tenant slug, reusing the `acme`/`globex`
  tenants and their locations already looked up by slug (never re-invent a demo tenant). Seed, per tenant:
  at least one **all-locations** service (`location=None`) and at least one **per-location** service so the
  nullable-location filter has both shapes to exercise; at least one service with `requires_resource=True` and
  one with `False`; at least one `is_active=False` row on each model so the active/inactive filter has both
  buckets; **at least two `Resource` rows per location** (seed rule "seed multiple locations" — a
  single-resource site hides the `(location, name)` uniqueness and the by-resource ordering). Dedupe
  `Service` on `(tenant, location, name)` and `Resource` on `(tenant, location, name)` via an existence check
  before create, exactly like the existing `Contact` dedupe pattern (`if Model.objects.filter(**lookup).exists():
  skipped += 1; continue`). Update the seeder's module docstring's "Sub-modules seeded so far" list to add
  `* 4.2  Service, Resource — a service catalogue and resource set per location, ...`. Touches no provider.

## Realtime & agent surface

No consumer, no `routing.py` entry, no live surface this pass — `scheduling` still has no websocket route.
**No LLM tool is implemented in this sub-module.** The forward reference is `get_business_info` (named in
`research-agents-2.1.md`, confirmed again here), which belongs to **3.3 Tools & Dispatcher** (does not exist
yet). What 4.2 ships for 3.3 to call later is the **queryable shape**, documented here so 3.3's plan has a
verified contract instead of re-deriving it: `Service.objects.filter(tenant=tenant, is_active=True).filter(
Q(location=location_id) | Q(location__isnull=True))` and `Resource.objects.filter(tenant=tenant,
location=location_id, is_active=True)`, both ordered by the existing `Meta.ordering`. When 3.3 is built, the
tool takes **zero model-supplied arguments** — `tenant_id`/`location_id` come from server-held session state
(Invariant 3) — and returns `data.services: [{"name", "description", "duration_minutes"}]` /
`data.resources: [{"name"}]` in a pure read, never touching the tool-result envelope's `error` branch on
success.

## Prompt / variables

None. No new entry on `agents.AgentSetting.variables` this pass — a rendered service list reaching the prompt
(rather than being read on-demand by the `get_business_info` tool) is explicitly the pattern this sub-module's
research rejected, citing Retell/Vapi's own "tool over static prompt" finding (research §"Beyond the bullets").

## Provider adapter

None. This sub-module makes no Twilio/STT/TTS/LLM call and adds nothing to `apps/runtime/providers/` — the
research's own Compliance section confirms "No provider call, no cost line."

## CallSession.usage cost lines

None. `calls.CallSession` does not exist yet (Module 5) and this sub-module appends nothing to any per-turn
usage ledger.

## Wire-up

- [ ] `apps/accounts/navigation.py` — add **exactly one** new entry to `LIVE_LINKS`:
  `'4.2': {'Services': 'scheduling:service_list', 'Resources': 'scheduling:resource_list'}` (two labels, one
  key — matches the existing multi-link shape already used by `'0.2'`/`'0.3'`; `MODULE_ICONS['4']` already
  exists, no change there)
- [ ] `config/settings.py` — **untouched**, `'apps.scheduling'` already in `INSTALLED_APPS` from 4.1
- [ ] `config/urls.py` — **untouched**, `path('scheduling/', include('apps.scheduling.urls'))` already present
- [ ] `config/asgi.py` — **untouched**, no websocket surface this pass
- [ ] `AUTH_USER_MODEL` — **N/A**, already declared before Module 0's first `makemigrations`

## Templates (templates/scheduling/catalog/service/ and templates/scheduling/catalog/resource/)

New sub-module slug `catalog` per CLAUDE.md's own worked example for `apps/scheduling`
(`calendar/ bookings/ directory/ catalog/ callbacks/`); two entity folders underneath it, since 4.2 owns two
models (graduates straight to the rule-2 two-level form — never single-entity-folds `catalog/` itself).

- [ ] `templates/scheduling/catalog/service/list.html` — filter bar reflecting `request.GET` (`q`, `location`
  `<select>` built from `location_choices` **plus an explicit "All locations" option that maps to the
  `all_locations` sentinel**, `status`), a `badge-info`/`badge-muted` style badge per row showing the resolved
  location ("All locations" vs. the named site — reusing the theme's colour-named badge classes, no
  `badge-purple`), Actions column (view/edit/delete-POST+confirm+csrf, delete gated to `MANAGEMENT_TIERS` in
  the template matching the view), pagination with `has_previous`/`has_next` guards, empty-state ("No services
  yet — add one to start taking bookings.")
- [ ] `templates/scheduling/catalog/service/detail.html` — full field display including the resolved
  location, `requires_resource`/`is_active` as badges, the import-guarded appointment panel (empty-state today);
  Actions sidebar (Edit, Delete-POST+confirm gated on tier, Back to List)
- [ ] `templates/scheduling/catalog/service/form.html` — shared create/edit; renders `location` as an explicit
  `<select>` with the "All locations" empty option (the one field this sub-module DOES let the user post,
  documented inline as the deliberate exception), `name`, `description`, `duration_minutes`, `buffer_minutes`,
  `requires_resource`, `display_order`, `is_active`
- [ ] `templates/scheduling/catalog/resource/list.html` — a **visible active-location indicator** in the page
  header/subtitle (e.g. "Resources — {{ request.location.name }}", reusing `active_location` from context —
  the deliberate opposite of `directory/contact/list.html`'s "all locations" header, called out inline exactly
  as the task requires), filter bar (`q`, `status`), Actions column, pagination, empty-state ("No resources at
  this location yet.")
- [ ] `templates/scheduling/catalog/resource/detail.html` — full field display, import-guarded appointment
  panel; Actions sidebar
- [ ] `templates/scheduling/catalog/resource/form.html` — shared create/edit; `name`, `resource_number`,
  `description`, `display_order`, `is_active` — **no `location` field rendered**, unlike `service/form.html`

## Verify

- [ ] `makemigrations scheduling` + `migrate` — expect `0002_…`, an incremental migration (not "No changes
  detected", and not a rebuilt `0001_initial`)
- [ ] `seed_scheduling` ×2 — second run reports the new `Service`/`Resource` rows as already present alongside
  the existing `Contact` idempotency message
- [ ] `manage.py check` — no new issues
- [ ] `PROVIDER_MODE=fake` — asserted even though this sub-module makes no provider call
- [ ] `pytest` — model tests (`Service.location` nullable + `on_delete=CASCADE`, `Resource`'s `(location,
  name)` unique_together actually raises, both `Meta.ordering`s), form tests (`ServiceForm`'s location narrowed
  to the requesting tenant and defaults to "All locations" when left blank; `ResourceForm.clean_name()` rejects
  a duplicate name at the same location but allows the same name at a different location), view tests (list
  search/filter/pagination on both, the `location` filter's additive `Q(location=X) | Q(location__isnull=True)`
  behaviour proven — NOT just asserted, a specific-location filter run and both an all-locations row AND that
  location's own row must both appear — create/edit/detail/delete on both), all under `apps/scheduling/tests/`
- [ ] Twilio webhook signature + idempotency — **N/A**, this sub-module ships no webhook
- [ ] websocket connect/reject — **N/A**, this sub-module ships no consumer
- [ ] `temp/` smoke sweep as `admin_acme` (password from `seed_accounts.py`, `navai-demo-2026`) covering every
  new `scheduling:service_*` / `scheduling:resource_*` url: 200/302, no `{#`/`{% comment` leaks, page titles, a
  seeded record visible; **cross-tenant IDOR** — `admin_acme` requesting a `globex` service/resource detail/
  edit/delete by pk gets 404; **cross-location IDOR** — `admin_acme` switched to Acme Downtown requesting an
  Acme Uptown `Resource`'s detail/edit/delete by pk gets 404 (Resource is fully location-scoped, so this check
  is new relative to 4.1, which had no location axis to test); an all-locations `Service` remains visible after
  switching the active location, while a per-location `Service` does not appear when the wrong location is
  active in the `location` filter
- [ ] Sidebar shows `4.2` Live under Module 4, both "Services" and "Resources" links resolve

## Close-out

- [ ] Review agents: `code-reviewer` → `explorer` → `frontend-reviewer` → `performance-reviewer` →
  `realtime-reviewer` (expected to find nothing — no realtime surface this pass) → `qa-smoke-tester` →
  `security-reviewer` (confirm neither model carries PII, per research's Compliance section — a sanity check,
  not an expected finding) → `test-writer`
- [ ] **UPDATE** `.claude/skills/scheduling/SKILL.md` — **do not re-author**. Add `Service`/`Resource` to the
  Models section (with the nullable-location vs. fully-location-scoped contrast spelled out), the Build State
  table row flip from "not built" to "**BUILT**" for 4.2, the new routes, the new `templates/scheduling/catalog/`
  entries, the extended seeder rows, the `get_business_info` forward contract under Tools & prompt surface, and
  a new Conventions & gotchas bullet for the `ResourceForm.clean_name()` manual uniqueness check
- [ ] README — note the two new list pages if the project README enumerates them (unlikely; skip if it doesn't
  already enumerate 4.1's Contacts page either)

## Later passes / deferred

Carried over verbatim from `research-scheduling-4.2.md`'s own Deferred section — nothing here is dropped, only
parked:

- `price`/`price_cents` field on `Service` — no payments capability exists among the seven; revisit only if one
  is ever added.
- Split `buffer_before_minutes`/`buffer_after_minutes` — the ERD's single applied-after `buffer_minutes` is
  sufficient for this product's single-service-at-a-time booking flow; revisit only on a real prep-time need.
- Multiple duration variants per service (Cal.com's `multipleDuration`) — workaround is a separate `Service` row
  per duration; a durations array/table is unwarranted complexity at this size.
- `resource_type`/category field (room vs. chair vs. equipment) — free-text `name`/`description` already covers
  it; no comparator hard-types it either.
- `Service` ↔ `Resource` eligibility matrix (M2M) — a third table, over this pass's two-model scope;
  `Service.requires_resource` plus 4.3's location-scoped resource search covers the common case.
- `capacity` field on `Resource` — **deliberately rejected, not merely postponed**: would require attendee-count
  support on `Appointment` that does not exist and is not requested by any of the seven capabilities.
- Availability-search slot computation reading `duration_minutes`/`buffer_minutes`/`requires_resource`/
  `is_active` → **4.3 Availability & Booking**.
- `Appointment.service`/`Appointment.resource` FK wiring (`on_delete=SET_NULL`, stated as intent above, not
  built here) → **4.3**.
- The calendar's "By Resource and By Provider" column toggle consuming `Resource.display_order` → **4.4
  Calendar Views**.
- `get_business_info` LLM tool implementation, argument-free schema, and result envelope (contract documented
  above under Realtime & agent surface) → **3.3 Tools & Dispatcher**.
- Booking-list filters by service/resource (4.5's "Booking List" bullet) → **4.5 Bookings List & Callback
  Requests**.

## Review notes

(filled in at the end)

## Review notes — 4.2 Services & Resources

### Built

Two models (`Service`, `Resource`), ten views, eight templates, migration `0002`, an extended seeder and
`LIVE_LINKS['4.2']`. Verified 64/64 by `temp/verify_4_2.py`; the pytest suite went 89 → **224 passing**.

### Bugs the reviewers caught, all real

1. **CRITICAL — the silent widening.** `ServiceForm` narrowed the `location` select to the editor's own
   assigned locations. Opening an Uptown-pinned service as a Downtown-only user rendered *no* option as
   selected, so the browser fell back to the first one — the blank "All locations" — and saving an
   unrelated description edit **silently changed the service to be offered at every site**. No error, no
   warning, wrong data. Fixed by UNIONing the instance's current location into the queryset.
2. **The write gate was missing.** `_tenant_services` is tenant-only by design (the catalogue is
   business-wide to READ), but `service_edit_view` and `service_delete_view` reused it unchanged for
   WRITES — so a Downtown-only user could rename, deactivate or re-time an Uptown-pinned service and
   change what the agent books at a site they do not work at. Both now refuse.
3. **`.isdigit()` before `int()` is a 500.** `'²'.isdigit()` is `True`; `int('²')` raises. `?scope=²`
   was an unhandled `ValueError`, violating the project's own "junk degrades, never raises" filter rule.
   `.isdecimal()` is the correct guard. **Worth grepping for project-wide.**
4. **TOCTOU on the hand-rolled uniqueness checks.** `.exists()` then `.save()` with nothing between them:
   a double-click or two concurrent writers both pass validation and the second insert 500s on exactly the
   path the manual check exists to keep friendly. Added `views/_helpers.py::save_or_report_conflict`.
5. **A broad `IntegrityError` catch with no traceback** would show a FK or NOT NULL violation to the user
   as a name clash and leave nothing to triage from. Now `logger.exception`.

### Decisions

* **`Service.location` is hand-declared, not inherited.** Neither `TenantOwned` nor `TenantLocationOwned`
  expresses "tenant + optional location", and forcing either would lose a real case.
* **`Resource` has no `capacity` and no user FK.** A room is exclusive (no group-class model exists), and
  the provider is a separate concern from the room — merging them would conflate two independent
  constraints.
* **Read business-wide, write location-gated** for site-pinned services. See bug 2.

### Deferred

Price, split before/after buffers, multi-duration services, a `resource_type` category, a Service↔Resource
requirement M2M. All carried in `research-scheduling-4.2.md`.

### Sequence steps NOT run for 4.2

`frontend-reviewer`, `performance-reviewer`, `realtime-reviewer` and `qa-smoke-tester` were skipped for
context budget. `code-reviewer`, `explorer`, `security-reviewer` and `test-writer` all ran and their
findings are applied. **Run the four skipped agents against `apps/scheduling` and
`templates/scheduling/catalog/` in a fresh session before treating 4.2 as fully closed.** Note that
`realtime-reviewer` will find nothing — this sub-module has no async surface.

---
# Sub-module 4.3 — Availability & Booking (Module 4: Calendar & Bookings, `scheduling`) — plan from research-scheduling-4.3.md (2026-07-19)

## Shape: CRUD (EXTEND run — `apps/scheduling` already exists from 4.1/4.2, no scaffolding)

One genuinely new tenant-**and**-location-scoped table, `scheduling.Appointment` (confirmed absent by
`research-scheduling-4.3.md`'s own repo sweep), so this is CRUD-shaped. It ships full list/create/detail/
edit/delete per the CRUD Completeness Rule, **plus** a non-model availability-search/booking service the
future voice tools (Module 3.3) will call. **EXTEND run**: `apps/scheduling/apps.py`, `INSTALLED_APPS`,
`config/urls.py`'s `scheduling/` include and `config/asgi.py` are already wired from 4.1 and are untouched.
New artifacts: one `Bookings/` sub-folder in each of `models/ forms/ views/ urls/` (per the invoking
instruction — this sub-module's short PascalCase form is `Bookings`, not `AvailabilityBooking`), one new
flat file `apps/scheduling/services.py` (availability + booking logic — a single-purpose flat module per
CLAUDE.md Backend rule 8, which lists `services.py` by name), migration `0003_…`, and an idempotent
extension of `seed_scheduling.py` **plus** a small, additive extension of `seed_accounts.py` (see Backend —
`provider_hours` has no data to search without it). `booked_by_session` is explicitly **omitted** this pass
— `apps/calls` has zero files, and Django refuses `makemigrations` against a string FK to an uninstalled
app; it lands as an additive migration when Module 5 creates `calls.CallSession`, per the invoking
instruction. No placeholder field stands in for it.

## Models (from research — 1, within the 1–3 ceiling)

- [ ] **`scheduling.Appointment`** — `TenantLocationOwned` (verified base class, `apps/scheduling/models/
  _base.py`; SKILL.md already documents `Appointment` as one of the three `TenantLocationOwned` models in
  this app). Tenant **and** location scoped — both required, `on_delete=CASCADE` on both, inherited.
  - `contact` — FK `scheduling.Contact` (verified: `models/ContactDirectory/Contacts.py`),
    `on_delete=models.PROTECT`, `related_name='appointments'` — **per the ERD, not `CASCADE`/`SET_NULL`**.
    This is what forces the erasure path the skill's "Delete vs erase" section already anticipates: once
    this lands, a `Contact` with bookings raises `ProtectedError` on hard delete and must be anonymized
    instead. Availability Search / Booking Provenance driver.
  - `provider` — FK `settings.AUTH_USER_MODEL`, `null=True, blank=True, on_delete=models.SET_NULL,
    related_name='provider_appointments'` — Availability Search (provider working-hours) driver. Never
    `CASCADE`: a deleted staff account should not delete the appointment history, just detach from it.
  - `resource` — FK `scheduling.Resource` (verified), `null=True, blank=True, on_delete=models.SET_NULL,
    related_name='appointments'` — Resource Exclusivity driver. Matches the **on_delete intent 4.2's own
    todo already stated in advance** ("`Appointment.service`/`Appointment.resource` will be
    `on_delete=SET_NULL, null=True`" — 4.2 plan, "FK intent for 4.3's Appointment").
  - `service` — FK `scheduling.Service` (verified), `null=True, blank=True, on_delete=models.SET_NULL,
    related_name='appointments'` — Duration + Buffer Subtraction driver (`service.total_minutes`).
  - `start_at`, `end_at` — `DateTimeField()`, both required — Timezone-Correct Evaluation driver; always
    written/read as tz-aware values evaluated against `location.tzinfo`, never `timezone.localtime()`'s
    server default.
  - `status` — `CharField(max_length=24, db_index=True, default='scheduled', choices=STATUS_CHOICES)`,
    `STATUS_CHOICES = [('scheduled','Scheduled'),('confirmed','Confirmed'),('completed','Completed'),
    ('cancelled','Cancelled'),('no_show','No-show')]` — Reschedule & Cancel + No-Show-as-distinct-status
    driver. `SCHEDULED_LIKE = ('scheduled', 'confirmed')` class constant — the "still live" set every guard
    below checks against.
  - `reason` — `CharField(max_length=255, blank=True)` — why the appointment was booked (caller-dictated on
    the AI path — untrusted text, same PII discipline as `Contact.notes`).
  - `notes` — `TextField(blank=True)` — staff/agent notes, same discipline; renders `|linebreaksbr`, never
    `|safe`.
  - `source` — `CharField(max_length=16, choices=SOURCE_CHOICES, default='manual')`,
    `SOURCE_CHOICES = [('ai_phone','AI Phone'),('manual','Manual'),('web','Web')]` — mirrors
    `Contact.SOURCE_*`. Booking Provenance driver — **server-stamped, never a form field**: the manual
    create view hard-codes `source='manual'`; the future tool path (3.3) hard-codes `source='ai_phone'`.
  - `cancelled_at` — `DateTimeField(null=True, blank=True)` — Reschedule & Cancel driver.
  - `cancellation_reason` — `CharField(max_length=255, blank=True)` — Reschedule & Cancel driver.
  - **`booked_by_session` — NOT included this pass.** Model docstring states explicitly: *"Module 5 adds
    `booked_by_session` (FK `calls.CallSession`, null, `SET_NULL`) as an additive migration once
    `apps/calls` exists. Until then an `ai_phone` row has no back-link to the call that created it."*
  - **No `number` field.** CLAUDE.md's own Seed Command Rules use `APPT-00001` as an illustrative example
    of the (already-built, currently-unused) `TenantNumbered` abstract base, but the ERD given for this
    sub-module does not list a `number` field and no researched feature asks for one — adding it would be
    an uncommitted schema guess. `TenantNumbered` stays unused this pass (see Deferred). Seeder dedup keys
    on `(tenant, location, contact, start_at)` instead of a number.
  - `Meta.indexes`: `models.Index(fields=['tenant','location','start_at'], name='idx_appt_tenant_loc_start')`
    (the live-call availability hot path), `models.Index(fields=['tenant','status'],
    name='idx_appt_tenant_status')`, `models.Index(fields=['tenant','contact'], name='idx_appt_tenant_contact')`
    — all three straight from the ERD. `Meta.ordering = ['start_at']`.
  - Methods: `is_editable` (property, `status in SCHEDULED_LIKE`), `cancel(reason)` (stamps
    `status='cancelled'`, `cancelled_at=timezone.now()`, `cancellation_reason=reason`, `save(update_fields=…)`
    — reused by both the staff cancel view and the future `cancel_appointment` tool via `services.py`),
    `__str__` (`f"{self.contact} — {self.start_at:%Y-%m-%d %H:%M}"`).

## Availability service module, slot token & concurrency (the non-model half of this pass)

- [ ] **Location decision: `apps/scheduling/services.py`, flat at the app root** — not inside the
  `Appointments.py` entity file, not under `views/_helpers.py`. Justification: CLAUDE.md Backend rule 8
  explicitly names `services.py` as one of the canonical flat single-purpose modules every app keeps at its
  root (`admin.py, apps.py, services.py, consumers.py, routing.py, …`); this is pure business logic with no
  Django request/response shape, called by BOTH the human-facing views in this pass and the not-yet-built
  LLM tools in 3.3 — putting it in `views/` would force 3.3 to import a `views` module for non-view logic.
  Note the name collision risk with the `scheduling.Service` **model** is real but accepted — it is the
  file CLAUDE.md itself names; the module docstring calls this out explicitly so nobody "fixes" it into
  `Services.py`/`availability.py` later.
- [ ] Module-level constants (no `settings.py`/model field — research's own recommendation: "a simple
  settings constant for this pass, not a new field"): `MIN_BOOKING_NOTICE_MINUTES = 60`,
  `MAX_OFFERED_SLOTS = 5` (the Server-Capped Slot Set), `SLOT_GRID_MINUTES = 15` (candidate start-time
  granularity within a provider's working window), `SLOT_TOKEN_SALT = 'scheduling.slot'`,
  `SLOT_TOKEN_TTL_SECONDS = 300` (5 minutes — long enough for a multi-turn phone confirmation or a staff
  form submit, short enough that a stale offer cannot be redeemed hours later).
- [ ] `overlapping_appointments(tenant, location, start_at, end_at, resource=None, provider=None,
  exclude_pk=None)` — the ONE overlap query every other function below reuses: non-cancelled
  (`status__in=Appointment.SCHEDULED_LIKE`) rows at `(tenant, location)` whose window intersects
  `[start_at, end_at)`, `OR`ed across `resource=`/`provider=` when supplied (Provider AND Resource Must
  Both Clear — a busy room with a free provider is still unbookable, and vice versa).
- [ ] `slot_is_free(...)` — `not overlapping_appointments(...).exists()`. Used directly by
  `AppointmentForm.clean()` for the plain staff-typed-time path (no token involved).
- [ ] `find_available_slots(tenant, location, service, date_from, date_to, resource=None, provider=None,
  max_slots=MAX_OFFERED_SLOTS)` — **pure read, no write.** For each day in range × each eligible provider
  (working-hours source: `provider.provider_hours[str(location.id)]`, filtered to that weekday's `days`
  entry, parsed against `location.tzinfo` — Timezone-Correct Evaluation) × each 15-minute grid start: builds
  a candidate span of `service.total_minutes` (Duration + Buffer Subtraction), drops it if it starts before
  `location.local_now() + MIN_BOOKING_NOTICE_MINUTES` (Minimum Notice), drops it if `service.requires_resource`
  and no eligible `Resource` at that location clears `slot_is_free` for that window (Resource Exclusivity —
  `Resource` carries no capacity, one appointment fully occupies it), drops it if the chosen provider does
  not independently clear `slot_is_free` too. Sorts soonest-first, returns at most `max_slots` — **capped
  server-side, never model- or client-controlled** (Server-Capped Slot Set). Reused verbatim by the
  human-facing create/reschedule slot-picker AND (once built) 3.3's `get_availability` tool — one function,
  two callers, per research's explicit "slot count independent of the booking-form UI" finding.
- [ ] `_mint_slot(tenant, location, service, provider, resource, start_at, end_at)` — the **opaque signed
  slot token**. Payload: `{"tenant_id", "location_id", "service_id", "provider_id", "resource_id",
  "start_at" (isoformat), "end_at" (isoformat)}` — semantic fields the SERVER put there, never fields the
  model is asked to construct. `signing.dumps(payload, salt=SLOT_TOKEN_SALT)` — same
  `django.core.signing` pattern as `EMAIL_CHANGE_SALT` in `apps/accounts/views/Auth.py`. Returns
  `{"slot_token", "starts_at", "ends_at", "provider_label", "resource_label"}` — **display fields only**;
  the model/human never needs to know or send back a raw resource/provider id.
- [ ] `redeem_slot_token(token, tenant, location)` — `signing.loads(token, salt=SLOT_TOKEN_SALT,
  max_age=SLOT_TOKEN_TTL_SECONDS)`, catching `signing.BadSignature` → `(None, {"code": "slot_expired", ...})`
  (covers tampering, wrong salt AND expiry in one branch, matching the established `email_change_confirm`
  pattern). **Defense in depth**: the decoded payload's own `tenant_id`/`location_id` are cross-checked
  against the SERVER-HELD `tenant`/`location` arguments (never trusted alone) → `(None, {"code":
  "not_permitted", ...})` on mismatch. This is what stops a token minted for one location being replayed
  against another location's active context.
- [ ] **Concurrency mechanism, named explicitly: `transaction.atomic()` + `select_for_update()` on the
  overlap queryset, re-checked AFTER the lock is taken, inside `book_appointment_from_slot()` /
  `reschedule_appointment()`.** No distributed/Redis-style lock (research explicitly rejects one — no
  cache/lock service in this project's scope). Sequence: (1) open `transaction.atomic()`; (2)
  `Appointment.objects.select_for_update().filter(<the overlap predicate>)` and force materialization
  (`list(...)`) so the row lock is actually taken before the next step, not deferred; (3) re-run
  `slot_is_free()` inside the lock — if a concurrent writer committed a conflicting row between the
  availability search and this write, it is visible now and the call returns `{"ok": false, "error":
  {"code": "slot_unavailable", ...}}`; (4) only then create/update the row. **Honest limit, stated so a
  reviewer doesn't assume otherwise: there is no portable DB-level range-exclusion constraint on
  MySQL/MariaDB** (unlike Postgres's `EXCLUDE USING gist`), so this transactional check-under-lock IS the
  enforcement, not a belt-and-suspenders addition to one. On the production MySQL/MariaDB backend, a second
  writer's `select_for_update()` genuinely blocks until the first transaction commits, then re-sees the
  just-committed conflict on its own re-check — this is what actually prevents the double-book. On SQLite
  (pytest, `config.settings_test`) the whole-database write lock is coarser but still correctness-preserving
  for a same-process race test. Plan a test that opens two overlapping `book_appointment_from_slot()` calls
  against the same resource/provider/window and asserts the second gets `slot_unavailable`, not a duplicate
  row and not a raw `IntegrityError`.
- [ ] **Idempotent booking write — the exact mechanism.** No new DB table, no cached token registry. Inside
  the same locked transaction, before insert: look for an existing non-cancelled `Appointment` at
  `(tenant, location, contact, start_at, end_at, resource_id, provider_id)` matching the token's own
  decoded payload exactly. If found, **return that row**, not a new one — a retried tool call (model
  timeout-retry, or a double-submitted form) redeeming the SAME token twice is a no-op on the second call,
  not a duplicate booking and not an error.
- [ ] `book_appointment_from_slot(token, tenant, location, contact, source, reason='', notes='',
  actor_contact_id=None)` → `(appointment_or_None, error_dict_or_None)`. `actor_contact_id` is an optional
  forward parameter — `None` for every call in THIS pass (the staff-facing create view never sets it); when
  3.3 lands, the tool passes the server-identified `contact_id` and this function is where Invariant 3's
  "authorized server-side against tenant, location AND the identified contact" gets enforced for booking.
- [ ] `reschedule_appointment(appointment, token, tenant, location, actor_contact_id=None)` → same
  `(obj_or_None, error_dict_or_None)` shape. Guards `appointment.status in Appointment.SCHEDULED_LIKE` first
  (`{"code": "invalid_argument", ...}` otherwise), then the same redeem → lock → re-check → write sequence,
  updating `start_at`/`end_at`/`resource`/`provider` on the **same row** — never a bare field edit outside
  this function, matching the research finding verbatim. When `actor_contact_id` is supplied and does not
  match `appointment.contact_id` → `{"code": "not_permitted", ...}` (Invariant 3, wired now even though no
  caller sets it yet).
- [ ] `cancel_appointment(appointment, reason, actor_contact_id=None)` → same shape, guards
  `SCHEDULED_LIKE`, stamps via the model's own `cancel(reason)` method, same `actor_contact_id` check.
- [ ] Error codes used above are exactly the closed set from CLAUDE.md's tool-result envelope:
  `slot_unavailable`, `slot_expired`, `not_permitted`, `invalid_argument` — no ad-hoc string invented.

## Backend (apps/scheduling/{models,forms,views,urls}/Bookings/ — EXTEND, append re-exports)

Models:
- [ ] `apps/scheduling/models/Bookings/__init__.py`
- [ ] `apps/scheduling/models/Bookings/Appointments.py` — the `Appointment` model above
- [ ] **APPEND** to `apps/scheduling/models/__init__.py`: `from apps.scheduling.models.Bookings.Appointments
  import Appointment`, extend `__all__` to `['Contact', 'Service', 'Resource', 'Appointment']`, extend the
  module docstring's sub-module-folder list with `* Bookings/  — 4.3  Appointment`

Services (flat, not a package):
- [ ] `apps/scheduling/services.py` — all functions/constants above

Forms:
- [ ] `apps/scheduling/forms/Bookings/__init__.py`
- [ ] `apps/scheduling/forms/Bookings/Appointments.py` — `AppointmentForm(TenantLocationModelForm)`,
  `tenant_scoped_fields = ('contact',)`, `Meta.fields = ('contact', 'service', 'provider', 'resource',
  'start_at', 'end_at', 'reason', 'notes', 'status')`. `__init__`: narrows `service` via the reused
  `_bookable_here()` helper from `views/ServicesResources/Services.py` (`Service.objects.filter(tenant=self
  .tenant, is_active=True)` passed through it — additive nullable-location filter, per the skill's own
  gotcha), narrows `resource` to `Resource.objects.filter(tenant=self.tenant, location=self.location,
  is_active=True)`, narrows `provider` to `User.objects.filter(tenant=self.tenant, is_provider=True,
  user_locations__location=self.location).distinct()` (bespoke — `User` is not itself location-scoped via a
  plain FK, so this is hand-written, not the generic `location_scoped_fields` helper). On **create**
  (`not self.instance.pk`): pops `status` (server-stamped `'scheduled'` in the view). On **edit**
  (`self.instance.pk` set): sets `start_at`, `end_at`, `provider`, `resource` to `disabled=True` — Django's
  real disabled-field mechanism (ignores POST, keeps the instance value) — because time/resource/provider
  changes go through the dedicated Reschedule action's slot-locking machinery, never a bare field edit
  (research finding, enforced structurally here); restricts `status`'s choices to exclude `'cancelled'`
  (cancel has its own dedicated reason-requiring action). `clean()`: rejects `end_at <= start_at`; on
  create only, calls `slot_is_free(...)` with the cleaned `resource`/`provider` and raises a friendly
  `ValidationError` on conflict (edit's time fields are disabled, so no re-check needed there).
- [ ] **APPEND** to `apps/scheduling/forms/__init__.py`: import `AppointmentForm`, extend `__all__`

Views:
- [ ] `apps/scheduling/views/Bookings/__init__.py`
- [ ] `apps/scheduling/views/Bookings/Appointments.py`:
  - [ ] `_location_appointments(request)` — `Appointment.objects.filter(tenant=request.tenant,
    location=request.location).select_related('contact', 'provider', 'resource', 'service')` — **both**
    filters always (fully location-scoped, like `Resource`, not business-wide like `Contact`)
  - [ ] `appointment_list_view` — `@login_required` only. Filters applied before pagination: `q` search
    across `contact__first_name`/`contact__last_name`/`contact__phone_e164` via `Q()`; `status` GET param
    against `Appointment.STATUS_CHOICES`, junk degrades to no filter; `date_from`/`date_to` GET params
    (`YYYY-MM-DD`, parsed defensively — an unparseable value degrades to no filter, never a 500) against
    `start_at__date__gte`/`__lte`. Passes `status_choices=Appointment.STATUS_CHOICES` (Filter Rule 1).
    **Provider/resource/service dropdown filters and contact-name search enrichment are 4.5's job** (parked
    below) — this pass ships the baseline CLAUDE.md mandates: search + one categorical filter + a date
    range, all applied before pagination, all degrading gracefully.
  - [ ] `appointment_create_view` — `@login_required`. **Dual path**: if `request.POST.get('slot_token')` is
    present, calls `services.book_appointment_from_slot(token, request.tenant, request.location,
    contact=<posted contact>, source='manual')` — ignores any raw posted `start_at`/`end_at` (the token is
    authoritative); on `(None, error)` re-renders the form with `error['message']` attached via
    `form.add_error(None, ...)`. Otherwise falls back to the plain `AppointmentForm` path (`request=request`),
    server-stamps `obj.status = 'scheduled'` and `obj.source = 'manual'` before save, wraps the whole write
    in `transaction.atomic()` with the same lock-then-recheck sequence as `services.py` (extracted so both
    paths share the exact same overlap semantics — do not duplicate the check inline).
  - [ ] `appointment_slots_view` (GET, `@login_required`) — reads `service` (required — degrade to an
    empty-slots response with a message if missing/invalid), `date_from`/`date_to` (default: today .. today
    +14, clamped to that window even if the client asks for more), optional `resource`/`provider` GET
    preferences (pk values authorised against `request.tenant`/`request.location` querysets, junk → ignored,
    never trusted blind). Calls `services.find_available_slots(...)`. Renders the
    `_slot_picker.html` partial (HTMX endpoint — no full page).
  - [ ] `appointment_detail_view` — `@login_required`; shows contact/provider/resource/service, status
    badge, reason/notes (`|linebreaksbr`), cancellation details when cancelled. Actions sidebar per CRUD
    rule 3: Edit + Reschedule + Cancel all conditional on `obj.status in Appointment.SCHEDULED_LIKE`; Delete
    conditional on tier; Back to List always.
  - [ ] `appointment_edit_view` — `@login_required`; **guards `obj.status in Appointment.SCHEDULED_LIKE`**
    before rendering/accepting POST (redirect to detail with a message otherwise — a completed/cancelled/
    no-show appointment is a record of what happened, not editable, mirroring the project's own
    `CallSession`-has-no-edit-view precedent applied here to terminal statuses). `AppointmentForm(request
    .POST or None, instance=obj, request=request)` — time/provider/resource render disabled per the form's
    own `__init__` logic; only `contact`/`service`/`reason`/`notes`/`status` (non-`cancelled` choices)
    actually change.
  - [ ] `appointment_reschedule_view` (GET + POST, `@login_required`) — same `SCHEDULED_LIKE` guard. GET:
    renders `reschedule.html` with the slot picker pre-scoped to the appointment's own `service`/`location`
    (via the same `appointment_slots_view` HTMX endpoint, `hx-vals` carrying the appointment pk for context
    only — never trusted as an identity source, the pk is re-fetched with the tenant+location guard on
    POST). POST: requires `slot_token` (no raw-entry escape hatch — unlike create, research's own finding
    is enforced with no exception here); calls `services.reschedule_appointment(obj, token, request.tenant,
    request.location)`; on success redirects to detail with a success message, on error re-renders with
    `error['message']`.
  - [ ] `appointment_cancel_view` (GET + POST, `@login_required`) — same `SCHEDULED_LIKE` guard. GET: shows
    `cancel.html`, a small reason form (`cancellation_reason`, required — a bare confirm() dialog cannot
    collect free text, unlike `contact_forget`'s simpler POST+JS-confirm shape). POST: calls
    `services.cancel_appointment(obj, reason)`, redirects to detail with a success message on success.
  - [ ] `appointment_delete_view` — `@login_required` + `tier_required(*MANAGEMENT_TIERS)` (the ONE
    tier-gated view in this sub-module, per the confirmed access tier), `@require_POST`. Hard delete, **no**
    status guard (management cleanup action, matches the unconditional tier-gated delete already
    established for `Contact`/`Service`/`Resource`). Redirects to list with a success message.
- [ ] **APPEND** to `apps/scheduling/views/__init__.py`: import all eight new views (`appointment_list`,
  `appointment_create`, `appointment_slots`, `appointment_detail`, `appointment_edit`,
  `appointment_reschedule`, `appointment_cancel`, `appointment_delete`), extend `__all__`

URLs:
- [ ] `apps/scheduling/urls/Bookings/__init__.py`
- [ ] `apps/scheduling/urls/Bookings/Appointments.py` — literal-before-`<int:pk>`, checked against the
  WHOLE concatenated `urls/__init__.py` list, not just this file (no collision: `appointments/` is a new,
  disjoint prefix from `contacts/`/`services/`/`resources/`): `appointments/` → `appointment_list`,
  `appointments/create/` → `appointment_create`, `appointments/slots/` → `appointment_slots`,
  `appointments/<int:pk>/` → `appointment_detail`, `appointments/<int:pk>/edit/` → `appointment_edit`,
  `appointments/<int:pk>/reschedule/` → `appointment_reschedule`, `appointments/<int:pk>/cancel/` →
  `appointment_cancel`, `appointments/<int:pk>/delete/` → `appointment_delete`
- [ ] **APPEND** to `apps/scheduling/urls/__init__.py` (do not rewrite): import the new `urlpatterns` list,
  concatenate it onto the existing `urlpatterns = list(contact_directory_urlpatterns) + service_urlpatterns
  + resource_urlpatterns`

- [ ] `apps/scheduling/admin.py` — **APPEND** `AppointmentAdmin` (`list_display=('__str__', 'tenant',
  'location', 'status', 'source', 'start_at')`, `list_filter=('tenant', 'location', 'status', 'source')`,
  `search_fields=('contact__first_name', 'contact__last_name', 'contact__phone_e164')`,
  `list_select_related=('tenant', 'location', 'contact', 'provider', 'resource', 'service')`,
  `readonly_fields=('cancelled_at',)`) — do not touch `ContactAdmin`/`ServiceAdmin`/`ResourceAdmin`
- [ ] `makemigrations scheduling` → expect `0003_appointment` (one new model, no FK to `calls` — nothing to
  break `makemigrations` this time, unlike the deferred field)
- [ ] **EXTEND** `apps/accounts/management/commands/seed_accounts.py`'s `DEMO_USERS` user-creation loop —
  after each `is_provider=True` user's `UserLocation` rows are created, also stamp `provider_hours` on that
  user, keyed by each assigned location's **resolved id** (Mon–Fri 09:00–17:00 default), because
  `find_available_slots()` has no candidate window to search without it. Only two users need this today:
  `acme_downtown` (Marco Reyes, Downtown only) and `globex_riverside` (Tom Bergstrom, Riverside only). A
  plain field assignment + `save(update_fields=['provider_hours'])`, idempotent by construction (same
  deterministic value every run, not an append). This is an additive edit to an EXISTING seeder file, not a
  new one — its own commit, per the one-file-per-commit rule.
- [ ] **EXTEND** `apps/scheduling/management/commands/seed_scheduling.py` idempotently — do not create a
  new seeder file. Add `_seed_appointments(tenants)` after `_seed_services`/`_seed_resources`, reusing the
  already-seeded `Contact`/`Service`/`Resource`/provider `User` rows by lookup (never re-invent them).
  Cover **at least one appointment at every demo location** (Downtown, Uptown, Riverside, Lakeside — the
  "seed multiple locations" rule, doubly important here since Uptown/Lakeside have no assigned provider and
  must prove `provider=None` appointments still work), spanning all five `status` values across the two
  tenants combined, at least one `requires_resource=True` service with a `resource` attached and one
  `requires_resource=False` service with none, and at least one `ai_phone`-sourced row (Booking Provenance —
  what 3.3 will eventually attach `booked_by_session` to). Dedup key: `(tenant, location, contact, start_at)`
  existence check before create (no `number` field to key on this pass — see Models). Update the seeder's
  module docstring's "Sub-modules seeded so far" list to add `* 4.3  Appointment — bookings across every
  demo location, spanning every status and both resource-required and resource-free services.`

## Realtime & agent surface

No consumer, no `routing.py` entry this pass — `scheduling` still has no websocket route. **No LLM tool is
implemented in this sub-module** (confirmed by research: "4.3 itself ships no LLM tools"). What it ships
instead is the forward contract Module 3.3 will build its tools on top of, documented here so that plan has
a verified contract rather than re-deriving one:
- [ ] `get_availability` (future) → calls `services.find_available_slots(tenant, location, service,
  date_from, date_to, resource=None, provider=None)` with `tenant`/`location` from **server-side session
  state**, never tool parameters (Invariant 3); returns `data.slots` = the list `find_available_slots`
  already produces, each entry carrying only `slot_token` + display fields.
- [ ] `book_appointment` (future) → calls `services.book_appointment_from_slot(token, tenant, location,
  contact, source='ai_phone', reason=<model arg>, notes=<model arg>)` — `contact`/`tenant`/`location` from
  server state (the identified caller), `source` hard-coded `'ai_phone'` never a model arg, `slot_token`
  is the only identity-shaped argument the model supplies and it is opaque.
- [ ] `reschedule_appointment` (future) → calls `services.reschedule_appointment(appointment, token, tenant,
  location, actor_contact_id=<server-identified contact>)` — `appointment_id` the model supplies is
  resolved server-side (`get_object_or_404(Appointment, pk=appointment_id, tenant=tenant, location=location)`)
  BEFORE being handed to this function, and `actor_contact_id` is what makes the "authorised against the
  identified contact" half of Invariant 3 real, not just documented.
- [ ] `cancel_appointment` (future) → calls `services.cancel_appointment(appointment, reason,
  actor_contact_id=<server-identified contact>)`, same authorization shape.
- [ ] All four return the `{"ok": bool, "data": {...}, "error": {"code", "message"} | null}` envelope at
  the tool layer (3.3's job to wrap); `services.py`'s own functions return `(value, error_dict_or_None)`
  tuples this pass, which is what 3.3 wraps into that envelope — not the envelope itself, since this
  sub-module has no dispatcher to envelope for.

## Prompt / variables

None. No new entry on `agents.AgentSetting.variables` — availability/booking is tool-driven (a live DB
read at the moment of the call), never baked into the static prompt, matching 4.2's own established finding
("tool over static prompt").

## Provider adapter

None. `apps/runtime/providers/` untouched — this sub-module is pure ORM/DB logic, no Twilio/STT/TTS/LLM
call.

## CallSession.usage cost lines

None. `calls.CallSession` does not exist yet (Module 5).

## Wire-up

- [ ] `apps/accounts/navigation.py` — add **exactly one** new entry: `'4.3': {'Appointments':
  'scheduling:appointment_list'}` (singular label matching the 4.1/4.2 plural-entity-name convention;
  `MODULE_ICONS['4']` unchanged)
- [ ] `config/settings.py` — **untouched**, `'apps.scheduling'` already in `INSTALLED_APPS`
- [ ] `config/urls.py` — **untouched**, `path('scheduling/', include('apps.scheduling.urls'))` already present
- [ ] `config/asgi.py` — **untouched**, no websocket surface this pass
- [ ] `AUTH_USER_MODEL` — **N/A**, already declared before Module 0's first `makemigrations`

## Templates (templates/scheduling/bookings/appointment/)

New sub-module slug `bookings`, per CLAUDE.md's own worked example for `apps/scheduling`
(`calendar/ bookings/ directory/ catalog/ callbacks/`); one entity folder underneath it (`appointment/`)
since 4.3 owns one model.

- [ ] `templates/scheduling/bookings/appointment/list.html` — filter bar reflecting `request.GET` (`q`,
  `status` `<select>` from `status_choices`, `date_from`/`date_to`), a status badge per row using the
  canonical badge map applied to Appointment's own choices — `scheduled`→`badge-info`,
  `confirmed`→`badge-info`, `completed`→`badge-green`, `cancelled`→`badge-muted`, `no_show`→`badge-red`,
  `{% else %}` fallback to `{{ obj.get_status_display }}` (no `badge-purple`), Actions column
  (view/edit/reschedule/cancel all wrapped in `{% if obj.status == 'scheduled' or obj.status == 'confirmed'
  %}`, delete POST+confirm+csrf wrapped in the tier check), pagination with `has_previous`/`has_next`
  guards, empty-state ("No appointments yet — book the first one.")
- [ ] `templates/scheduling/bookings/appointment/detail.html` — full field display (contact, provider,
  resource, service, start/end in the location's local time, reason, notes via `|linebreaksbr`,
  cancellation block when cancelled), status badge, Actions sidebar per CRUD rule 3 (Edit/Reschedule/Cancel
  conditional on status, Delete conditional on tier, Back to List)
- [ ] `templates/scheduling/bookings/appointment/form.html` — shared create/edit; renders contact, service,
  provider, resource, start_at, end_at, reason, notes (+ status on edit only, per the form's own logic);
  includes `_slot_picker.html` via HTMX on create only, with a "or enter a time directly" fallback section
  for the plain-entry path
- [ ] `templates/scheduling/bookings/appointment/_slot_picker.html` — HTMX partial, `MAX_OFFERED_SLOTS`
  buttons/radios labelled with the display fields (`starts_at`, `provider_label`, `resource_label`), each
  posting its own `slot_token`; empty-state ("No open slots in this window — try a different date range.")
- [ ] `templates/scheduling/bookings/appointment/reschedule.html` — the slot-picker-only flow (no raw-entry
  fallback), shows the appointment's current time for reference, submits `slot_token`
- [ ] `templates/scheduling/bookings/appointment/cancel.html` — reason `<textarea>` (required), confirm/
  cancel buttons, csrf

## Verify

- [ ] `makemigrations scheduling` + `migrate` — expect `0003_appointment`, an incremental migration
- [ ] `seed_accounts` ×2 — second run leaves `provider_hours` unchanged (idempotent field stamp, not a
  duplicate row); `seed_scheduling` ×2 — second run reports the new `Appointment` rows as already present
- [ ] `manage.py check` — no new issues
- [ ] `PROVIDER_MODE=fake` — asserted even though this sub-module makes no provider call
- [ ] `pytest` — model tests (`Appointment.contact` really is `PROTECT`, `resource`/`service` really are
  `SET_NULL`, `Meta.ordering`, the three indexes exist), `services.py` tests (`find_available_slots`
  respects working hours/buffer/min-notice/resource-exclusivity/timezone, `slot_is_free` catches an overlap
  on `resource` alone and on `provider` alone, `redeem_slot_token` rejects tampering/wrong-salt/expiry/
  wrong-location, **the concurrency race test**: two overlapping `book_appointment_from_slot()` calls
  against the same window → the second gets `slot_unavailable`, not a duplicate row, **the idempotency
  test**: redeeming the SAME token twice returns the same `Appointment.pk` both times), form tests
  (`AppointmentForm` narrows service/resource/provider correctly, disables time/provider/resource on edit,
  rejects `end_at <= start_at`), view tests (list search/filter/pagination, create via both the slot-token
  path and the plain-entry path, detail/edit/reschedule/cancel/delete, the `SCHEDULED_LIKE` guard blocking
  edit/reschedule/cancel on a completed/cancelled/no_show row), all under `apps/scheduling/tests/`
- [ ] **Replace** `test_views.py`'s `TODO(4.3 / Module 5)` regression guard (currently asserting
  `_appointments_for`/`_call_sessions_for` return `None`) with the real cross-location assertion its own
  docstring specifies: a user assigned only to location A1 sees an appointment of this contact's at A1 but
  NOT one at A2 (same tenant, different location) — `_appointments_for` needs no code change (it is already
  written and import-guarded), only its test does
- [ ] Twilio webhook signature + idempotency — **N/A**, this sub-module ships no webhook
- [ ] websocket connect/reject — **N/A**, this sub-module ships no consumer
- [ ] `temp/` smoke sweep as `admin_acme` (password `navai-demo-2026`, from `seed_accounts.py`) covering
  every new `scheduling:appointment_*` url: 200/302, no `{#`/`{% comment` leaks, page titles, a seeded
  record visible; **cross-tenant IDOR** — `admin_acme` requesting a `globex` appointment detail/edit/
  reschedule/cancel/delete by pk gets 404; **cross-location IDOR** — `admin_acme` switched to Downtown
  requesting an Uptown appointment by pk gets 404; a `slot_token` minted for Downtown redeemed while the
  active location is Uptown returns `not_permitted`, not a cross-location booking; the status guard actually
  blocks edit/reschedule/cancel GET on a `completed` row (redirect, not a 200 with a live form)
- [ ] Sidebar shows `4.3` Live under Module 4, "Appointments" link resolves

## Close-out

- [ ] Review agents: `code-reviewer` → `explorer` → `frontend-reviewer` → `performance-reviewer` →
  `realtime-reviewer` (expected to find nothing — no realtime surface this pass, same as 4.2) →
  `qa-smoke-tester` → `security-reviewer` (confirm `reason`/`notes` PII discipline, confirm the slot-token
  payload never leaks a raw resource/provider id anywhere logged) → `test-writer`
- [ ] **UPDATE** `.claude/skills/scheduling/SKILL.md` — **do not re-author**. Flip the Build State table row
  for 4.3 to **BUILT**, add `Appointment` to Models (with the `PROTECT`/`SET_NULL`/`SET_NULL` on_delete
  contrast spelled out and the `booked_by_session` deferral noted), add the new routes, the new
  `templates/scheduling/bookings/` entries, document `apps/scheduling/services.py` and its four public
  functions as a new subsection, replace the "no realtime surface" line's forward-looking tool contract
  with the concrete `get_availability`/`book_appointment`/`reschedule_appointment`/`cancel_appointment`
  signatures under Tools & prompt surface, extend the seeder rows (both `seed_scheduling` AND the
  `provider_hours` addition to `seed_accounts`), and remove the now-resolved `test_views.py` TODO note
- [ ] README — note the new Appointments page only if the project README already enumerates 4.1/4.2's pages

## Later passes / deferred

Carried over verbatim from `research-scheduling-4.3.md`'s own Deferred section, plus this pass's own:

- `booked_by_session` FK — blocked on Module 5 (`calls.CallSession`) existing; additive migration then.
- A distributed/pessimistic slot-lock cache (Redis TTL lock) — `select_for_update()` inside
  `transaction.atomic()` is the right-sized equivalent for this single-DB deployment.
- A waitlist/re-offer-on-cancellation entity (NexHealth) — no entity in the ERD, not asked for.
- Per-service or per-location minimum-notice override field (Acuity) — `MIN_BOOKING_NOTICE_MINUTES` stays a
  flat module constant this pass; a real field is a well-scoped future addition, not an uncommitted guess.
- Cancellation-cutoff-window enforcement — the researched market leader (Calendly) does not enforce this
  server-side either; not invented here.
- `TenantNumbered`/`APPT-00001` numbering on `Appointment` — considered and rejected, not merely deferred:
  the ERD given for this sub-module carries no `number` field and no researched feature asks for one.
- Appointment list filters by provider/resource/service, and search-by-contact enrichment → **4.5 Bookings
  List & Callback Requests** (this pass ships only the CLAUDE.md-mandated baseline: `q`, `status`, date
  range).
- Day/week calendar grid, resource/provider column toggle, slot click-through, status colouring → **4.4
  Calendar Views** (a view sub-module — reads `Appointment`, ships no model).
- The actual LLM tool registration/dispatch wiring (the `apply_tool_call` branches, the tool-result
  envelope construction around `services.py`'s `(value, error)` tuples) → **Module 3.3**. 4.3 supplies the
  model + `services.py`; it registers no tool itself.
- `CallbackRequest` CRUD → **4.5**.

## Review notes

(filled in at the end)

## Review notes — 4.3 Availability & Booking

### Built

`scheduling.Appointment` + a new flat `availability.py` (slot search, opaque signed tokens, race-safe
booking, reschedule, cancel). Nine views, five templates, migration `0003`, 14 seeded appointments.
Verified **87/87** by `temp/verify_4_3.py`; the suite went 225 → **377 passing**.

### What the pre-code adversarial critique caught

Four things that would have shipped as production bugs, found BEFORE any code was written:

1. **A range lock over zero rows does not serialise.** `SELECT … FOR UPDATE` on a query matching no rows
   takes only *gap locks* in InnoDB, and gap locks are mutually compatible — both writers pass, both
   insert. Fixed by locking the concrete `Resource` / provider `User` row instead.
2. **Under REPEATABLE READ a plain re-check cannot see a concurrent commit** — it reads the transaction's
   pinned snapshot, reports "free", and double-books. The in-lock check must be `for_update=True`.
3. **`__date` is a production-only landmine.** It converts in the *active* timezone, not the location's,
   and on MySQL compiles to `CONVERT_TZ()`, which returns NULL without tz tables loaded — passing on
   SQLite in the test settings and silently returning zero rows in production.
4. **Timezone care was invisible.** Templates render in `settings.TIME_ZONE` (UTC), so all of it would have
   been for nothing until `ActiveLocationMiddleware` activated the location's zone.

### What the post-code review caught (all seven verified adversarially, all real)

1. `appointment_edit_view` had no `is_open` guard and `status` was postable — a direct POST could set
   `cancelled` with no `cancelled_at`, freeing the slot with no record, or reopen a completed booking.
2. `reschedule_appointment` / `cancel_appointment` never checked the appointment's own tenant/location.
   Safe through the views, unsafe for 3.3, which passes a MODEL-supplied `appointment_id` (Invariant 3).
3. `SlotError.code` emitted codes outside the set 3.3 can branch on. Now a closed frozenset, asserted.
4. **The manual booking path was pure check-then-act.** `save_or_report_conflict` cannot help: MySQL has
   no overlap constraint, so no `IntegrityError` can fire. Two receptionists both succeeded.
5. Suspended providers were still offered — in the search, the form dropdown and the list filter.
6. **"Find a new time" created a SECOND appointment.** The slot page hardcoded the book action, so
   `appointment_reschedule_view` and its route were dead code and the original booking stayed live.
7. **A 60-day search issued >9,000 queries / 37s** — one conflict query per resource per 15-minute
   candidate, each with its own aggregate. Now a single prefetched interval index: **4 queries.**

### Bug I introduced fixing #5, then fixed

Refusing a suspended pinned provider made `providers` empty, which fell through to the `[None]` branch —
so asking for a specific unavailable person returned slots *with no provider* instead of nothing. Caught
by the verify sweep.

### Decisions

* **`booked_by_session` deferred.** Django refuses a string FK to the uninstalled `calls` app. **Module 5
  must add it as an additive migration** and un-stub the detail page's originating-call panel.
* **`end_at` holds duration only.** The buffer extends what blocks the NEXT booking, never the rendered
  length.
* **`seed_accounts` changed** (another module's seeder, deliberately): every provider had
  `provider_hours = {}`, and unconfigured hours mean *unavailable*, so availability found nothing anywhere.
  `is_provider=True` with no hours is a broken state, not a neutral default.
* **`ActiveLocationMiddleware` now activates the location timezone** — a foundation change, justified
  because it implements a stated project invariant for every template at once.

### Environment note

The dev database holds a stray `acme-lakeview` location left by an earlier session's QA agent. Not seeder
output; `seed_tenants --flush` clears it.

---
# Sub-module 4.4 — Calendar Views (Module 4: Calendar & Bookings, `scheduling`) — plan from research-scheduling-4.4.md (2026-07-20)

## Shape: VIEW — zero new models, zero migrations

All four bullets (Day & Week Grid, By Resource and By Provider, Slot Click-Through, Status Colouring) read
`scheduling.Appointment`, built in 4.3, plus `scheduling.Resource`/`accounts.User` for column headers and
`scheduling.Contact` for block labels — all grep-verified to already exist. Inventing a `CalendarEvent` or
similar table here would be the exact bug the view branch exists to prevent. **Acceptance criterion:**
`venv\Scripts\python.exe manage.py makemigrations scheduling --check` must print "No changes detected."

## Models (NONE — view sub-module, zero models, zero migrations)

Tables READ: `scheduling.Appointment` (`start_at`/`end_at`/`status`/`contact`/`provider`/`resource`/
`service`, all tenant+location scoped), `scheduling.Resource` (by-resource column headers),
`accounts.User` (by-provider column headers, `is_provider`/`status=STATUS_ACTIVE`/`user_locations`),
`tenants.Location` (`.tzinfo`, `.local_now()`), `scheduling.Contact` (block label, already
`select_related` by the reused queryset). No FK is added to any of them.

## Backend (apps/scheduling/{views,urls}/CalendarViews/ — no models/ or forms/ folder, this pass adds neither)

- [ ] **Refactor first (CLAUDE.md Backend Package Structure rule 5):** `_location_appointments`,
  `_parse_local_date`, `_authorised_pk`, `_location_providers`, `_location_resources` currently live as
  "private" helpers inside `views/Bookings/Appointments.py`. 4.4 is a SECOND sub-module that needs all five,
  which is exactly the rule's trigger ("used by more than one sub-module go in `views/_helpers.py`").
  Move all five into `apps/scheduling/views/_helpers.py` (new file); `Bookings/Appointments.py` imports them
  from there instead of defining them (`from apps.scheduling.views._helpers import (...)`); no behaviour
  change, pure relocation. `_save_booking_under_lock` and `_bookable_services` stay in `Bookings/Appointments.py`
  — only 4.3's own create/edit path uses them.
- [ ] `apps/scheduling/views/CalendarViews/__init__.py` — empty, makes the package importable (matches
  `Bookings/__init__.py`'s pattern)
- [ ] `apps/scheduling/views/CalendarViews/Calendar.py` — `calendar_day_view(request)`,
  `calendar_week_view(request)`, both `@login_required` only (no tier gate — reading the calendar is
  front-desk work, same posture as list/detail across 4.1–4.3), plus module-private geometry helpers:
  `_visible_window(location, day, items)`, `_bucket_by_column(items, by, columns)`, `_lane_pack(items)`,
  `_hour_marks(window_start, window_end)`. Constants: `CALENDAR_WINDOW_START_HOUR = 7`,
  `CALENDAR_WINDOW_END_HOUR = 19`, `PX_PER_SLOT = 26` (matches the shipped `.calendar-slot { height: 26px }`),
  `PX_PER_MINUTE = PX_PER_SLOT / SLOT_GRANULARITY_MINUTES` (imported from `apps.scheduling.availability`,
  never a second hardcoded `15`).
- [ ] `apps/scheduling/urls/CalendarViews/__init__.py` — empty
- [ ] `apps/scheduling/urls/CalendarViews/Calendar.py` — `path('calendar/', calendar_day_view,
  name='calendar_day')`, `path('calendar/week/', calendar_week_view, name='calendar_week')`. Distinct
  `calendar/` prefix — checked against the whole concatenated `urls/__init__.py` list (contacts/, services/,
  resources/, appointments/ prefixes) and does not collide with any `<int:pk>` route.
- [ ] `urls/__init__.py` — import and concatenate `calendar_urlpatterns` (own section comment, "4.4 Calendar
  Views")
- [ ] `views/__init__.py` — import and re-export `calendar_day_view`, `calendar_week_view`
- [ ] `models/__init__.py`, `forms/__init__.py` — **untouched**, this pass adds neither layer
- [ ] `admin.py` — **N/A**, no new model to register
- [ ] **Additive change to the EXISTING `appointment_create_view`** (`views/Bookings/Appointments.py`) for
  slot click-through — see "Slot Click-Through wiring" below; this is a same-file edit, not a new view
- [ ] `apps/scheduling/tests/test_calendar_views.py`, `apps/scheduling/tests/test_calendar_security.py` —
  new test files (see Verify)
- [ ] Extend `seed_scheduling` idempotently (see Wire-up → Seeder below) — no migration implied

## Realtime & agent surface

**N/A — this sub-module has no realtime surface**, exactly like every prior `scheduling` sub-module (per
`.claude/skills/scheduling/SKILL.md`: "no `consumers/`, no `routing.py`, no `async def`"). It registers no
LLM tool, adds no prompt variable, calls no provider adapter, and appends nothing to
`calls.CallSession.usage` (`calls.CallSession` does not exist yet, and 4.4 makes no provider call regardless).

## Design decisions (from research, made concrete)

- [ ] **Two views, two URL names, not one `?view=day|week` view.** Day = many columns/one date; Week = one
  chosen column's whole week — different column semantics (resource/provider vs. day-of-week), different
  geometry, different templates. A single view branching its entire grid shape on a query param is more
  complex than two small views sharing helpers. `scheduling:calendar_day` (`/schedule/calendar/`) is the
  `LIVE_LINKS['4.4']` target; `scheduling:calendar_week` is reached only via an in-page link.
- [ ] **Date parsing/defaulting.** `?date=YYYY-MM-DD`, reuses `_parse_local_date` (now in `_helpers.py`),
  defaults to `request.location.local_now().date()` on missing/junk input — never the server's date. Day
  nav: `date ± 1 day`. Week nav: `week_start = date - timedelta(days=date.weekday())` (Monday-start);
  `date ± 7 days` moves the anchor. "Today" always recomputes from `location.local_now()`, so it is correct
  per-location even though Lakeside (Denver) and Riverside (LA) sit in different zones under the same tenant.
  All three nav links (prev/next/today) are built server-side as `?date=...&by=...&resource=...&provider=...`
  query strings that preserve every other active filter — a real Django `<a href>`, no JS required.
- [ ] **Column-mode toggle: `?by=resource|provider`, default `provider`** (staff already navigate by
  provider name elsewhere in this app; either default is defensible, this pass picks provider). Junk value
  degrades to the default. **The SAME base queryset serves both modes** — bucketed in Python by
  `.resource_id` or `.provider_id` after one identical DB fetch; the SQL `WHERE` clause never changes with
  `by`. This is the literal meaning of the bullet's "without changing the underlying query."
- [ ] **The exact query — Day view:** `_location_appointments(request)` (already
  `select_related('contact','service','resource','provider','location')`) filtered by
  `lo, hi = local_day_bounds_utc(location, date)` → `.filter(start_at__gte=lo, start_at__lt=hi)`. **ONE**
  query, hits `idx_appt_tenant_loc_start`. Plus `_location_providers(request)` and `_location_resources(request)`
  for the column headers (both fetched regardless of `by`, so the toolbar can offer a "switch mode" control
  without a second round trip) = **3 queries total** for the grid body, independent of appointment count.
- [ ] **The exact query — Week view:** `lo, _ = local_day_bounds_utc(location, week_start)`;
  `_, hi = local_day_bounds_utc(location, week_start + timedelta(days=6))`; **ONE** ranged query —
  `_location_appointments(request).filter(start_at__gte=lo, start_at__lt=hi, resource=chosen)` (or
  `provider=chosen`) — chained onto the SAME queryset, so the resource/provider narrowing costs nothing
  extra. Bucket into 7 day-columns in Python via `appointment.local_start().date()`. **This is 1 query, not
  a naive 7** — the research catalog's "chained 7× `local_day_bounds_utc` calls" phrasing describes computing
  7 day boundaries, not issuing 7 queries; only the week's overall `lo`/`hi` are needed for the single ranged
  filter. Plus the providers-or-resources lookup for authorising `?resource=`/`?provider=` = **≤3 queries
  total**, asserted with `assertNumQueries` in tests.
- [ ] **Block positioning arithmetic — computed in the view, never in the template** (theme.css's own comment:
  "Django templates cannot do arithmetic, and a filter chain that fakes it is how columns end up one row
  off"). Per rendered day: `window_start`/`window_end` default to `CALENDAR_WINDOW_START_HOUR`(7)/
  `CALENDAR_WINDOW_END_HOUR`(19) local, but **auto-expand** (floor/ceil to the hour) to cover the earliest
  `local_start()` / latest `local_end()` actually present that day across ALL columns — so the axis is
  shared by every column of the same day (rows line up) and **no appointment is ever clipped or silently
  hidden** for starting before 7am or ending after 7pm. Per item: `top_px = minutes since window_start ×
  PX_PER_MINUTE`, `height_px = max(duration_minutes, SLOT_GRANULARITY_MINUTES) × PX_PER_MINUTE` (a 15-min
  floor so no block ever renders as an invisible sliver). Template consumes these as
  `style="--slot-start:{{ item.top_px }}; --slot-span:{{ item.height_px }};"` — the **existing**
  `.calendar-event` CSS already reads exactly these two custom properties. Zero new CSS.
- [ ] **Hour labels + "now" line — reuse existing structure, no new CSS class.** The 68px gutter column in
  `.calendar-grid`'s own `grid-template-columns: 68px repeat(...)` is already sized for this. Hour labels are
  plain text `<div>`s inside a `.calendar-column`-classed gutter (existing `position: relative` is all that's
  needed), each with its own `top_px`. The "now" line renders only when `date == location.local_now().date()`,
  as one inline-styled 2px `<div>` per column (`position:absolute; inset-inline:0; top:{{ now_top_px }}px;
  border-top:2px solid var(--red-fg);`) — no `theme.css` change, since the styling is fully inline. Both are
  "common", not one of the four REQUIRED bullets — cut first if the pass overruns.
- [ ] **Overlap-safe lane layout — one shared function, used by every column in both views.** Sort a
  column's non-cancelled items by `start_at`; greedy interval-graph colouring assigns each item the first
  lane whose current end `≤` this item's `local_start()` (comparing against `local_end()`, the VISUAL end —
  not `blocks_until`, which is a booking-time concept, not a rendering one), else opens a new lane. Each item
  carries `(lane, lane_count)`; template turns that into inline `left`/`width` percentages layered inside the
  existing absolutely-positioned `.calendar-event` box — no new CSS class. `lane_count == 1` (the overwhelming
  majority of cells) computes to the same numbers as today's implicit full-width box, so the common case is
  visually unchanged. This is a defensive rendering rule (research: "common, not REQUIRED" — `Resource` has
  no capacity and the booking lock already prevents most same-column overlaps) for the genuine edge cases
  that remain: two provider-less+resource-less bookings sharing "Unassigned" at overlapping times, or a
  stale row after a manual DB edit.
- [ ] **Which appointments are excluded from the grid: NONE by status.** No default status filter — the
  researched leaders (Fresha, Acuity) keep cancelled/no-show visible for follow-up, and the sub-module's own
  4th bullet asks for status **colouring**, not status **filtering**. The only exclusion is the date/week
  range itself.
- [ ] **Cancelled must not look like it still occupies the grid (HARD FACT).** Cancelled appointments ARE
  rendered (never hidden) but are (a) **excluded from the lane-packing pass** — they no longer represent real
  occupancy once 4.3 frees the slot, so they must not force a live appointment into a needless side lane —
  and (b) rendered as a fixed one-slot-row (26px) low-emphasis marker anchored at `top_px` only, not spanning
  the original duration, with inline `pointer-events: none`, so a click anywhere in that freed time range
  still reaches the empty-slot click target underneath and opens a NEW booking there. `no_show` gets NO such
  treatment — it genuinely occupied that time and renders as a normal full block (amber), in the lane-packing
  pass, same as `completed`. This distinction is deliberate: only `cancelled` frees its slot (4.3's own
  contract); `no_show` does not.
- [ ] **The "Unassigned" catch-all column — Day view only, always rendered (even empty, even when
  `columns` itself is empty).** `Appointment.resource`/`.provider` are both nullable; a strict grouping would
  silently drop a phone-only or not-yet-assigned booking off the grid — a data-integrity bug, not cosmetic.
  Appended as the LAST column after every real resource/provider column. **Week view has no Unassigned
  column** — it is scoped to exactly one chosen resource/provider by design (Mindbody/Setmore finding), and
  an appointment with neither FK does not belong to any single person's/room's week diary; it stays visible
  on the Day view instead.

## Slot Click-Through wiring (edit to an existing view, not a new one)

- [ ] Each empty `.calendar-slot` cell (one per column per `SLOT_GRANULARITY_MINUTES`, matching the booking
  engine's own 15-min grain so the calendar and `find_available_slots` never disagree) is an `<a>` to:
  `{% url 'scheduling:appointment_create' %}?date={{ day|date:'Y-m-d' }}&time={{ slot_time|time:'H:i' }}
  &resource={{ column.resource_id|default:'' }}&provider={{ column.provider_id|default:'' }}` — `resource=`
  set only when `by == 'resource'` and the column is a real resource (never on the Unassigned column);
  `provider=` set only when `by == 'provider'` and the column is a real provider.
- [ ] `AppointmentForm` needs **NO code change** — verified by reading `TenantModelForm.__init__` /
  `TenantLocationModelForm.__init__`: both accept `**kwargs` and pass them straight through to
  `forms.ModelForm.__init__`, which already accepts stock `initial=`. The change is entirely in
  `appointment_create_view` (`views/Bookings/Appointments.py`): on GET (unbound form), build
  `initial = {}` from `request.GET` using `_parse_local_date` + a new small `_parse_local_time(raw)` helper
  (mirrors `_parse_local_date`: `datetime.strptime(raw, '%H:%M').time()`, degrades to `None` — stays local to
  `Bookings/Appointments.py`, used by one entity only) + `_authorised_pk` against `_location_resources`/
  `_location_providers`: `initial['start_at'] = f'{d:%Y-%m-%dT}{t:%H:%M}'` when both parse,
  `initial['resource'] = resource.pk` / `initial['provider'] = provider.pk` when authorised. Then
  `form = AppointmentForm(request.POST or None, request=request, initial=initial)`.
- [ ] Clicking an **existing** block navigates to `scheduling:appointment_detail` (unchanged) — never create.
  Prevents an accidental double-booking through the grid; moving a booking is the detail page's existing
  "Reschedule" button (4.3, already routes into slot-search-in-reschedule-mode).
- [ ] Race protection is inherited for free: the click-through still lands in `appointment_create_view`,
  which already calls `_save_booking_under_lock`. Zero new locking code.

## Status Colouring wiring

- [ ] `{% include "partials/_appointment_status_badge.html" with obj=item.appointment %}` inside each event
  block, unchanged, reused verbatim (single source of truth).
- [ ] Event block class: `class="calendar-event {{ item.appointment.status }}"` — reuses the **existing**
  `.calendar-event.scheduled/.confirmed/.completed/.cancelled/.no_show` CSS 1:1 with the badge partial. Zero
  new CSS.
- [ ] `templates/scheduling/calendar/_status_legend.html` — five static badge chips (`badge-info`/
  `badge-green`(×2)/`badge-red`/`badge-amber`) against their plain-English label, included once above the
  grid on both `day.html` and `week.html`. Static partial, no query.

## Wire-up

- [ ] `apps/accounts/navigation.py` → `LIVE_LINKS['4.4'] = {'Calendar': 'scheduling:calendar_day'}` — the
  week view is reached from within the day view (a "View full week" link per column header), not a second
  sidebar row, per the research's recommended build scope.
- [ ] `config/settings.py` / `config/urls.py` / `config/asgi.py` — **untouched**, `scheduling` is not a
  brand-new app this pass.
- [ ] **Seeder — extend `seed_scheduling.DEMO_APPOINTMENTS` idempotently, 3 new rows, no seeder-logic
  change:**
  1. **Uptown gets a `day_offset: 0` row** (it currently has none — offsets 1, 2 only, verified by direct
     read of the file): `('Dana', 'Whitfield')`, `'Orthodontic review'`, `'Surgery 1'`, `day_offset=0`,
     `09:30`. Without this, switching the active location to Uptown and opening `/schedule/calendar/`
     (which defaults to today) renders an EMPTY grid — the exact "looks broken to a new developer" failure
     the existing Downtown `day_offset: 0` comment already warns about, just uncovered for this location.
  2. **Lakeside gets a `day_offset: 0` row** (currently offsets 1, 4 only): `('Theo', 'Nakamura')`,
     `'Follow-up'`, `'Consult room A'`, `day_offset=0`, `10:30`. Same failure mode, same fix.
  3. **Downtown gets one genuinely overlapping row** to exercise the lane-packing code by default: a second
     `resource=None` booking at the SAME `day_offset=0, hour=11, minute=15` as the existing Priya Raman
     "Phone consultation" row — `('Marcus', 'Whitfield')`, `'Phone consultation'`, `resource=None`,
     `day_offset=0, hour=11, minute=15`, `status='scheduled'`. Identical start time guarantees a real overlap
     in the "Unassigned" column (`by=resource`, today), and the model's own contract — "a provider-less +
     resource-less booking never conflicts" — means the seeder's direct `.create()` needs no lock bypass.
  Idempotent via the existing `(location, contact, start_at)` dedupe check already in the loop — no new
  dedupe logic. Re-run `seed_scheduling` twice; the second run reports these 3 as already present.
  `seed_accounts` is untouched (no new provider needed — Uptown/Lakeside already have one from 4.3).

## Templates (templates/scheduling/calendar/ — standalone page, per Template Folder Structure rule 6)

- [ ] `templates/scheduling/calendar/day.html` — extends `base.html`; includes `_toolbar.html` and
  `_status_legend.html`; renders `.calendar-grid` with `style="--calendar-columns: {{ columns|length|add:1
  }};"` (real columns + 1 for Unassigned); one `.calendar-column` per resource/provider plus the trailing
  Unassigned column; hour-label gutter; "now" line when applicable; empty-slot `<a>` cells; `.calendar-event`
  blocks with inline lane/position styles, wrapped in an `<a>` to `appointment_detail`; empty-state
  (`partials/_empty_state.html`) when the location has zero appointments AND zero resources/providers for
  the active `by` mode.
- [ ] `templates/scheduling/calendar/week.html` — sibling standalone page; same toolbar + legend; 7 day
  columns (Mon–Sun) for the ONE chosen resource/provider (shown in the toolbar header, not per-column); a
  `<select>` to change which resource/provider the week is scoped to, submitting the same `?by=`/`?resource=`/
  `?provider=` query contract as the day view; empty-state when the location has zero resources/providers
  for the active `by` mode ("No providers/resources at this location yet").
- [ ] `templates/scheduling/calendar/_toolbar.html` — shared partial: today/prev/next `<a>` nav, an explicit
  `<input type="date">` `<form method="get">` (hidden inputs preserve `by`/`resource`/`provider` across
  submission, no JS required), the `by=resource|provider` toggle, and (week only) the resource/provider
  `<select>`.
- [ ] `templates/scheduling/calendar/_status_legend.html` — the five-chip legend (see Status Colouring above).
- [ ] No `form.html` this pass — click-through reuses 4.3's existing `bookings/appointment/form.html`
  unchanged.

## Verify

- [ ] `makemigrations scheduling --check` → **"No changes detected"** (the sub-module's own acceptance
  criterion — zero models, zero migrations)
- [ ] `seed_scheduling` ×2 — second run reports the 3 new appointment rows as already present, 0 duplicates
- [ ] `manage.py check` — no new issues
- [ ] `PROVIDER_MODE=fake` — asserted even though this sub-module makes no provider call (blanket policy,
  same as every prior `scheduling` sub-module)
- [ ] `pytest apps/scheduling` — `test_calendar_views.py`: `_visible_window` auto-expands for an out-of-range
  appointment and never clips it; `_bucket_by_column` puts a `resource=None`/`provider=None` appointment in
  Unassigned on Day and nowhere on Week; `_lane_pack` assigns two truly-overlapping items different lanes
  and two non-overlapping items the same lane (lane_count stays 1 for the common case); day/week route
  200s with a seeded record visible; `?date=` degrades a junk value to today; `?by=` degrades a junk value
  to the default; week `?resource=`/`?provider=` degrades an unauthorised pk to the first authorised column,
  not a 500; the click-through link on an empty Downtown 09:00 Monday slot produces
  `?date=...&time=09:00&resource=<Surgery 1 pk>` and `appointment_create_view` renders that value pre-filled
  in the `start_at`/`resource` fields (assert the rendered `<option selected>`/input value, not just a 200);
  a cancelled appointment's block carries no lane (excluded from `_lane_pack`) and its wrapper element has
  no click target over the freed time; `assertNumQueries` — day view ≤4 total scheduling queries, week view
  ≤4, never scaling with appointment count or with 7. `test_calendar_security.py`: cross-tenant — `admin_acme`
  requesting `?resource=<globex Resource pk>` gets "no filter applied" (not a 500, not a leak) and sees only
  `acme` rows; cross-location — a user assigned only to Downtown requesting `?resource=<Uptown Resource pk>`
  on the calendar gets the same silent-degrade, never an Uptown booking; a user with no active location gets
  the location-required redirect (mirrors `appointment_slots_view`'s own guard), not an unscoped
  `Appointment.objects.all()` grid.
- [ ] Twilio webhook signature + idempotency — **N/A**, this sub-module ships no webhook
- [ ] websocket connect/reject — **N/A**, this sub-module ships no consumer
- [ ] `temp/verify_4_4.py` smoke sweep as `admin_acme` (password `navai-demo-2026`, from `seed_accounts.py`):
  `calendar_day` 200 with today's 4 Downtown appointments visible incl. the new overlap pair both rendered
  (not one hidden behind the other); `?date=` for each seeded offset (-14, -7, +1..+4) 200 with the right
  contact name visible; `?by=resource` and `?by=provider` both 200, same total appointment count either way;
  `calendar_week?by=provider&provider=<pk>` 200, spans the right Mon–Sun dates; switch active location to
  Uptown → `calendar_day` (today) now shows the new seeded row, not an empty grid; same for Lakeside; the
  slot click-through link on an open cell round-trips into `appointment_create` with the prefilled value
  visible in the rendered form HTML; cross-tenant `?resource=<globex pk>` while on `acme` → silently ignored,
  never a `globex` row rendered; no `{#`/`{% comment` leaks; sidebar shows `4.4` Live under Module 4 with a
  working "Calendar" link.

## Close-out

- [ ] Review agents: `code-reviewer` → `explorer` → `frontend-reviewer` (badge/CSS class fidelity, the
  `--calendar-columns`/`--slot-start`/`--slot-span` custom-property contract) → `performance-reviewer`
  (confirm the ≤4-query budget holds and doesn't regress into a per-appointment query) → `realtime-reviewer`
  (expected to find nothing — no realtime surface, same as 4.1/4.2/4.3) → `qa-smoke-tester` →
  `security-reviewer` (confirm `notes`/`reason` PII discipline carries into the grid's rendered block text,
  confirm the `?resource=`/`?provider=` params can never leak a foreign tenant/location row) → `test-writer`
- [ ] **UPDATE** `.claude/skills/scheduling/SKILL.md` — do not re-author. Flip the Build State row for 4.4 to
  **BUILT**; add the "Calendar" section under Templates/Routes (`calendar_day`/`calendar_week`, no new
  model); document the `_helpers.py` relocation of the five shared query helpers (so a later 4.5 knows where
  to find them, not to redefine them a third time); note the `appointment_create_view` querystring-prefill
  addition; extend the Seeder section with the 3 new `DEMO_APPOINTMENTS` rows and why (Uptown/Lakeside
  today-emptiness, the Downtown overlap demo); add a Conventions & gotchas entry for the "cancelled
  appointments are excluded from lane-packing and rendered non-blocking" rule, since it is easy to "fix" by
  a future editor who doesn't know why.
- [ ] README — note the new Calendar page only if the project README already enumerates 4.1–4.3's pages

## Later passes / deferred

Carried over verbatim from `research-scheduling-4.4.md`'s own Deferred section:

- Full N-lane overlap-packing algorithm (Google Calendar's general case) — the simple two-events-side-by-side
  rule (implemented this pass as a general greedy packer, which happens to also cover N>2) is enough; a
  dedicated N-lane packer library is more machinery than this app's realistic overlap rate justifies.
- Configurable colour source (team member / category / status), à la Fresha — one status-based colour map is
  the sub-module's own bullet; configurability would fork the single source of truth for no requested benefit.
- "Combined" all-staff overlay view (Square) — sits awkwardly against the bullet's explicit "switch the
  grid's COLUMNS between resources and providers," which wants columns, not an overlay.
- Month view — not named by either "Day & Week" bullet; a 30-day grid's information density is a materially
  different UI problem, scope on its own if ever requested.
- Printable/exportable day sheet (Jane App) — real precedent exists in this project
  (`calls/transcript/transcript_print.html`, once Module 5 lands), but not named by any of 4.4's bullets.
- Per-status "hide cancelled/no-show" toggle — the bullets want status **coloured**, not filtered out; the
  full-day picture stays intact by default, matching Fresha/Acuity's own research finding.
- Drag-and-drop rescheduling directly on the grid — only "Slot Click-Through" is named by the bullets; the
  existing detail-page "Reschedule" button already covers moving a booking. Real differentiator in Square/
  Fresha/Google Calendar, but adds JS/HTMX complexity beyond this pass's scope.
- External calendar sync (Google/Outlook two-way) — this product's calendar **is** `scheduling.Appointment`;
  there is no second calendar to reconcile against. Google Calendar was used only as a layout-mechanics
  reference in the research, never as an integration target.
- `booked_by_session` / "originating call" link on a grid block — blocked on Module 5 (`calls.CallSession`)
  existing, same deferral already recorded against 4.3.
- Appointment list with full filter set, contact search, `CallbackRequest` queue → **4.5 Bookings List &
  Callback Requests** (unchanged from 4.3's own deferred list — 4.4 is the grid, not a second list page).

## Review notes

(filled in at the end)

## Review notes — 4.4 Calendar Views

### Built

A **VIEW sub-module**: zero models, **zero migrations** (`makemigrations scheduling --check` →
"No changes detected"). Two views (`calendar_day`, `calendar_week`), three templates, two `theme.css`
rules, shared helpers promoted to `views/_helpers.py`. Verified 76/76 by `temp/verify_4_4.py`, rendered
and measured in a real browser, and the suite went 377 → **424 passing**.

### The bug only the browser could find

`temp/verify_4_4.py` was **76/76 green while every clickable slot had zero height.** Empty slots are `<a>`
elements, and `height` does not apply to a non-replaced inline element — so the grid's rows and the entire
click-to-book surface were invisible. The page returned 200, the context assertions passed, and the
appointment blocks even positioned correctly. Fixed with `display: block` on `.calendar-slot`.

**Lesson: for anything visual, assertions prove behaviour, not appearance. Look at it.**

### What the pre-code critique caught

* **The sticky column head is still IN FLOW**, so events positioned against `.calendar-column` land one
  head-height above their gridline — and the offset varies with font size and zoom, so no constant fixes
  it. Hence `.calendar-column-body`.
* **A float in a CSS custom property renders as `112,666`** under a non-English locale, invalidating the
  `calc()` and snapping every block to `top: 0`. Every value is an `int`.
* **`?date=9999-12-31` was an uncaught `OverflowError` 500** via `local_day_bounds_utc`'s
  `day + timedelta(days=1)` — and it already reached 4.3's `?from=`/`?to=`. `parse_local_date` now clamps.
* **Column membership, not FK null-ness**: a booking on a deactivated resource has a non-null FK and no
  column, and would have vanished from the grid entirely.
* **`no_show` frees its slot** (it is not in `BLOCKING_STATUSES`), so it must not occupy grid time.

### What the post-code review caught

* The week header counted all statuses while the grid painted only live ones — and unlike the day view it
  has no freed-bookings table to explain the gap.
* `bookable_resources as _location_resources` made one name mean two opposite things in the same app:
  4.2's own `_location_resources` deliberately does NOT filter `is_active`. Aliases dropped.
* `.calendar-event.confirmed` and `.completed` were byte-identical green — the only two statuses a live
  grid normally shows, with colour as their sole carrier. `completed` is now muted.
* Status reached screen readers nowhere: colour only, and `title` is dropped from the accessible name once
  an anchor has text content. Every event now carries an `aria-label`.

### Verified geometry (measured in-browser at 1280×800)

09:30 → `top: 156px` (90 min × 26/15) · 14:30 → 676 · 30/60/15-min → 52/104/26px ·
40 slots × 26 = 1040px column body · the 09:30 block sits exactly on the 09:30 row ·
week is Monday-anchored with exactly one now-line.

### Note

The dev Daphne on :8000 predates these changes and does not auto-reload — **restart it to see 4.4**. A
second launch entry on :8001 was added so a preview can run without colliding with it.

---
# Sub-module 4.5 — Bookings List & Callback Requests (Module 4: Calendar & Bookings, `scheduling`) — plan from research-scheduling-4.5.md (2026-07-21)

## Shape: CRUD — one new model, plus a small enrichment of an already-built surface

`CallbackRequest` is the one genuinely new tenant+location-scoped domain table this pass introduces — the
CRUD test ("does this sub-module's data already exist?") fails for it, so it gets full list/create/detail/
edit/delete. The Booking List and Appointment Detail bullets, by contrast, are **already built in 4.3**
(`appointment_list_view`'s full filter set, `bookings/appointment/detail.html`'s contact/service/resource/
notes panel) — re-verified by direct read of `apps/scheduling/views/Bookings/Appointments.py` and
`templates/scheduling/bookings/appointment/{list,detail}.html` before writing this plan. Their only honest gap
(no one-click status transition, no quick date-range presets) is a small, secondary enrichment of the
EXISTING `Appointment` views/templates — not a second model and not a rebuild.

## Models (from research — 1 new model, within the 1–3 ceiling)

- [ ] **`scheduling.CallbackRequest`** — tenant **AND** location-scoped (`TenantLocationOwned`, confirmed in
  advance by `apps/scheduling/models/_base.py`'s own docstring, which already names this model alongside
  `Resource` and `Appointment`). Verified FK targets: `tenants.Tenant`/`tenants.Location` (via the base),
  `scheduling.Contact` (`apps/scheduling/models/ContactDirectory/Contacts.py`, grep-confirmed). Fields, per
  ERD lines 293-305 and the research's build scope, each tied to a specific researched feature:
  - `contact` — FK `scheduling.Contact`, **`null=True, blank=True`, `on_delete=models.SET_NULL`** — a
    deliberate CONTRAST with `Appointment.contact`'s `PROTECT`: a callback is a transient operational queue
    item, not permanent booking history, so it must survive a contact's removal rather than block it
    (research: "Beyond the bullets"). Drives: Callback Request Queue's "an unidentified caller" case
    (Invariant 1 — never a second identity table; an identified caller gets `contact` set from server state,
    an unknown one leaves it null).
  - `caller_name` — `CharField(max_length=255, blank=True)` — Callback Request Queue ("name ... captured even
    for an unidentified caller").
  - `caller_phone` — `CharField(max_length=32, blank=True)` — Callback Request Queue ("phone ... captured"),
    the confirmed callback number; drives the Rosie-style `tel:` tap-to-call link in the templates.
  - `reason` — `TextField(blank=True)` — Callback Request Queue ("reason").
  - `status` — `CharField(max_length=16, choices=STATUS_CHOICES, default='pending', db_index=True)`,
    `STATUS_CHOICES = [('pending','Pending'), ('contacted','Contacted'), ('closed','Closed')]` — Callback
    Request Queue + Callback Resolution bullets ("a `pending`/`contacted`/`closed` status").
  - `source` — `CharField(max_length=32, choices=SOURCE_CHOICES, default='ai_phone')`,
    `SOURCE_CHOICES = [('ai_phone','AI phone call'), ('manual','Added manually'), ('web','Web')]` — mirrors
    `Contact.source`/`Appointment.source`'s established three-choice pattern (research: "Beyond the bullets" —
    the field this model must carry so Module 3.4's documented transfer-fallback write and the future
    `request_callback` tool have something to stamp). **Server-stamped only, never a form field** — same
    prompt-injection discipline as `Appointment.source`.
  - `notes` — `TextField(blank=True)` — Callback Resolution ("Close with notes").
  - `Meta.indexes = [models.Index(fields=['tenant', 'location', 'status'], name='idx_callback_tenant_loc_status')]`;
    `Meta.ordering = ['-created_at']` — both per ERD lines 301/305 verbatim.
  - **No FK to `calls.CallSession`.** `apps/calls` does not exist, and Django refuses to migrate a relation to
    an uninstalled app (the exact failure documented in `Appointment`'s own `booked_by_session` docstring).
    Re-checked the ERD's `CallbackRequest` section itself (lines 293-305): unlike `Appointment`, it specifies
    **no session FK at all** — there is nothing to omit-and-document beyond following the same project-wide
    discipline; no placeholder integer column either way.
  - **Form excludes:** `tenant`, `location` (stamped by `TenantLocationModelForm` from `request.tenant`/
    `request.location`, never posted), `source` (server-stamped — `SOURCE_MANUAL` on staff creation through
    this CRUD, exactly like `appointment_create_view` re-stamping `Appointment.source`), `created_at`/
    `updated_at` (inherited `TimeStamped`).
  - **PII discipline (compliance section of the research):** `caller_phone` and `reason` get the same
    treatment as `Contact.notes`/`Appointment.reason` — rendered with `|linebreaksbr`, never `|safe`; never
    logged at INFO (every log line in the views below carries `pk`/`tenant_id`/`user_id` only).

## Backend (apps/scheduling/{models,forms,views,urls}/CallbackRequests/ — new sub-module folder)

- [ ] `apps/scheduling/models/CallbackRequests/__init__.py` — empty, makes the package importable.
- [ ] `apps/scheduling/models/CallbackRequests/CallbackRequests.py` — the `CallbackRequest` class as specified
  above, `from apps.scheduling.models._base import *`, `__all__ = ['CallbackRequest']`.
- [ ] `apps/scheduling/models/__init__.py` — add `from apps.scheduling.models.CallbackRequests.CallbackRequests
  import CallbackRequest`; append `'CallbackRequest'` to `__all__`; extend the module docstring's sub-module
  list with `* CallbackRequests/ — 4.5  CallbackRequest`.
- [ ] `apps/scheduling/forms/CallbackRequests/__init__.py` — empty.
- [ ] `apps/scheduling/forms/CallbackRequests/CallbackRequests.py` — two forms:
  - `CallbackRequestForm(TenantLocationModelForm)` — `tenant_scoped_fields = ('contact',)`;
    `Meta.fields = ('contact', 'caller_name', 'caller_phone', 'reason', 'status', 'notes')`; `reason`/`notes`
    as `Textarea(rows=3)`; `contact` `required=False`; `__init__` further narrows the `contact` queryset to
    `Contact.objects.filter(tenant=self.tenant, anonymized_at__isnull=True)` — the same "an erased contact must
    not be re-attachable" rule `AppointmentForm.__init__` already enforces. No status restriction here (the
    research's "no rigid linear state machine" point — the general form permits any of the three values, same
    posture as `AppointmentForm` permitting any of its non-cancelled statuses through one form).
  - `CallbackResolveForm(forms.ModelForm)` — `Meta.model = CallbackRequest`, `Meta.fields = ('status', 'notes')`
    — the dedicated Callback Resolution action, structurally identical in spirit to `AppointmentCancelForm`
    (a small, purpose-built form for one transition, not the general CRUD form). `__init__` restricts
    `self.fields['status'].choices` to `[(CallbackRequest.STATUS_CONTACTED, 'Contacted'),
    (CallbackRequest.STATUS_CLOSED, 'Closed')]` — resolving never regresses a callback back to `pending`;
    that correction path is the general edit form.
- [ ] `apps/scheduling/forms/__init__.py` — add
  `from apps.scheduling.forms.CallbackRequests.CallbackRequests import (CallbackRequestForm, CallbackResolveForm)`;
  append both names to `__all__`.
- [ ] `apps/scheduling/views/CallbackRequests/__init__.py` — empty.
- [ ] `apps/scheduling/views/CallbackRequests/CallbackRequests.py` — `_location_callbacks(request)` (an
  entity-local helper, per Backend Package Structure rule 5 — only this file uses it, so it stays here rather
  than in `views/_helpers.py`): returns `CallbackRequest.objects.none()` when `request.location is None`, else
  `CallbackRequest.objects.filter(tenant=request.tenant, location=request.location).select_related('contact', 'location')`.
  Views, all `@login_required`:
  - `callbackrequest_list_view` — search `q` (`Q()` across `caller_name`, `caller_phone`, `reason`,
    `contact__first_name`, `contact__last_name`, `contact__phone_e164`); status defaults to `pending` **unless
    the querystring explicitly overrides it** (research: "the queue defaults to `pending`, not a full
    history") — `if 'status' in request.GET: status = request.GET['status'].strip()` (empty string means
    "all") `else: status = CallbackRequest.STATUS_PENDING`; apply `.filter(status=status)` only when `status`
    is truthy and a valid choice — a junk value degrades to "all", never raises (Filter Implementation Rules).
    Context passes `status_choices=CallbackRequest.STATUS_CHOICES` and `default_status='pending'` so the
    filter bar can preselect Pending.
  - `callbackrequest_detail_view` — `obj` via `get_object_or_404(_location_callbacks(request), pk=pk)`, plus
    `resolve_form=CallbackResolveForm(instance=obj)`.
  - `callbackrequest_create_view` — `CallbackRequestForm(request.POST or None, request=request)`; on success,
    stamp `obj.source = CallbackRequest.SOURCE_MANUAL` if it isn't already (mirrors
    `appointment_create_view`'s own re-stamp); `logger.info` with `pk`/`tenant_id`/`user_id` only; redirect to
    detail.
  - `callbackrequest_edit_view` — same form bound to the instance; no closed-state guard (the research's
    "no rigid linear state machine" point applies to editing too — a queue item stays correctable at any
    status, unlike a closed-out `Appointment`, which is a record of what already happened).
  - `callbackrequest_delete_view` — `@tier_required(*MANAGEMENT_TIERS)`, `@require_POST` — outright delete;
    `CallbackRequest` has no PROTECT-guarded children, so there is no `ProtectedError` branch to handle.
    Redirect to list.
  - `callbackrequest_resolve_view` — `@require_POST` — `CallbackResolveForm(request.POST, instance=obj)`;
    on success, `messages.success`; redirect via
    `safe_redirect_target(request, default=reverse('scheduling:callbackrequest_detail', args=[obj.pk]))` so
    both the list row's quick-resolve form and the detail page's resolve card return the user to where they
    were (a hidden `next` input carries `request.get_full_path` from whichever page posted).
- [ ] `apps/scheduling/views/__init__.py` — add the six `callbackrequest_*_view` imports and `__all__` entries.
- [ ] `apps/scheduling/urls/CallbackRequests/__init__.py` — empty.
- [ ] `apps/scheduling/urls/CallbackRequests/CallbackRequests.py` — `callbacks/` prefix (distinct from
  `contacts/`, `services/`, `resources/`, `appointments/`, `calendar/` — checked against the whole
  concatenated list): `callbacks/` (list), `callbacks/create/` (create) — literals — then
  `callbacks/<int:pk>/` (detail), `callbacks/<int:pk>/edit/` (edit), `callbacks/<int:pk>/resolve/` (resolve),
  `callbacks/<int:pk>/delete/` (delete).
- [ ] `apps/scheduling/urls/__init__.py` — import `urlpatterns as callback_request_urlpatterns` and
  `urlpatterns += callback_request_urlpatterns` under a new `# -- 4.5 Bookings List & Callback Requests --`
  comment section, after the existing 4.4 block.
- [ ] `apps/scheduling/admin.py` — register `CallbackRequestAdmin`: `list_display = ('status', 'location',
  'tenant', 'contact', 'caller_name', 'caller_phone', 'source', 'created_at')`, `list_filter = ('status',
  'source', 'tenant', 'location')`, `search_fields = ('caller_name', 'caller_phone', 'reason',
  'contact__first_name', 'contact__last_name')`, `list_select_related = ('tenant', 'location', 'contact')`,
  `ordering = ('-created_at',)`, `readonly_fields = ('created_at', 'updated_at')`.
- [ ] `makemigrations scheduling` → new migration (next in sequence after `0003_appointment.py`) adding
  `CallbackRequest` only — no changes to any other model.
- [ ] Extend `seed_scheduling.py` idempotently (see Wire-up → Seeder below) — same command, no new file, per
  the Seed Command Rules.

## `Contact.anonymize()` erasure-cascade fix (edit to an EXISTING file, this sub-module's own exposure)

- [ ] **`apps/scheduling/models/ContactDirectory/Contacts.py` — `Contact.anonymize()`.** The research's own
  Compliance section flags a genuine gap this sub-module CREATES: `CallbackRequest.contact` is `SET_NULL`, so
  `Contact.anonymize()` blanking a contact's own fields leaves any linked `CallbackRequest` row's free-text
  `caller_name`/`caller_phone` untouched — PII that is independent of the `Contact` row and survives an
  erasure request. Fix it in this pass, since 4.5 is what creates the exposure:
  - Add a private step called at the end of `anonymize()`, after the existing `self.save(update_fields=[...])`:
    `self._scrub_linked_callback_requests()`.
  - `_scrub_linked_callback_requests(self)` — local import `from apps.scheduling.models import CallbackRequest`
    (avoids a module-level circular import, matching the lazy-import pattern already used by
    `views/ContactDirectory/Contacts.py::_appointments_for`); `CallbackRequest.objects.filter(contact=self,
    tenant_id=self.tenant_id).update(caller_name='', caller_phone='', updated_at=timezone.now())` — `timezone`
    is already imported at module level (used by the existing `self.anonymized_at = timezone.now()` line), so
    no new import. **`reason` and `notes` are deliberately left untouched** — they are the callback's
    operational message, not caller identity, and scrubbing them would erase the queue's own working record of
    what the callback was about; this mirrors the research's own scope boundary ("not solved this pass because
    4.1 didn't build a cross-app erasure cascade either... but the gap should be visible" — now it's visible
    AND fixed for the two fields the research specifically names).
  - Update the method's docstring to note the cascade and why `reason`/`notes` are excluded from it.
  - Idempotent by construction: re-running `anonymize()` on an already-anonymized contact returns early before
    reaching the cascade (existing `if self.anonymized_at: return self` guard), and re-running the cascade
    itself against already-blank fields is harmless.

## Appointment enrichment (secondary — edits to EXISTING 4.3 files, not a new model)

- [ ] **One-click Mark Completed / Mark No-show.** `apps/scheduling/views/Bookings/Appointments.py` —
  new `appointment_mark_view(request, pk, new_status)`, `@login_required` + `@require_POST` (no tier gate —
  same posture as `appointment_edit_view`). `obj = get_object_or_404(location_appointments(request), pk=pk)`;
  reject any `new_status` not in `{Appointment.STATUS_COMPLETED, Appointment.STATUS_NO_SHOW}` (never
  `cancelled`, which keeps its own reasoned `appointment_cancel_view` flow); reject (with a message) when
  `not obj.is_open`; on success set `obj.status = new_status`, `obj.save(update_fields=['status', 'updated_at'])`,
  log `appointment_id`/`new_status`/`user_id` only, then
  `redirect(safe_redirect_target(request, default=reverse('scheduling:appointment_detail', args=[obj.pk])))` —
  `safe_redirect_target` and `reverse` are already available via the existing
  `from apps.scheduling.views._common import *` wildcard import, so no new import.
  `apps/scheduling/urls/Bookings/Appointments.py` — add
  `path('appointments/<int:pk>/mark/<str:new_status>/', views.appointment_mark_view, name='appointment_mark')`
  as a member route (checked against the whole concatenated `urls/__init__.py` list — the `mark/` literal
  segment is unique, so no ordering conflict with `edit/`, `delete/`, `reschedule/` or `cancel/`).
  `apps/scheduling/views/__init__.py` — add `appointment_mark_view` to the import + `__all__`.
- [ ] **Quick date-range presets (Today / This week / Upcoming).** `appointment_list_view` — when
  `request.location` is set, compute `today_local = request.location.local_now().date()`,
  `week_start = today_local - timedelta(days=today_local.weekday())`, `week_end = week_start + timedelta(days=6)`;
  pass `quick_ranges = {'today': f'?from={today_local:%Y-%m-%d}&to={today_local:%Y-%m-%d}', 'week':
  f'?from={week_start:%Y-%m-%d}&to={week_end:%Y-%m-%d}', 'upcoming': f'?from={today_local:%Y-%m-%d}'}` in
  context (`None` when no active location). Pure view/template sugar over the already-existing `?from=`/`?to=`/
  `local_day_bounds_utc` machinery — no model, no new query.

## Realtime & agent surface

**N/A this pass for its own write path** — exactly like every prior `scheduling` sub-module, 4.5 registers no
LLM tool, adds no consumer, calls no provider adapter, and appends nothing to `calls.CallSession.usage`
(`calls.CallSession` does not exist yet). It ships **the write target only**:
- [ ] Document (in the model's own docstring) that `CallbackRequest` is the write target of a future
  `request_callback(reason, caller_name?, caller_phone?)` tool (Module 3.3, not built) and of the documented
  off-hours/no-answer transfer-fallback write (Module 3.4, already committed elsewhere in the catalog) —
  `tenant_id`/`location_id`/`contact_id` (when known) would come from server session state in both cases,
  never a model argument, exactly mirroring how 4.3 supplies `Appointment` as `book_appointment`'s write target
  without registering a tool itself. Nothing to trace through "both runtime paths" yet — there is no tool to
  trace, only the model shape it will need.

## Wire-up

- [ ] `apps/accounts/navigation.py` → `LIVE_LINKS['4.5'] = {'Callback Requests': 'scheduling:callbackrequest_list'}`
  — the one new entry this pass adds; every other key untouched.
- [ ] `config/settings.py` / `config/urls.py` / `config/asgi.py` — **untouched**, `scheduling` is not a
  brand-new app this pass.
- [ ] **Seeder — extend `seed_scheduling.py` idempotently, new `DEMO_CALLBACK_REQUESTS` dict keyed by location
  slug, covering ALL FOUR demo locations (Seed Command Rule 6 — "seed at least two locations per tenant"; this
  sub-module does both tenants):**
  - `downtown` (3 rows): one linked to the existing `('Dana', 'Whitfield')` contact, `status='pending'`,
    `source='ai_phone'`, `reason='Called after hours asking about Saturday availability'`; one unidentified
    caller, `contact=None`, `caller_phone='+13125550777'`, `status='contacted'`, `source='ai_phone'`,
    `notes='Called back, offered 9am Tuesday — waiting for confirmation.'`; one linked to
    `('Owen', 'Baptiste')`, `status='closed'`, `source='manual'`, `notes='Emailed price list, resolved.'`.
  - `uptown` (2 rows): one unidentified caller, `caller_name='Grace'`, `caller_phone='+17735550199'`,
    `status='pending'`, `source='ai_phone'`, `reason='Asked to be transferred to billing, transfer failed'`;
    one linked to `('Dana', 'Whitfield')` (proves a business-wide contact can have a callback logged at a
    DIFFERENT site than their usual one), `status='closed'`, `source='web'`.
  - `riverside` (2 rows): one linked to `('Helena', 'Ostrom')`, `status='pending'`, `source='ai_phone'`; one
    unidentified caller, `caller_phone='+15035550444'`, `status='pending'`, `source='ai_phone'`,
    `reason='Hung up before giving details'`.
  - `lakeside` (2 rows): one linked to `('Theo', 'Nakamura')`, `status='contacted'`, `source='ai_phone'`,
    `notes='Left voicemail, awaiting response.'`; one unidentified caller, `status='closed'`,
    `source='ai_phone'`, `reason='No-answer transfer fallback triggered after hours'`,
    `notes='Called back next morning, resolved directly.'`.
  - Dedupe key (idempotent, Seed Command Rule 1): `CallbackRequest.objects.filter(tenant=tenant,
    location=location, caller_phone=spec.get('caller_phone', ''), reason=spec['reason']).exists()` — skip if
    already present. New `Command._seed_callback_requests(self, tenants)` method, called from `handle()` after
    `self._seed_appointments(tenants)`; contacts resolved by the same `(tenant, first_name, last_name)` lookup
    `_seed_appointments` already uses. Update the module docstring's "Sub-modules seeded so far" list to add
    `* 4.5  CallbackRequest — a queue per location spanning all three statuses, identified and unidentified
    callers, and mixed source values.` Print-instructions block gets one new line noting callback requests are
    location-scoped like appointments.

## Templates (templates/scheduling/callbacks/callbackrequest/ — new sub-module + entity folder)

- [ ] `templates/scheduling/callbacks/callbackrequest/list.html` — extends `base.html`; page header + "Log a
  callback" primary action to `callbackrequest_create`; includes `_filters.html`; table columns: Logged
  (`created_at`), Caller (contact link + display name, or `caller_name`/"Unidentified caller" with a `tel:`
  link on `caller_phone` when present — Rosie's tap-to-call pattern), Reason (truncated, `|linebreaksbr`),
  Status (`pending`→`badge-amber`, `contacted`→`badge-info`, `closed`→`badge-green`, else `{% else %}` fallback
  to `{{ obj.get_status_display }}` per the Filter Implementation Rules), Source (mirrors Contact/Appointment's
  own three-value badge pattern), Actions (view/edit/delete-POST+confirm+csrf, all guarded by
  `request.user.tier == 'owner' or 'manager'` for delete only); empty-state via `partials/_empty_state.html`
  when none match, distinguishing "no location chosen" from "no callbacks match the filter" exactly like
  `bookings/appointment/list.html` does.
- [ ] `templates/scheduling/callbacks/callbackrequest/_filters.html` — `q` search input + `status` `<select>`
  preselected to `default_status` (`==` string comparison, per Filter Implementation Rules) with an explicit
  "All" option (`value=""`) so a user can see the full history, not just the pending queue; Reset link.
- [ ] `templates/scheduling/callbacks/callbackrequest/detail.html` — Details card (contact link or
  "Unidentified caller", `caller_name`, `tel:` link on `caller_phone`, `reason|linebreaksbr`, status/source
  badges); a "Resolve this callback" card rendering `resolve_form` (status choice limited to
  Contacted/Closed + notes textarea) posting to `callbackrequest_resolve` with a hidden
  `<input type="hidden" name="next" value="{{ request.get_full_path }}">`; Actions sidebar (Edit / Delete-POST
  +confirm+csrf, tier-gated / Back to callbacks); Record card (`created_at`/`updated_at`); `notes|linebreaksbr`.
- [ ] `templates/scheduling/callbacks/callbackrequest/form.html` — one template for create/edit, mirrors
  `directory/contact/form.html`'s two-column layout; sidebar note explaining `source` and `tenant`/`location`
  are not shown because they are server-stamped, same convention as the contact form's own sidebar copy.

## Templates — Appointment enrichment (edits to EXISTING files, not new templates)

- [ ] `templates/scheduling/bookings/appointment/list.html` — add a small quick-range button row (Today /
  This week / Upcoming, from `quick_ranges`) above the existing `_filters.html` include; add two inline
  one-button POST forms in the Actions column, guarded `{% if a.is_open %}`, posting to
  `appointment_mark a.pk 'completed'` / `appointment_mark a.pk 'no_show'` with a hidden `next` input carrying
  `request.get_full_path`.
- [ ] `templates/scheduling/bookings/appointment/detail.html` — add the same two Mark buttons to the Actions
  sidebar, guarded `{% if obj.is_open %}`, alongside the existing Edit/Find-a-new-time actions.

## Verify

- [ ] `makemigrations scheduling` → one new migration adding only `CallbackRequest` (verify no unrelated diff
  on `Appointment`/`Resource`/`Service`/`Contact`); `migrate`.
- [ ] `seed_scheduling` ×2 — second run reports every new `CallbackRequest` row as already present (idempotent
  per the `(tenant, location, caller_phone, reason)` dedupe key), 0 duplicates.
- [ ] `manage.py check` — no new issues.
- [ ] `PROVIDER_MODE=fake` asserted — this sub-module makes no provider call either (same blanket policy as
  every prior `scheduling` sub-module).
- [ ] `pytest apps/scheduling` — new files:
  - `test_callback_models.py` — `STATUS_CHOICES` default is `pending`; `contact` `SET_NULL` proved through a
    real delete (unlike `Appointment.contact`'s `PROTECT`); `Contact.anonymize()` blanks `caller_name`/
    `caller_phone` on a linked `CallbackRequest` but leaves `reason`/`notes` untouched; a `CallbackRequest`
    with `contact=None` is unaffected by anonymizing an unrelated contact; ordering is `-created_at`.
  - `test_callback_forms.py` — `CallbackRequestForm` excludes `tenant`/`location`/`source` from rendered
    fields; `contact` queryset excludes an anonymized contact and a different tenant's contact;
    `CallbackResolveForm`'s `status` field never offers `pending` as a choice.
  - `test_callback_views.py` — list defaults to `pending` when `?status=` is absent, shows all three statuses
    when `?status=` is present-but-empty, degrades a junk `?status=` to "all" not a 500; search matches on
    `caller_name`, `caller_phone` and `reason`; create/edit/delete/resolve round-trip; resolve rejects
    `pending` as a posted status value; a location with zero callbacks renders the correct empty-state
    variant.
  - `test_callback_security.py` — cross-tenant `admin_acme` cannot reach a `globex` `CallbackRequest` (404 on
    detail/edit/delete/resolve); cross-location — a user assigned only to Downtown gets 404 on an Uptown
    callback's detail/edit/delete/resolve; delete is refused (redirect + message, not a 403 crash) for a
    non-management tier.
  - Extend `test_booking_views.py` / `test_booking_security.py` — `appointment_mark_view` accepts only
    `completed`/`no_show` (a posted `cancelled` or junk value is refused, not silently applied); refuses a
    closed appointment; cross-tenant/cross-location `appointment_mark` on another tenant's/location's booking
    is 404; quick-range links produce the exact `?from=`/`?to=` pair `local_day_bounds_utc` already covers
    (assert against the existing filter test fixtures, no new query path).
- [ ] Twilio webhook signature + idempotency — **N/A**, this sub-module ships no webhook.
- [ ] websocket connect/reject — **N/A**, this sub-module ships no consumer.
- [ ] `temp/verify_4_5.py` smoke sweep as `admin_acme` (password from `seed_accounts.py`, printed at the end of
  the seed run): `callbackrequest_list` 200, defaults to Pending, shows the seeded Downtown/Uptown rows; toggle
  `?status=` to see `closed`/`contacted` rows; `callbackrequest_detail` 200 with contact link or "Unidentified
  caller" rendered correctly for both seeded shapes; resolve a `pending` row to `closed` with notes, confirm
  the list under the default Pending filter no longer shows it; create/edit/delete round-trip; cross-tenant
  `globex` callback pk → 404; switch location to Uptown → sees Uptown's rows, not Downtown's; on the
  appointments list, click Mark Completed on an open Downtown booking → status flips, redirected back to the
  list with query string preserved; Mark No-show on an already-completed booking → refused with a message;
  Today/This week/Upcoming quick-range links each 200 with the expected subset of appointments; no `{#`/
  `{% comment` leaks; sidebar shows `4.5` Live under Module 4 with a working "Callback Requests" link.

## Close-out

- [ ] Review agents, in order: `code-reviewer` → `explorer` → `frontend-reviewer` (badge-class fidelity —
  `pending`/`contacted`/`closed` are NOT the canonical call-status map, confirm no accidental reuse of
  `_appointment_status_badge.html`; confirm the `tel:` link and `_filters.html` pattern match 4.1's contact
  directory) → `performance-reviewer` (confirm the list view stays at a small fixed query count, confirm the
  anonymize cascade's `.update()` doesn't trigger an N+1 anywhere it's called from) → `realtime-reviewer`
  (expected to find nothing — no realtime surface, same as 4.1-4.4) → `qa-smoke-tester` → `security-reviewer`
  (confirm `caller_phone`/`reason` PII discipline, confirm the anonymize cascade actually fires and doesn't
  silently no-op, confirm `source` cannot be posted) → `test-writer`.
- [ ] **UPDATE** `.claude/skills/scheduling/SKILL.md` — do not re-author. Flip the Build State row for 4.5 to
  **BUILT**; add the `CallbackRequest` model/routes/templates section; document the resolve-action pattern
  (`CallbackResolveForm` restricting choices, mirroring `AppointmentCancelForm`'s "small dedicated form"
  convention) so a later module doesn't reinvent it differently; document the `appointment_mark_view` +
  quick-range additions to 4.3's surface; extend the Seeder section with `DEMO_CALLBACK_REQUESTS`; add a
  Conventions & gotchas entry for the `Contact.anonymize()` cascade (what it scrubs, what it deliberately
  doesn't, and why) so a future contact-erasure change doesn't silently break it.
- [ ] README — note the new Callback Requests page and the Appointment list's quick-range/mark-status
  additions, only if the project README already enumerates 4.1-4.4's pages.

## Later passes / deferred

Carried over verbatim from `research-scheduling-4.5.md`'s own Deferred / Out-of-scope sections:

- **`request_callback` LLM tool + its dispatcher registration + the actual live-call write path** — blocked on
  Module 3 (Call Runtime) not existing yet; this pass ships only the write target's model shape.
- **The off-hours/no-answer transfer-fallback write into `CallbackRequest`** — same blocker, Module 3.4.
- **`Appointment.booked_by_session` FK completion** ("originating call" on the Appointment Detail bullet) —
  blocked on Module 5 (`calls.CallSession`); carried forward from 4.3's own deferred list, not re-litigated.
- **Urgency/priority tagging on `CallbackRequest`** (Smith.ai) — not in the ERD or the sub-module's bullets;
  a well-scoped future addition if ever asked for.
- **`resolved_by`/`resolved_at` audit pair** — reasonable future addition; `updated_at` covers "when" well
  enough for this pass, and no researched leader's public docs specify a distinct pair either.
- **CSV/print export** of the bookings list or the callback queue — no reporting capability documented for
  this product yet.
- **Instant multi-channel staff notification on a new callback** (email/SMS/push) — no outbound
  notification/messaging capability among the seven capabilities; this product's email use is limited to the
  Module 0 account-security flows.
- **CRM / Zapier / Google-Sheets auto-export of leads** (Goodcall) — no integrations capability among the
  seven.
- **Live in-queue hold / ACD callback position** (Dialpad's In-Queue Callback) — a concurrent-live-call
  hold-queue concept; this product transfers to one configured destination number, not a multi-agent queue.
- **Unified inbox merging voice calls with SMS/text threads** (Rosie) — no SMS channel among the seven.
- **Scheduled follow-up reminders** (Ruby) — would need a reminder/notification engine this product doesn't
  have.
- **Scrubbing `CallbackRequest.reason`/`notes` on `Contact.anonymize()`** — deliberately NOT done this pass
  (see the cascade fix above): those fields are the queue's own operational message, not caller identity: a
  well-scoped future addition if a stricter erasure policy is ever adopted, not silently expanded to now.

## Review notes

(filled in at the end)
