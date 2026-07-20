"""Shared presentation helpers used across every module's templates.

    {% load ui %}

Kept deliberately small: these exist because Django templates cannot do the work
safely inline, not as a general utility drawer.
"""
import json
import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag(takes_context=True)
def querystring_without_page(context):
    """Return the current query string minus `page`, ready to append.

    Pagination links must preserve the active filters — otherwise page 2 silently
    shows the unfiltered list — but must not carry the old page number. Output is
    either an empty string or `&k=v&k2=v2`, so a template can write
    `?page={{ n }}{{ qs }}` unconditionally.
    """
    request = context.get('request')
    if request is None:
        return ''

    params = request.GET.copy()
    params.pop('page', None)

    encoded = params.urlencode()
    return mark_safe('&' + encoded) if encoded else ''


# A permissive E.164-ish match: optional +, 8-15 digits. Anything else is shown
# unchanged rather than mangled.
_E164_RE = re.compile(r'^\+?(\d{8,15})$')

# North American numbers get the familiar grouping; everything else keeps its
# E.164 form, because guessing another country's grouping is worse than not.
_NANP_RE = re.compile(r'^1(\d{3})(\d{3})(\d{4})$')


@register.filter(name='phone_e164')
def phone_e164(value):
    """Render a stored E.164 number for humans.

    Every phone number in the product renders through this one filter — never an
    ad-hoc slice in a template, which is how a caller's number ends up truncated
    on one page and not another.
    """
    if not value:
        return ''

    raw = str(value).strip()
    match = _E164_RE.match(raw.replace(' ', '').replace('-', ''))
    if not match:
        return raw

    digits = match.group(1)
    nanp = _NANP_RE.match(digits)
    if nanp:
        return '+1 ({}) {}-{}'.format(*nanp.groups())
    return '+' + digits


@register.filter(name='initials')
def initials(value):
    """Two-letter initials from a display name, for `.avatar-initial`."""
    parts = [part for part in str(value or '').split() if part]
    if not parts:
        return '?'
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


@register.filter(name='level_badge')
def level_badge(level):
    """Map a call event-log level onto the fixed badge inventory.

    The design system's modifiers are colour-named and closed. This filter exists
    so an event level never reaches a template as an invented `badge-<level>`.
    """
    return {
        'debug': 'badge-muted',
        'info': 'badge-info',
        'warning': 'badge-amber',
        'error': 'badge-red',
        'critical': 'badge-red',
    }.get(str(level or '').lower(), 'badge-muted')


@register.filter(name='dict_get')
def dict_get(mapping, key):
    """`mapping[key]` with a silent miss — for JSON blobs rendered defensively.

    CallSession's transcript/logs/analysis/usage columns are JSON written by the
    runtime; a detail page must render an abandoned call that has none of them
    without raising.
    """
    try:
        return mapping.get(key)
    except (AttributeError, TypeError):
        return None


@register.simple_tag
def peaks_dom_id(prefix, pk):
    """Build the waveform's `json_script` element id in one place.

    Assembling this id from a filter chain in the template is silently broken —
    the id and the `data-peaks-id` reference drift and the waveform renders empty.
    """
    return escape(f'{prefix}-{pk}')


# The tool-call event log renders the arguments the agent passed to a function —
# and by CLAUDE.md's own example a `create_contact` args payload is a full name
# and a date of birth. Redaction on WRITE is Module 3's job (unbuilt). This is
# the belt to that suspenders: a value the write path forgot to redact is still
# hidden at DISPLAY, because a log surface must never be the place a caller's DOB
# leaks. Substrings, not exact keys — one entry catches every spelling
# (`name` → first_name/last_name/full_name; `phone` → phone_e164/caller_phone;
# `dob`/`birth` → date_of_birth). Over-redaction is the safe direction here.
_REDACT_KEY_SUBSTRINGS = (
    'name', 'dob', 'birth', 'ssn', 'social', 'phone', 'email', 'address',
    'zip', 'postal', 'card', 'cvv', 'credit', 'insurance', 'medical',
    'diagnosis', 'symptom', 'password', 'secret', 'token', 'auth',
)
REDACTION_MARKER = '[redacted]'


@register.filter(name='redact_args')
def redact_args(value):
    """A display-time redaction pass over a tool-call argument dict.

    Returns a NEW dict — never mutates the input — where any key whose name
    case-insensitively contains a sensitive substring has its value replaced with
    `[redacted]`, so a developer sees WHICH fields a tool was called with without
    the page ever rendering a caller's name, number or date of birth. Non-sensitive
    keys (`service`, `day`, `window`, `topic`) keep their real values.

    Recurses exactly one level into a nested dict value, so the `arguments` inside
    a whole `raw_json` dump are covered too — the point being that the expandable
    raw-payload disclosure cannot become a hole around this filter.

    Never raises: anything that is not a dict returns `{}`, so a template can chain
    it unconditionally. It returns a plain dict and touches no HTML — escaping is
    the template layer's job (see `pretty_json`).
    """
    if not isinstance(value, dict):
        return {}

    def _sensitive(key):
        low = str(key).lower()
        return any(sub in low for sub in _REDACT_KEY_SUBSTRINGS)

    redacted = {}
    for key, val in value.items():
        if _sensitive(key):
            redacted[key] = REDACTION_MARKER
        elif isinstance(val, dict):
            # One level down — a benign-named key (`arguments`, `error`) can still
            # hold sensitive fields. Not deeper: unbounded recursion over
            # runtime-written JSON is a place to hang, and one level covers the
            # {tool, arguments:{…}, error:{…}} shape the runtime actually writes.
            redacted[key] = {
                k: (REDACTION_MARKER if _sensitive(k) else v)
                for k, v in val.items()
            }
        else:
            redacted[key] = val
    return redacted


@register.filter(name='pretty_json')
def pretty_json(value):
    """A JSON blob as an indented string — NOT marked safe, so it stays escaped.

    The raw-payload disclosure shows this inside a `<pre>`. Django's stock
    `pprint` marks its output `is_safe=True`, which would skip auto-escaping the
    exact runtime-written content this sub-module exists to control — so this
    returns a plain string and lets autoescape HTML-escape it. Harmless for JSON
    (only `<`/`>`/`&` are touched), and the whole point.

    Never raises: a value `json.dumps` cannot serialise falls back to `str(value)`.
    """
    try:
        return json.dumps(value, indent=2, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


@register.filter(name='error_log_count')
def error_log_count(logs):
    """How many event-log entries are error- or critical-level.

    Lets the "N error(s) on this call" callout live entirely in the template, with
    no view-side computation and no extra context variable — the same
    template-does-the-work posture the analysis and cost cards take. Returns 0 for
    anything that is not a list of dicts.
    """
    if not isinstance(logs, list):
        return 0
    count = 0
    for entry in logs:
        try:
            if str(entry.get('level', '')).lower() in ('error', 'critical'):
                count += 1
        except (AttributeError, TypeError):
            continue
    return count
