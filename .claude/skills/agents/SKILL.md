---
name: agents
description: Work on the Agent Setup & Telephony module (per-location agent config, greeting and prompt, prompt variables, Twilio credentials and inbound number, transfer settings and hours, test call). Use when the user asks to add/change/debug anything under apps/agents or templates/agents, anything about AgentSetting, the encrypted twilio_auth_token, transfer keywords, or invokes /agents.
---

# Module 2 — Agent Setup & Telephony (`apps/agents`)

## Overview

Everything a location's voice agent needs, in one row. Mounted at **`/agent/`**.

| Sub-module | Ships |
|---|---|
| 2.1 Per-Location Agent Configuration | Enable, voice mode, greeting, prompt, `{{variables}}`, preview |
| 2.2 Twilio Connection | Per-location SID + encrypted token, inbound number, webhook URLs, connection check |
| 2.3 Transfer Settings | Destinations, weekly windows, escalation keywords |
| 2.4 Test Call | Readiness check + a call that can only ring you |

**Only 2.1 added a model.** 2.2, 2.3 and 2.4 edit different field groups of the
same `AgentSetting` row and added no migration.

## Model — `agents.AgentSetting`

`models/AgentConfiguration/AgentSettings.py`. Tenant- AND location-scoped, unique
on `(tenant, location)` — exactly one row per location.

Three field groups, three forms, each blind to the others so saving a greeting
cannot clear a credential:

* **2.1** `enabled`, `voice_provider` (`live`/`google`/`gemini`), `greeting`,
  `prompt_text`, `variables` (JSON)
* **2.2** `inbound_phone_number`, `twilio_account_sid`, `twilio_auth_token`
* **2.3** `transfer_enabled`, `transfer_phone_number`,
  `transfer_secondary_number`, `transfer_timezone`, `transfer_working_hours`
  (JSON), `transfer_keywords` (JSON list)

Helpers: `has_auth_token`, `masked_auth_token`, `twilio_connected`, `is_ready`,
`readiness_issues()`.

## THE TWO CONSTRAINTS THAT DO REAL WORK

**`inbound_phone_number` is unique GLOBALLY, across every tenant.** An inbound
webhook has no session — it resolves tenant and location from the dialled number:

```python
setting = AgentSetting.objects.get(inbound_phone_number=to_number)
```

Two businesses owning one DID makes that ambiguous, which is a cross-tenant leak.
The column is **nullable, never blank-defaulted**: NULLs are distinct in a unique
index, empty strings are not, so several locations may have no number but no two
may share one. `clean()` and `save()` both normalise `''` to `None`.

**`twilio_auth_token` is encrypted at rest and write-only in forms.** See below.

## Credential handling — read this before touching 2.2

`apps/agents/fields.py` — `EncryptedCharField`, prefixed (`fernet:`) idempotent
Fernet over `settings.ENCRYPTION_KEY`.

* **Column width is 512**, not the ERD's `Char(128)`. Measured: a 32-character
  token encrypts to ~147 characters. The ERD records the deviation.
* `deconstruct` deliberately does NOT hide `max_length` — stripping it would
  unpin the column so a later default change altered the schema with no migration.
* A rotated key makes stored tokens unreadable. `decrypt_value` returns `''` and
  logs, so the page shows "not configured" rather than 500-ing.
* **`twilio_auth_token` is NOT in `TwilioConnectionForm.Meta.fields`.** A
  `ModelForm` binds every field it names to its current value — listing it would
  render the credential into the edit page's `value=` attribute. A separate
  always-empty `new_auth_token` field is used instead, and blank means *unchanged*.
* Never log it, never `messages.*` it (message bodies persist in the session
  store), never return it. The SID is an identifier and is safe to show — but a
  SID plus a leaked token is a live Twilio account, so don't log the SID either.

## URLs — `app_name = 'agents'`, prefix `/agent/`

`urls.py` is FLAT — one model, nine literal routes; four `urls/<SubModule>/`
folders holding one `path()` each would be harder to read (CLAUDE.md rule 10).

`agent_setup` · `agent_setup_edit` · `agent_preview` · `twilio_connection` ·
`twilio_connection_edit` · `twilio_check` · `transfer_settings` ·
`transfer_settings_edit` · `test_call`

**NO ROUTE TAKES A PK.** Every view resolves its row from `request.tenant` and
`request.location` via `views/_helpers.get_setting_for_active_location`, which
`get_or_create`s on first visit. With no id to tamper with, this module has no
cross-tenant or cross-location IDOR surface at all — the bug class is absent
rather than guarded. Do not add a pk route.

## Templates — `templates/agents/<submodule>/<page>.html`

`agents` is a DOMAIN app, so it carries the sub-module folder level:
`setup/{detail,form,preview}.html`, `twilio/{detail,form}.html`,
`transfer/{detail,form}.html`, `testcall/index.html`, plus `_tabs.html`.

## Tools & prompt surface

No LLM tool is registered yet — that is Module 3. What this module OWNS and
Module 3 will consume:

```python
from apps.agents.services import (
    render_template,            # greeting + prompt rendering, 0 LLM tokens
    build_runtime_context,      # the variable map for one render
    is_transfer_available,      # transfer window gate
    next_transfer_window,       # for the off-hours spoken fallback
    resolve_transfer_number,    # label -> configured E.164
    matches_transfer_keyword,   # escalation detection
)
```

* `render_template` is **named substitution, not Django's template engine** —
  the prompt is tenant-authored text rendered into speech, and a real engine
  would hand it tag execution and attribute traversal.
* `resolve_transfer_number(setting, target)` takes a **label** (`"primary"` /
  `"secondary"`), never a number. This is the Invariant 3 enforcement point: a
  destination the caller or the model produced is not dialable by construction.
* `RESERVED_RUNTIME_VARIABLES` cannot be overridden by a tenant — a business
  pinning `current_time` would make the agent state a false time to every caller.
* **Time-dependent variables must be rebuilt per turn** (`current_time`,
  `is_open_now`, `transfer_available`, `transfer_reopens_at`). Computing them
  once at call start makes a long call assert the wrong day.

## Realtime surfaces

**This module has no realtime surface** — no consumer, no `routing.py` entry, no
webhook handler. It only *displays* the webhook URLs for Module 3's ingress.

## Provider safety — `apps/agents/telephony.py`

`get_backend()` resolves by `PROVIDER_MODE`. Anything not exactly `'live'`
returns `FakeTelephonyBackend`, which **imports no provider SDK and opens no
socket** — that is structural, not a policy. `LiveTelephonyBackend.__init__`
raises unless `PROVIDER_MODE == 'live'`, so an instance cannot exist in a
non-live process.

`get_backend()` already import-guards `apps.runtime.providers.telephony`, so when
Module 3 lands it takes over with **no change to any call site**.

## Seeder

`seed_agents` — one row per demo location, idempotent, fake credentials,
globally distinct inbound numbers. **Globex Lakeside is deliberately left
unconfigured** so the readiness check and the "not configured" surfaces have
something real to report.

## Conventions & gotchas

1. **Three forms, one row.** Never widen a form's `Meta.fields` across group
   boundaries — that is how saving a greeting wipes a credential.
2. **The test call takes no destination field.** It rings the signed-in user's
   own `primary_phone`, read server-side. An endpoint that dials a
   client-supplied number is a toll-fraud gadget; validating the number is not
   sufficient, because "valid E.164" and "safe to dial" differ.
3. **`{% verbatim %}` must never appear inside `{% comment %}`** — verbatim is
   handled by the LEXER, so it swallows the `{% endcomment %}` and the comment
   never closes. Cost a real debugging cycle.
4. **A literal `{{name}}` in a template** goes through `{% verbatim %}`. Writing
   `{{ "{{name}}" }}` is a syntax error, not an escape.
5. `day_rows` is built in `TransferSettingsForm`, not the template — a template
   cannot compose a field name from a loop variable, and faking it with a filter
   chain is how a schedule editor writes Tuesday's hours into Monday.
6. The collision message for a taken inbound number must NOT reveal that another
   business owns it.

## Common tasks

**Add an agent field** — model → the ONE form that owns its group → its detail
and form templates → `seed_agents` → `makemigrations agents`.

**Add a prompt variable** — if server-computed, add it to
`RESERVED_RUNTIME_VARIABLES` and `build_runtime_context`, and list it in
`templates/agents/setup/form.html`'s "computed for you" panel.

**Change transfer-hours storage** — change it in `services.py` only and keep
`is_transfer_available`'s signature stable; Module 3 calls it per turn.

## Sidebar wiring

```python
'2.1': {'Agent Setup': 'agents:agent_setup'},
'2.2': {'Twilio Connection': 'agents:twilio_connection'},
'2.3': {'Transfer Settings': 'agents:transfer_settings'},
'2.4': {'Test Call': 'agents:test_call'},
```
