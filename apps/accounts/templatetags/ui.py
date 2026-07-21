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
# `dob`/`birth` → date_of_birth). Over-redaction is the safe direction here, which
# is why broad-but-collision-prone stems are still avoided: `cell` is out because
# it lives inside `canCELLation`, and there is no bare `dl` because it is inside
# hanDLe/midDLe/moDeL. `first`/`last`/`account`/`contact` are in despite catching
# the odd benign key (`first_available`, `account_id`), because hiding a boolean
# or an integer is a harmless cost and missing a name is not. Collection stems
# (`attendee`/`participant`/`recipient`) redact an identity-bearing LIST wholesale
# via its key, which is the only lever there is over a list of bare strings.
_REDACT_KEY_SUBSTRINGS = (
    'name', 'first', 'last', 'contact', 'patient', 'caller',
    'dob', 'birth', 'ssn', 'social', 'phone', 'mobile',
    'email', 'address', 'zip', 'postal',
    'card', 'cvv', 'credit', 'account', 'iban', 'sortcode', 'nino',
    'passport', 'license', 'mrn',
    'insurance', 'medical', 'diagnosis', 'symptom',
    'attendee', 'participant', 'recipient',
    'password', 'secret', 'token', 'auth',
)
REDACTION_MARKER = '[redacted]'

# How deep to descend before giving up. Runtime-written JSON should never be this
# nested, and an unbounded walk over an adversarial payload is a place to hang —
# so at the cap a subtree is REPLACED with the marker rather than revealed. Over-
# redaction is the safe direction; a value we could not fully inspect is hidden,
# not shown. `raw_json → arguments → contact → field` is depth 4, well inside 6.
_MAX_REDACT_DEPTH = 6


def _redact_key(key):
    low = str(key).lower()
    return any(sub in low for sub in _REDACT_KEY_SUBSTRINGS)


def _redact_value(value, depth):
    """Redact recursively through dicts AND lists, to a bounded depth.

    A sensitive KEY hides its whole value; a non-sensitive key is descended into,
    because a benign name (`arguments`, `contact`, `attendees`) can still hold
    sensitive fields further down. A scalar under a non-sensitive key is safe to
    show. At `depth <= 0` a container is replaced wholesale with the marker — the
    safe direction when we have stopped inspecting.
    """
    if isinstance(value, dict):
        if depth <= 0:
            return REDACTION_MARKER
        return {
            k: (REDACTION_MARKER if _redact_key(k) else _redact_value(v, depth - 1))
            for k, v in value.items()
        }
    if isinstance(value, list):
        if depth <= 0:
            return REDACTION_MARKER
        return [_redact_value(item, depth - 1) for item in value]
    return value


@register.filter(name='redact_args')
def redact_args(value):
    """A display-time redaction pass over a tool-call argument dict.

    Returns a NEW dict — never mutates the input — where any key whose name
    case-insensitively contains a sensitive substring has its value replaced with
    `[redacted]`, so a developer sees WHICH fields a tool was called with without
    the page ever rendering a caller's name, number or date of birth. Non-sensitive
    keys (`service`, `day`, `window`, `topic`) keep their real values.

    **Recurses to a bounded depth through both nested dicts and lists** — so it
    redacts the SAME whether it is handed a bare `arguments` dict (the trace view)
    or a whole `raw_json` with `arguments` nested inside it (the raw-payload
    disclosure). That parity is the point: the two call sites sit at different
    depths, and a one-level filter would redact `arguments.contact.first_name` in
    the trace but leak it in the disclosure one level below. A doubly-nested value
    or a `[{full_name: …}]` list is caught too.

    **What it cannot catch, by construction:** it decides on KEY NAMES, so a
    sensitive value with no key hiding it slips through — a bare string inside a
    list (`{'attendees': ['Jane Roe']}`) is only protected if the LIST's key is on
    the denylist (then the whole list is redacted wholesale), and a name used as a
    dict KEY rather than a value is never inspected. Content-based PII detection is
    deliberately out of scope. The real fix for both is a Module 3 tool-schema
    rule — identity travels as a keyed dict value, never a bare list item or a
    key — with this filter as the display-time backstop.

    Never raises: anything that is not a dict returns `{}`, so a template can chain
    it unconditionally. It returns a plain structure and touches no HTML — escaping
    is the template layer's job (see `pretty_json`).
    """
    if not isinstance(value, dict):
        return {}
    return _redact_value(value, _MAX_REDACT_DEPTH)


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


@register.filter(name='iso_time')
def iso_time(value):
    """A log entry's `occurred_at` as a bare `HH:MM:SS`, from an ISO string.

    `logs` stamps are `.isoformat()` strings, not datetime objects, so Django's
    `date` filter cannot format them — it would return the raw string. The event
    log is a within-one-call timeline under a header that already names the day,
    so the wall-clock time is all a reader needs; the full ISO value stays in the
    `<time datetime="…">` attribute for machines.

    Accepts a datetime too (in case the runtime ever writes one). Falls back to
    the input unchanged on anything it cannot parse — a readable-but-raw stamp
    beats a blank cell.
    """
    if hasattr(value, 'strftime'):
        return value.strftime('%H:%M:%S')
    text = str(value or '').strip()
    if not text:
        return ''
    try:
        from datetime import datetime as _dt
        # `fromisoformat` handles the `+00:00` offset the seeder writes.
        return _dt.fromisoformat(text).strftime('%H:%M:%S')
    except (ValueError, TypeError):
        return text


_CONSENT_BASIS_LABELS = {
    'announced_notice': 'Recorded — consent announced',
    'two_party': 'Recorded — two-party consent',
    'one_party': 'Recorded — one-party consent',
    'not_recorded': 'Not recorded',
}


@register.filter(name='consent_basis_label')
def consent_basis_label(value):
    """A `metadata.consent_basis` value as a human label for the recording card.

    The recording consent basis is a compliance fact — WHY it was lawful to record
    this call — so it is shown, not hidden. Falls back to the raw value for an
    unrecognised basis rather than dropping it: Module 3 may add a
    jurisdiction-specific one later, and a compliance label must fail visible, not
    silent. Returns '' for an empty value so the badge simply does not render.
    """
    text = str(value or '').strip()
    if not text:
        return ''
    return _CONSENT_BASIS_LABELS.get(text, text)


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
