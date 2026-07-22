"""Prompt + ``{{variable}}`` rendering and the runtime variable set — sub-module 3.2.

The rendering rules are the binding contract in ``voice-agent-runtime`` skill §10;
this is the first code in the project to implement them.

* Placeholders are ``{{key}}``, whitespace-tolerant (``{{ key }}`` is identical).
* **A missing key renders as an empty string** — a live call must never leak a raw
  ``{{placeholder}}`` to a caller, so a spelling drift fails silently rather than
  loudly. That cuts both ways: ``is_open_now`` misspelled anywhere yields ``''``,
  so the name is spelled exactly once, here.
* Variables merge one way: ``AgentSetting.variables`` first, then the runtime vars,
  **which always win**.
* ``is_open_now`` is computed server-side as the literal ``"yes"``/``"no"`` — the
  model never derives open/closed from raw hours and a clock.
* ``current_date`` / ``current_time`` are in the **location's** timezone, never the
  server's, and are recomputed every turn (the caller of ``build_variables`` passes
  a fresh ``now``). Portable strftime only — ``%-d`` / ``%-I`` are unsupported on
  the Windows dev host, so the day number and 12-hour are built explicitly.

There is no "location opening hours" field in this product — the authoritative
hours are per-provider on ``accounts.User.provider_hours`` (Module 1.4). So
``is_open_now`` means *is any provider assigned to this location working now*,
computed through the audited ``tenants.services`` hours logic rather than a second,
divergent hours interpretation. The provider intervals are gathered once at connect
(``build_open_intervals``) so the per-turn check is pure in-memory.
"""
import re

from apps.accounts.models import UserLocation
from apps.tenants.services import WEEKDAY_BY_INDEX, get_provider_intervals

__all__ = [
    'RUNTIME_VAR_KEYS',
    'render_template',
    'build_open_intervals',
    'location_is_open_now',
    'build_variables',
    'render_greeting',
    'render_system_prompt',
]

#: Whitespace-tolerant ``{{ key }}`` — word chars, dot, hyphen (skill §10).
_TEMPLATE_RE = re.compile(r'\{\{\s*([\w.\-]+)\s*\}\}')

#: The runtime var set (skill §10). Extend it HERE, in one place, when a module
#: adds one. Documented so a reviewer can diff the code against the contract.
RUNTIME_VAR_KEYS = (
    'from_e164', 'to_e164', 'tenant_name', 'location_id', 'location_name',
    'location_address', 'is_open_now', 'current_date', 'current_time',
    'caller_display_name', 'agent_name',
)

#: Spoken when ``AgentSetting.greeting`` is blank — first audio must never be
#: silence (skill §6), so there is always a line to say.
DEFAULT_GREETING = 'Thank you for calling. How can I help you today?'
#: Fallback ``agent_name`` when a location has not configured one.
DEFAULT_AGENT_NAME = 'the receptionist'


def render_template(text, variables):
    """Substitute ``{{key}}`` placeholders; a missing key renders as ``''``."""
    if not text:
        return ''

    def _sub(match):
        value = variables.get(match.group(1))
        return '' if value is None else str(value)

    return _TEMPLATE_RE.sub(_sub, text)


def build_open_intervals(location):
    """Gather every provider interval at ``location`` (called once, in connect()).

    Tenant AND location scoped. Runs ORM, so the consumer calls it through
    ``database_sync_to_async``. Returns a flat list of
    ``{'start_time', 'end_time', 'days': [weekday_key, ...]}`` — the union of every
    assigned provider's configured hours.
    """
    intervals = []
    assignments = (
        UserLocation.objects
        .filter(tenant_id=location.tenant_id, location=location, user__is_provider=True)
        .select_related('user')
    )
    for assignment in assignments:
        intervals.extend(get_provider_intervals(assignment.user, location))
    return intervals


def location_is_open_now(open_intervals, now_local):
    """True iff ``now_local`` falls inside any provider interval. Pure, no ORM.

    "No configured hours" reads as closed, per the ``tenants.services`` contract —
    an empty interval list is not "open all day". Start-inclusive, end-exclusive.
    """
    weekday_key = WEEKDAY_BY_INDEX.get(now_local.weekday())
    at = now_local.time()
    for interval in open_intervals:
        if weekday_key in interval['days'] and interval['start_time'] <= at < interval['end_time']:
            return True
    return False


def _format_date(now_local):
    """`Thursday, July 23, 2026` — portable (no %-d)."""
    return f'{now_local.strftime("%A, %B")} {now_local.day}, {now_local.year}'


def _format_time(now_local):
    """`2:05 PM` — portable (no %-I)."""
    hour = now_local.hour % 12 or 12
    return f'{hour}:{now_local.minute:02d} {now_local.strftime("%p")}'


def build_variables(agent_setting, call_session, location, now, open_intervals,
                    contact=None):
    """The merged ``{{variable}}`` map for one turn.

    ``AgentSetting.variables`` first, runtime vars last (runtime wins, skill §10).
    ``now`` is a tz-aware UTC time; date/time vars are rendered in the location's
    own timezone. Pass a fresh ``now`` each turn so the time-sensitive vars refresh.
    """
    now_local = now.astimezone(location.tzinfo)
    configured = dict(agent_setting.variables or {})

    runtime_vars = {
        'from_e164': call_session.from_number or '',
        'to_e164': call_session.to_number or '',
        'tenant_name': location.tenant.name if location.tenant_id else '',
        'location_id': str(location.pk),
        'location_name': location.name,
        'location_address': location.full_address,
        'is_open_now': 'yes' if location_is_open_now(open_intervals, now_local) else 'no',
        'current_date': _format_date(now_local),
        'current_time': _format_time(now_local),
        'caller_display_name': contact.display_name if contact is not None else '',
        # agent_name is nominally a runtime var (so it always resolves), but its
        # value defers to the location's configured one — computing it here just
        # guarantees the key is never missing.
        'agent_name': configured.get('agent_name') or DEFAULT_AGENT_NAME,
    }
    return {**configured, **runtime_vars}


def render_greeting(agent_setting, variables):
    """The deterministic opener — rendered from ``AgentSetting.greeting``, 0 tokens.

    Falls back to a short built-in line when the greeting is blank, so first audio
    is never silence. Never waits on an LLM (skill §6).
    """
    rendered = render_template(agent_setting.greeting, variables).strip()
    return rendered or DEFAULT_GREETING


def render_system_prompt(agent_setting, variables):
    """The system prompt for one turn, rendered from ``AgentSetting.prompt_text``.

    Composed fresh each turn (skill §10) so the recomputed time vars take effect.
    Names no tool — trivially true now (the tool table is empty until 3.3), and the
    rendering itself never special-cases a tool name, so 3.3 needs no change here.
    """
    return render_template(agent_setting.prompt_text, variables)
