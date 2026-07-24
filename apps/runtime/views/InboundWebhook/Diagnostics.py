"""Runtime diagnostics — sub-module 3.1's observable surface.

A service sub-module ships no CRUD, but "no templates" never means "nothing to
look at" (``voice-agent-runtime`` skill §15). This read-only page answers, for the
**active location**, the question 3.1 exists to make answerable: *are inbound
calls being resolved, and where should Twilio point?* It shows recent resolved
call sessions, the location's agent/telephony readiness, the exact webhook URL to
configure in Twilio, and the ``PROVIDER_MODE`` the whole path is running under.

3.5 grew it into the fuller page it was always the seed of: an ended-reason tally,
per-stage ASR/LLM/TTS latency percentiles, a recent-errors panel and today's spend
— all read off ``CallSession``'s existing JSON columns over ONE bounded slice, not
a new table (Invariant 2: there is no ``RuntimeError``/``CallEvent`` model, and a
diagnostics panel is not a reason to invent one). Tenant AND location scoped on
every query — the session rows come through the single audited scoping helper.
"""
from collections import Counter

from apps.agents.models import AgentSetting
from apps.calls.models import CallSession
from django.db.models import Count, Q

from apps.runtime.agent.state import ENDED_REASON_DISPLAY
from apps.runtime.agent.transfer import (
    RESULT_CONNECTED,
    RESULT_DISABLED,
    RESULT_FAILED,
    RESULT_NO_ANSWER,
    RESULT_OFF_HOURS,
)
from apps.runtime.providers.telephony import media_stream_ws_url
from apps.runtime.views._common import *  # noqa: F401,F403
from apps.runtime.views._helpers import location_sessions, recent_location_sessions

__all__ = ['runtime_diagnostics_view']

#: Display order + label + badge for the transfer-outcome tally. Badge colours
#: match `templates/partials/_transfer_outcome.html` exactly — one colour map for
#: the one vocabulary, never a second one invented here.
_TRANSFER_RESULT_DISPLAY = [
    (RESULT_CONNECTED, 'Connected', 'badge-green'),
    (RESULT_OFF_HOURS, 'Off hours', 'badge-amber'),
    (RESULT_NO_ANSWER, 'No answer', 'badge-amber'),
    (RESULT_FAILED, 'Failed', 'badge-red'),
    (RESULT_DISABLED, 'Disabled', 'badge-muted'),
]
#: Bounds the Python-side tally so the page cost does not grow with call volume. A
#: JSON-key aggregate is not portably expressible across MySQL and SQLite (the test
#: DB), so the tally is done in Python over this bounded, most-recent slice.
_TRANSFER_TALLY_LIMIT = 200
#: The most-recent slice the three 3.5 panels share. Smaller than the transfer
#: tally's window on purpose: those rows are read with their `logs` column, which
#: is the largest JSON on the table, so the page pulls a diagnostic sample rather
#: than a history. The template says so, rather than implying these are all-time.
_DIAGNOSTICS_SAMPLE_LIMIT = 50
#: Newest-first cap on the recent-errors panel.
_ERROR_PANEL_LIMIT = 20
#: The turn stages that carry a latency `ms` in their log rows (written by
#: `agent/turn.py`). Display order is the order of a turn.
_LATENCY_STAGES = [('asr', 'Speech to text'), ('llm', 'Model'), ('tts', 'Speech synthesis')]


def _percentile(values, pct):
    """The ``pct`` percentile of ``values`` by nearest rank. None when empty.

    Deliberately the simple nearest-rank definition, not an interpolating one:
    these are latency samples over a few dozen calls, where an interpolated figure
    would imply a precision the sample size does not support.
    """
    if not values:
        return None
    ordered = sorted(values)
    index = int(round((pct / 100.0) * (len(ordered) - 1)))
    return ordered[min(max(index, 0), len(ordered) - 1)]


def _latency_stats(sessions):
    """Per-stage p50/p95 over the sampled sessions' event logs.

    Explicitly per-STAGE, not the end-to-end turn budget CLAUDE.md sets (≤1.5 s
    p50 / ≤3 s p95 from end-of-speech to first audio). That budget is the SUM of a
    turn's stages, and the log rows carry no shared turn-correlation id to sum them
    by — so reporting these as the budget would be an overclaim. The template
    labels them per stage for the same reason.
    """
    buckets = {key: [] for key, _label in _LATENCY_STAGES}
    for session in sessions:
        for entry in (session.logs if isinstance(session.logs, list) else []):
            if not isinstance(entry, dict):
                continue
            bucket = buckets.get(entry.get('category'))
            if bucket is None:
                continue
            raw = entry.get('raw_json')
            value = raw.get('ms') if isinstance(raw, dict) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                bucket.append(value)
    return [
        {'key': key, 'label': label, 'n': len(buckets[key]),
         'p50': _percentile(buckets[key], 50), 'p95': _percentile(buckets[key], 95)}
        for key, label in _LATENCY_STAGES
    ]


def _recent_errors(sessions, limit=_ERROR_PANEL_LIMIT):
    """The newest error/warning log rows across the sampled sessions.

    Reads ``CallSession.logs`` — the same column 5.3's per-call event log renders —
    across a bounded set of rows. **No `raw_json` is surfaced**: a tool row's
    payload is redacted at write time but still describes caller data, and an
    operator triaging "what is failing" needs the level, the stage and which call,
    not the caller's details.
    """
    rows = []
    for session in sessions:
        for entry in (session.logs if isinstance(session.logs, list) else []):
            if not isinstance(entry, dict) or entry.get('level') not in ('error', 'warning'):
                continue
            rows.append({
                'level': entry.get('level'),
                'badge': 'badge-red' if entry.get('level') == 'error' else 'badge-amber',
                'category': entry.get('category') or '—',
                'title': entry.get('title') or '',
                'occurred_at': entry.get('occurred_at') or '',
                'session_pk': session.pk,
                'call_sid': session.provider_call_sid,
            })
    rows.sort(key=lambda row: row['occurred_at'], reverse=True)
    return rows[:limit]


@login_required  # noqa: F405
@require_http_methods(['GET'])  # noqa: F405
def runtime_diagnostics_view(request):
    """The runtime status page for the active location."""
    location = request.location

    setting = None
    if location is not None:
        # Scoped by tenant AND location — pk alone is never enough, and here the
        # (tenant, location) pair is unique so this is the one row or nothing.
        setting = (
            AgentSetting.objects
            .filter(tenant=request.tenant, location=location)
            .select_related('location')
            .first()
        )

    # location_sessions returns .none() when no location is active, so the counts
    # are 0 and the list is empty without a special case here. Both totals in one
    # aggregate — one round trip, not two (and none() short-circuits to 0/0 with
    # no query at all when there is no active location).
    scoped = location_sessions(request)
    stats = scoped.aggregate(
        active=Count('pk', filter=Q(status=CallSession.STATUS_IN_PROGRESS)),
        total=Count('pk'),
        # 3.4: calls that handed off to a person (connected OR failed both end
        # 'transferred' — the media leg left the consumer either way).
        transferred=Count('pk', filter=Q(status=CallSession.STATUS_TRANSFERRED)),
    )
    sessions = list(recent_location_sessions(request))

    # Per-result transfer tally (includes off-hours attempts, which do NOT end as
    # status='transferred' — the call continued after the callback fallback), over
    # a bounded most-recent slice, counted in Python for cross-DB portability.
    # `values_list` (not `.only`) so it does not collide with `location_sessions`'s
    # own `select_related('location')` — a deferred field cannot also be traversed.
    result_counts = Counter(
        transfer.get('result')
        for transfer in scoped.order_by('-created_at').values_list(
            'transfer', flat=True)[:_TRANSFER_TALLY_LIMIT]
        if isinstance(transfer, dict) and transfer.get('result')
    )
    transfer_outcomes = [
        {'label': label, 'badge': badge, 'count': result_counts[key]}
        for key, label, badge in _TRANSFER_RESULT_DISPLAY if result_counts.get(key)
    ]

    # 3.5's three panels share ONE bounded read. These rows carry `logs`, the
    # largest JSON column on the table, so this is materialized once and passed to
    # each pass rather than re-queried three times for what is one sample.
    recent = list(scoped.order_by('-created_at')[:_DIAGNOSTICS_SAMPLE_LIMIT])

    reason_counts = Counter(
        (session.metadata or {}).get('ended_reason')
        for session in recent if isinstance(session.metadata, dict)
    )
    ended_reasons = [
        {'label': label, 'badge': badge, 'count': reason_counts[key]}
        for key, label, badge in ENDED_REASON_DISPLAY if reason_counts.get(key)
    ]
    latency_stats = _latency_stats(recent)
    recent_errors = _recent_errors(recent)

    # Today's spend, in the LOCATION's day — a Los Angeles location's "today" is
    # not the server's. `total_cost_usd` is the model's own derived property, so
    # cost is summed from `usage` by the one formula rather than a second one
    # reimplemented here that could drift from the call-detail page's figure.
    total_cost_today = 0.0
    if location is not None:
        local_now = timezone.localtime(timezone.now(), location.tzinfo)  # noqa: F405
        midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        total_cost_today = sum(
            session.total_cost_usd
            for session in scoped.filter(started_at__gte=midnight)
        )

    # The URL Twilio must POST the inbound call to. Built from the public tunnel
    # base when set (what a real Twilio number needs), else the current host so
    # the page is still useful on a bare dev run.
    webhook_path = reverse('runtime:voice_webhook')  # noqa: F405
    base = (settings.TWILIO_WEBHOOK_BASE_URL or '').rstrip('/')  # noqa: F405
    webhook_url = f'{base}{webhook_path}' if base else request.build_absolute_uri(webhook_path)

    provider_mode = settings.PROVIDER_MODE  # noqa: F405

    return render(request, 'runtime/diagnostics.html', {  # noqa: F405
        'active_location': location,
        'setting': setting,
        'readiness_issues': setting.readiness_issues() if setting else [],
        'sessions': sessions,
        'stats': stats,
        'transfer_outcomes': transfer_outcomes,
        'ended_reasons': ended_reasons,
        'latency_stats': latency_stats,
        'recent_errors': recent_errors,
        'total_cost_today': total_cost_today,
        'sample_limit': _DIAGNOSTICS_SAMPLE_LIMIT,
        'webhook_url': webhook_url,
        'stream_ws_url': media_stream_ws_url(),
        'provider_mode': provider_mode,
        'is_simulated': provider_mode != 'live',
    })
