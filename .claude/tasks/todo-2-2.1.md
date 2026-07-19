---
# Sub-module 2.1 — Per-Location Agent Configuration (Module 2: Agent Setup & Telephony, `agents`) — plan from research-agents-2.1.md (2026-07-19)

## Shape: CRUD — the ONLY model/migration in Module 2

`agents.AgentSetting` does not exist anywhere yet (`grep -rn "^class AgentSetting" apps/` → zero hits; `apps/agents`
does not exist at all — confirmed via `Glob apps/**`, only `accounts` and `tenants` present). This sub-module
**creates the app from nothing** and owns the app's **one and only model**. **2.1 is the ONLY sub-module in Module
2 that adds a model or a migration.** 2.2 (Twilio Connection), 2.3 (Transfer Settings) and 2.4 (Test Call) all edit
**different field groups of this same row** — `unique(tenant, location)` means there is exactly one
`AgentSetting` per location for the whole app's lifetime — and add **zero models, zero migrations**. Per the
research's explicit recommendation, the **full ERD field set is created in this pass's single migration** (it is
one table the whole app reuses across 2.1–2.3), but **this sub-module's own forms/views/templates touch only**:
`enabled`, `voice_provider`, `greeting`, `prompt_text`, `variables`.

**Deliberate deviation from the default list→create→detail→edit→delete CRUD chain, matching an existing
precedent exactly:** `AgentSetting` gets **no list page, no separate create view, no delete view** — only a
read-only Setup page and an Edit form, mirroring `tenants` sub-module 1.1's `Business Settings`
(`tenants:business_settings` / `business_settings_edit`, no pk in any URL). This is correct, not a gap, because:
- There is exactly **one row per (tenant, location)**, and `request.location` (the session's active location,
  already validated against `UserLocation` by `ActiveLocationMiddleware`) **is** the disambiguator. The research's
  own framing: *"makes 'the location's agent' an unambiguous lookup... never a list to disambiguate."* A list page
  would be a list of exactly the rows the location switcher already picks between — CLAUDE.md's CRUD-completeness
  chain is triggered by *a list page*, and there genuinely is nothing to list here (an owner switches location via
  the existing 0.4 switcher to reach a different site's Setup page, exactly like they already do for every other
  location-scoped surface).
- **No pk ever appears in a 2.1 URL.** This removes an entire IDOR class by construction rather than by a
  `get_object_or_404(..., tenant=..., location=...)` guard — there is no id to substitute.
- **"Create" is auto-provisioning, not a form**: the Setup view `get_or_create(tenant=request.tenant,
  location=request.location, defaults={'enabled': False, 'voice_provider': 'live'})`s the row on first visit —
  the research's own "Auto-provision an empty (disabled) row... on first visit to Setup" bullet.
- **No delete**: an agent configuration is disabled via the `enabled` toggle (already in scope), never removed —
  there is no reason to ever destroy a location's one configuration row.

## Models (from research — 1, the whole app's ceiling)

- [ ] **`agents.AgentSetting`** — tenant **AND** location scoped (`TenantLocationOwned`), `unique(tenant,
  location)`. FKs: `tenants.Tenant`, `tenants.Location` (both **verified** —
  `apps/tenants/models/Tenant.py`, `apps/tenants/models/Location.py`). Full ERD §3.2 field set, created in this
  pass's one migration:
  - `enabled` (Bool, default `False`) — **Enable Toggle & Voice Mode**: the master switch; Module 3 will read it
    before connecting the media stream. **2.1-owned field — in the form.**
  - `voice_provider` (Char(16), choices `live`/`google`/`gemini`, default `live`) — **Enable Toggle & Voice Mode**:
    selects the STT+LLM+TTS pipeline Module 3 will later branch on. **2.1-owned field — in the form.**
  - `greeting` (Text, blank) — **Deterministic Greeting**: spoken on connect with zero LLM round trip
    (CLAUDE.md Realtime Rule 5); `{{var}}`-aware via `render_template()`. **2.1-owned field — in the form.**
  - `prompt_text` (Text, blank) — **Prompt Authoring**: the full system prompt the LLM reasons over every turn.
    **2.1-owned field — in the form.**
  - `variables` (JSON dict, default `{}`) — **Prompt Variables**: the admin's own `{{var}}` substitution map,
    merged with server-computed reserved names at render time. **2.1-owned field — in the form.**
  - `inbound_phone_number` (Char(32), E.164, `unique=True`, **globally unique across ALL tenants**) — belongs to
    **2.2**. Declared `null=True, blank=True` (a deliberate, explicit departure from the ERD's bare "Char(32),
    blank" notation): a `CharField(unique=True)` with many rows holding `''` collides on the very first duplicate
    (MySQL treats `''` as one value, not "unset"), whereas `NULL` is the correct "not yet configured" sentinel and
    every `NULL` is independently distinct under a unique index on both MySQL and SQLite. **Excluded from 2.1's
    form** — 2.2 builds the write UI, the webhook-URL display and the connection check.
  - `twilio_account_sid` (Char(64), blank, default `''`) — belongs to **2.2**. **Excluded from 2.1's form.**
  - `twilio_auth_token` (Char(128), blank, default `''`) — belongs to **2.2**, and is **encrypted at rest from
    this very migration** (the research's REQUIRED security item: a plaintext-then-retrofit column is the exact
    anti-pattern CLAUDE.md's Vulnerability section forbids). Implemented as a custom `EncryptedCharField`
    (Fernet, `settings.ENCRYPTION_KEY`) in `apps/agents/models/_base.py` — see Backend section.
    **Excluded from 2.1's form, from `admin.py` list/detail display, and from every log line, unconditionally.**
  - `transfer_enabled` (Bool, default `False`) — belongs to **2.3**. **Excluded from 2.1's form.**
  - `transfer_phone_number`, `transfer_secondary_number` (Char(32), blank, default `''`) — belong to **2.3**.
    **Excluded from 2.1's form.**
  - `transfer_timezone` (Char(100), IANA, default `"America/Chicago"`) — belongs to **2.3**. **Excluded.**
  - `transfer_working_hours` (JSON dict, default `{}`) — belongs to **2.3**. **Excluded.**
  - `transfer_keywords` (JSON list, default `[]`) — belongs to **2.3**. **Excluded.**
  - Excluded from every form regardless of owning sub-module: `tenant`, `location` (stamped from
    `request.tenant` / `request.location` by `TenantLocationModelForm`, never posted), `created_at`, `updated_at`.
  - Constraints: `models.UniqueConstraint(fields=['tenant', 'location'], name='uniq_agentsetting_tenant_location')`.
  - `__str__`: `f'{self.location.name} agent'`.

## Backend (`apps/agents/{models,forms,views,urls}/PerLocationAgentConfiguration/` — `agents` is NOT a foundation
## app, so it DOES carry the sub-module folder, unlike `accounts`/`tenants`)

- [ ] `apps/agents/apps.py` — `AgentsConfig`, `name = 'apps.agents'`, `label = 'agents'`.
- [ ] `apps/agents/__init__.py`
- [ ] `apps/agents/models/_base.py` — re-exports `apps.accounts.models._base` (`TimeStamped`, `TenantOwned`,
      `TenantLocationOwned`, …) exactly as `apps/tenants/models/_base.py` does, **plus** a new
      `EncryptedCharField(models.CharField)`: `get_prep_value()` encrypts with
      `cryptography.fernet.Fernet(settings.ENCRYPTION_KEY.encode())` before writing,
      `from_db_value()`/`to_python()` decrypts on read, degrading a blank/`None` value straight through with no
      Fernet call (so an unconfigured token stays `''`, never `Fernet(b'').encrypt(b'')`). Add `'EncryptedCharField'`
      to `__all__`.
- [ ] `apps/agents/models/PerLocationAgentConfiguration/AgentSetting.py` — the model, using
      `from apps.agents.models._base import *`.
- [ ] `apps/agents/models/__init__.py` — `from apps.agents.models.PerLocationAgentConfiguration.AgentSetting
      import AgentSetting` + `__all__ = ['AgentSetting']`.
- [ ] `apps/agents/forms/_common.py` — re-exports `apps.accounts.forms._common` (`TenantModelForm`,
      `TenantLocationModelForm`, `style_widgets`, …), matching `apps/tenants/forms/_common.py`.
- [ ] `apps/agents/forms/PerLocationAgentConfiguration/AgentSetting.py` — `AgentSettingForm(TenantLocationModelForm)`:
  - `Meta.fields = ('enabled', 'voice_provider', 'greeting', 'prompt_text', 'variables')`.
  - `variables` rendered as a `forms.CharField(widget=forms.Textarea)` bound to the JSON field (parse/dump
    JSON by hand in `clean_variables()`/`__init__()` rather than the raw `JSONField` widget, so a malformed
    JSON body degrades to a field error, never a 500).
  - `clean_variables()` — `json.loads()` guarded (`ValidationError` on malformed JSON, never raises unguarded);
    requires a flat `dict` of string/number/bool leaf values (no nested objects — the substitution function is a
    flat string replacer); rejects any key colliding with `RESERVED_RUNTIME_VARIABLE_NAMES`
    (**Reserved-name collision guard**, listing the offending key(s)).
  - `clean()` — **Reject unknown placeholders at save time**: regex-extract every `{{identifier}}` token out of
    `greeting` **and** `prompt_text` combined, diff against
    `set(cleaned_data['variables'].keys()) | RESERVED_RUNTIME_VARIABLE_NAMES`; any token outside that union is a
    hard `ValidationError` naming every offending token (not just the first). An untemplated string (zero
    `{{...}}` tokens) is valid — **Untemplated-string safety**, no special-casing needed since the regex simply
    finds nothing.
  - Uses `apps.agents.services.extract_variable_names` / `RESERVED_RUNTIME_VARIABLE_NAMES` — no regex duplicated
    between the form and the service module.
- [ ] `apps/agents/forms/__init__.py` — `from apps.agents.forms.PerLocationAgentConfiguration.AgentSetting import
      AgentSettingForm` + `__all__ = ['AgentSettingForm']`.
- [ ] `apps/agents/views/_common.py` — re-exports `apps.accounts.views._common` + `tier_required`/
      `safe_redirect_target` from `apps.accounts.views._helpers`, plus a local
      `MANAGEMENT_TIERS = ('owner', 'manager')` (mirroring `apps/tenants/views/_common.py` — prompt/greeting text
      is spoken to every caller and reasoned over by the LLM, so it is gated exactly like Location and Business
      Settings, not left to `@login_required` alone).
- [ ] `apps/agents/views/PerLocationAgentConfiguration/AgentSetting.py`:
  - `agent_setup_view(request)` — `@login_required @tier_required(*MANAGEMENT_TIERS)`. Guards
    `request.location is None` → `messages.error(...)` + redirect to `accounts:dashboard` (mirrors
    `business_settings_edit_view`'s `tenant is None` guard). `AgentSetting.objects.get_or_create(tenant=
    request.tenant, location=request.location, defaults={'enabled': False, 'voice_provider': 'live'})` —
    **auto-provision on first visit**. Renders a read-only overview **plus the rendered preview** (Prompt
    Authoring's "rendered preview before saving" — here shown as "preview as currently saved") built from
    `render_template(obj.greeting/prompt_text, {**sample_runtime_context(request.location, obj), **obj.variables})`.
  - `agent_setup_edit_view(request)` — `@login_required @tier_required(*MANAGEMENT_TIERS)
      @require_http_methods(['GET', 'POST'])`. Same `get_or_create` fetch, binds `AgentSettingForm`. On valid POST:
    save, `messages.success`, redirect to `agents:agent_setup`. Logs `logger.info('AgentSetting updated
    agent_setting_id=%s location_id=%s by user_id=%s', ...)` — **never** logs `greeting`/`prompt_text`/`variables`
    content (PII/business-logic caution, matching the project's transcript-body logging rule in spirit).
  - `agent_setup_preview_view(request)` — `@login_required @tier_required(*MANAGEMENT_TIERS) @require_POST`.
    HTMX endpoint: reads **unsaved** `greeting`/`prompt_text`/`variables` straight off `request.POST` (the
    in-progress edit, not the saved row), parses `variables` defensively (bad JSON → treated as `{}` for the
    preview only, never a 500 — the *save* path is what enforces the hard validation), merges with
    `sample_runtime_context(request.location)`, runs `render_template()` on both fields, returns the
    `agents/setup/preview.html` fragment. This is the research's "Rendered preview before saving" bullet.
- [ ] `apps/agents/views/__init__.py` — re-exports all three view functions.
- [ ] `apps/agents/urls/PerLocationAgentConfiguration/AgentSetting.py` — three literal routes, no `<int:pk>`
      anywhere in this sub-module (see Shape justification above):
      `path('setup/', ..., name='agent_setup')`, `path('setup/edit/', ..., name='agent_setup_edit')`,
      `path('setup/preview/', ..., name='agent_setup_preview')`.
- [ ] `apps/agents/urls/__init__.py` — `app_name = 'agents'`; concatenates the entity module's `urlpatterns`
      (only one entity this pass, but keep the concatenation shape so 2.2/2.3's own url modules — `twilio/`,
      `transfer/` segments on the SAME model — append cleanly without reordering these three literals).
- [ ] `apps/agents/admin.py` — register `AgentSetting`. `list_display` excludes `twilio_auth_token` entirely;
      add a masked read-only method (`token_status(self, obj): return 'set' if obj.twilio_auth_token else
      'not set'`) if any Twilio-flavoured field is shown at all — **the raw token value is never displayed in
      Django admin**, matching the "write-only, never rendered" rule even though this admin's audience is
      platform staff, not tenant users.
- [ ] `apps/agents/services.py` — the shared, provider-free substitution toolkit Module 3 will import verbatim:
  - `RESERVED_RUNTIME_VARIABLE_NAMES = frozenset({'location_name', 'business_name', 'location_address',
      'location_timezone', 'from_number', 'to_number', 'current_date', 'current_time', 'is_open_now'})`.
  - `TOKEN_RE = re.compile(r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}')` — flat `{{identifier}}` only, **no**
      Django template engine (no `{% %}` tags, no filters, no attribute-lookup chains) — the research's explicit
      security/correctness finding: admin-authored text is semi-trusted, not developer-trusted.
  - `extract_variable_names(text: str) -> set[str]` — every distinct token name found.
  - `render_template(text: str, values: dict) -> str` — regex substitution; a token **not** present in `values`
      is left as the literal `{{token}}` (used by the live, not-yet-validated preview path; the save-time
      validator is what turns an unknown token into a hard error, so by the time this runs against a *saved* row
      every token is guaranteed resolvable).
  - `sample_runtime_context(location, agent_setting=None) -> dict` — `location_name=location.name`,
      `business_name=location.tenant.name`, `location_address=location.full_address`,
      `location_timezone=location.timezone`, `from_number='+15555550100'` (documented sample), `to_number=
      (agent_setting.inbound_phone_number if agent_setting and agent_setting.inbound_phone_number else
      '+15555550199')`, `current_date`/`current_time` from `location.local_now()`, `is_open_now='yes'`
      (**documented fallback — no `Location`-level business-hours field exists yet**, see Deferred).
- [ ] Re-export blocks double-checked in all four `__init__.py` — a model/form/view added without its re-export
      line is an `ImportError`/`AttributeError` at runtime, not a lint warning.
- [ ] `makemigrations agents` → `apps/agents/migrations/0001_initial.py` (+ `migrations/__init__.py`).
- [ ] `apps/agents/management/__init__.py`, `apps/agents/management/commands/__init__.py`,
      `apps/agents/management/commands/seed_agents.py` — **new command** (this app's first seeder):
      idempotent (`get_or_create` on `(tenant, location)`, `if AgentSetting.objects.filter(tenant=tenant,
      location=location).exists(): skip` pattern), reuses the four `Location` rows `seed_tenants` already
      created (Acme Downtown/Uptown, Globex Riverside/Lakeside — **CLAUDE.md Seed rule 6**, already satisfied by
      the existing multi-location seed data). Seeds the **whole row** for realism/reuse by 2.2–2.4 (not just the
      2.1-owned fields): `enabled` mixed True/False across the four rows (at least one disabled, proving the
      toggle is real), `voice_provider` mixed across `live`/`google`/`gemini`, a distinct `greeting` and
      `prompt_text` per location using `{{location_name}}`/`{{business_name}}`/`{{from_number}}` tokens plus one
      admin-defined custom `variables` key per row (e.g. `{"clinic_specialty": "general dentistry"}`), a
      **distinct fake E.164** `inbound_phone_number` per row (proves the global-uniqueness constraint holds
      across tenants — Acme and Globex numbers are never adjacent/copy-pasted), placeholder
      `twilio_account_sid`/`twilio_auth_token` (fake-format `AC` + 32 hex chars / a random 32-byte token —
      round-trips through `EncryptedCharField` so the encrypted-at-rest path is exercised by the seeder itself),
      `transfer_*` fields left at their model defaults (2.3's job to seed meaningfully). Prints, after seeding:
      which four `(tenant, location)` rows now exist, their `enabled`/`voice_provider` values, and a reminder
      that `admin_acme`/`acme_downtown` (from `seed_accounts`) can view/edit them once logged in and switched to
      the matching location. Never touches a real provider — `PROVIDER_MODE=fake` is implicit since nothing here
      calls out to Twilio at all.

## Realtime & agent surface

**No Channels consumer, no `routing.py` entry, no LLM tool in this sub-module** — `apps/runtime` (Module 3) does
not exist yet, and 2.1's job is to define the row and the shared render function Module 3 will later import
verbatim, not to run it on a live call.

- [ ] Prompt variables: `apps.agents.services.RESERVED_RUNTIME_VARIABLE_NAMES` (9 names, see Backend section)
      defined here as the reserved catalog; **the prompt/greeting name no tool and no tool parameter** — these are
      plain string substitutions applied server-side before the model or the caller sees anything, never an LLM
      tool call. Static-at-setup vs. must-recompute-per-turn is **documented here, enforced in Module 3**:
      `location_name`/`business_name`/`location_address`/`location_timezone`/`from_number`/`to_number` are safe
      to freeze once at call setup; `current_date`/`current_time`/`is_open_now` **must** be recomputed every turn
      by Module 3's turn loop — 2.1 only defines that these names exist and what they mean.
  - **Trace through BOTH runtime paths (explicit item, even though neither path exists yet):** (1) the
    deterministic greeting render at `connect()` — zero LLM tokens, computed once from `AgentSetting.greeting`;
    (2) the system-prompt render at session start and on every `current_date`/`current_time`/`is_open_now`
    boundary crossing — costs the turn's normal LLM tokens, computed from `AgentSetting.prompt_text`. Both paths
    call the **same** `apps.agents.services.render_template()` this sub-module ships; Module 3 does not
    reimplement substitution.
- [ ] Provider adapter: **none added.** `apps/runtime/providers/` does not exist yet and 2.1 must not import a
      module that isn't there. `PROVIDER_MODE` has no bearing on 2.1 — there is no Twilio/STT/TTS/LLM call
      anywhere in this sub-module's scope (that starts at 2.2's Connection Check and 2.4's Test Call).
- [ ] `CallSession.usage` cost lines: **none.** 2.1 makes no provider call and appends nothing to
      `calls.CallSession.usage` (that model doesn't exist yet either — Module 5). Authoring-time preview is pure
      local string substitution: zero LLM tokens, zero API cost, at save time AND at preview time. Contrast:
      the runtime render of `prompt_text` at actual call time (Module 3) is what costs LLM tokens later — the
      `greeting` render costs **zero** tokens even then, per CLAUDE.md Realtime Rule 5.

## Wire-up

- [ ] `apps/accounts/navigation.py::LIVE_LINKS['2.1'] = {'Agent Setup': 'agents:agent_setup'}` — points at the
      STAFF-facing Setup page, matching the label style already used for 1.1 (`'Business Settings'`) and 1.2
      (`'Locations'`) — a short, page-derived label, not a verbatim bullet copy.
- [ ] `config/settings.py::INSTALLED_APPS` — add `'apps.agents',` under a new `# Module 2 — Agent Setup &
      Telephony` comment, directly after the `apps.tenants` line (brand-new-app run — this app does not exist
      yet).
- [ ] `config/urls.py` — `path('agents/', include('apps.agents.urls'))`, inserted **after** the `manage/`
      (`apps.tenants`) include and **before** the trailing `path('', include('apps.accounts.urls'))` (accounts
      owns the root and must stay last, exactly as the file's own comment already states).
- [ ] `config/asgi.py` — **no change.** 2.1 has no websocket surface; `websocket_urlpatterns` stays empty until
      Module 3. Do not add a placeholder route for an app that doesn't consume it.
- [ ] `AUTH_USER_MODEL` ordering item: **not applicable this run** — `AUTH_USER_MODEL = 'accounts.User'` was
      already declared and migrated in Module 0. This is not the first `makemigrations` of the whole project;
      noted only so the checklist doesn't silently skip a mandatory item.

## Templates (`templates/agents/setup/` — single-entity sub-module, the `setup/` folder IS the entity folder
## per CLAUDE.md Template Folder Structure rule 3; sub-module slug taken from CLAUDE.md's own listed set for
## `apps/agents`: `setup/ twilio/ transfer/`)

- [ ] `templates/agents/setup/detail.html` — read-only Setup overview for `request.location`: `enabled` badge
      (`badge-green` when true / `badge-muted` when false — no semantic "on/off" badge class exists, reuse the
      closed colour set), `voice_provider` display value, `greeting`/`prompt_text` shown **as saved** alongside
      their rendered preview (via the view-computed context, not a live HTMX call on this page), the `variables`
      map as a small key/value table, an Edit button gated the same as the view (`{% if user.tier in
      management_tiers %}` passed from context, mirroring how `business/detail.html` gates its Edit link on
      `can_edit`). Empty-state copy when `greeting`/`prompt_text` are blank ("No greeting configured yet — the
      caller will hear dead air until one is set" style warning), per the `partials/_empty_state.html` pattern
      but inline (this is a single-object page, not a list).
- [ ] `templates/agents/setup/form.html` — the edit form (`{% extends "base.html" %}`, `enabled`/`voice_provider`/
      `greeting`/`prompt_text`/`variables` fields via `AgentSettingForm`), an HTMX-wired "Preview" button
      (`hx-post="{% url 'agents:agent_setup_preview' %}" hx-target="#preview-panel"`) posting the live textarea
      values and swapping in the fragment, `{% csrf_token %}`, Save/Cancel actions, help text on `variables`
      listing the 9 reserved names so an admin never has to guess why save was rejected.
- [ ] `templates/agents/setup/preview.html` — the HTMX fragment returned by `agent_setup_preview_view`: rendered
      greeting text and rendered prompt text side by side, each token that resolved shown plain, no raw
      `{{...}}` left visible for a token that WAS resolved (an unresolved one only appears in this fragment when
      the in-progress edit has a typo not yet caught by save-time validation — intentional early feedback).
- [ ] No `list.html`, no separate `create` page, no `delete` template — see Shape justification. No
      `templates/agents/overview.html` landing page either; the sidebar's own sub-module row plus the single
      `LIVE_LINKS['2.1']` link is the whole navigable surface for this pass.

## Verify

- [ ] `makemigrations agents` produces exactly one new migration; `migrate` applies cleanly against MySQL
      (`navai_receptionist`) AND the SQLite test DB.
- [ ] `seed_agents` ×2 — second run reports "already exists" / performs zero inserts (idempotent), still exactly
      4 `AgentSetting` rows after two runs.
- [ ] `manage.py check` — clean.
- [ ] `PROVIDER_MODE=fake` assertion: `config.settings_test` already pins it; explicit regression test/grep that
      `apps/agents` (this pass) imports **no** Twilio/`requests`/`httpx` SDK anywhere — there is nothing in 2.1's
      scope that could reach a real provider even if misconfigured, and the test proves that by absence, not by
      mocking.
- [ ] `pytest -q apps/agents`:
  - **Model** — `unique(tenant, location)` violated → `IntegrityError`/`ValidationError`; two different
    tenants' rows CAN share nothing else but genuinely differ on `inbound_phone_number`; saving a **second**
    `AgentSetting` (different tenant, different location) with the **same** `inbound_phone_number` as an
    existing row → `IntegrityError` (proves the "globally unique across ALL tenants" ERD constraint is real, not
    accidentally scoped per-tenant); `EncryptedCharField` round-trip — set `twilio_auth_token`, reload from DB,
    the raw column value on disk (raw SQL / `.values_list()` on the underlying column) is **never** equal to the
    plaintext, `obj.twilio_auth_token` after reload IS the original plaintext.
  - **Services** — `extract_variable_names()` finds all tokens incl. duplicates-deduped; `render_template()`
    substitutes known tokens and leaves unknown ones literal; `sample_runtime_context()` always includes all 9
    reserved names, `is_open_now` is always `'yes'`.
  - **Form** — unmatched `{{typo}}` in `greeting` or `prompt_text` → `ValidationError` naming the token; a
    `variables` key equal to a reserved name (e.g. `current_time`) → `ValidationError`; malformed `variables`
    JSON → field error, not an exception; an untemplated `greeting`/`prompt_text` (no `{{...}}` at all) → valid.
  - **Views** — first GET to `agent_setup` **auto-provisions** a disabled row (`enabled=False`,
    `voice_provider='live'`) when none exists; edit POST with valid data saves and redirects; preview POST
    returns 200 with substituted text in the fragment; a `staff`-tier user hitting `agent_setup`/`agent_setup_edit`
    is redirected with an error message (not a 500, not silently allowed through).
- [ ] Twilio webhook signature/idempotency check: **N/A this sub-module** — no webhook exists until Module 3.1;
      explicitly recorded so this checklist item isn't silently missing rather than deliberately skipped.
- [ ] Websocket connect/reject check: **N/A this sub-module** — no consumer exists until Module 3; same rationale.
- [ ] Cross-**tenant** IDOR: no pk ever appears in a 2.1 URL, so the attack surface is entirely
      `request.tenant`/`request.location` scoping. Log in as an Acme user, confirm `agent_setup` renders ONLY
      Acme-Downtown's row (never Globex's greeting/prompt/variables, even though both exist in the same table);
      assert the response never contains Globex's seeded greeting text.
- [ ] Cross-**location** IDOR: log in as `acme_downtown` (single-location manager, per `seed_accounts`), confirm
      `agent_setup` shows Downtown's row; confirm the existing 0.4 switcher infrastructure (already shipped,
      re-verified here rather than re-implemented) refuses a switch to Uptown for this user, so there is no path
      by which this sub-module's `request.location` could ever resolve to a location the user isn't assigned to.
- [ ] Junk-payload degradation: POST `agent_setup_edit` with an invalid `voice_provider` choice → field error,
      not 500; POST with unbalanced/garbage JSON in `variables` → field error, not 500; POST `agent_setup_preview`
      with the same garbage JSON → 200 with the fragment treating `variables` as empty for preview purposes only
      (never a 500); POST without a CSRF token → 403 (Django default, re-verified for this view).
- [ ] `twilio_auth_token` never appears in any rendered response, any log line emitted by this sub-module's
      views, or in a `messages.*` call — grep-style assertion over the `agent_setup`/`agent_setup_edit` responses'
      full rendered HTML AND over captured log output during the edit-save test.
- [ ] `temp/` smoke as `admin_acme` (password from `seed_accounts.DEMO_PASSWORD`, printed at the end of its run):
      GET `agents:agent_setup` → 200, title present, seeded/auto-provisioned Downtown values shown, no `{#`/
      `{% comment` leaks; GET `agents:agent_setup_edit` → 200, form pre-filled with the saved values; POST a
      valid edit → 302 + success message + persisted change; POST `agents:agent_setup_preview` → 200 fragment
      with `{{location_name}}` resolved to "Acme Downtown"; switch active location to Uptown via the existing
      0.4 switcher → `agent_setup` now shows **Uptown's own, distinct** seeded greeting/prompt (proves location
      scoping, not just tenant scoping); log in as `acme_downtown` → `agent_setup` reachable (200) for Downtown
      only.
- [ ] Sidebar shows `2.1` Live — `LIVE_LINKS['2.1']` resolves, Module 2's row switches from greyed-out roadmap
      to a live link in `build_sidebar()`.

## Close-out

- [ ] Review agents, in order: `code-reviewer` → `explorer` → `frontend-reviewer` → `performance-reviewer` →
      `realtime-reviewer` (expect "no realtime surface in this sub-module" as its finding, not a defect) →
      `qa-smoke-tester` → `security-reviewer` (encrypted-token handling + global-uniqueness + IDOR-by-construction
      are the load-bearing findings to confirm) → `test-writer`.
- [ ] **Author** `.claude/skills/agents/SKILL.md` — brand-new-app run, so this is authored fresh (not an update):
      `name: agents`, trigger description covering "agent config, greeting, prompt, Twilio, transfer, test call —
      apps/agents or templates/agents, or /agents"; document `AgentSetting`'s full field set (flagging which
      sub-module owns which fields), the three 2.1 routes, `templates/agents/setup/`, the
      `render_template`/`sample_runtime_context`/`RESERVED_RUNTIME_VARIABLE_NAMES` service surface, "this module
      has no realtime surface yet — Module 3 will add one", `seed_agents`, and the `LIVE_LINKS['2.1']` entry.
      Leave clearly-marked placeholders/TODO subsections for 2.2 (Twilio Connection), 2.3 (Transfer Settings) and
      2.4 (Test Call) so their runs **update** this file rather than needing to guess its shape.
- [ ] Update root `README.md`'s "what's built / what's planned" table — move `apps/agents` (at least
      `AgentSetting`, `seed_agents`, and 2.1's views/templates) out of the "planned" column now that it exists;
      Module 2 catalog row's status note updated to reflect 2.1 built, 2.2–2.4 still planned.

## Later passes / deferred

- **2.2 Twilio Connection** — `twilio_account_sid`/`twilio_auth_token` write-only form (never round-tripping the
  secret, "set / not set" indicator only), `inbound_phone_number` binding UI, webhook URL display, Connection
  Check against Twilio (still never placing a call).
- **2.3 Transfer Settings** — `transfer_enabled`, `transfer_phone_number`, `transfer_secondary_number`,
  `transfer_timezone`, `transfer_working_hours`, `transfer_keywords` forms/views.
- **2.4 Test Call** — placed test call, fake-mode test path, setup-readiness check (flags a missing
  greeting/prompt/inbound number/transfer target before a tenant tries a real call).
- **Module 3 (`runtime`)** — the actual server-side render of `greeting`/`prompt_text` at call connect time,
  per-turn recomputation of `current_date`/`current_time`/`is_open_now`, `CallSession.mode` mirroring
  `AgentSetting.voice_provider`, the `get_business_info` LLM tool (complementary to, not a replacement for,
  2.1's injected variables), and Module 3.5's consent-gating logic (deciding *whether* recording actually
  starts — 2.1 only established that the disclosure wording's authoring surface is `greeting`, not a new field).
- **A real `is_open_now`** — needs a `tenants.Location` business-hours field, which is a foundation-app
  migration outside this sub-module's ownership. `is_open_now` stays hardcoded `'yes'` in
  `sample_runtime_context()` (and, later, in Module 3's per-turn computation) until that field exists; the admin
  only ever references the variable name, so no prompt-authoring change is needed when it lands.
- **Prompt version history/rollback** — needs a new revision-history table; violates the zero-second-model
  constraint for this pass. Deferred until there's a concrete requirement.
- **Voice/tone style preset chips, prompt-engineering starter templates** — editor-polish, not requested by any
  bullet; deferred as differentiator-tier.
- **Prompt A/B testing** — out of scope for the product; no experimentation capability among the seven documented
  capabilities.

## Review notes
(filled in at the end)
