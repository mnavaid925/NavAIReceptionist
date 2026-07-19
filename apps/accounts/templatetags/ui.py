"""Shared presentation helpers used across every module's templates.

    {% load ui %}

Kept deliberately small: these exist because Django templates cannot do the work
safely inline, not as a general utility drawer.
"""
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
