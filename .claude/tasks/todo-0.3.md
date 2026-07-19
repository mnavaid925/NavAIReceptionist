---
# Sub-module 0.3 — User Profile & Directory (Module 0: Accounts & Access, `accounts`) — plan from research-accounts-0.3.md (2026-07-19)

## Shape: CRUD sub-module over an EXISTING model — ZERO new models, ZERO migrations

`accounts.User` and `accounts.UserLocation` were both created in **0.1** (the `AUTH_USER_MODEL` hard
requirement forced them to exist before the first `makemigrations`). 0.3 does not introduce a new table — it
is the first pass that actually ships list/create/detail/edit/delete pages over `User`, plus a narrower
self-service form over the same row. This is the CRUD-over-existing-model exception the todo-agent brief
calls out explicitly: the right model count for this pass is **zero new tables, all new
views/forms/templates**. Because it introduces a list page with full CRUD, every rule in CLAUDE.md's **CRUD
Completeness Rules** applies in full — list, create, detail, edit AND delete are all mandatory — with the
delete route implemented as **deactivation** (`status = User.STATUS_INACTIVE`), never `.delete()`, per the
sub-module's own fourth bullet and per `User`'s own `status` help text ("Deactivate rather than delete, so
historical appointments keep a valid provider reference").

`accounts.UserLocation` stays **read-only** this pass (`user.assigned_locations()`, already built) — creating
or editing `UserLocation` rows is **1.3's** job.

## Models (existing — 0 new, 0 migrations this pass)

- [ ] **`accounts.User`** (existing, verified in `apps/accounts/models/User.py` — not touched by this pass
  beyond its forms/views). Tenant-scoped only, not location-scoped (verified: no `location` FK on `User`; the
  CLAUDE.md Multi-Tenancy rule explicitly lists `accounts.User` under "Not location-scoped"). Two DIFFERENT
  forms sit over the same table, split by who is allowed to touch which fields — this split IS the
  privilege-escalation guardrail the research flags as REQUIRED:
  - **`UserAdminForm`** (owner/manager only, via `user_create_view`/`user_edit_view`) —
    `Meta.fields = ('email', 'username', 'first_name', 'last_name', 'full_name', 'primary_phone', 'tier',
    'status', 'is_provider')`. Drivers: `tier` and `status` ← **User Create & Edit** bullet
    ("tier (`owner`, `manager`, `staff`), status ... `is_provider` flag"); `status` doubling as the
    reactivation control ← **Deactivation Instead of Deletion** ("editing status back to active ... is
    reactivation, no separate button needed"); `is_provider` ← same bullet, feeds Module 4 later, 0.3 only
    sets the bit. Excludes (never in `Meta.fields`, never rendered): `tenant` (stamped from `request.tenant`
    via `TenantModelForm.save()`), `password` (never admin-typed — see invite flow below), `is_staff` (Django
    admin flag, not the product's tier), `provider_hours` (1.4's field), `last_login`/`created_at`/`updated_at`
    (system-owned).
  - **`OwnProfileForm`** (any authenticated tenant user, own row only, via `profile_view`) —
    `Meta.fields = ('first_name', 'last_name', 'full_name', 'primary_phone')` only. Driver: **Own Profile**
    bullet, verbatim field list. Excludes everything `UserAdminForm` excludes **plus** `email` (0.2's Change
    Email owns that), `username`, `tier`, `status`, `is_provider` — a self-editable tier/status/is_provider
    field is the exact privilege-escalation bug this research flags as REQUIRED to prevent. `full_name`'s
    help text notes the field is auto-derived from first+last when left blank (`User.clean()`/`.save()`,
    already built — surfaced via help text only, no new logic) ← **Full-name auto-derivation** bullet.
- [ ] **`accounts.UserLocation`** (existing, verified in `apps/accounts/models/UserLocation.py`) —
  **read-only** this pass, via `user.assigned_locations()` (verified method on `User`), rendered on the user
  list row and the user detail page. Driver: **Assigned-locations display** researched feature. No form, no
  create/edit/delete view for `UserLocation` in this pass — that belongs to **1.3**.

## Backend (apps/accounts/{models,forms,views}/ + urls.py — FLAT, no sub-module level, per rule 9/10)

- [ ] `apps/accounts/views/_helpers.py` — add `tier_required(*allowed_tiers)`, the gate research flags as
  missing (`grep` of `middleware.py` for `tier|role|permission` returns nothing today): a decorator that
  wraps `@login_required`, then `raise PermissionDenied` (→ Django's 403) when
  `request.user.tier not in allowed_tiers`. Import `from functools import wraps` and
  `from django.core.exceptions import PermissionDenied`. Used by all five admin CRUD views below —
  `tier_required(User.TIER_OWNER, User.TIER_MANAGER)` — never by `profile_view` (every tier may edit their
  own profile).
- [ ] `apps/accounts/forms/Users.py` — `UserAdminForm(TenantModelForm)` per the field split above. No
  `tenant_scoped_fields` (no FK fields on `User` besides `tenant` itself, which `TenantModelForm` already
  strips). Plural filename (`Users.py`, not `User.py`) deliberately mirrors the `CallSessions.py`/
  `Appointments.py` plural-entity convention in CLAUDE.md's Backend Package Structure rule 1, and sidesteps
  the exact "module name shadows the re-exported class" trap `models/User.py`'s own docstring warns about.
- [ ] `apps/accounts/forms/Profile.py` — `OwnProfileForm(TenantModelForm)` per the field split above.
- [ ] `apps/accounts/views/Users.py` — the five admin views, all decorated `@tier_required(User.TIER_OWNER,
  User.TIER_MANAGER)`:
  - `user_list_view` — `User.objects.filter(tenant=request.tenant).prefetch_related('user_locations__location')`
    (avoids N+1 when the list renders each row's assigned locations); search via
    `Q(full_name__icontains=q) | Q(email__icontains=q) | Q(username__icontains=q)` on
    `request.GET.get('q', '').strip()`; `tier` filter (`request.GET.get('tier', '')`, degrades to no filter on
    a junk value); `status` filter (same pattern); apply both BEFORE `paginate()`; pass
    `tier_choices=User.TIER_CHOICES`, `status_choices=User.STATUS_CHOICES` in context.
  - `user_create_view` — `UserAdminForm(request.POST or None, request=request)`; on valid POST,
    `user = form.save(commit=False)`, then `user.set_unusable_password()` (Django's documented
    "no password yet" state — `check_password()` always fails, `has_usable_password()` returns `False`, and
    `default_token_generator.make_token()` still works because it hashes the whole password field, usable or
    not), `user.save()`, then send the invite email (below), redirect to `user_detail`.
  - `user_detail_view` — `get_object_or_404(User, pk=pk, tenant=request.tenant)` (pk alone is never enough —
    the cross-tenant IDOR boundary for this sub-module); context includes
    `assigned_locations = obj.assigned_locations()` and a computed
    `is_invited = obj.last_login is None and not obj.has_usable_password()` (the **"Invited, not yet
    active" indicator** bullet — zero schema impact, template-only conditional).
  - `user_edit_view` — same `UserAdminForm`, `instance=obj` from the same tenant-scoped `get_object_or_404`.
  - `user_delete_view` — `@require_POST`; `get_object_or_404(User, pk=pk, tenant=request.tenant)`; **guard 1
    (self-deactivation)**: `if obj.pk == request.user.pk:` → `messages.error(...)`, redirect back, no write —
    ← **Self-deactivation guard** bullet; **guard 2 (last-owner)**: if
    `obj.tier == User.TIER_OWNER and obj.status == User.STATUS_ACTIVE`, count
    `User.objects.filter(tenant=request.tenant, tier=User.TIER_OWNER, status=User.STATUS_ACTIVE).exclude(pk=obj.pk)`
    — if that count is `0`, block with a message ← **Last-owner guard** bullet; otherwise
    `obj.status = User.STATUS_INACTIVE; obj.save(update_fields=['status', 'updated_at'])`, redirect to
    `user_list` ← **Deactivation Instead of Deletion** bullet, this IS the mandatory delete route.
  - `_send_invite_email(request, user)` — private helper, same shape as `Auth.py`'s `_send_reset_email`:
    `default_token_generator.make_token(user)` + `urlsafe_base64_encode(force_bytes(user.pk))`, links to the
    **already-existing** `accounts:password_reset_confirm` route (zero new URL — a token-bearing user with an
    unusable password sets their first password through the exact same page 0.1 already built), subject/body
    are a "Welcome, set your password" variant, `fail_silently` pattern matching `_send_reset_email` (log and
    swallow, never surface a mail-server failure to the admin who clicked Create). ← **Invite-to-set-password**
    bullet, deliberately zero-schema.
- [ ] `apps/accounts/views/Profile.py` — `profile_view`, `@login_required` only (no tier gate — every tier
  edits their own profile): `OwnProfileForm(request.POST or None, instance=request.user, request=request)`;
  on valid POST, save and re-render with a success message; GET renders the same template pre-filled.
- [ ] `apps/accounts/forms/__init__.py` — re-export `UserAdminForm` (from `.Users`) and `OwnProfileForm`
  (from `.Profile`); add both to `__all__`.
- [ ] `apps/accounts/views/__init__.py` — re-export `user_list_view`, `user_create_view`, `user_detail_view`,
  `user_edit_view`, `user_delete_view` (from `.Users`) and `profile_view` (from `.Profile`); add all six to
  `__all__`. Forgetting this step is the ImportError CLAUDE.md warns about — the `crud()` factory looks views
  up as `views.<name>_<suffix>_view`.
- [ ] `apps/accounts/urls.py` — replace the two scaffold comment lines
  (`# urlpatterns += crud('users', 'user') # 0.3 User Directory` / `# Keep them AFTER the literals above.`)
  with real code: add `path('profile/', views.profile_view, name='profile')` inside the existing
  `urlpatterns = [...]` literal block (a `# -- 0.3 User Profile & Directory --` comment header, same style as
  the existing `0.1` one), then, after the closing `]`, `urlpatterns += crud('users', 'user')`. This is
  exactly the pass the `crud()` factory (already written, currently unused) was built for.
- [ ] `apps/accounts/models/__init__.py` — **no change** (0 new models this pass; `User`/`UserLocation` are
  already re-exported from 0.1).
- [ ] `apps/accounts/admin.py` — **no change** (already registers `User`/`UserLocation` with a correct
  password-safe `UserAdmin`; the product's own management UI is what this pass adds, not the admin).
- [ ] `apps/accounts/management/commands/seed_accounts.py` — **no change needed.** The four existing demo
  users (`admin@acme.test`/owner/2-location, `downtown.manager@acme.test`/manager/provider/1-location,
  `admin@globex.test`/owner/2-location, `riverside.staff@globex.test`/staff/provider/1-location) already
  exercise every tier, the provider badge, single- vs multi-location assignment, and both tenants for the
  cross-tenant IDOR check. No seeded row has `status != 'active'` or an unusable password yet — that is fine:
  the delete route's own smoke test produces an `inactive` row, and the "invited" computed indicator is
  covered by a unit test that creates a user with `password=None` directly, not by seed data.

## Realtime & agent surface

N/A this sub-module — confirmed by research's "Compliance & provider constraints": 0.3 touches no
`calls.CallSession`, no LLM tool, no provider adapter, no Channels consumer, and makes no provider call (the
one outbound side-effect, the invite email, reuses 0.1's already-configured `EMAIL_BACKEND`). No tool
declaration, no prompt variable, no `AgentSetting.variables` entry, no `CallSession.usage` cost line.

## Wire-up

- [ ] `apps/accounts/navigation.py` — add exactly one new key:
  `LIVE_LINKS["0.3"] = {"User List & Detail": "accounts:user_list"}`. Reasoning: of the four bullets (Own
  Profile, User List & Detail, User Create & Edit, Deactivation Instead of Deletion), "User List & Detail" is
  the one genuine hub page a signed-in admin lands on and clicks into everything else from — matching the
  "public-surface bullets point at the STAFF-facing management page" rule. Known, accepted limitation
  (documented here, not silently swallowed): `user_list` is gated `tier_required(owner, manager)`, so a
  staff-tier user still SEES the sidebar row (LIVE_LINKS resolves by URL existence, not by the viewer's tier)
  but gets a 403 on click — `navigation.py`'s `build_sidebar()` has no per-viewer permission filtering today
  and adding it is out of scope for this pass; `Own Profile` (`accounts:profile`, reachable by every tier) is
  deliberately NOT the sidebar entry precisely because it under-represents "0.3 is live" (login → dashboard
  already proves the shell works; the user directory is the actual new capability).
- [ ] `config/settings.py`, `config/urls.py`, `config/asgi.py` — **no action.** This is not a brand-new-app
  run; `accounts` and its full settings/urls wiring already exist from 0.1.
- [ ] `AUTH_USER_MODEL` — already declared before the first `makemigrations` (0.1). No action, not the first
  run of all.

## Templates (templates/accounts/ — FLAT, no sub-module level, per Template Folder Structure rule 4)

- [ ] `templates/accounts/user/list.html` — extends `base.html`. Filter bar reflecting `request.GET`: search
  input (`q`), `tier` `<select>` built from `tier_choices` (`{% if request.GET.tier == value %}selected{% endif %}`,
  string compare — `tier` is a CharField, not a pk), `status` `<select>` from `status_choices` (same string
  compare). Table columns: name/email, tier badge (plain text or `badge-slate`, not a status color), status
  badge (**fixed map**: `active`→`badge-green`, `inactive`→`badge-muted`, `suspended`→`badge-red`, with an
  `{% else %}{{ u.get_status_display }}{% endif %}` fallback), a `badge-info` "Provider" chip when
  `u.is_provider`, assigned locations (comma-joined names from the prefetched `u.user_locations.all` —
  template-side join, not a second query), Actions column (view/edit/deactivate — eye/pencil/ban icons,
  deactivate is a POST form with `{% csrf_token %}` and `onclick="return confirm('Deactivate this user?')"`,
  hidden entirely on the row matching `request.user.pk` per the self-deactivation guard). `{% include
  "partials/_pagination.html" with page_obj=page_obj elided_page_range=elided_page_range %}` and
  `{% include "partials/_empty_state.html" with icon="users" title="No users yet" action_url=... %}` when
  empty.
- [ ] `templates/accounts/user/detail.html` — extends `base.html`. Read-only: email, username, tier
  (`get_tier_display`), status badge (same fixed map), provider badge, primary phone, last login
  (`{{ obj.last_login|default:"Never" }}`), an amber "Invited — hasn't signed in yet" note when the view's
  computed `is_invited` is true, assigned locations as a list. Actions sidebar: Edit button (links
  `user_edit`), Deactivate button (POST + confirm, hidden if `obj.pk == request.user.pk`), Back to List link.
- [ ] `templates/accounts/user/form.html` — shared create/edit template (same shape as `login.html`'s sibling
  pattern but extends `base.html`, since this is behind auth). Fields: email, username, first_name, last_name,
  full_name (help text: "Leave blank to auto-generate from first + last name"), primary_phone, tier, status,
  is_provider. **No password field of any kind** — a comment in the template itself notes new users are
  invited by email, existing users' passwords are changed only via 0.2's dedicated flow.
- [ ] `templates/accounts/profile.html` — **standalone page, app root, no entity folder** (Template Folder
  Structure rule 6 — it is not `user`'s list/detail/form triple, it's the single-purpose self-service page,
  exactly like `dashboard.html`). Extends `base.html`. Fields: first_name, last_name, full_name, primary_phone
  only — the template itself never references `tier`/`status`/`is_provider`/`email`, so there is no field to
  accidentally leak even if the view context were ever polluted.

## Verify

- [ ] `manage.py check`
- [ ] assert `PROVIDER_MODE=fake` (trivially true — 0.3 imports no provider adapter)
- [ ] `makemigrations --check` — must report **no changes detected** (0 new models is the whole point of this
  pass; a stray migration here is a bug, not progress).
- [ ] `pytest -q apps/accounts` covering: `tier_required` (owner and manager pass; staff gets 403; anonymous
  redirects to login); `user_list_view` (search matches name/email/username; tier filter; status filter; a
  junk `?tier=xyz` degrades to unfiltered, never 500; pagination); `user_create_view` (creates with
  `has_usable_password() is False`; invite email lands in `mail.outbox` with the `password_reset_confirm`
  link; `tenant` is stamped from `request.tenant`, never from POST); `user_detail_view` (`is_invited` true for
  a freshly-created never-logged-in user, false for a seeded demo user; assigned locations render); `user_edit_view`
  (tier/status/is_provider all change; editing `status` from `inactive` back to `active` is reactivation with
  no separate endpoint); `user_delete_view` (status becomes `inactive`, never an actual row delete; **self-
  deactivation guard**: acting user targeting their own pk is blocked, status unchanged; **last-owner guard**:
  a manager targeting the tenant's sole active owner is blocked, status unchanged — promote a second demo user
  to owner in the test to also prove the ALLOWED path when two owners exist); `profile_view` (self-service
  first/last/full-name/phone edit persists; **privilege-escalation check**: POST-spoofing `tier`, `status`,
  `is_provider` or `email` alongside valid profile fields leaves all four unchanged, because `OwnProfileForm`
  never declares those fields — assert directly against the DB row after the POST, not just the 302).
- [ ] Twilio signature / idempotency — **N/A**, 0.3 has no webhook.
- [ ] websocket connect/reject — **N/A**, 0.3 has no Channels consumer.
- [ ] `temp/` smoke sweep as `admin_acme` (password printed by `seed_accounts`, currently `navai-demo-2026` —
  re-read the command's own output, don't hardcode it into a script): `accounts:user_list` GET→200 with the
  filter bar and the four seeded users visible, no `{#`/`{% comment` leaks; `accounts:user_create` GET→200,
  POST valid→302 to detail, new row has an unusable password; `accounts:user_detail` for a seeded user→200,
  correct badges; `accounts:user_edit`→200 pre-filled, POST changing tier/status→302, badge reflects the
  change; `accounts:user_delete` POST on `downtown.manager@acme.test` (not self, not the sole owner)→302 to
  list, status badge now `Inactive`/`badge-muted`; `accounts:profile` GET→200 own data only, POST→302,
  changes visible on next GET; **cross-tenant IDOR**: as `admin_acme`, GET `accounts:user_detail` /
  `accounts:user_edit` for `admin@globex.test`'s pk → **404** both times; **privilege escalation**: log in as
  `riverside.staff@globex.test` (`TIER_STAFF`), GET `accounts:user_list` / `user_create` / `user_detail` /
  `user_edit` / `user_delete` → **403** on every one, then GET `accounts:profile` → 200 (own profile still
  reachable) and confirm the rendered form has no tier/status/is_provider/email inputs anywhere in the HTML.
- [ ] sidebar shows `0.3` Live (the "User List & Detail" row resolves and is clickable when logged in as
  `admin_acme`).

## Close-out

- [ ] review agents (code-reviewer → explorer → frontend-reviewer → performance-reviewer → realtime-reviewer
  → qa-smoke-tester → security-reviewer → test-writer) — realtime-reviewer should have nothing to flag (no
  realtime surface) but still runs per the mandatory sequence; performance-reviewer should specifically check
  the `prefetch_related('user_locations__location')` on `user_list_view` actually avoids the N+1 the plan
  calls out.
- [ ] **SKILL.md: NONE for this module**, same carve-out 0.1 already documented — CLAUDE.md's Per-Module
  Skill section: *"Module 0 (`accounts`) is the foundation and is covered by the workflow skills
  (`next-module`, `frontend-design`, `voice-agent-runtime`). Modules 1–5 each get their own skill via this
  rule."* Do not author `.claude/skills/accounts/SKILL.md` in this pass.
- [ ] README — update the root `README.md` if it tracks build state/module status; skip if it carries no such
  section yet (same condition 0.1 recorded).

## Later passes / deferred

Carried over from research-accounts-0.3.md, nothing lost:

- **Deactivation impact preview** ("N upcoming appointments reference this provider") — blocked on
  `scheduling.Appointment`, which does not exist yet (Module 4 not built). Ship the plain confirm dialog now;
  revisit once Module 4 ships.
- **A 4th "pending/invited" status value** — deliberately not built; the existing 3-value `status` enum plus
  the computed `has_usable_password()`/`last_login is None` check covers it with zero schema change.
- **Audit trail of who edited which user's tier/status** — needs a table outside the eleven-model set;
  permanently deferred (restated from 0.1's research, resurfaces here in User Create & Edit).
- **Self-tier-demotion lockout guard** (an owner editing their own `tier` away from `owner` via `user_edit`)
  — not a researched bullet; only the delete-path last-owner guard is required. Noted as an accepted gap, not
  silently dropped.
- Change Password / Change Email / Credential Change Notice → **0.2** (not yet built; 0.3 touches
  `User.password` only via `set_unusable_password()` at invite time).
- Assigned-location list (switcher-facing UI), Session Active Location, Assignment Validation, Location
  Context Header → **0.4**.
- Assignment Matrix (creating/editing `UserLocation` rows from either side), the per-location bookable-target
  behavior of Provider Marking, Unassignment Guard → **1.3** (0.3 only displays existing rows read-only and
  only sets the raw `is_provider` bit).
- Per-Location Hours (`provider_hours` editor) → **1.4**.
- Enterprise SSO auto-role-assignment, per-navigation-area granular RBAC, a non-login "directory contact"
  person-type, mobile app team management, restore-window/soft-delete recovery UI — all out of scope for this
  product per research's "Out of scope" section (no SSO, 3-tier IS the whole permission model, one identity
  table for humans-with-accounts, web-only, deactivate already is the soft-delete floor).

## Review notes

(filled in at the end)
