---
# Sub-module 2.2 — Twilio Connection (Module 2: Agent Setup & Telephony, `agents`) — plan from research-agents-2.2.md  (2026-07-19)

## Shape: Service — one-line justification

**Service sub-module. Adds ZERO new models and (in the normal case) ZERO migrations.** `agents.AgentSetting`
is created **whole** — every ERD §3.2 field, including this sub-module's `twilio_account_sid`,
`twilio_auth_token`, `inbound_phone_number` — by sub-module **2.1** in its first migration (confirmed by
`research-agents-2.1.md`: *"Full ERD field set is created in this pass's migration... `2.1`'s own forms/views/
templates touch only the 2.1-bulleted columns"*). 2.2 does not create the row shape; it EXTENDS behaviour on the
same row: a scoped edit form over three already-existing columns, a write-only/encrypted-token contract, and a
`PROVIDER_MODE`-gated external verification (Connection Check) with a mandatory fake implementation. That
combination — encrypted-credential handling plus a provider-adapter-shaped external check, with "a settings form"
as its explicit observable surface — is exactly what CLAUDE.md's CRUD-Completeness **service-sub-module
exemption** describes, not an independent CRUD entity. **Per the invoking brief, only 2.1 adds a model; 2.2, 2.3
and 2.4 all edit different field groups of that same row and add no model.**

**One conditional exception, spelled out up front so it is never confused with "2.2 adds a model":** two schema
defects the research surfaced are specific to the fields THIS sub-module owns and would silently break this
sub-module's two REQUIRED bullets if left as literally specified in the ERD. Both are pre-flight checks against
whatever 2.1 actually built, not new functionality:

1. **`twilio_auth_token` column width.** The ERD's `Char(128)` is a *plaintext* bound. A Fernet-encrypted 32-char
   Twilio auth token serializes to ~140 base64 characters; a 128-char plaintext serializes to ~268. Either blows
   past `Char(128)`. If 2.1's migration used the literal ERD width, this sub-module cannot save an encrypted token
   without truncation/`DataError`.
2. **`inbound_phone_number` global uniqueness must tolerate multiple unconfigured rows.** A plain
   `UniqueConstraint(fields=['inbound_phone_number'])` over a non-nullable `CharField(blank=True, default='')`
   rejects the **second** never-yet-connected location's save, because two blank strings collide under a bare
   unique constraint. Needed: a **conditional** constraint that only applies when the field is non-blank.

**Action:** before writing any 2.2 code, read the actual field defined by 2.1
(`apps/agents/models/<SubModule>/AgentSetting.py`). If both are already correct (width ≥ 512 or `TextField`;
constraint already conditional/partial), this exception is a no-op — check the boxes and move on. If not, 2.2 adds
**one** small migration (`AlterField` + `AlterConstraint`/`RemoveConstraint`+`AddConstraint`) that fixes the shared
row's schema — a defect fix on the existing model, not a new model, and the only migration this sub-module is
permitted to author.

## Models

**NONE.** `agents.AgentSetting` (tenant **and** location scoped, `UniqueConstraint(tenant, location)`) already
exists as of 2.1's build. FKs verified: `tenants.Tenant` (`apps/tenants/models/Tenant.py`), `tenants.Location`
(`apps/tenants/models/Location.py`) — both confirmed present by grep. 2.2 reads/writes exactly three existing
columns on that row:

- `twilio_account_sid` — Char(64), blank. Pre-filled/redisplayed in the edit form (an identifier, not a secret —
  per the ERD's own security note) — **never logged**.
- `twilio_auth_token` — encrypted-at-rest ciphertext column (width per the pre-flight note above). **Write-only**:
  never a `ModelForm` field, never rendered, never in `messages.*`, never logged at any level.
- `inbound_phone_number` — Char(32), E.164, globally unique across **all** tenants (see pre-flight note above).

No child table. No `Transcript`/`Lead`/audit-log table invented to hit a model quota — this sub-module's whole
point is that the quota was already spent by 2.1.

## Backend (apps/agents/… — service sub-module: no CRUD models, but real files)

Sub-module folder for this pass's own layers: `TwilioConnection` (short PascalCase of "2.2 Twilio Connection",
matching the CLAUDE.md example `2.3 Transfer Settings → TransferSettings/`). Entity file name: `AgentSetting.py`
(same entity 2.1 and 2.3 also touch — each sub-module's OWN `forms/views/urls` folder holds its own scoped
form/view/urls for that entity; only the `models/` layer is singular and owned by 2.1).

- [ ] **Pre-flight schema check** (see Shape note above) — read 2.1's actual `AgentSetting.py` and migration;
      if needed, one `apps/agents/migrations/000X_widen_twilio_auth_token_and_fix_inbound_uniqueness.py`:
      - `AlterField('agentsetting', 'twilio_auth_token', models.CharField(max_length=512, blank=True))`
      - Replace the plain `UniqueConstraint(fields=['inbound_phone_number'])` with
        `UniqueConstraint(fields=['inbound_phone_number'], condition=Q(inbound_phone_number__gt=''), name='uniq_agentsetting_inbound_number')`
        (a partial/conditional unique constraint — Django's `UniqueConstraint(condition=...)` — so any number of
        rows may sit at `''` simultaneously; only a non-blank value must be globally unique).
      - **Skip this entire item, unmarked as not-applicable, if 2.1 already built it this way.**
- [ ] `apps/agents/crypto.py` (flat, single-purpose module) — `encrypt_secret(plaintext: str) -> str` /
      `decrypt_secret(ciphertext: str) -> str`, `Fernet(settings.ENCRYPTION_KEY.encode())`. Raises a clear,
      loud `ImproperlyConfigured`-style error at first use if `ENCRYPTION_KEY` is unset or not a valid 32-byte
      url-safe-base64 Fernet key — never silently stores plaintext. `decrypt_secret` is called from exactly two
      places in the whole codebase: `apps/agents/telephony.py`'s connection-check path, and (later) Module 3's
      telephony adapter — **never** from a view that renders to a browser response, never from a template.
- [ ] `apps/agents/telephony.py` (flat, single-purpose module) — the thin `PROVIDER_MODE`-resolved seam:
      - `verify_credentials(account_sid: str, auth_token: str) -> bool`
      - `verify_number_ownership(account_sid: str, auth_token: str, phone_number: str) -> bool`
      - `check_connection(agent_setting) -> ConnectionCheckResult` (small dataclass/NamedTuple:
        `credentials_valid: bool`, `number_found: bool`, `detail: str`) — orchestrates the two calls above,
        decrypting the token internally via `crypto.decrypt_secret`, and is the ONLY function views call.
      - `fake`/`sandbox` (this pass treats `sandbox` identically to `fake`, per research — Module 3 may later
        give `sandbox` a richer meaning): deterministic canned result, **zero network calls** — e.g. "valid" iff
        both `account_sid` and `auth_token` are non-empty and `account_sid` starts with `AC`; "number found" iff
        `agent_setting.inbound_phone_number` is non-blank. No `twilio.rest.Client` construction at all in this path.
      - `live`: constructs `twilio.rest.Client(account_sid, auth_token)`, calls
        `client.api.accounts(account_sid).fetch()` (free, non-billable — 401/`TwilioRestException` code 20003 on
        bad credentials → `credentials_valid=False`), then
        `client.incoming_phone_numbers.list(phone_number=agent_setting.inbound_phone_number)` for ownership
        (empty result → `number_found=False`). Bounded: explicit request timeout, no retry loop (Connection Check
        is a single user-triggered click, not a hot-path call — Realtime Rule 4's bounded-retry is a Module-3
        concern for live-call provider calls, not this button).
      - Docstring/code comment: **explicit handoff note** that this module is a temporary stand-in — when Module 3
        builds `apps/runtime/providers/telephony.py`, that adapter owns the `live`/`fake` split and this file
        becomes a thin caller of it. Do not let Module 3 duplicate the Twilio REST calls written here.
      - `twilio` package already in `requirements.txt` (`twilio>=9.0,<10.0`) — no new dependency for this file.
- [ ] `requirements.txt` — add `cryptography>=42,<50` (confirmed **not** currently listed despite the brief
      assuming it is installed; `crypto.py` needs it). Own commit.
- [ ] `apps/agents/forms/TwilioConnection/AgentSetting.py`:
      - `class AgentSettingTwilioForm(TenantLocationModelForm)` (from `apps.accounts.forms._common` — `AgentSetting`
        is tenant **and** location scoped, so it is never a plain `ModelForm`).
      - `Meta.fields = ('twilio_account_sid', 'inbound_phone_number')` — **`twilio_auth_token` is never in
        `Meta.fields`.**
      - `twilio_auth_token = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False),
        help_text='Leave blank to keep the current token.')` — a plain form field, not model-bound.
      - `clean_inbound_phone_number()`: normalize to E.164 (strip whitespace/punctuation, enforce leading `+`,
        reject anything that doesn't parse as E.164 — a regex check is enough, no external call); then
        `AgentSetting.objects.exclude(pk=self.instance.pk).filter(inbound_phone_number=normalized).exists()`
        **run with no `tenant=` filter at all** (deliberately cross-tenant); on a hit raise ONE generic
        `ValidationError("This number is already connected to another account. Contact support if this is "
        "unexpected.")` — **identical wording** whether the collision is same-tenant (another of this business's
        own locations) or a different tenant. Blank input passes through untouched (unsetting is allowed; the
        DB-level partial-unique constraint from the pre-flight item is what makes two blank rows coexist safely).
      - `save(commit=True)`: `instance = super().save(commit=False)` (stamps tenant/location, does not persist);
        `token = self.cleaned_data.get('twilio_auth_token', '').strip()`; `if token:
        instance.twilio_auth_token = encrypt_secret(token)` — **an empty submission never touches the stored
        ciphertext.** `if commit: instance.save()`.
- [ ] `apps/agents/forms/__init__.py` — extend the re-export block:
      `from .TwilioConnection.AgentSetting import AgentSettingTwilioForm` + add to `__all__`.
- [ ] `apps/agents/views/TwilioConnection/AgentSetting.py`:
      - `_current_agent_setting(request)` helper: guards `request.tenant is None` / `request.location is None`
        (redirect with a message, mirroring `tenants.views.Business.business_settings_edit_view`'s tenant guard
        and pointing the "no location" case at `accounts:my_locations`), then
        `AgentSetting.objects.get_or_create(tenant=request.tenant, location=request.location)` — tolerant of
        build order relative to 2.1 (whichever of 2.1/2.2 a user reaches first still gets a row; every other
        field keeps its model-level default).
      - `twilio_connection_view(request)` — `@login_required`, `@tier_required('owner', 'manager')` (read-only:
        masked status only, no secret ever rendered, so manager-level visibility is safe). Renders
        `has_twilio_auth_token = bool(agent_setting.twilio_auth_token)` (a `bool()` check on the ciphertext column
        computed **in the view**, never a model property doing a decrypt — no model file touched) plus the two
        displayed webhook URLs (see Templates below) into
        `templates/agents/twilio/agentsetting/detail.html`.
      - `twilio_connection_edit_view(request)` — `@login_required`, `@tier_required('owner')` (write access to
        live Twilio credentials is owner-only — stricter than the read view), `@require_http_methods(['GET',
        'POST'])`. `AgentSettingTwilioForm(request.POST or None, instance=agent_setting, request=request)`;
        on valid POST, `form.save()`, `logger.info('Twilio connection updated location_id=%s by user_id=%s',
        agent_setting.pk, request.user.pk)` — **never logs `twilio_account_sid`, `twilio_auth_token`, or the
        submitted `inbound_phone_number`'s validity details beyond the pk**; `messages.success(request, 'Twilio
        connection saved.')`; redirect to `agents:twilio_connection`. Renders
        `templates/agents/twilio/agentsetting/form.html`.
      - `twilio_connection_check_view(request)` — `@login_required`, `@tier_required('owner')`, `@require_POST`,
        HTMX-fragment endpoint (`hx-post`, no CSRF bypass — normal `{% csrf_token %}` inside the form that posts
        it). Calls `telephony.check_connection(agent_setting)`, builds one of three states from the result
        (`credentials_valid=False` → invalid-credentials; `credentials_valid=True, number_found=False` →
        number-not-found; both True → connected) and renders
        `templates/agents/twilio/agentsetting/check.html` as the HTMX-swapped fragment. Copy on every state
        explicitly says **"this does not place a call."** Debounce is client-side only (disable button while
        `hx-request` in flight via `hx-indicator`/`disabled` attr pattern) — no server-side rate limiting needed
        at this scale (documented in research as sufficient).
      - **No LLM tool anywhere in this file.** Connection Check is explicitly not in Module 3's built-in tool set
        (`NavAIReceptionist.md` §3.3) — it is an operator-facing button behind `@tier_required('owner')`, never
        something the voice agent invokes mid-call. State this in a code comment so nobody adds
        `check_twilio_connection` to the tool dispatcher later by analogy.
- [ ] `apps/agents/views/__init__.py` — extend the re-export block:
      `from .TwilioConnection.AgentSetting import (twilio_connection_view, twilio_connection_edit_view,
      twilio_connection_check_view)` + add to `__all__`.
- [ ] `apps/agents/urls/TwilioConnection/AgentSetting.py`:
      ```python
      urlpatterns = [
          path('twilio/', views.twilio_connection_view, name='twilio_connection'),
          path('twilio/edit/', views.twilio_connection_edit_view, name='twilio_connection_edit'),
          path('twilio/check/', views.twilio_connection_check_view, name='twilio_connection_check'),
      ]
      ```
      All three are literal routes (no `<int:pk>` anywhere in this sub-module — see URL design note below), so
      ordering relative to each other is safe; still place them before any later sub-module's `<int:pk>` routes
      in the concatenated `urls/__init__.py` per the first-match-wins rule.
- [ ] `apps/agents/urls/__init__.py` — extend: import this module's `urlpatterns` and concatenate (mirrors
      `apps/tenants/urls.py`'s literal-routes-first pattern; `agents` is not a foundation app, so it keeps the
      `urls/` **package** shape with its own `__init__.py` doing the concatenation, unlike `tenants`' flat file).
- [ ] `apps/agents/admin.py` (existing flat file from 2.1) — **harden, do not newly register**: confirm
      `twilio_auth_token` is excluded from `ModelAdmin.fields`/`fieldsets`/`list_display` entirely (the stored
      value is ciphertext, not plaintext, but "never rendered" is the product rule regardless of which value would
      show); confirm `twilio_account_sid` and `inbound_phone_number` are not in `list_display` in a way that
      encourages copy-paste sharing of a live account identifier. This is an edit to an existing single-purpose
      file, not a new model/migration.
- [ ] `apps/agents/management/commands/seed_agents.py` (existing file from 2.1) — **extend idempotently**: for
      each seeded location's `AgentSetting` row, set `twilio_account_sid` (a recognizable fake value, e.g.
      `'AC' + '0' * 32`), `twilio_auth_token` via `agent_setting.twilio_auth_token = encrypt_secret('fake-auth-token-' + location.slug)` (so the seeder proves the encrypt path works, never a real credential), and a
      **globally-unique** `inbound_phone_number` per location (e.g. `+1813555010{n}` incrementing across ALL
      seeded locations across ALL demo tenants — cross-tenant uniqueness must hold in the seeded data too, or the
      seeder itself would violate the constraint it's supposed to demonstrate). Guard with
      `if agent_setting.twilio_account_sid: continue` per the idempotent-seeder rule. Leave at least one demo
      location's Twilio fields blank to exercise the "Not configured" / partial-unique-constraint path on every
      run. Own commit (one file).

## Realtime & agent surface

- [ ] **No Channels consumer, no `routing.py` entry.** 2.2 is not a live-call surface — the Connection Check is an
      explicit, user-triggered, post-call/config-time button press (per the documented bullet: "reports the
      result WITHOUT placing a call"). State this explicitly rather than leaving it implicit, per the plan
      template's requirement.
- [ ] **No LLM tool.** No `apply_tool_call` dispatcher branch, no tool declaration dict. Confirmed not in Module
      3's built-in tool set. (See the view-file note above — this is deliberately re-stated here too.)
- [ ] **No prompt variables.** 2.2 adds nothing to `AgentSetting.variables` or the reserved runtime-variable
      catalog (that catalog belongs to 2.1). N/A for this sub-module.
- [ ] **Provider adapter method + fake implementation** (the one realtime-adjacent surface this sub-module DOES
      own): `apps/agents/telephony.py::verify_credentials` / `verify_number_ownership` / `check_connection`, as
      detailed in Backend above — fake implementation is the default and ships in the same commit as the live
      path, never a follow-up. This is the sub-module's "thin telephony-control seam," explicitly a stand-in for
      Module 3's later `apps/runtime/providers/telephony.py`.
- [ ] **`CallSession.usage` cost lines: none.** The Connection Check is a free, non-billable Twilio metadata call
      and there is no `CallSession` involved (this isn't a call). Confirm no code path in this sub-module ever
      touches `calls.CallSession` — there shouldn't be an import of it anywhere in `apps/agents/` for 2.2.

## Wire-up

- [ ] `apps/accounts/navigation.py::LIVE_LINKS["2.2"] = {'Twilio Connection': 'agents:twilio_connection'}` — one
      new entry, keyed to the exact `### 2.2 Twilio Connection` heading; points at the read-only overview page
      (`twilio_connection_view`), which needs zero URL args — matches `_resolve()`'s bare `reverse(url_name)` call
      and the existing `tenants:business_settings` / `tenants:location_list` precedent (no other `LIVE_LINKS`
      entry in the codebase takes a required kwarg).
- [ ] **`config/settings.py` / `config/urls.py` / `config/asgi.py` — NOT touched by 2.2.** `apps.agents` is
      installed, mounted and (if it needs ASGI routing at all — it doesn't, 2.2 has no consumer) wired by 2.1's
      brand-new-app run. If, at build time, `apps/agents` is somehow not yet in `INSTALLED_APPS` /
      `config/urls.py`, **stop and build 2.1 first** — 2.2 has no scaffolding responsibility and must not silently
      duplicate or fight 2.1's wire-up.
- [ ] **URL design note (no `<int:pk>` anywhere in this sub-module):** `AgentSetting` is looked up via
      `request.tenant` + `request.location` (the active-location contract, revalidated every request by
      `ActiveLocationMiddleware`), exactly like `tenants:business_settings` uses `request.tenant` with no pk. A
      pk-in-URL design here would be a strictly worse, redundant IDOR surface for a row that is already uniquely
      addressed by session state — do not add one.

## Templates (templates/agents/twilio/agentsetting/ — two-level: submodule `twilio/` → entity `agentsetting/`)

- [ ] `templates/agents/twilio/agentsetting/detail.html` — read-only overview reachable with no pk:
      - Credentials status: `badge-green "Connected"` (has_twilio_auth_token AND twilio_account_sid set) /
        `badge-amber "Partially configured"` (one of the two set) / `badge-muted "Not connected"` (neither) —
        **never** renders `twilio_auth_token` or any substring of it, anywhere, ever.
      - `twilio_account_sid` shown in full (an identifier, not a secret, per the ERD's own note) inside a
        `<code>` element, with a copy-to-clipboard affordance.
      - Inbound number: `{{ agent_setting.inbound_phone_number|phone_e164 }}` (existing `ui` templatetag, already
        used identically in `templates/tenants/location/detail.html`) or a muted "Not set" empty-state.
      - Webhook URL Display: two copy-pasteable strings, computed in the view (not `{% url %}` — the target
        routes don't exist until Module 3):
        `voice_webhook_url = f"{settings.TWILIO_WEBHOOK_BASE_URL}/webhooks/twilio/voice/"` and
        `media_stream_url` = the same base with `https://`→`wss://` / `http://`→`ws://` plus
        `/ws/twilio/media-stream/` — **one shared URL for all locations** (Twilio POSTs the dialed `To` number in
        the request body; the ERD's own resolution mechanism — `AgentSetting.objects.get(inbound_phone_number=
        to_number)` — needs no per-location path segment). Label both clearly: *"Paste this into this number's
        Twilio Console → Voice → A call comes in. (Module 3 is not built yet — this URL will start answering once
        it ships.)"* if `TWILIO_WEBHOOK_BASE_URL` is unset, show a muted placeholder instead of a broken link.
        Copy-to-clipboard is a small vanilla-JS/Alpine snippet, no backend call.
      - "Check connection" button — `hx-post="{% url 'agents:twilio_connection_check' %}"`,
        `hx-target="#twilio-check-result"`, `hx-indicator`, disabled while in flight; explicit helper text above
        the button: **"This does not place a call — it only checks that your Twilio credentials and number are
        recognized."** `<div id="twilio-check-result">` starts empty.
      - Actions: Edit (→ `agents:twilio_connection_edit`, owner-tier gate reflected by hiding the button for
        non-owners rather than showing a dead link), Back to Location (→ `tenants:location_detail` for
        `request.location`, since that's where a tenant naturally arrived from per `_agent_setting_for()`).
- [ ] `templates/agents/twilio/agentsetting/form.html` — SID input, write-only token `PasswordInput` with the
      "leave blank to keep the current token" help text rendered from the form, inbound-number input with E.164
      help text and the exact tenant-blind validation-error message surfaced through normal Django form-error
      rendering (no custom leak-y copy in the template itself). Cancel → `agents:twilio_connection`.
- [ ] `templates/agents/twilio/agentsetting/check.html` — the HTMX-swapped fragment: one of three states
      (`badge-red` "Invalid credentials" / `badge-amber` "Number not found on this account" / `badge-green`
      "Connected") plus one sentence of guidance per state (fix the SID/token vs. fix the number vs. done) and a
      timestamp ("Checked just now" — never persisted, per research's explicit "don't cache the result" call).
      No `{% else %}`-less badge branch — every state maps to a real theme.css class, none invented.

## Verify

- [ ] `manage.py check` passes with `apps.agents` installed (already true from 2.1; re-run after 2.2's files land).
- [ ] **Pre-flight schema check resolved** (widened `twilio_auth_token`, conditional inbound-number uniqueness) —
      confirmed either already correct from 2.1 or fixed by 2.2's one permitted migration; `makemigrations
      apps.agents --check` then reports no further changes.
- [ ] `seed_agents` run twice — idempotent (second run makes zero duplicate rows, zero `IntegrityError` on the
      globally-unique inbound number, zero re-encryption of an already-set token).
- [ ] `PROVIDER_MODE=fake` (the default) — assert `telephony.check_connection()` never constructs
      `twilio.rest.Client` (patch/mock and assert `not_called`) for both `fake` and `sandbox` modes; only under an
      explicitly-set `live` mode (never in tests/dev/seed) does the code path reach the SDK, and even then a test
      mocks the HTTP layer rather than hitting real Twilio.
- [ ] `pytest -q apps/agents` covers:
      - `crypto.py`: encrypt→decrypt round-trip returns the original plaintext; a tampered ciphertext raises
        (Fernet's built-in HMAC check) rather than returning garbage; a missing/invalid `ENCRYPTION_KEY` raises
        loudly at first use, not a silent plaintext fallback.
      - `AgentSettingTwilioForm`: blank `twilio_auth_token` submission leaves `instance.twilio_auth_token`
        byte-for-byte unchanged after `save()`; a non-blank submission replaces it (re-encrypted, and the new
        ciphertext decrypts back to the submitted plaintext); the rendered form never contains any prior
        ciphertext or plaintext token value in its HTML (assert the string is absent from the response body);
        `inbound_phone_number` collision — same-tenant-different-location AND cross-tenant collision both produce
        the **identical** error string (assert equality, not just "an error exists") and neither reveals the
        other row's tenant/location; a malformed number (`"not-a-number"`, empty, absurd length) degrades to a
        clean form error, never a 500.
      - Views: unauthenticated → redirect to login; `staff`-tier → `twilio_connection_view` allowed,
        `twilio_connection_edit_view`/`_check_view` redirected with an error message (owner-only write); `manager`
        tier → same split (read yes, write/check no); a user with `request.location is None` (unassigned or
        between-switch) is redirected to `accounts:my_locations`, never shown another location's row by falling
        through to a stale session value.
      - `twilio_connection_check_view`: fake-mode good SID/blank inbound number → "number not found" state; empty
        SID/token → "invalid credentials" state; fully-seeded row → "connected" state; response body never
        contains the raw or encrypted token.
      - No transcript/log line anywhere in the test run contains a raw token value — grep the captured `caplog`
        output in the test for the plaintext fixture token string and assert it is absent.
- [ ] **Cross-tenant / cross-location isolation** (this sub-module's IDOR-equivalent, since there is no pk in any
      URL — see the URL design note above): log in as `acme_downtown` (single-location manager, per
      `seed_accounts.py`'s `DEMO_USERS`), confirm the Twilio overview/edit pages only ever reflect Downtown's
      `AgentSetting` row, never Uptown's, regardless of query-string tampering (`?location=<uptown-pk>` on any
      of the three URLs is silently ignored — these views read `request.location`, not `request.GET`); confirm
      Globex's inbound numbers/SIDs never appear in any Acme-scoped response body.
- [ ] **Junk payload handling:** POST with missing fields, an overlong `twilio_account_sid`, a Unicode/emoji
      inbound number, and a duplicate-of-an-existing-number all degrade to a normal re-rendered form with field
      errors — zero 500s, zero unhandled exceptions in the server log.
- [ ] `.env.example`'s `ENCRYPTION_KEY` placeholder validated as a real 44-char url-safe-base64 Fernet key (or
      documented as needing local regeneration via `Fernet.generate_key()`) — `crypto.py`'s loud-failure path is
      exercised once against it so a broken example doesn't surface for the first time in someone else's dev setup.
- [ ] `temp/` smoke sweep as `admin_acme` (owner tier, both locations — password `navai-demo-2026`, confirmed by
      reading `apps/accounts/management/commands/seed_accounts.py::DEMO_PASSWORD` rather than assumed): all three
      `agents:twilio_connection*` URLs return 200/302 as expected; page titles present; no `{#`/`{% comment`
      leaks; the seeded fake SID/inbound-number are visible, the seeded fake token is NOT (grep the rendered HTML
      for the seeder's known fake-token string and assert absence).
- [ ] Sidebar shows **2.2 Live** under Module 2, linking to the Twilio Connection overview page.

## Close-out

- [ ] Review agents, in order: `code-reviewer` → `explorer` → `frontend-reviewer` → `performance-reviewer` →
      `realtime-reviewer` → `qa-smoke-tester` → `security-reviewer` (this sub-module is the highest-value target
      for it — encrypted credential handling, write-only forms, tenant-blind collision copy) → `test-writer`.
- [ ] **Update** (do not re-author) `.claude/skills/agents/SKILL.md` — it should already exist from 2.1's
      brand-new-app run. Add this sub-module's routes (`agents:twilio_connection`, `_edit`, `_check`), the
      `crypto.py`/`telephony.py` service modules, the admin hardening note, and the seeder extension to the
      existing document — never overwrite 2.1's Models/Overview sections.
- [ ] README — note if the module-level README needs a one-line mention of the new Twilio-connection settings
      page; skip if the README doesn't track per-sub-module detail.

## Later passes / deferred (carried from research-agents-2.2.md)

- **Credential-change email notice** (the `0.2`-style account-takeover tripwire applied to Twilio credentials) —
  deferred until `apps.agents` can confirm `send_credential_change_notice`-style plumbing is cleanly reusable from
  outside `accounts`; not part of this pass's four required bullets.
- **Audit log of credential changes** — no model budget under the eleven-model ceiling; revisit only if a
  product-wide activity-log sub-module is ever explicitly scoped.
- **Auto-configuring the Twilio number's Voice URL via the Twilio API** (ElevenLabs-style write-not-just-display)
  — the documented bullet specifies display, not write; explicitly out of this pass's scope.
- **Caching the last Connection Check result** (a "last verified at" field/badge) — would need a new field or a
  `metadata`-style JSON column the ERD doesn't define for `AgentSetting`; the check is cheap enough to re-run live
  instead.
- **A real `sandbox` `PROVIDER_MODE` behavior** distinct from `fake` for the telephony seam — this pass treats
  them identically; a genuine sandbox (e.g., Twilio Test Credentials against the real API) is better scoped once
  Module 3's provider adapters exist.
- **SIP trunking / multi-provider telephony / self-service number provisioning** — out of scope for the product's
  seven capabilities entirely, not just deferred.
- Everything belonging to sibling sub-modules on the same row: enable/voice/greeting/prompt/variables (**2.1**),
  transfer enable/targets/hours/keywords (**2.3**), the placed test call and setup-readiness gate (**2.4**), and
  the real webhook endpoint / signature verification / media-stream consumer / live telephony adapter home
  (**Module 3**, `3.1`–`3.2`).

## Review notes
(filled in at the end)
