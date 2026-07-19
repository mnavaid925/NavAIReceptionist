---
# Sub-module 2.3 — Transfer Settings (Module 2: Agent Setup & Telephony, `agents`) — plan from research-agents-2.3.md (2026-07-19)

## Build-order note — READ FIRST

**Only sub-module 2.1 creates `agents.AgentSetting` and its one migration.** 2.2, 2.3 and 2.4 all edit
**different field groups of that same row** and add **NO model and NO migration**. This plan assumes
`apps/agents/models/.../AgentSetting.py` (the full ERD-spec model — every field from
`NavAIReceptionist-ERD.md` §3.2, one migration, `unique(tenant, location)`) has already been created by
sub-module 2.1's plan by the time this plan is executed. 2.3 imports `AgentSetting` via
`from apps.agents.models import AgentSetting` and touches only its own six `transfer_*` fields.

**Contingency (build-order is not actually guaranteed across four concurrently-planned sub-modules):** if,
at build time, `apps/agents/models/` still has no `AgentSetting` class (`grep -rn "^class AgentSetting"
apps/agents/models/` returns nothing), **STOP and build 2.1 first** (`.claude/tasks/todo-2-2.1.md` if it
exists, else the ERD §3.2 field list directly). Do **not** improvise a second, competing model definition
or a second migration for the same row here — a `unique(tenant, location)` settings row cannot be split
across per-sub-module migrations without churn, and two migrations creating overlapping fields on the same
table is exactly the class of bug this note exists to prevent. The same contingency applies to
`apps/agents/{forms,views,urls}/__init__.py` and their package-root `INSTALLED_APPS` / `config/urls.py`
wiring — if 2.1 hasn't created them yet, create them **minimally** (empty re-export blocks + the app's own
url mount) rather than blocking, mirroring the precedent in `.claude/tasks/todo-1.3-1.4.md`.

**Repo state verified before writing this plan (2026-07-19):**
- `apps/agents/` today has only `__init__.py`, `apps.py` (`label='agents'`), `migrations/__init__.py`,
  `fields.py` (a working `EncryptedCharField` — Fernet, `fernet:` prefix, `mask_secret()`, 512-char column;
  this is 2.2's `twilio_auth_token` field, already built, not re-planned here).
- `grep -rn "^class AgentSetting" apps/agents/` → **no matches**. `apps.agents` is **not yet in
  `INSTALLED_APPS`** (`config/settings.py:88-104` lists only `apps.accounts`, `apps.tenants`).
  `config/urls.py` mounts only `manage/` (tenants) and `''` (accounts). `config/asgi.py`'s
  `websocket_urlpatterns` is empty (Module 3 territory, untouched here).
- `apps\tenants\models\Tenant.py:11` — `class Tenant(TimeStamped)`; `apps\tenants\models\Location.py:18` —
  `class Location(TenantOwned)`. Both verified to exist for the FKs `AgentSetting.tenant`/`.location` carry
  (2.1 builds the FK declarations; 2.3 adds none).
- Reusable, not re-planned: `TenantModelForm` / `TenantLocationModelForm` / `style_widgets`
  (`apps/accounts/forms/_common.py`), `paginate()` (`apps/accounts/views/_common.py`), `tier_required()` /
  `safe_redirect_target()` (`apps/accounts/views/_helpers.py`), `templates/base.html` (blocks `title`/
  `content` only), `partials/_pagination.html`, `partials/_empty_state.html`. The `tenants:business_settings`
  / `business_settings_edit` view pair (`apps/tenants/views/Business.py`) is the direct precedent for a
  no-pk, one-row-per-tenant(-here: per-location) settings surface — this plan mirrors its
  detail-view/edit-view split exactly.
- theme.css badge/stat-icon modifiers are colour-named and CLOSED: `badge-green/red/amber/info/muted/slate`.
  No `badge-purple`, no semantic `-success/-danger` names.
- `apps/agents` is **NOT** a foundation app (unlike `accounts`/`tenants`) — Backend Package Structure rule 9
  does not apply to it. It gets the full `<layer>/<SubModule>/<Entity>.py` package shape (rule 1). The
  sub-module heading `### 2.3 Transfer Settings` → PascalCase folder `TransferSettings/`.

---

## Shape: CRUD (zero-migration, shared-row fieldset)

A settings-singleton view+edit surface over the `transfer_*` fieldset of an existing (2.1-created)
`agents.AgentSetting` row — no list page, no create, no delete (a location's `AgentSetting` row is never
deleted by end users; it lives and dies with the `Location`). Mirrors the `tenants:business_settings` /
`business_settings_edit` singleton pattern exactly, one location down instead of one tenant. **Not** a
service sub-module (Module 3 is that) and **not** a view sub-module (it writes, not just reads) — it is
CRUD in the narrow, ERD-mandated sense of "one form, one row, tenant AND location scoped."

## Models — NONE new (reuses `agents.AgentSetting`, created by 2.1)

- [ ] `agents.AgentSetting` — **tenant AND location scoped**, `unique(tenant, location)` — this pass touches
      only:
      - `transfer_enabled` (Bool, default `False`) — driver: **Transfer Enable & Targets**, master toggle.
      - `transfer_phone_number` (Char(32), E.164) — driver: **Transfer Enable & Targets**, required primary
        destination once `transfer_enabled=True`.
      - `transfer_secondary_number` (Char(32), E.164, blank) — driver: **Transfer Enable & Targets**,
        optional overflow/second-language destination.
      - `transfer_timezone` (Char(100), IANA, default `"America/Chicago"`) — driver: **Transfer Working
        Hours**, deliberately its **own** field, never a reuse of `tenants.Location.timezone` (a tenant may
        staff a shared answering line in a different timezone than the location operates in).
      - `transfer_working_hours` (JSON, `{weekday: {"enabled": bool, "start": "HH:MM", "end": "HH:MM"}}` for
        `monday`…`sunday`) — driver: **Transfer Working Hours**; empty dict `{}` = no restriction (transfer
        available whenever `transfer_enabled` is `True`) — the **opposite default polarity** from
        `tenants`' 1.4 `provider_hours` (there, empty/missing = zero availability). One interval per named
        weekday, keyed by weekday — **not** shared code with 1.4's formset (different shape: one row's JSON
        vs. a per-location fan-out over many users).
      - `transfer_keywords` (JSON list, blank list) — driver: **Transfer Keywords**; tenant additions
        layered on top of a hardcoded `DEFAULT_TRANSFER_KEYWORDS` set Module 3 will own, lowercased /
        de-duplicated / capped at save time.
      - FKs (not added here, already on the row): `tenant` → `tenants.Tenant` (verified above), `location` →
        `tenants.Location` (verified above).
      - **Form-excluded fields** (owned by sibling sub-modules, never touched by 2.3's form/view): `enabled`,
        `voice_provider`, `greeting`, `prompt_text`, `variables` (2.1); `inbound_phone_number`,
        `twilio_account_sid`, `twilio_auth_token` (2.2, and `twilio_auth_token` is additionally **write-only,
        encrypted at rest — never a readable form value anywhere in the app**, 2.3 included).

## Backend (`apps/agents/{models,forms,views,urls}/TransferSettings/` — agents IS a domain app, full package shape)

- [ ] `apps/agents/forms/TransferSettings/__init__.py` — empty package marker (NEW).
- [ ] `apps/agents/forms/TransferSettings/AgentSetting.py` (NEW):
      ```python
      from apps.accounts.forms._common import *  # noqa: F401,F403  (TenantLocationModelForm, style_widgets)
      from apps.agents.models import AgentSetting
      from apps.agents.services import WEEKDAYS, DEFAULT_TRANSFER_KEYWORDS, MAX_TENANT_TRANSFER_KEYWORDS

      __all__ = ['TransferSettingsForm']

      E164_RE = re.compile(r'^\+[1-9]\d{7,14}$')

      class TransferSettingsForm(TenantLocationModelForm):
          """Edits ONLY the transfer fieldset of a shared AgentSetting row.

          `tenant`/`location` are stamped by the base class, never form fields
          (Invariant-adjacent — this row also carries twilio_auth_token, so this
          form's Meta.fields list is a hard boundary: widening it is how a secret
          field would leak onto this page by accident).
          """
          class Meta:
              model = AgentSetting
              fields = ['transfer_enabled', 'transfer_phone_number', 'transfer_secondary_number',
                        'transfer_timezone']
              # twilio_auth_token, twilio_account_sid, inbound_phone_number, enabled,
              # voice_provider, greeting, prompt_text, variables are DELIBERATELY absent.

          # transfer_working_hours and transfer_keywords don't map 1:1 onto model
          # fields, so they're hand-declared here and assembled in clean()/save():
          #   - one BooleanField `{day}_enabled` + two TimeField `{day}_start`/`{day}_end`
          #     per entry in WEEKDAYS (21 extra fields, added in __init__)
          #   - transfer_keywords_text = forms.CharField(widget=forms.Textarea, required=False,
          #     help_text=f'One phrase per line or comma-separated. Always active: '
          #               f'{", ".join(DEFAULT_TRANSFER_KEYWORDS)}. Up to '
          #               f'{MAX_TENANT_TRANSFER_KEYWORDS} additional phrases.')

          def __init__(self, *args, **kwargs):
              super().__init__(*args, **kwargs)
              for day in WEEKDAYS:
                  self.fields[f'{day}_enabled'] = forms.BooleanField(required=False)
                  self.fields[f'{day}_start'] = forms.TimeField(required=False, input_formats=['%H:%M'])
                  self.fields[f'{day}_end'] = forms.TimeField(required=False, input_formats=['%H:%M'])
              self.fields['transfer_keywords_text'] = forms.CharField(
                  widget=forms.Textarea, required=False)
              if self.instance and self.instance.pk:
                  hours = self.instance.transfer_working_hours or {}
                  for day in WEEKDAYS:
                      entry = hours.get(day) or {}
                      self.fields[f'{day}_enabled'].initial = bool(entry.get('enabled'))
                      # start/end initial parsed from 'HH:MM' via datetime.strptime, malformed -> None
                  self.fields['transfer_keywords_text'].initial = '\n'.join(
                      self.instance.transfer_keywords or [])
              style_widgets(self)

          def clean_transfer_phone_number(self): ...   # E164_RE.match or ValidationError
          def clean_transfer_secondary_number(self): ...  # same, but blank is allowed

          def clean(self):
              cleaned = super().clean()
              # 1. transfer_enabled=True requires a non-blank transfer_phone_number ->
              #    ValidationError on transfer_phone_number, not a bare form-level error.
              # 2. Assemble working_hours = {day: {'enabled': bool, 'start': 'HH:MM', 'end': 'HH:MM'}}
              #    for every day in WEEKDAYS. A day with enabled=True and a missing/unparsable
              #    start or end, or end <= start, raises ValidationError naming that weekday
              #    ("Tuesday: end time must be after start time."). A day with enabled=False
              #    is stored as {'enabled': False} with no start/end keys.
              # 3. Parse transfer_keywords_text: split on comma AND newline, strip, drop empty,
              #    lowercase, de-dupe preserving first-seen order, then cap at
              #    MAX_TENANT_TRANSFER_KEYWORDS — over the cap raises ValidationError on the
              #    field (never silently truncates: an admin adding phrase #21 must see why
              #    it didn't save, not lose it silently).
              # Never raises on already-malformed instance.transfer_working_hours data loaded
              # from the DB (that's a READ-time concern for services.py, not this form).
              return cleaned

          def save(self, commit=True):
              instance = super().save(commit=False)
              instance.transfer_working_hours = self._assembled_working_hours   # built in clean()
              instance.transfer_keywords = self._assembled_keywords            # built in clean()
              if commit:
                  instance.save()
              return instance
      ```
- [ ] `apps/agents/views/TransferSettings/__init__.py` — empty package marker (NEW).
- [ ] `apps/agents/views/TransferSettings/AgentSetting.py` (NEW):
      ```python
      from apps.agents.forms import TransferSettingsForm
      from apps.agents.models import AgentSetting
      from apps.agents.services import DEFAULT_TRANSFER_KEYWORDS, WEEKDAYS
      from apps.accounts.views._common import *          # noqa: F401,F403
      from apps.accounts.views._helpers import tier_required

      __all__ = ['transfer_settings_view', 'transfer_settings_edit_view']

      @login_required
      def transfer_settings_view(request):
          """Read-only summary of this location's transfer configuration.

          No pk in the URL — scoped entirely by request.tenant/request.location,
          exactly like tenants:business_settings. get_object_or_404 (NOT
          get_or_create): a location that hasn't run 2.1's setup yet has no row,
          and that is a genuine 404, not an auto-created blank row a user could
          stumble into editing before greeting/prompt/Twilio are configured.
          """
          if request.location is None:
              messages.info(request, 'Switch to a location to view its transfer settings.')
              return redirect('accounts:my_locations')
          setting = get_object_or_404(AgentSetting, tenant=request.tenant, location=request.location)
          return render(request, 'agents/transfer/detail.html', {
              'setting': setting,
              'weekdays': WEEKDAYS,
              'default_keywords': DEFAULT_TRANSFER_KEYWORDS,
              'can_edit': request.user.tier in ('owner', 'manager'),
          })

      @login_required
      @tier_required('owner', 'manager')
      @require_http_methods(['GET', 'POST'])
      def transfer_settings_edit_view(request):
          if request.location is None:
              messages.error(request, 'Switch to a location first.')
              return redirect('accounts:my_locations')
          setting = get_object_or_404(AgentSetting, tenant=request.tenant, location=request.location)
          form = TransferSettingsForm(request.POST or None, instance=setting, request=request)
          if request.method == 'POST' and form.is_valid():
              form.save()
              messages.success(request, 'Transfer settings saved.')
              return redirect('agents:transfer_settings')
          return render(request, 'agents/transfer/form.html', {
              'form': form,
              'setting': setting,
              'weekdays': WEEKDAYS,
              'default_keywords': DEFAULT_TRANSFER_KEYWORDS,
          })
      ```
      Note the deliberate absence of `get_or_create`: if 2.1's per-location setup flow is the thing that
      first creates the `AgentSetting` row (typical), this page 404s until that happens, with the 404
      itself being the desired "you haven't set this location up yet" signal. `seed_agents` (below) ensures
      every seeded demo location has a row, so the smoke sweep never hits this path.
- [ ] `apps/agents/urls/TransferSettings/__init__.py` — empty package marker (NEW).
- [ ] `apps/agents/urls/TransferSettings/AgentSetting.py` (NEW):
      ```python
      from django.urls import path
      from apps.agents import views

      urlpatterns = [
          path('transfer/', views.transfer_settings_view, name='transfer_settings'),
          path('transfer/edit/', views.transfer_settings_edit_view, name='transfer_settings_edit'),
      ]
      ```
- [ ] `apps/agents/urls/__init__.py` — set `app_name = 'agents'`; concatenate this sub-module's
      `urlpatterns` with the other sub-modules' (create the file minimally, per the Build-order note, if it
      doesn't exist yet). Both `transfer/` routes are literal — no `<int:pk>` route exists anywhere in this
      app yet, so ordering is low-risk today, but list this block on its own for when a future sub-module
      (e.g. a later per-tenant provider-number list) adds a `<int:pk>` route that must sit after it.
- [ ] `apps/agents/forms/__init__.py` — add `from .TransferSettings.AgentSetting import TransferSettingsForm`
      + `__all__` entry (create the file minimally if it doesn't exist yet).
- [ ] `apps/agents/views/__init__.py` — add
      `from .TransferSettings.AgentSetting import transfer_settings_view, transfer_settings_edit_view` +
      `__all__` entries (create minimally if missing).
- [ ] `apps/agents/services.py` (flat module at the app root, per Backend Package Structure rule 8 —
      NEW, or extend if 2.1/2.2 already started it):
      ```python
      """Pure-Python contract consumed by Module 3's future runtime. No provider I/O,
      no Django ORM writes, no network calls — every function here must be safe to
      call on the live-call hot path once Module 3 exists (CLAUDE.md Realtime Rule:
      no sync blocking work on the event loop; these are just fast in-memory checks
      wrapped in database_sync_to_async by whatever calls them later).
      """
      import datetime
      from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

      from django.utils import timezone as dj_timezone

      __all__ = ['WEEKDAYS', 'DEFAULT_TRANSFER_KEYWORDS', 'MAX_TENANT_TRANSFER_KEYWORDS',
                 'is_transfer_available', 'next_transfer_window', 'resolve_transfer_number',
                 'matches_transfer_keyword']

      WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')

      #: Baseline escalation phrases that ALWAYS trigger a transfer offer, on day one,
      #: with zero tenant configuration. Not a DB row — AgentSetting.transfer_keywords
      #: stores only the tenant's ADDITIONS on top of this set.
      DEFAULT_TRANSFER_KEYWORDS = (
          'speak to a person', 'talk to a human', 'representative', 'operator',
          'real person', 'customer service', 'manager', 'supervisor',
          'connect me', 'transfer me',
      )

      #: Caps the tenant-added keyword list so the prompt/keyword surface a caller's
      #: speech is matched against can't grow unbounded.
      MAX_TENANT_TRANSFER_KEYWORDS = 20


      def _resolve_tzinfo(agent_setting):
          """Never raises — a bad IANA name degrades to UTC, mirroring
          tenants.Location.tzinfo's documented degrade pattern."""
          try:
              return ZoneInfo(agent_setting.transfer_timezone or 'UTC')
          except (ZoneInfoNotFoundError, ValueError, KeyError):
              return ZoneInfo('UTC')


      def is_transfer_available(agent_setting, at=None):
          """True iff transfer_enabled AND (transfer_working_hours is empty OR
          today's weekday entry, evaluated in transfer_timezone, has enabled=True
          and `at` falls within [start, end)).

          Empty dict {} = no restriction — the OPPOSITE default from
          tenants.get_provider_intervals (there, empty/missing = zero
          availability). A day whose key is present with enabled=False, or
          absent from a non-empty dict, is CLOSED that day. A malformed
          start/end on an enabled day is treated as CLOSED that day, never
          raises. NEVER raises — a bad transfer_working_hours value degrades to
          "unavailable" rather than crashing the tool-dispatch hot path.
          """
          if not agent_setting.transfer_enabled:
              return False
          hours = agent_setting.transfer_working_hours or {}
          if not hours:
              return True
          at = at or dj_timezone.now()
          local = at.astimezone(_resolve_tzinfo(agent_setting))
          day_key = WEEKDAYS[local.weekday()]
          entry = hours.get(day_key) or {}
          if not entry.get('enabled'):
              return False
          try:
              start = datetime.datetime.strptime(entry['start'], '%H:%M').time()
              end = datetime.datetime.strptime(entry['end'], '%H:%M').time()
          except (KeyError, ValueError, TypeError):
              return False
          return start <= local.time() < end


      def next_transfer_window(agent_setting, at=None):
          """Human-readable next open window ('Monday at 09:00 AM CDT'), for the
          {{transfer_reopens_at}} prompt variable. Returns None when
          transfer_working_hours is empty (no restriction -> always open, so
          "next window" is meaningless) or when transfer_enabled is False.
          Scans forward up to 7 days from `at`, inclusive of later-today.
          NEVER raises.
          """
          ...

      def resolve_transfer_number(agent_setting, target='primary'):
          """Returns transfer_phone_number for target='primary',
          transfer_secondary_number for target='secondary'; None for anything
          else (including a blank configured number). NEVER accepts a phone
          number as input — this IS the Invariant 3 enforcement point: a caller's
          speech or a model's tool call may select WHICH configured number to
          try, never WHAT number to dial.
          """
          if target == 'primary':
              return agent_setting.transfer_phone_number or None
          if target == 'secondary':
              return agent_setting.transfer_secondary_number or None
          return None

      def matches_transfer_keyword(utterance, agent_setting):
          """Lowercase substring check against DEFAULT_TRANSFER_KEYWORDS union
          agent_setting.transfer_keywords. A PRE-FILTER SIGNAL, not the sole
          transfer gate -- Module 3's model reasons about intent using
          prompt_text (2.1) too; a false negative here does not block a
          transfer the model otherwise decides to offer. Empty/None utterance
          returns False, never raises.
          """
          if not utterance:
              return False
          text = utterance.lower()
          all_keywords = set(DEFAULT_TRANSFER_KEYWORDS) | set(agent_setting.transfer_keywords or [])
          return any(kw in text for kw in all_keywords)
      ```
- [ ] `admin.py` — no change if 2.1 already registered `AgentSetting`; if it hasn't (Build-order
      contingency), register it minimally there, not here.
- [ ] Migration — **NONE**. `makemigrations agents --check` must report "No changes detected." for this
      pass's own diff (see Build-order note for what to do if the model itself is still missing).

## Tool surface — SPECIFICATION ONLY (Module 3 implements; `apps/runtime` does not exist yet)

- [ ] `transfer_to_human(target: "primary" | "secondary")` — declaration dict (name, description, JSON-schema
      parameters restricted to the two-value enum `target`), for Module 3's future tool registry. Identity
      (`tenant_id`, `location_id`, `session_id`) comes from server-side session state, **never** a tool
      argument — `target` selects between two pre-configured numbers, it never supplies one (Invariant 3;
      the explicit anti-pattern flagged in research against Vapi's/Synthflow's dynamic-transfer designs).
      Dispatcher branch (future): resolve `agent_setting` from session state →
      `services.is_transfer_available(agent_setting)`; if `False`, return
      `{"ok": false, "data": null, "error": {"code": "not_permitted", "message": "Transfer is not available right now."}}`
      with **zero LLM round trip** (CLAUDE.md Realtime Rule 5's deterministic-fallback pattern, applied to
      refusal, not just the greeting); if `True`, `services.resolve_transfer_number(agent_setting, target)` →
      `{"ok": true, "data": {"destination": "+1XXXXXXXXXX", "mode": "warm"}, "error": null}`, then set the
      **deferred transport-mutating signal** (Realtime Rule 6 — the transport dials only after this turn's
      audio completes). `matches_transfer_keyword` feeds the model's own judgment as a pre-filter hint, not a
      hard gate (see services.py docstring above).
      **Nothing to trace through "both runtime paths" today** — Module 3 doesn't exist, so there is exactly
      one path (none). This item exists so Module 3's build has a checked contract to implement against, not
      because 2.3 ships any of it.

## Prompt / variables

- [ ] Two new runtime-injected prompt variables, computed by Module 3 at call setup (not stored, not a DB
      field) and merged into the same `{{var}}` map `AgentSetting.variables` already documents (owned by
      2.1, reused here rather than duplicated):
      - `{{transfer_available}}` — `str(services.is_transfer_available(agent_setting)).lower()` → `"true"` /
        `"false"`, computed server-side, injected as the literal string per the ERD's "Derived, never
        stored" table (§5) — never handed the LLM raw hours + a clock to reason about itself.
      - `{{transfer_reopens_at}}` — `services.next_transfer_window(agent_setting) or ''`.
      - `prompt_text` (2.1's field) names **no tool and no tool parameter** — it may reference
        `{{transfer_available}}`/`{{transfer_reopens_at}}` in prose, exactly like it already may reference
        `{{from_number}}`/`{{location_name}}`.

## Provider adapter — NONE for this pass

- [ ] 2.3 places no call and reaches no provider. `services.py` has zero imports of `twilio`, `requests`,
      `httpx`, or `apps.runtime` — verified by a static test assertion (see Verify). `PROVIDER_MODE` is
      therefore irrelevant to this pass's own code path; it matters only once Module 3's transfer executor
      exists and must resolve to the fake adapter whenever `PROVIDER_MODE != 'live'`.

## `CallSession.usage` cost lines

- [ ] **NONE appended by 2.3** (no calls placed, `calls.CallSession` doesn't exist yet — Module 5). Naming
      the future keys so Module 5's cost breakdown has a stable contract to read once Module 3 writes them:
      `usage.transfer_leg_minutes` / `usage.transfer_leg_cost`, appended by Module 3's transfer executor when
      a transfer actually dials a second concurrent Twilio leg. Documented here, not implemented here.

## Wire-up

- [ ] `apps/accounts/navigation.py` — add to `LIVE_LINKS`:
      `'2.3': {'Transfer Settings': 'agents:transfer_settings'}` (points at the detail/landing view, matching
      the `'1.1': {'Business Settings': 'tenants:business_settings'}` precedent — the edit form is reached
      FROM the detail page, not from the sidebar directly).
- [ ] `config/settings.py` `INSTALLED_APPS`, `config/urls.py` (`path('agents/', include('apps.agents.urls'))`
      or similar prefix), `config/asgi.py` — **NOT this pass's job**. That is 2.1's (first sub-module of a
      brand-new app) responsibility. 2.3 does not touch these three files **unless** the Build-order
      contingency fires (2.1 hasn't landed and `apps.agents` genuinely isn't wired anywhere yet) — in that
      case, wire it minimally (one `INSTALLED_APPS` entry, one `config/urls.py` `include()`) so this pass's
      own routes are reachable, and say so plainly in the commit message.
- [ ] `AUTH_USER_MODEL = 'accounts.User'` — **not applicable**, already declared before Module 0/1's first
      migration; this pass makes no first migration of its own.

## Templates (`templates/agents/transfer/` — single-entity sub-module, folder doubles as entity folder)

- [ ] `templates/agents/transfer/detail.html` — read-only summary: `transfer_enabled` as `badge-green`
      (on) / `badge-slate` (off); primary/secondary numbers (plain text — these are not secrets, unlike
      `twilio_auth_token`); `transfer_timezone`; a 7-row Mon–Sun table rendering each day's
      `enabled`/`start`–`end` or "Closed" from `setting.transfer_working_hours`, with a banner reading "No
      restriction — a human is offered any time transfer is enabled" when the dict is empty (the
      empty-JSON-default state, called out explicitly per its opposite-of-1.4 polarity); built-in keyword
      chips (from `default_keywords`, read-only, non-removable styling) separate from tenant-added chips
      (from `setting.transfer_keywords`); an "Edit" button (only when `can_edit`) linking to
      `agents:transfer_settings_edit`; a "Switch location" prompt when `request.location` differs from what
      the admin expects. **No `list.html`** (one row per location, nothing to list) and **no delete action**
      (the row is never end-user-deletable).
- [ ] `templates/agents/transfer/form.html` — the edit form: enable toggle, two E.164 number inputs
      (rendered as **named fields**, never `{{ form }}`/`{{ form.as_p }}` wholesale — a wholesale render is
      exactly how a future field addition to this row could leak onto this page unnoticed), a timezone
      `<select>` (a short curated IANA list — `America/Chicago`, `America/New_York`, `America/Denver`,
      `America/Los_Angeles`, `America/Phoenix`, `UTC`, plus the currently-stored value if it's outside that
      list so an existing row never silently loses its setting), 7 weekday rows (enabled checkbox + two
      `HH:MM` time inputs each, degrading gracefully when a row is left blank while unchecked), the keyword
      textarea with the built-in list shown as read-only reference text above it and the
      `MAX_TENANT_TRANSFER_KEYWORDS` cap stated as help text, Save/Cancel buttons, `{% csrf_token %}`. Badge
      colours from the closed theme.css set only.

## Verify

- [ ] `venv\Scripts\python.exe manage.py makemigrations agents --check` → "No changes detected." (2.3 is
      zero-migration; if this fails because `AgentSetting` doesn't exist at all, STOP per the Build-order
      note rather than generating a migration here).
- [ ] `venv\Scripts\python.exe manage.py check`.
- [ ] **`PROVIDER_MODE=fake` never reaches a real provider** — a static test asserts `apps/agents/services.py`
      imports none of `twilio`, `requests`, `httpx`, `apps.runtime` (read the module source, `assert` none of
      those substrings appear as an `import`); every `services.py` function call in the test suite runs with
      no network access enabled (e.g. via `pytest-socket` or a monkeypatched `socket.socket` that raises) and
      passes — proving these are genuinely pure functions, not just currently-unused ones.
- [ ] `venv\Scripts\python.exe manage.py seed_agents` ×2 — idempotent: `transfer_enabled=True`, both
      destination numbers, a realistic per-weekday window (Mon–Fri 09:00–17:00, weekends `enabled=False`),
      and 2–3 tenant keyword additions land on **at least one seeded location per tenant**, across the
      required **two locations per tenant**; a second run does not duplicate rows (get-or-create by
      `(tenant, location)`, the row's own unique constraint) and does not clobber a value a human already
      edited via the UI (write the transfer fields only when they're still at the model's own defaults, same
      pattern as 1.4's `provider_hours` backfill in `todo-1.3-1.4.md`).
- [ ] `venv\Scripts\python.exe -m pytest -q apps/agents` — new tests:
      - `test_services.py` — `is_transfer_available`: disabled → `False`; enabled + empty `{}` → `True` at
        any hour; enabled + configured hours → correct boundary behaviour at the exact `start`/`end` minute,
        across a non-UTC `transfer_timezone`; a malformed `transfer_working_hours` entry (bad `HH:MM`,
        missing key, non-dict) never raises, degrades to closed-that-day. `next_transfer_window`: `None` on
        empty hours or disabled; correct next-open-day string when currently closed.
        `resolve_transfer_number`: `'primary'`/`'secondary'` map correctly; any other value (including
        `None`, an empty string, or a caller-supplied phone number string) returns `None`, never raises,
        never echoes an arbitrary input back as a destination. `matches_transfer_keyword`: built-in hit,
        tenant-added hit, case-insensitivity, no false positive on unrelated text, `None`/`''` utterance →
        `False`.
      - `test_forms.py` — `TransferSettingsForm`: non-E.164 primary/secondary → `ValidationError`;
        `transfer_enabled=True` with a blank primary number → `ValidationError`; an unparsable `HH:MM` on an
        enabled day → `ValidationError`; `end <= start` on an enabled day → `ValidationError`; a 21st tenant
        keyword → `ValidationError` (never silently truncated); duplicate/whitespace-only keyword lines
        de-duped and stripped; **`'tenant' not in form.fields` and `'location' not in form.fields`**;
        **`TransferSettingsForm.Meta.fields` contains none of `twilio_auth_token`, `twilio_account_sid`,
        `inbound_phone_number`, `enabled`, `voice_provider`, `greeting`, `prompt_text`, `variables`** — a
        hard assertion so a future edit can't accidentally widen this form's blast radius onto a sibling
        sub-module's (or a secret) field.
      - `test_views.py` — both views `@login_required`; `transfer_settings_edit_view` tier-gated (a
        `staff`-tier user redirected with a message, never a 500); saving the transfer fieldset leaves
        `enabled`, `voice_provider`, `greeting`, `prompt_text`, `variables`, `inbound_phone_number`,
        `twilio_account_sid`, `twilio_auth_token` **byte-for-byte unchanged** on the row (fetch before/after,
        assert equality — this is the shared-row regression this whole plan exists to prevent).
- [ ] **Cross-tenant IDOR → 404.** There is no pk anywhere in this sub-module's URLs by design (mirrors
      `tenants:business_settings`) — scoping comes entirely from `request.tenant`/`request.location`, which
      are session-resolved, never client-supplied, so classic pk-guessing IDOR is structurally unreachable.
      The test instead proves the session-based scoping itself: as tenant B (`admin_globex`), GET
      `agents:transfer_settings` / POST `agents:transfer_settings_edit` while active-located at a Globex
      location with **no** `AgentSetting` row yet → **404**, and the response never contains tenant A
      (Acme)'s `transfer_phone_number`, `transfer_secondary_number` or `transfer_keywords` values anywhere
      in the body.
- [ ] **Cross-location IDOR → 404 / correct isolation.** Two locations of the **same** tenant (Acme
      Downtown, Acme Uptown) each get their own seeded `AgentSetting` row with **different**
      `transfer_phone_number`/`transfer_working_hours`/`transfer_keywords`. Switch `request.location` between
      them (via the validated location switcher, never a raw session write) and confirm each view only ever
      returns/edits the currently-active location's row — editing Downtown's transfer settings never
      modifies Uptown's row (assert both rows independently after the edit). A location the signed-in user
      is **not** assigned to (no `UserLocation` row) can never become `request.location` in the first place
      (already enforced by `ActiveLocationMiddleware`, re-verified here rather than re-implemented) — attempt
      a session-key tamper for an unassigned location's id and confirm it degrades to `request.location is
      None`, landing on this page's "switch to a location" redirect, not another location's data.
- [ ] **Junk GET/POST payloads degrade, never 500:** `transfer_phone_number="not-a-number"`,
      `monday_start="25:99"`, `tuesday_end` equal to `tuesday_start`, a `transfer_keywords_text` with 200
      lines, a POST with every field omitted, a hand-crafted `?location=<id>` query string on either view
      (both views take location **only** from `request.location`, never a GET/POST param — confirm the
      query string is simply ignored). All of these render a `200` with field-level form errors (edit view)
      or are no-ops (detail view has no POST), never a `500`.
- [ ] **The auth token never appears in any rendered page or log.** `twilio_auth_token`'s decrypted value and
      its `fernet:`-prefixed ciphertext are asserted absent from both `detail.html` and `form.html`'s
      rendered response bodies in tests (grep the response content). Confirm `form.html` renders **named**
      fields only (`{{ form.transfer_enabled }}`, `{{ form.transfer_phone_number }}`, …) — never
      `{{ form }}` or `{{ form.as_p }}` wholesale, which would silently leak any field this form ever gains.
      Confirm no `logger.*` call anywhere in `apps/agents/{views,forms}/TransferSettings/` interpolates
      `agent_setting`/`setting` as a whole object (only `.pk`/`.location_id` are ever logged, per the PII
      rule already governing `twilio_account_sid`).
- [ ] **The globally-unique inbound number.** `AgentSetting._meta.get_field('inbound_phone_number').unique is
      True` (guards the Build-order contingency path in case this pass ever had to touch the model
      directly — it must not). Confirmed unchanged per the `test_views.py` before/after assertion above.
- [ ] `temp/` smoke sweep as `admin_acme` (password printed at the end of `seed_accounts` — read
      `apps/accounts/management/commands/seed_accounts.py` rather than assuming it): `GET
      /agents/transfer/` and `/agents/transfer/edit/` → `200` for **both** seeded Acme locations (switch
      active location between them and repeat); content assertions — no `{#`/`{% comment` leaks, correct
      page title, the seeded transfer numbers/hours/keywords visible on the detail page and pre-filled on the
      edit form; `POST /agents/transfer/edit/` with a valid payload → `302` back to the detail page with
      `messages.success`; as `admin_globex`, the same URLs never render Acme's numbers. Sidebar: Module 2
      shows `2.3` as Live with a working "Transfer Settings" link (2.1/2.2/2.4 may still show as
      roadmap/unbuilt — no assumption made about their build order here).

## Close-out

- [ ] Review agents, in order: `code-reviewer` → `explorer` → `frontend-reviewer` → `performance-reviewer` →
      `realtime-reviewer` (expected finding: "no realtime surface shipped in this pass, only a documented
      future tool contract" — fine, no empty commit required) → `qa-smoke-tester` → `security-reviewer`
      (expect this to scrutinize the shared-row/token-leak boundary closely — that's the point) →
      `test-writer`.
- [ ] **`.claude/skills/agents/SKILL.md`** — `agents` is a brand-new module getting real code across this and
      three sibling concurrently-planned sub-module passes (2.1, 2.2, 2.4). **Check existence before deciding
      create vs. update**, exactly as `todo-1.3-1.4.md` did for `tenants`: if a sibling pass lands first and
      already authored the skill, this pass **UPDATES** it in place — add the Transfer Settings fieldset
      (which fields it owns on the shared row), the `agents:transfer_settings`/`transfer_settings_edit`
      routes, `templates/agents/transfer/*`, the `services.py` contract (`is_transfer_available`,
      `next_transfer_window`, `resolve_transfer_number`, `matches_transfer_keyword`,
      `DEFAULT_TRANSFER_KEYWORDS`), and the `seed_agents` transfer-fieldset seeding — **never re-author it**,
      that clobbers whichever sibling sub-module landed first. If this pass somehow lands FIRST, author the
      skill fresh but scope its "Models" section honestly to what 2.3 actually verified/built (the transfer
      fieldset), not the whole row's other three sub-modules' fields it hasn't seen built yet.
- [ ] README — update only if the project root README enumerates built sub-modules.

## Later passes / deferred (carried over from research-agents-2.3.md)

- Holiday/date-specific transfer-hours exceptions — needs an `"exceptions"` schema extension beyond the
  current weekday-only `transfer_working_hours` shape; mirrors 1.4's identical deferral for `provider_hours`.
- Warm/cold transfer mode toggle, whisper/three-way announce text, on-hold music — no field in the ERD's
  given `AgentSetting` list; Module 3 defaults to one fixed warm-style announcement.
- SIP URI transfer destinations — `transfer_phone_number`/`transfer_secondary_number` are E.164-typed
  `Char(32)`; no PBX/SIP integration need identified.
- Department/intent-based multi-destination routing — the model has exactly two destinations; a department
  map would be a genuine schema extension.
- Sentiment-based escalation, human-presence detection before bridging, live handoff-summary construction
  from `calls.CallSession.transcript`/`.analysis` — all Module 3 runtime/reasoning behaviors, not config.
- Test-dial / reachability verification of the configured transfer destination, setup-readiness flags for a
  missing transfer target — **2.4 Test Call**'s explicit bullet; 2.3 validates format only, not reachability.
- `scheduling.CallbackRequest` creation as an off-hours alternative to a bare apology — **Module 4**; 2.3
  only guarantees `{{transfer_reopens_at}}` is available for that future prompt instruction to reference.
- Writing the realized transfer outcome (`CallSession.transfer` JSON) and displaying it in the call detail
  view — **Module 5**.
- `enabled`, `voice_provider`, `greeting`, `prompt_text`, `variables` fieldset/forms/views — **2.1** (same
  row, different fieldset).
- `inbound_phone_number`, `twilio_account_sid`, `twilio_auth_token`, webhook URL display, connection check —
  **2.2** (same row, different fieldset).

## Review notes
(filled in at the end)
