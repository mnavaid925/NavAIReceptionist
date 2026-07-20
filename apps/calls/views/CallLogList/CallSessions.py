"""The call log's list and detail pages (sub-module 5.1).

`CallSession` is fully location-scoped, so every queryset here carries BOTH
`tenant=request.tenant` and `location=request.location`. A call belongs to the
site whose number was dialled, and the people who answer for one site have no
business reading another site's callers.

**List and detail, and nothing else.** There is no create, edit or delete view in
this module and their absence is correct rather than pending — a completed call
is a record of what happened, and CLAUDE.md names this exact model as the
carve-out to the CRUD Completeness Rules. Nothing in Module 5 writes a row here;
Module 3's media-stream consumer is the only writer.

**Date filters never use `started_at__date`.** Django's `__date` lookup converts
using the ACTIVE timezone rather than the location's, and on MySQL it compiles to
`CONVERT_TZ()`, which returns NULL unless the server's timezone tables have been
loaded — so a `__date` filter passes under the SQLite test settings and silently
returns zero rows in production. It also cannot use `idx_call_tenant_loc_started`,
which is the one index this page's own query depends on. The same rule 4.3 states
in its own module docstring applies here verbatim: convert the local calendar day
to a half-open UTC range via `availability.local_day_bounds_utc` and compare the
raw column.

PII note: `from_number`, `to_number`, the transcript and the tool-call argument
blobs inside `logs` are personal data by definition. Nothing here logs a field
value — and the detail view logs nothing at all, because "who read whose call" is
an audit question this module has no audit trail to answer honestly.
"""
from apps.calls.models import CallSession
from apps.calls.views._common import *  # noqa: F401,F403
from apps.scheduling.availability import local_day_bounds_utc
from apps.scheduling.views._helpers import parse_local_date

# No module logger, deliberately. Every other view module in this project keeps
# one, so its absence here reads as an oversight unless it is stated: these two
# views only READ, and the only things worth naming in a log line — the caller's
# number, who they were matched to, what was said — are exactly the PII that must
# never reach a log at INFO. A logger with nothing safe to say is a loaded gun.

__all__ = [
    'OUTCOME_NO_TRANSFER',
    'OUTCOME_CHOICES',
    'callsession_list_view',
    'callsession_detail_view',
]

#: The "nothing was ever attempted" pseudo-outcome. Not a value the runtime ever
#: writes into `transfer.result` — it is the ABSENCE of one, which is why it
#: needs a sentinel of its own rather than another equality filter.
OUTCOME_NO_TRANSFER = 'no_transfer'

#: A derived filter axis, not a model field, so it lives in the view rather than
#: on `CallSession`: the transfer outcome is a key inside the `transfer` JSON
#: column and there is no `TRANSFER_RESULT_CHOICES` for it to be the display half
#: of. The five real values mirror `partials/_transfer_outcome.html`'s own branch
#: set exactly — that partial shipped first and is what fixed this vocabulary.
OUTCOME_CHOICES = [
    (OUTCOME_NO_TRANSFER, 'No transfer attempted'),
    ('connected', 'Connected'),
    ('off_hours', 'Off hours'),
    ('disabled', 'Disabled'),
    ('failed', 'Failed'),
    ('no_answer', 'No answer'),
]


def _location_sessions(request):
    """Calls at the active location. Tenant AND location scoped, always.

    Entity-local on purpose, mirroring 4.5's `_location_callbacks`: only this
    module reads call sessions today. It moves to `views/_helpers.py` when a
    SECOND sub-module actually shares it — 5.2's transcript page and 5.3's cost
    page will both want it, and that is the moment to promote it, not now.

    Returns nothing when no location is active — the safe direction, matching
    `location_appointments`. A user who has not chosen a site sees an empty log
    and the global "choose a location" banner, never another site's calls.

    `select_related('contact', 'location')` because every row on the list renders
    the caller's display name and the site's timezone; without it a 25-row page
    costs 51 queries.

    `prefetch_related('booked_appointments')` for the same reason one level out:
    both the list and the detail page render what the call booked, and that is a
    REVERSE FK, which `select_related` cannot follow. Without it the list pays
    one extra query per row — the N+1 that `select_related` above is there to
    prevent, reintroduced by a different relation. One query for the whole page
    either way.
    """
    if request.location is None:
        return CallSession.objects.none()
    return CallSession.objects.filter(
        tenant=request.tenant, location=request.location
    ).select_related('contact', 'location').prefetch_related('booked_appointments')


def _apply_outcome_filter(queryset, outcome):
    """Narrow by transfer outcome. Junk degrades to no filter, never raises.

    `transfer__result` is a JSON key transform, so it reads through the column
    without the row needing the key at all.

    `no_transfer` uses `__isnull=True` rather than comparing `transfer` to `{}`:
    the key is genuinely missing both when the dict is empty (the common case —
    most callers never ask for a human) and when the runtime recorded a transfer
    attempt that died before it had a result to write. Exact-dict equality would
    catch only the first and would also compile differently across MySQL and the
    SQLite test backend, which is the kind of divergence that passes CI and
    returns the wrong rows in production.
    """
    if outcome == OUTCOME_NO_TRANSFER:
        return queryset.filter(transfer__result__isnull=True)
    if outcome in dict(OUTCOME_CHOICES):
        return queryset.filter(transfer__result=outcome)
    # Anything else — including an empty parameter and outright junk — is "any
    # outcome". A filter bar must never be able to 500 the page it sits on.
    return queryset


@login_required  # noqa: F405
def callsession_list_view(request):
    """The call log: newest first, searchable, filtered on four axes."""
    # Newest call first, explicitly. `Meta.ordering` is `-created_at`, which is
    # ALMOST the same order and is not the same thing: a session row is created
    # when the webhook lands and stamped `started_at` when the media stream
    # actually opens, so a slow answer can reorder the pair. The page is about
    # when calls HAPPENED, and this ordering is also what lets the query ride
    # `idx_call_tenant_loc_started`.
    queryset = _location_sessions(request).order_by('-started_at')

    search = request.GET.get('q', '').strip()
    if search:
        # Both the raw numbers AND the linked contact, because the same caller
        # appears either way: an unrecognised number is all there is on a first
        # call, and once someone attaches a `Contact` the person is findable by
        # name. Searching only one half loses whichever rows took the other path.
        queryset = queryset.filter(
            Q(from_number__icontains=search)  # noqa: F405
            | Q(to_number__icontains=search)  # noqa: F405
            | Q(contact__first_name__icontains=search)  # noqa: F405
            | Q(contact__last_name__icontains=search)  # noqa: F405
            | Q(contact__phone_e164__icontains=search)  # noqa: F405
        )

    # Each of the three choice filters is checked against the model's own choice
    # dict, so `?status=whatever` degrades to "no filter" instead of returning an
    # empty page that looks like "this site has never taken a call".
    status = request.GET.get('status', '').strip()
    if status in dict(CallSession.STATUS_CHOICES):
        queryset = queryset.filter(status=status)

    mode = request.GET.get('mode', '').strip()
    if mode in dict(CallSession.MODE_CHOICES):
        queryset = queryset.filter(mode=mode)

    outcome = request.GET.get('outcome', '').strip()
    queryset = _apply_outcome_filter(queryset, outcome)

    # `parse_local_date` is imported from `scheduling` rather than copied: it is
    # the same `YYYY-MM-DD` query parameter, and its non-obvious part is the
    # 1900-2200 clamp that stops `?from=9999-12-31` overflowing the `+ 1 day`
    # inside `local_day_bounds_utc`. A second copy would be a second place for
    # that clamp to rot. `authorised_pk` is deliberately NOT imported — this list
    # has no FK filter for it to resolve, and importing an unused guard invites a
    # later reader to reach for it on a queryset that was never scoped.
    location = request.location
    date_from = parse_local_date(request.GET.get('from'))
    date_to = parse_local_date(request.GET.get('to'))
    # Guarded on `location`, not just on the parsed date: `local_day_bounds_utc`
    # reads `location.tzinfo`, so a date supplied with no active site would raise
    # on `None`. That path is unreachable through the UI and trivially reachable
    # by hand-editing the query string.
    if location is not None and date_from is not None:
        lo, _ = local_day_bounds_utc(location, date_from)
        queryset = queryset.filter(started_at__gte=lo)
    if location is not None and date_to is not None:
        _, hi = local_day_bounds_utc(location, date_to)
        queryset = queryset.filter(started_at__lt=hi)

    # Pagination LAST, after every filter — paginating first would count and slice
    # the unfiltered log and hand the template a page of rows the filters exclude.
    page_obj, elided_page_range = paginate(request, queryset)  # noqa: F405

    return render(request, 'calls/calllog/callsession/list.html', {  # noqa: F405
        'call_sessions': page_obj.object_list,
        'page_obj': page_obj,
        'elided_page_range': elided_page_range,
        'total_count': page_obj.paginator.count,
        # Every filter dropdown's data, passed explicitly — a template cannot
        # conjure a choice list it was not given, and a silently empty <select>
        # is the classic broken-filter bug.
        'status_choices': CallSession.STATUS_CHOICES,
        'mode_choices': CallSession.MODE_CHOICES,
        'outcome_choices': OUTCOME_CHOICES,
    })


@login_required  # noqa: F405
def callsession_detail_view(request, pk):
    """One call. Deliberately thin — the rich panels belong to 5.2-5.4.

    Scoped through `_location_sessions`, so a pk from another tenant or another
    site 404s rather than rendering: a bare `get_object_or_404(CallSession,
    pk=pk)` here would be a cross-location IDOR onto a transcript.

    The `booked_appointments` prefetch this page needs lives on
    `_location_sessions` rather than here, because the LIST needs it just as
    much — it renders the same reverse FK per row, where the cost is per row
    rather than once.
    """
    obj = get_object_or_404(_location_sessions(request), pk=pk)  # noqa: F405

    return render(request, 'calls/calllog/callsession/detail.html', {  # noqa: F405
        'obj': obj,
    })
