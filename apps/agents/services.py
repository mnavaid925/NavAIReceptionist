"""Pure logic for Module 2 — prompt rendering (2.1) and transfer gating (2.3).

Both plans proposed their own `services.py`; they are merged here so there is one
module, because Module 3's turn loop will import from both halves on the same
call and a split would guarantee drift.

**Everything here is pure and hot-path safe** — no ORM writes, no network, no
provider import. It runs inside the realtime turn loop, where a blocking call
freezes audio for every concurrent call on the worker.
"""
import re
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = [
    'RESERVED_RUNTIME_VARIABLES',
    'DEFAULT_TRANSFER_KEYWORDS',
    'WEEKDAY_KEYS',
    'extract_variable_names',
    'render_template',
    'unknown_variable_names',
    'sample_runtime_context',
    'build_runtime_context',
    'is_transfer_available',
    'next_transfer_window',
    'resolve_transfer_number',
    'matches_transfer_keyword',
]

# --------------------------------------------------------------------------- #
# 2.1 — Prompt and greeting rendering
# --------------------------------------------------------------------------- #

_VARIABLE_RE = re.compile(r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}')

#: Names the SERVER computes at call time. A tenant cannot override them — a
#: caller-visible "current time" that the business could pin to a constant would
#: make the agent lie about its own availability.
RESERVED_RUNTIME_VARIABLES = {
    'business_name',
    'location_name',
    'location_phone',
    'current_date',
    'current_time',
    'from_number',
    'is_open_now',
    'transfer_available',
    'transfer_reopens_at',
}


def extract_variable_names(text):
    """Every `{{name}}` referenced in `text`, in first-appearance order."""
    seen, names = set(), []
    for match in _VARIABLE_RE.finditer(text or ''):
        name = match.group(1)
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def unknown_variable_names(text, variables):
    """Placeholders that would render as nothing.

    Caught at SAVE time rather than at call time: an unresolved `{{name}}` on a
    live call becomes either a literal brace sequence read aloud to a caller, or
    a silent gap in a sentence. Both are worse than a form error.
    """
    known = set(variables or {}) | RESERVED_RUNTIME_VARIABLES
    return [name for name in extract_variable_names(text) if name not in known]


def render_template(text, context):
    """Substitute `{{name}}` from `context`.

    Deliberately NOT Django's template engine. This string is authored by a
    tenant and rendered into speech; running it through a real template engine
    would hand a caller-adjacent input tag execution, filters and attribute
    traversal. Plain named substitution is the whole feature.

    An unknown placeholder renders as an empty string — by the time a call is in
    flight, a gap is better than braces read aloud.
    """
    if not text:
        return ''

    def replace(match):
        value = (context or {}).get(match.group(1), '')
        return '' if value is None else str(value)

    return _VARIABLE_RE.sub(replace, text)


def build_runtime_context(setting, *, from_number='', now=None):
    """The variable map for one render.

    Runtime values are applied LAST so they win over the tenant's map — see
    `RESERVED_RUNTIME_VARIABLES`.

    NOTE for Module 3: `current_time`, `current_date`, `is_open_now`,
    `transfer_available` and `transfer_reopens_at` are time-dependent and MUST be
    rebuilt per turn. Computing them once at call start makes a long call assert
    the wrong day, or offer a human after the transfer window has closed.
    """
    location = setting.location
    tz = location.tzinfo
    moment = (now or datetime.now(tz)).astimezone(tz)

    context = dict(setting.variables or {})
    context.update({
        'business_name': setting.tenant.name if setting.tenant_id else '',
        'location_name': location.name,
        'location_phone': location.phone or '',
        # Padded forms only — %-d and %-I are a glibc extension the Windows
        # runtime rejects outright.
        'current_date': moment.strftime('%Y-%m-%d'),
        'current_time': moment.strftime('%H:%M'),
        'from_number': from_number or '',
        # The SERVER decides open/closed and injects a literal yes/no. Handing the
        # model raw hours plus a clock and asking it to work this out is how an
        # agent tells a caller the wrong thing.
        'is_open_now': 'yes',
        'transfer_available': 'yes' if is_transfer_available(setting, now=moment) else 'no',
        'transfer_reopens_at': next_transfer_window(setting, now=moment) or '',
    })
    return context


def sample_runtime_context(setting):
    """A representative context for the save-time preview."""
    return build_runtime_context(setting, from_number='+13125550000')


# --------------------------------------------------------------------------- #
# 2.3 — Transfer gating
# --------------------------------------------------------------------------- #

WEEKDAY_KEYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday',
                'saturday', 'sunday']

#: Built into the runtime. `AgentSetting.transfer_keywords` ADDS to this set —
#: it never replaces it, so a tenant cannot accidentally make "emergency"
#: stop escalating by saving a narrower list.
DEFAULT_TRANSFER_KEYWORDS = (
    'human', 'person', 'agent', 'representative', 'operator',
    'manager', 'supervisor', 'someone else', 'real person',
    'speak to somebody', 'talk to someone', 'emergency', 'urgent',
)


def _parse_hhmm(value):
    """`"HH:MM"` to a `time`, or None. Never raises on stored JSON."""
    if isinstance(value, dt_time):
        return value
    if not isinstance(value, str):
        return None
    parts = value.strip().split(':')
    if len(parts) < 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return dt_time(hour, minute)


def _transfer_tz(setting):
    """The timezone the transfer windows are expressed in.

    `transfer_timezone` is its own field rather than the location's, because a
    business can route handoffs to a call centre in a different zone from the
    site the caller dialled.
    """
    try:
        return ZoneInfo(setting.transfer_timezone or 'UTC')
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo('UTC')


def is_transfer_available(setting, *, now=None):
    """Whether a human handoff can be offered right now.

    False when transfer is off, when no destination is configured, or when the
    moment falls outside the configured window. An empty window map means no
    restriction — always available.
    """
    if not setting.transfer_enabled:
        return False
    if not setting.transfer_phone_number:
        # Promising a handoff with nowhere to send it is the failure this guards.
        return False

    hours = setting.transfer_working_hours or {}
    if not isinstance(hours, dict) or not hours:
        return True

    tz = _transfer_tz(setting)
    moment = (now or datetime.now(tz)).astimezone(tz)
    day = hours.get(WEEKDAY_KEYS[moment.weekday()])
    if not isinstance(day, dict) or not day.get('enabled'):
        return False

    start = _parse_hhmm(day.get('start'))
    end = _parse_hhmm(day.get('end'))
    if start is None or end is None:
        return False
    return start <= moment.time() < end


def next_transfer_window(setting, *, now=None):
    """When transfer next opens, as `"Monday 09:00"`, or '' if never/always.

    Lets the agent say something useful off-hours instead of a bare refusal.
    """
    if not setting.transfer_enabled or not setting.transfer_phone_number:
        return ''
    hours = setting.transfer_working_hours or {}
    if not isinstance(hours, dict) or not hours:
        return ''

    tz = _transfer_tz(setting)
    moment = (now or datetime.now(tz)).astimezone(tz)

    for offset in range(8):
        index = (moment.weekday() + offset) % 7
        day = hours.get(WEEKDAY_KEYS[index])
        if not isinstance(day, dict) or not day.get('enabled'):
            continue
        start = _parse_hhmm(day.get('start'))
        if start is None:
            continue
        if offset == 0 and moment.time() >= start:
            continue
        return f'{WEEKDAY_KEYS[index].title()} {start.strftime("%H:%M")}'
    return ''


def resolve_transfer_number(setting, target='primary'):
    """The number to dial. NEVER accepts a number as input.

    This is the Invariant 3 enforcement point for transfers. The model picks a
    LABEL — `"primary"` or `"secondary"` — and the server maps it to a configured
    E.164 value. A number produced by the caller or by the model is not dialable
    by construction, which is what stops a prompt-injected agent from bridging a
    call to an attacker's line.
    """
    if not setting.transfer_enabled:
        return ''
    if target == 'secondary' and setting.transfer_secondary_number:
        return setting.transfer_secondary_number
    return setting.transfer_phone_number or ''


def matches_transfer_keyword(utterance, setting=None):
    """Whether caller speech should trigger a handoff offer.

    Tenant keywords are added to the built-ins, never substituted for them.
    """
    text = (utterance or '').lower()
    if not text:
        return False

    extra = []
    if setting is not None:
        raw = setting.transfer_keywords or []
        if isinstance(raw, list):
            extra = [str(k).lower().strip() for k in raw if str(k).strip()]

    return any(keyword in text for keyword in tuple(DEFAULT_TRANSFER_KEYWORDS) + tuple(extra))
