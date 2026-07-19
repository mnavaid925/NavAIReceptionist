---
# Sub-module 0.2 — Credential Management (Module 0: Accounts & Access, `accounts`) — plan from research-accounts-0.2.md (2026-07-19)

## Shape: service/view — ZERO new models, ZERO migrations

0.2 mutates two existing columns on the already-migrated `accounts.User` (`email`, `password`) through three
new authenticated/token-gated views. It is not a CRUD sub-module (no new tenant-scoped model, no
list/detail/edit/delete entity) and not a pure read-only view sub-module either (it writes, it doesn't just
read) — its closest fit is the CRUD-completeness doc's **service-sub-module exemption**, whose observable
surface is explicitly allowed to be "a settings form" rather than a table. Per research: *"0.2 introduces ZERO
new models and ZERO migrations — confirmed correct by research, not merely mandated. Every researched feature
above is satisfied by mutating the two existing columns on the already-migrated `accounts.User`."* No twelfth
model, no `PendingEmailChange` table — the pending-email-change state lives entirely in a signed,
short-TTL `django.core.signing` token, never in a row.

## Models: NONE — zero new models, zero migrations

- Reuses **`accounts.User`** (verified: `apps/accounts/models/User.py`, migrated in `accounts/0001_initial.py`)
  — `.email` and `.password` columns only; no new field. Re-validates the **existing**
  `UniqueConstraint(fields=['tenant', 'email'], name='uniq_user_tenant_email')`
  (`User.Meta.constraints`, verified) at **confirmation time**, not only at request time — the address could be
  claimed by a second user inside the token's TTL window, so `email_change_confirm_view` must re-check
  `User.objects.filter(tenant=user.tenant, email__iexact=new_email).exclude(pk=user.pk).exists()` immediately
  before saving and fail gracefully (friendly result page, never an `IntegrityError` bubbling into a 500) if the
  race lost.
- No new table for the pending email change. The payload is
  `django.core.signing.dumps({'user_id': user.pk, 'new_email': new_email, 'old_email': user.email},
  salt='accounts.email_change')`, verified with `loads(token, max_age=settings.EMAIL_CHANGE_TOKEN_MAX_AGE,
  salt='accounts.email_change')` (`EMAIL_CHANGE_TOKEN_MAX_AGE = 3600`, already in `config/settings.py`). This is
  the **first use of `django.core.signing`** in the repo (confirmed absent by grep in research). Self-invalidates
  because the confirm view compares `user.email == payload['old_email']` before applying — a token already used,
  superseded by a newer request, or invalidated by an admin edit elsewhere all fail this check identically.

## Backend (apps/accounts/{forms,views}/Auth.py + views/_helpers.py + urls.py — FLAT, no sub-module level, rule 9)

- [ ] `forms/Auth.py` — add `ChangePasswordForm(forms.Form)`: fields `old_password` (PasswordInput,
  `autocomplete=current-password`), `new_password1`, `new_password2` (PasswordInput,
  `autocomplete=new-password`). `__init__(self, *args, user=None, **kwargs)` stores `self.user`.
  `clean_old_password()` calls `self.user.check_password(...)`, adding a field error
  (`'Your current password is incorrect.'`) on mismatch — a specific field-level message is correct here
  (unlike login) because the caller is already authenticated as this account; there is no enumeration channel
  to protect. `clean()` mirrors `SetNewPasswordForm`'s two-field-match check +
  `password_validation.validate_password(new_password1, self.user)`. `save()` does
  `self.user.set_password(...)` + `self.user.save(update_fields=['password'])`. `style_widgets(self)` in
  `__init__`, matching the file's existing convention.
- [ ] `forms/Auth.py` — add `ChangeEmailRequestForm(forms.Form)`: fields `password` (PasswordInput,
  `autocomplete=current-password`), `new_email` (EmailField, `autocomplete=email`). `__init__(self, *args,
  user=None, **kwargs)` stores `self.user`. `clean_password()` calls `self.user.check_password(...)` with a
  field error on mismatch. `clean_new_email()` strips/normalizes and does a **request-time UX check** —
  `User.objects.filter(tenant=self.user.tenant, email__iexact=value).exclude(pk=self.user.pk).exists()` → field
  error `'That address is already in use.'` — explicitly a courtesy check, not the authoritative one; the
  authoritative re-check happens again in `email_change_confirm_view` per the Models section above.
  `style_widgets(self)` in `__init__`.
- [ ] `forms/Auth.py` — update the module's `__all__` to add `'ChangePasswordForm'`, `'ChangeEmailRequestForm'`.
- [ ] `forms/__init__.py` — add `ChangePasswordForm`, `ChangeEmailRequestForm` to the `from
  apps.accounts.forms.Auth import (...)` block and to `__all__` (keep `LoginForm`, `PasswordResetRequestForm`,
  `SetNewPasswordForm` untouched).
- [ ] `views/_helpers.py` — add the shared **Credential Change Notice**:
  `CREDENTIAL_CHANGE_SUBJECTS = {'password': 'Your NavAIReceptionist password was changed', 'email': 'Your
  NavAIReceptionist email address was changed'}` and matching `CREDENTIAL_CHANGE_BODIES` dict — the `'password'`
  body is the existing `CHANGED_EMAIL_BODY` text verbatim (renamed into this dict); the `'email'` body is new
  copy stating plainly *"your email was changed to {new_email}"* plus the same *"if this wasn't you, contact
  your administrator"* call-to-action, mirroring the existing phrasing. Add
  `send_credential_change_notice(user, kind, detail=None, to_email=None)`: `kind` is `'password'` or `'email'`;
  `detail` is the new email address (only meaningful for `kind='email'`, interpolated into the body); `to_email`
  overrides the recipient (used to notify the **OLD** address on an email change, since by the time the notice
  fires `user.email` already holds the new one) and defaults to `user.email`. `send_mail(..., fail_silently=True)`
  wrapped in `try/except Exception: logger.exception(...)` — notice delivery must never block or fail the
  credential change itself, and a send failure must still be logged (the operational side of the
  account-takeover tripwire), exactly the pattern already proven in `_send_password_changed_email`.
- [ ] `views/Auth.py` — **delete** the local `_send_password_changed_email(user)` helper and its
  `CHANGED_EMAIL_SUBJECT`/`CHANGED_EMAIL_BODY` module constants (both relocated into `views/_helpers.py` above);
  update `password_reset_confirm_view`'s call site from `_send_password_changed_email(user)` to
  `send_credential_change_notice(user, 'password')`, imported from `apps.accounts.views._helpers`.
- [ ] `views/Auth.py` — add `change_password_view(request)`: `@login_required`, `@require_http_methods(['GET',
  'POST'])`. Throttle scope `'change_password'`: `keys = throttling.build_keys('change_password',
  str(request.user.pk), get_client_ip(request))`. If `throttling.is_throttled(keys)`: attach `THROTTLED_ERROR`
  (imported from the same module, reused verbatim) as a non-field form error, do not process the POST. Else:
  `form = ChangePasswordForm(request.POST or None, user=request.user)`; on invalid POST (wrong current
  password or a validator failure), `throttling.register_failure(keys)`; on valid POST: `form.save()`,
  `update_session_auth_hash(request, request.user)` **immediately** after the save so the change-password flow
  never logs the user out mid-request, `throttling.clear(keys)`, `send_credential_change_notice(request.user,
  'password')`, `logger.info('Password changed for user_id=%s tenant_id=%s', ...)` (never the password itself),
  `messages.success(...)`, redirect to `accounts:dashboard`. Render `accounts/change_password.html` on GET / on
  form errors.
- [ ] `views/Auth.py` — add `change_email_request_view(request)`: `@login_required`, `@require_http_methods(['GET',
  'POST'])`. Same throttle shape with scope `'change_email'`. `form =
  ChangeEmailRequestForm(request.POST or None, user=request.user)`; on invalid POST,
  `throttling.register_failure(keys)`; on valid POST: build the signed token
  (`signing.dumps({'user_id': request.user.pk, 'new_email': form.cleaned_data['new_email'], 'old_email':
  request.user.email}, salt='accounts.email_change')`), build the confirm URL via
  `request.build_absolute_uri(reverse('accounts:email_change_confirm', kwargs={'token': token}))`, send a
  confirmation email to the **new** address (not the old one) stating the link expires in
  `EMAIL_CHANGE_TOKEN_MAX_AGE // 60` minutes, `throttling.clear(keys)`, set `sent = True` in context (same
  `sent`-boolean-on-the-same-page pattern already used by `password_reset_request_view`, not a redirect) so the
  user sees *"check `new@address` to confirm — link expires in 1 hour"* without losing the page. Render
  `accounts/change_email.html` with `sent`, `form`, and `current_email=request.user.email` in context for every
  path (GET, POST-invalid, POST-valid).
- [ ] `views/Auth.py` — add `email_change_confirm_view(request, token)`: GET-only
  (`@require_http_methods(['GET'])`), **no `@login_required`** — matches `password_reset_confirm_view`'s shape,
  because identity is proven by the signed token, not by the session in the browser that clicks the link (it
  may be a different device). Decode with `signing.loads(token, max_age=settings.EMAIL_CHANGE_TOKEN_MAX_AGE,
  salt='accounts.email_change')`; catch `signing.BadSignature`/`SignatureExpired` → render `valid=False`. Look
  up `User.objects.filter(pk=payload['user_id']).select_related('tenant').first()`; `None` → `valid=False`.
  **Self-invalidation check:** `user.email != payload['old_email']` → `valid=False` (already used, superseded,
  or changed by another route). **Confirmation-time uniqueness re-check** (see Models section) →
  `valid=False` on collision. Otherwise: `old_email = user.email`; `user.email = payload['new_email']`;
  `user.save(update_fields=['email'])`; `send_credential_change_notice(user, 'email',
  detail=payload['new_email'], to_email=old_email)` (fires to the address being **replaced**, per the
  documented bullet); `logger.info('Email change confirmed for user_id=%s tenant_id=%s', ...)` (never either
  raw address); `messages.success(...)`. Render `accounts/email_change_confirm.html` with `valid=True,
  new_email=payload['new_email']`. The template itself branches on `user.is_authenticated` (see Templates) to
  offer a dashboard link vs. a sign-in link, so the view needs no extra branching logic.
- [ ] `views/Auth.py` — update the module's `__all__` to add `'change_password_view'`,
  `'change_email_request_view'`, `'email_change_confirm_view'`.
- [ ] `views/__init__.py` — add `change_password_view`, `change_email_request_view`,
  `email_change_confirm_view` to the `from apps.accounts.views.Auth import (...)` block and to `__all__`.
- [ ] `urls.py` — append three literal routes to the existing flat `urlpatterns` list, **after** the 0.1 block
  and before the `# Later sub-modules append their crud() blocks here` comment (no `<int:pk>` route exists yet
  in this file, so ordering only matters relative to future `crud()` calls):
  `path('change-password/', views.change_password_view, name='change_password')`,
  `path('change-email/', views.change_email_request_view, name='change_email')`,
  `path('change-email/confirm/<str:token>/', views.email_change_confirm_view, name='email_change_confirm')`.
  These two exact names (`change_password`, `change_email`) **must** match what
  `context_processors.py`'s `OPTIONAL_CHROME_URLS` already expects — do not rename.
- [ ] `admin.py` — **no change.** No new model to register.
- [ ] Migration — **none.** Verify with `makemigrations accounts --check --dry-run` reporting "No changes
  detected" (see Verify).
- [ ] `seed_accounts` — **no change.** No new model or field to seed; 0.2's smoke sweep exercises the
  demo users `seed_accounts` already creates (`admin@acme.test` / `admin_acme`, password `navai-demo-2026` —
  confirmed by reading `apps/accounts/management/commands/seed_accounts.py`).

## Realtime & agent surface

N/A — this sub-module has no consumer, no websocket route, no LLM tool, no prompt variable and no provider
adapter. Per research: *"No provider cost line. The only external dependency is outbound email... already
routed through the same configurable `EMAIL_BACKEND`... no Twilio/STT/TTS/LLM involvement, nothing appended to
any `calls.CallSession.usage`."*

## Wire-up

- [ ] `apps/accounts/navigation.py` — add **exactly one** new `LIVE_LINKS` entry:
  `'0.2': {'Change Password': 'accounts:change_password'}`, placed immediately after the existing `'0.1'` entry.
  `'Change Password'` is the literal `**Feature**` bullet text from `NavAIReceptionist.md` §0.2, and
  `accounts:change_password` is the STAFF-facing settings page (never the token-confirm link, which is a
  one-shot email action, not a page to navigate to from the sidebar). Touch no other key.
- [ ] `config/settings.py` / `config/urls.py` / `config/asgi.py` — **no change.** `accounts` already exists as
  an app; this is not a brand-new-app run.
- [ ] `context_processors.py` — **no change.** `nav_urls.change_password`/`nav_urls.change_email` already
  resolve defensively; they will now resolve to real URLs instead of `None`.
- [ ] `templates/partials/_topbar.html` / `_sidebar.html` — **deliberately not touched this pass.** Neither
  currently renders `nav_urls.change_password`/`change_email` — that entry point belongs to 0.3's Own Profile
  page (the natural "account settings" hub), which is why `context_processors.py`'s own comment calls these
  "chrome links that arrive across several sub-module runs." 0.2 ships two directly-reachable pages
  (`/change-password/`, `/change-email/`) that cross-link each other and back to the dashboard (see Templates);
  0.3 wires them into the profile page later. Do not add a topbar/sidebar link in this pass.

## Templates (templates/accounts/ — flat, foundation app, rule 4)

- [ ] `templates/accounts/change_password.html` — extends `base.html` (authenticated shell). Card form: current
  password, new password, confirm new password. Non-field errors block (throttled message /
  `'old_password'` mismatch surfaces as a normal per-field error, since this is post-auth — not the
  uniform-failure pattern 0.1 uses pre-auth). A link to `accounts:change_email` and back to
  `accounts:dashboard`.
- [ ] `templates/accounts/change_email.html` — extends `base.html`. Shows the current address read-only
  (`{{ current_email }}`) so the user confirms which address they're replacing, then the request form
  (current password, new email). On `sent=True`, replaces the form with the flash notice *"check `<new
  email>` to confirm — this link expires in 60 minutes"* (derived from
  `settings.EMAIL_CHANGE_TOKEN_MAX_AGE // 60`, not hardcoded) rather than a raw redirect, mirroring
  `password_reset_request.html`'s existing `sent`-boolean pattern. A link to `accounts:change_password` and
  back to `accounts:dashboard`.
- [ ] `templates/accounts/email_change_confirm.html` — extends `auth_base.html` (no shell, matches
  `password_reset_confirm.html`'s pre-auth-page pattern, since the click may land in a browser with no active
  session). Two branches, no form (GET-only action page):
  - `{% if not valid %}` — friendly *"this link is no longer valid"* card (covers bad signature, expired,
    already-used/stale, and the confirmation-time uniqueness conflict alike — one generic message, matching
    `password_reset_confirm.html`'s existing invalid-link copy style) with a link back to
    `accounts:change_email` (if the user happens to be signed in) and to `accounts:login`.
  - `{% else %}` — *"Your email address has been updated to `{{ new_email }}`."* Branches on
    `{% if user.is_authenticated %}` for a "Continue to dashboard" link (`accounts:dashboard`) vs. a "Sign in
    with your new address" link (`accounts:login`) — no extra view logic needed, the template reads
    `request.user` directly like every other page.

## Verify

- [ ] `manage.py check`
- [ ] `makemigrations accounts --check --dry-run` → **"No changes detected"** — the empirical proof of the
  zero-model claim; if this reports pending changes, the plan (or the code) has drifted from "reuses existing
  columns only."
- [ ] Assert `PROVIDER_MODE=fake` in `config.settings_test` (inherited default; 0.2 adds no provider call of
  its own, so this is a non-regression check, not new surface).
- [ ] `pytest -q apps/accounts` — new tests in `apps/accounts/tests/test_credential_management.py` (package did
  not exist before 0.2; add `tests/__init__.py` too):
  - `change_password_view`: anonymous → redirect to login; wrong `old_password` → 200 with a field error, no
    state change, throttle counter increments; a weak new password → rejected by
    `password_validation.validate_password`; correct old password + valid new password → 302, `check_password`
    succeeds against the new value, **the same session survives** (`update_session_auth_hash` proven by a
    follow-up authenticated request in the same client that does NOT redirect to login), exactly one
    credential-change-notice email fires to `user.email`, throttle counter is cleared on success.
  - `change_email_request_view`: anonymous → redirect to login; wrong password → 200 with a field error, no
    email sent; an already-claimed-in-this-tenant `new_email` → 200 with a field error (request-time UX check);
    valid request → exactly one email sent, addressed to the **new** address, containing a working
    `accounts:email_change_confirm` link; `User.email` is **unchanged** until the link is followed.
  - `email_change_confirm_view`: a valid link → `User.email` updated, exactly one credential-change-notice
    email fires to the **old** address (not the new one), success page renders `new_email`; a token frozen past
    `EMAIL_CHANGE_TOKEN_MAX_AGE` (loads with `max_age=-1` or a mocked clock) → `valid=False`, `User.email`
    unchanged; a malformed/garbage token string → 200 friendly page, never a 500; **replaying the same
    already-used link** → `valid=False` (the self-invalidation check: `user.email != payload['old_email']`);
    the **cross-tenant `(tenant, email)` uniqueness re-check at confirmation time** — create a second user in
    the same tenant who claims the pending `new_email` address *between* the request and the confirm click →
    confirm renders `valid=False` gracefully, no `IntegrityError`, `User.email` unchanged.
  - Throttling: `LOGIN_ATTEMPT_LIMIT` consecutive wrong-`old_password` attempts on `change_password` → the
    next attempt (even with the correct password) is refused with `THROTTLED_ERROR`; the `change_email` scope
    throttles independently of `change_password` (same user, same IP, different scope string).
- [ ] Twilio signature / idempotency — **N/A**, no webhook in this sub-module.
- [ ] Websocket connect/reject — **N/A**, no consumer in this sub-module.
- [ ] `temp/smoke_0_2.py` (new file, modeled on the existing `temp/smoke_0_1.py` — same
  `config.settings_test` / SQLite-in-memory / `DiscoverRunner` harness) run as `admin_acme`
  (`admin@acme.test` / `navai-demo-2026`, seeded by `seed_accounts` — confirmed by reading the seeder, not
  assumed): covers `PROVIDER_MODE` first, then GET `change_password`/`change_email` anonymous → 302 to login;
  GET both authenticated → 200, no `{#`/`{% comment` leak; POST wrong current password on each → 200 with a
  field error, `mail.outbox` empty; POST correct old password + new password on `change_password` → 302, a
  follow-up authenticated GET does **not** bounce to login (session survived), `mail.outbox` has exactly one
  credential-change-notice; POST a valid `change_email` request → `mail.outbox` has exactly one email containing
  a `/change-email/confirm/` link, `User.email` unchanged; GET that link → `User.email` updated,
  `mail.outbox` gains the old-address notice, page shows the new address; GET it again (replay) → 200 "no
  longer valid", `User.email` unchanged the second time; a bogus token path segment → 200, never 500;
  cross-tenant IDOR check — the `globex` tenant's admin cannot use an `acme` user's confirm token to change
  a `globex` account's email (token's `user_id` resolves to the `acme` user regardless of who clicks it, and
  the applied change stays inside that user's own tenant — assert the `globex` user's email is untouched);
  sidebar shows **0.2 Live** (`Change Password` link resolves and appears in the rendered authenticated shell).

## Close-out

- [ ] Review agents, in order: `code-reviewer` → `explorer` → `frontend-reviewer` → `performance-reviewer` →
  `realtime-reviewer` (expected no-op: no realtime surface) → `qa-smoke-tester` → `security-reviewer` →
  `test-writer`.
- [ ] **Skip skill authoring/update.** Per `.claude/CLAUDE.md`'s **Per-Module Skill** section: *"Module 0
  (`accounts`) is the foundation and is covered by the workflow skills (`next-module`, `frontend-design`,
  `voice-agent-runtime`)... Modules 1–5 each get their own skill via this rule."* `accounts` is explicitly
  exempted from `.claude/skills/<slug>/SKILL.md` — do not create or touch one for this sub-module.
- [ ] README — no project-level README change required by this sub-module.

## Later passes / deferred

- **"Sign out of other sessions" on password change** — needs session-to-user tracking beyond
  `accounts.User`/`accounts.UserLocation`; identical gap to 0.1's deferred "Force logout / active-session &
  device management." Do not re-solve here.
- **Security/audit log of credential-change events** — needs a new table with no home in the eleven-model set;
  identical gap to 0.1's deferred "Login audit trail," now extended to change-password/change-email events too.
- **TOTP MFA / step-up re-authentication** before a sensitive change — would start as extra fields on
  `accounts.User` (not a new table), but not required by any of 0.2's three documented bullets; deferred to an
  explicitly-scoped security-hardening pass.
- **Dual old-address notification at REQUEST time** (OWASP's stricter recommendation, vs. this product's
  documented apply-time-only notice) — optional strengthening, buildable later as one more call site to
  `send_credential_change_notice`; not required now.
- **CAPTCHA after repeated failed "current password" entries** — third-party dependency, not required for the
  documented bullets.
- **SSO/OIDC enterprise sign-in** and its interaction with local credential management (e.g. disabling password
  change for an SSO-linked user) — 0.1 already deferred SSO itself (needs a twelfth table for per-tenant IdP
  config); nothing to build here until SSO exists.
- **Persistent pending-change banner across page loads** (research's option (b): echoing the pending new-email
  into `request.session` purely for UX) — not built this pass; only the one-time flash message (option (a))
  ships. Optional UX nicety for a later pass, not a gap.
- **Masked-email display pattern reused in an admin's user-edit form** (an admin editing a different user's
  email) → 0.3's "User Create & Edit" — a materially different flow (the admin isn't proving mailbox ownership,
  the target user is), does not need the token-confirmation dance.
- Own-profile editing (name/phone), user list/detail/create/edit, tier/status, `is_provider`, deactivation →
  0.3.
- Assigned-location list, active-location switcher, assignment validation, location context header → 0.4.

## Review notes
(filled in at the end)
