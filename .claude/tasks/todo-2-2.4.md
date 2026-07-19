---
# Sub-module 2.4 — Test Call (Module 2: Agent Setup & Telephony, `agents`) — plan from research-agents-2.4.md (2026-07-19)

## Shape: SERVICE sub-module — adds NO model and NO migration

2.4 reuses `agents.AgentSetting` (the ONE model Module 2 owns — created by sibling **2.1 Per-Location Agent
Configuration**) strictly **read-only**, plus one new derived **method** on that existing model,
`has_twilio_auth_token()` — a presence-check, never a field, never a schema change. 2.1, 2.2 and 2.3 each edit a
different field group of that same row; 2.4 edits none of its fields at all — it only reads. There is no CRUD
entity of 2.4's own: it ships a telephony-control seam (`telephony.py`), a pure readiness-check function
(`readiness.py`), and one action page (readiness banner + "place a test call" trigger), exactly the "diagnostics
page / settings form" observable surface the service-sub-module exemption requires. `makemigrations agents --check`
must report **"No changes detected"** after this pass.

**Repo state confirmed before planning (grepped, not assumed):**
- `apps/agents/` currently contains only `__init__.py`, `apps.py`, `migrations/__init__.py`, `fields.py`
  (the `EncryptedCharField` used by `twilio_auth_token`) — no `models/`, `forms/`, `views/`, `urls/`, `admin.py`
  yet. `apps.agents` is **not** in `INSTALLED_APPS` and has no `include()` in `config/urls.py` yet.
- Sibling research files `research-agents-2.1.md`, `-2.2.md`, `-2.3.md` all exist — 2.1 owns the `AgentSetting`
  model file itself (**1 model**, per its own "Recommended build scope"). 2.4 depends on that file existing
  before this pass's model-method edit lands; if this pass runs before 2.1's code is written, the method edit and
  the `AgentSetting` import in `telephony.py`/`readiness.py`/the view are **blocked on 2.1 landing first** — note
  this dependency explicitly rather than duplicating the model.
- `apps/tenants/views/Location.py:97-110` (`_agent_setting_for`) and `apps/tenants/views/_helpers.py:13-27`
  (`future_appointment_count`) are the exact import-guard precedent `get_telephony_backend()` reuses:
  `try: from apps.runtime.providers.telephony import get_telephony_backend as _real /
  except (ImportError, ModuleNotFoundError): fall back locally` — so Module 3 takes over with **zero edits** at
  any 2.4 call site.
- `config/settings.py` already carries everything this pass needs: `PROVIDER_MODE` (fake/sandbox/live, default
  `fake`, invalid values coerce to `fake`, lines 320-322), `TWILIO_WEBHOOK_BASE_URL` /`TWILIO_ACCOUNT_SID`/
  `TWILIO_AUTH_TOKEN` (platform fallback, not the per-location ones), `ENCRYPTION_KEY` (line 353),
  `PROVIDER_TIMEOUT_SECONDS=10` (line 363), `MAX_CONCURRENT_CALLS=25` (line 364), and a working `CACHES['default']`
  locmem backend (line 260) for the rate-limit counter.
- `accounts.User.primary_phone` (Char32, blank) already exists — no schema change needed for the
  "verified destination" gate. Seeded `admin@acme.test` / `admin_acme` carries `primary_phone='+13125550101'`
  (`apps/accounts/management/commands/seed_accounts.py`), so the fake-mode smoke test has a real number to use.
  `DEMO_PASSWORD = 'navai-demo-2026'`.
- `apps/accounts/views/_helpers.py::tier_required` and `apps/tenants/views/_common.py::MANAGEMENT_TIERS =
  ('owner', 'manager')` are the reusable privilege gate — placing even a fake test call is a privileged action,
  gated the same way `apps/tenants/views/Location.py` gates location writes.
- `apps/accounts/forms/_common.py` (`TenantModelForm`/`TenantLocationModelForm`) is **not** used here: the test-call
  trigger binds no model instance, so it is a plain `forms.Form`, not a `ModelForm`.

## Models — NONE (service sub-module; reads `agents.AgentSetting` read-only)

- [ ] **No new model file.** Add one method to the EXISTING `AgentSetting` model class in the file sibling 2.1
      creates — expected at `apps/agents/models/PerLocationAgentConfiguration/AgentSetting.py` (PascalCase of
      `### 2.1 Per-Location Agent Configuration`; confirm the exact folder name against 2.1's actual build before
      editing — do not create a second file defining `class AgentSetting`):
      ```python
      def has_twilio_auth_token(self) -> bool:
          """Presence-only check — never decrypts, never logs, never renders the value.
          Used by the 2.4 readiness gate to flag a missing live-mode credential without
          ever touching plaintext."""
          return bool(self.twilio_auth_token)
      ```
      This is a Python method, not a field — `makemigrations agents --check` must say "No changes detected"
      after adding it.

## Backend (apps/agents/ — flat single-purpose modules + one TestCall/ sub-module folder)

- [ ] `apps/agents/telephony.py` (flat, per Backend Package rule 8 — single-purpose module, not under a
      `SubModule/` folder):
  - [ ] `TestCallResult` frozen dataclass: `ok: bool`, `status: str` (`queued|ringing|completed|failed|skipped`),
        `provider_call_sid: str`, `message: str`
  - [ ] `TelephonyBackend` interface: `place_test_call(*, agent_setting, destination_e164) -> TestCallResult`,
        `check_connection(*, agent_setting) -> TestCallResult`
  - [ ] `FakeTelephonyBackend(TelephonyBackend)` — used for `PROVIDER_MODE in {'fake', 'sandbox'}`. Contains
        **no `twilio` import anywhere in the module and opens no socket** — structurally, not just by default,
        incapable of reaching Twilio. Returns a deterministic `TestCallResult(ok=True, status='completed',
        provider_call_sid='FAKE-<uuid>', message='Simulated — no real call was placed.')`
  - [ ] `LiveTelephonyBackend(TelephonyBackend)` — `__init__` raises `ImproperlyConfigured` unless
        `settings.PROVIDER_MODE == 'live'`. `place_test_call()` additionally requires
        `agent_setting.twilio_account_sid`, `agent_setting.has_twilio_auth_token()` and
        `agent_setting.inbound_phone_number` all truthy before attempting anything — missing credentials in live
        mode is a hard failure (`ImproperlyConfigured`), never a silent fallback to fake. The outbound REST call is
        bounded by `settings.PROVIDER_TIMEOUT_SECONDS`.
  - [ ] `get_telephony_backend()` — the ONLY place `PROVIDER_MODE` is read for telephony control:
        ```python
        def get_telephony_backend():
            try:
                from apps.runtime.providers.telephony import get_telephony_backend as _real
                return _real()
            except (ImportError, ModuleNotFoundError):
                pass
            from django.conf import settings
            if settings.PROVIDER_MODE == 'live':
                return LiveTelephonyBackend()
            return FakeTelephonyBackend()
        ```
        Import-guarded exactly like `_agent_setting_for` / `future_appointment_count` — the moment Module 3 ships
        `apps.runtime.providers.telephony`, this function (and every 2.4 call site) upgrades automatically, no
        edit required here or at the call site.
- [ ] `apps/agents/readiness.py` (flat):
  - [ ] `ReadinessIssue` frozen dataclass: `code: str`, `field: str`, `message: str`, `live_only: bool`
  - [ ] `check_setup_readiness(agent_setting) -> list[ReadinessIssue]`, pure/no I/O:
    - `agent_setting is None` → single issue `not_configured` (`live_only=False`) — location has no agent config
      row yet, blocks even a fake test
    - blank `greeting` → `missing_greeting` (`live_only=False`) — blocks fake AND live
    - blank `prompt_text` → `missing_prompt` (`live_only=False`) — blocks fake AND live
    - blank `inbound_phone_number` → `missing_inbound_number` (`live_only=True`) — live test only
    - `transfer_enabled=True` and blank `transfer_phone_number` → `missing_transfer_target`
      (`live_only=True`) — live test only, and only when transfer is actually on
    - blank `twilio_account_sid` OR `not agent_setting.has_twilio_auth_token()` →
      `missing_twilio_credentials` (`live_only=True`) — live test only; never touches the decrypted token
- [ ] `apps/agents/forms/TestCall/AgentSetting.py` — `TestCallForm(forms.Form)`:
      **no destination-number field at all.** The anti-toll-fraud gate is closed structurally, not by validation:
      the destination is *always* `request.user.primary_phone`, read server-side, never posted, never editable.
      The form is a single required `confirm = forms.BooleanField(label='I confirm this is my own phone number
      and I want to receive a test call.')`. `style_widgets()` from `apps/accounts/forms/_common.py` applied in
      `__init__` for the checkbox's theme class.
- [ ] `apps/agents/forms/__init__.py` — **extend** (shared across 2.1-2.3, do not clobber): add
      `from .TestCall.AgentSetting import TestCallForm` to the re-export block.
- [ ] `apps/agents/views/TestCall/AgentSetting.py` — `test_call_view(request)`:
  - [ ] `@login_required`, `@tier_required(*MANAGEMENT_TIERS)` (owner/manager only — placing even a fake call is
        a privileged action, same gate `apps/tenants/views/Location.py` uses for location writes)
  - [ ] `if request.location is None:` → message + redirect to `accounts:my_locations` (no active location, no
        `AgentSetting` to test)
  - [ ] `agent_setting = AgentSetting.objects.filter(tenant=request.tenant, location=request.location).first()`
        — **tenant AND location scoped**, `.filter().first()` not `get_object_or_404` because "not configured
        yet" is a valid, renderable state, not a 404
  - [ ] `issues = check_setup_readiness(agent_setting)`; `blocking = [i for i in issues if not i.live_only]`
  - [ ] GET → render the page with `issues`, `form`, `agent_setting`, `settings.PROVIDER_MODE`
  - [ ] POST →
    1. `blocking` non-empty → error message, redirect back (never proceeds to a fake OR live call)
    2. `settings.PROVIDER_MODE == 'live'` and any live-only issue present → error message, redirect back
    3. no `request.user.primary_phone` → error message ("set your phone number in your profile first"),
       redirect back
    4. rate limit exceeded (see `_check_rate_limit` below) → error message, redirect back, **no side effect**
    5. `form.is_valid()` (the confirm checkbox) → `get_telephony_backend().place_test_call(agent_setting=
       agent_setting, destination_e164=request.user.primary_phone)`; surface `result.message` via
       `messages.success`/`messages.error` keyed on `result.ok`
    6. redirect (PRG) back to `agents:test_call` in every branch — never renders a POST response body directly
  - [ ] `_check_rate_limit(tenant_id, location_id)` (private, single call site, stays in this module):
        cache key `f'agents:test_call_rate:{tenant_id}:{location_id}:{now:%Y%m%d%H}'`,
        `TEST_CALL_RATE_LIMIT_PER_HOUR = 5`, `django.core.cache.cache` (locmem, already configured) —
        no new table, matches `MAX_CONCURRENT_CALLS`'s cost-control pattern
- [ ] `apps/agents/views/__init__.py` — **extend**: add `from .TestCall.AgentSetting import test_call_view`.
- [ ] `apps/agents/urls/TestCall/AgentSetting.py`:
      ```python
      from django.urls import path
      from apps.agents import views

      urlpatterns = [
          path('test-call/', views.test_call_view, name='test_call'),
      ]
      ```
- [ ] `apps/agents/urls/__init__.py` — **extend** (shared, `app_name = 'agents'` set once): add the
      `TestCall.AgentSetting` import + concatenation line; check the literal `test-call/` route against the
      whole concatenated list per Backend Package rule 6 (no `<str:token>`/`<int:pk>` route in 2.1-2.3 should be
      able to swallow it — it has no dynamic segment so this is low-risk, but confirm at build time).
- [ ] `apps/agents/admin.py` — **no change** (no new model).
- [ ] `apps/agents/tests/__init__.py`, `test_telephony.py`, `test_readiness.py`, `test_views_test_call.py`
      (see Verify).
- [ ] No seeder owned by 2.4 (adds no data). **Coordination note for 2.1's `seed_agents`:** seed at least one
      location's `AgentSetting` deliberately incomplete (blank `greeting`, or `transfer_enabled=True` with a
      blank `transfer_phone_number`) so the readiness banner has something real to flag in demo data. If 2.1's
      seeder has already landed without this by the time 2.4 executes, add it there as a one-line, own-commit
      extension — not a new seeder here.

## Realtime & agent surface

- [ ] **No LLM tool.** Test Call is an operator-triggered setup-time action, never something the live agent
      decides to do mid-call — no `apply_tool_call` dispatcher branch, no tool declaration dict.
- [ ] **No prompt variables added.** 2.4 renders no prompt/greeting preview text of its own in this pass (that
      preview belongs to 2.1's authoring UI); it only triggers the backend call.
- [ ] **No Channels consumer, no `routing.py` entry.** The test-call trigger is a synchronous Django
      request/response view, not a websocket surface.
- [ ] **Provider adapter method + fake implementation, in the same pass** — since `apps/runtime/providers/`
      (Module 3) does not exist yet, this pass's adapter seam lives at `apps/agents/telephony.py` instead
      (`TelephonyBackend` / `FakeTelephonyBackend` / `LiveTelephonyBackend` / `get_telephony_backend()` above).
      Module 3 later ships the real `apps.runtime.providers.telephony` module; `get_telephony_backend()`'s
      import-guard picks it up automatically with no edit here.
- [ ] **`CallSession.usage` cost lines: none.** `calls.CallSession` does not exist until Module 5; this pass
      creates no cost-ledger row of any kind for a test call (Invariant 2 — no parallel ledger). Whether a live
      test call should later append a `CallSession.usage` entry is Module 5's decision, not this pass's.

## Wire-up

- [ ] `apps/accounts/navigation.py` — add `'2.4': {'Test Call': 'agents:test_call'}` to `LIVE_LINKS`. (Exact bullet
      text in `NavAIReceptionist.md` is "Placed Test Call" / "Fake-Mode Test" / "Setup Readiness Check"; the
      sidebar label follows the `1.2`-style precedent of a short label over the sub-module's own name, "Test Call".)
- [ ] **Brand-new-app wiring — do ONLY if not already added by a sibling 2.1/2.2/2.3 pass that ran first:**
  - [ ] `config/settings.py` `INSTALLED_APPS` — add `'apps.agents'` (after `'apps.tenants'`, matching the existing
        `'apps.accounts'` / `'apps.tenants'` ordering at lines 101/103).
  - [ ] `config/urls.py` — add `path('agent/', include('apps.agents.urls'))` **before**
        `path('', include('apps.accounts.urls'))` (the accounts catch-all/dashboard route must stay last, exactly
        as the file's own docstring already explains for `manage/`).
  - [ ] `config/asgi.py` — **no change**; this sub-module has no realtime surface.
- [ ] `AUTH_USER_MODEL` — already declared (Modules 0/1 are complete); nothing to do here.

## Templates (templates/agents/testcall/ — standalone action page, no entity folder: Test Call owns no model)

- [ ] `templates/agents/testcall/index.html` — the one page this sub-module ships:
  - readiness banner: when `issues` is non-empty, a checklist of each `ReadinessIssue.message`, each row tagged
    live-only or not (`badge-amber` for live-only, `badge-red` for a blocking-in-fake-mode issue), with the
    field name shown so a later pass can deep-link to the 2.1/2.2/2.3 edit form for that field
  - when `issues` is empty: an explicit affirmative "Ready to go live" state (`badge-green`), not silence
  - a `PROVIDER_MODE` badge: `fake`/`sandbox` → `badge-muted` "Fake Mode — simulated, no real call will be
    placed"; `live` → `badge-info` "Live Mode"
  - the destination line: "A test call will be placed to **{{ request.user.primary_phone|default:'—' }}**" —
    display only, never an editable input
  - the `TestCallForm` (confirm checkbox) + `{% csrf_token %}` + submit button "Place Test Call", disabled via
    template logic when `blocking` issues exist or `primary_phone` is blank
  - messages block renders the last `TestCallResult.message` via the standard `messages` partial (canonical
    status→badge mapping: `queued`/`ringing` → `badge-info`, `completed` → `badge-green`, `failed` → `badge-red`,
    `skipped` → `badge-muted`, plus an `{% else %}` fallback)
  - empty-state when `agent_setting is None`: "This location has no agent configuration yet" with a link toward
    2.1's setup page (confirm the exact `agents:*` url name against 2.1's actual build before wiring the link)

## Verify

- [ ] `manage.py check`
- [ ] `makemigrations agents --check` → **"No changes detected"** (the `has_twilio_auth_token()` method must
      never produce a migration)
- [ ] `PROVIDER_MODE=fake` asserted: `get_telephony_backend()` returns `FakeTelephonyBackend`; `test_telephony.py`
      asserts (a) the `apps.agents.telephony` module source contains no `import twilio` anywhere reachable from
      `FakeTelephonyBackend`, (b) `FakeTelephonyBackend().place_test_call(...)` opens no socket (patch
      `socket.socket` to raise and assert it is never called), (c) the returned `TestCallResult.message` says
      "Simulated — no real call was placed."
- [ ] `LiveTelephonyBackend()` raises `ImproperlyConfigured` when `PROVIDER_MODE != 'live'` (test with
      `@override_settings(PROVIDER_MODE='fake')` and `='sandbox'`)
- [ ] `LiveTelephonyBackend().place_test_call(...)` raises when `PROVIDER_MODE='live'` but
      `twilio_account_sid`/`twilio_auth_token`/`inbound_phone_number` are incomplete on the `AgentSetting` — test
      each of the three missing independently
- [ ] Each of the 5 readiness codes (`not_configured`, `missing_greeting`, `missing_prompt`,
      `missing_inbound_number`, `missing_transfer_target`, `missing_twilio_credentials` — 6 total) fires and
      clears correctly on a fixture `AgentSetting`, including: `missing_transfer_target` only fires when
      `transfer_enabled=True`; `live_only=True` is set on exactly the last three
- [ ] Rate limit: 6th test-call POST within the same `(tenant, location)` hour bucket is rejected with **no**
      `place_test_call` invocation (mock the backend and assert call count stays at 5)
- [ ] Junk/empty POST (`confirm` unchecked, or missing entirely) degrades to a re-render with a form error —
      never a 500
- [ ] `twilio_auth_token` never appears in the rendered `index.html` response body or in captured log output —
      seed an `AgentSetting` with a known plaintext token via `has_twilio_auth_token()`'s underlying field, hit
      the page, assert the plaintext string is absent from `response.content` and from caplog
- [ ] Cross-tenant / cross-location isolation (no pk in this view's URL, so the check is that the view is
      **incapable** of acting on any `AgentSetting` other than the caller's own active one):
  - as `acme_downtown` (assigned ONLY to Downtown per `seed_accounts.py`), GET `/agent/test-call/` and confirm
    the page only ever reflects the Downtown `AgentSetting`, never Uptown's or another tenant's — there is no
    GET/POST parameter that names a location or tenant, so this reduces to confirming `request.location` is the
    sole input and `ActiveLocationMiddleware` re-validates it against `UserLocation` on every request (existing
    Module 0/1 guarantee — assert it is not bypassed by this view)
  - a user from a second tenant (`globex`) hitting the same URL sees only their own tenant's `AgentSetting`
    (`tenant=request.tenant` filter) — never Acme's
- [ ] `admin_acme` smoke (`temp/` sweep, `PROVIDER_MODE=fake`, password `navai-demo-2026` per
      `seed_accounts.DEMO_PASSWORD`): GET `/agent/test-call/` → 200, page title present, no `{#`/`{% comment`
      leaks; POST with `confirm=on` → redirect → success message "Simulated — no real call was placed." present
      on the next GET
- [ ] Sidebar shows `2.4` Live (`LIVE_LINKS['2.4']` present, `agents:test_call` resolves)

## Close-out

- [ ] review agents (code-reviewer → explorer → frontend-reviewer → performance-reviewer → realtime-reviewer →
      qa-smoke-tester → security-reviewer → test-writer)
- [ ] create or update `.claude/skills/agents/SKILL.md` — if it does not yet exist when this pass executes,
      author it (brand-new app); if a sibling 2.1/2.2/2.3 pass already created it, **UPDATE** in place: add the
      *Test Call* page/url, `telephony.py`/`readiness.py` surfaces, and the `has_twilio_auth_token()` method note
      to the existing *Models* section — never re-author the file
- [ ] README — note the new `agent/test-call/` route and the fake/live telephony seam if the project README
      tracks routes

## Later passes / deferred

- **Live-mode real Twilio outbound test call** — needs Module 3's `apps.runtime.providers` to exist; the seam and
  the fake path ship now, the live path activates automatically via the import-guarded `get_telephony_backend()`.
- **Recording a test call into a browsable log** — needs Module 5's `calls.CallSession`; whether test calls should
  be logged at all is that pass's decision, not this one.
- **Regression/simulation test suites (scored personas, multi-scenario)** — out of the eleven-model ceiling and
  outside the seven capabilities; not planned.
- **Browser/WebRTC test call, no phone number needed** — needs Module 3's real-time audio pipeline; track as a
  transport enhancement to this same feature once available, not a new one.
- **`sandbox` behavioral divergence from `fake`** — currently identical by design; revisit once Module 3 defines
  what `sandbox` should uniquely mean.
- **Whether a live test call should append a `CallSession.usage` cost-ledger entry** — decide once Module 5 exists,
  per Invariant 2 (no parallel ledger before then).
- **Field-linked deep-link from a readiness issue to its 2.1/2.2/2.3 edit form** — the issue already carries the
  field name; wiring the actual anchor/url depends on 2.1/2.2/2.3's final url names, confirm at build time.

## Review notes

(filled in at the end)
