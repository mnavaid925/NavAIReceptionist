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
