"""Day and week calendar grids (sub-module 4.4).

A **VIEW sub-module**: zero models, zero migrations. Everything here reads
`scheduling.Appointment`, which 4.3 already owns, and renders it as a grid.

## The geometry, and why it is computed here rather than in the template

`theme.css` positions `.calendar-event` from two CSS custom properties,
`--slot-start` and `--slot-span`, both in pixels. Django templates cannot do
arithmetic, so the view does it and hands over finished integers.

Four things about that arithmetic are easy to get wrong, and all four bite:

1. **Offsets come from NAIVE LOCAL wall-clock minutes**, never from subtracting
   two aware datetimes. The gutter is labelled in wall-clock time, so on a DST
   day elapsed-time arithmetic would put every block an hour away from its own
   label. `local_start()` gives the wall clock; `minutes-from-midnight` is what
   the axis is measured in.
2. **Every custom-property value is an `int`.** `26px / 15min` is `1.7333…`, and
   a float rendered under a non-English locale becomes `112,666` — which makes
   the surrounding `calc()` invalid, so every block silently snaps to `top: 0`.
3. **Columns are keyed on COLUMN MEMBERSHIP, not on FK null-ness.** A booking on
   a deactivated resource or a suspended provider has a perfectly non-null FK and
   no column to sit in; keying on `is None` would drop it off the grid entirely.
   Anything without a home column goes to "Unassigned".
4. **One vertical window for the whole page.** The week grid shares a single
   gutter across seven columns, so seven per-day windows would give seven
   different vertical origins against one set of labels.
"""
import logging
from datetime import date, datetime, time as dt_time, timedelta

from django.utils import timezone as dj_timezone

from apps.scheduling.availability import BLOCKING_STATUSES, local_day_bounds_utc
from apps.scheduling.models import Appointment
from apps.scheduling.views._common import *  # noqa: F401,F403
from apps.scheduling.views._helpers import (
    authorised_pk,
    bookable_providers,
    bookable_resources,
    location_appointments,
    parse_local_date,
)

logger = logging.getLogger(__name__)

__all__ = ['calendar_day_view', 'calendar_week_view']

#: Must match `.calendar-slot { height: 26px }` in theme.css. The two are a
#: contract: change one and the blocks drift away from the gridlines.
SLOT_PX = 26
SLOT_MINUTES = 15

#: The window shown when a day has no appointments to widen it.
DEFAULT_WINDOW_START_MIN = 8 * 60
DEFAULT_WINDOW_END_MIN = 18 * 60

#: Minutes in a day. A block ending after midnight is clamped to this rather than
#: wrapping to a smaller number, which would invert the axis.
MINUTES_IN_DAY = 24 * 60

#: Column modes. `resource` is the default: a demo (and many real businesses)
#: has one provider per site, which renders the provider grid as a single stacked
#: column beside an empty Unassigned.
BY_RESOURCE = 'resource'
BY_PROVIDER = 'provider'
COLUMN_MODES = (BY_RESOURCE, BY_PROVIDER)


def _px(minutes):
    """Minutes to pixels, as an int. See docstring note 2."""
    return int(round(minutes * SLOT_PX / SLOT_MINUTES))


def _local_minutes(when, tzinfo):
    """Wall-clock minutes from midnight, in `tzinfo`. See docstring note 1."""
    local = when.astimezone(tzinfo)
    return local.hour * 60 + local.minute


def _block_span(appointment, tzinfo):
    """`(start_min, end_min)` for one appointment, in wall-clock minutes.

    `end_min` may exceed 1440 for a booking that runs past midnight; the caller
    clamps. Duration comes from the stored span, NOT from the service — `service`
    is `SET_NULL`, so a deleted service must not silently shrink a booking that
    really did last an hour.
    """
    start_min = _local_minutes(appointment.start_at, tzinfo)
    duration = max(
        1, int((appointment.end_at - appointment.start_at).total_seconds() // 60)
    )
    return start_min, start_min + duration


def _visible_window(spans):
    """One `(start_min, end_min)` window covering every span on the page.

    Rounded out to whole hours so the gutter reads in clean hours, widened to at
    least the default business day, and clamped to the day so a booking running
    past midnight cannot invert the axis.
    """
    start = DEFAULT_WINDOW_START_MIN
    end = DEFAULT_WINDOW_END_MIN

    for span_start, span_end in spans:
        start = min(start, span_start)
        end = max(end, span_end)

    start = max(0, (start // 60) * 60)
    end = min(MINUTES_IN_DAY, -(-end // 60) * 60)
    if end <= start:
        end = min(MINUTES_IN_DAY, start + 60)
    return start, end


def _hour_labels(window_start, window_end):
    """The gutter's hour rows."""
    return [
        {
            'label': f'{hour:02d}:00',
            'top_px': _px(hour * 60 - window_start),
        }
        for hour in range(window_start // 60, -(-window_end // 60))
    ]


def _pack_lanes(items):
    """Assign each item a lane so overlapping blocks sit side by side.

    `theme.css` gives `.calendar-event` `inset-inline: 4px`, i.e. full column
    width, so two overlapping bookings would render exactly on top of each other
    with the lower one invisible. Greedy first-fit: an item takes the first lane
    whose last block has already ended.

    Returns the lane count so the template can size each block as a fraction.
    """
    lanes = []
    for item in sorted(items, key=lambda i: (i['start_min'], i['end_min'])):
        for index, lane_end in enumerate(lanes):
            if item['start_min'] >= lane_end:
                item['lane'] = index
                lanes[index] = item['end_min']
                break
        else:
            item['lane'] = len(lanes)
            lanes.append(item['end_min'])
    lane_count = max(1, len(lanes))
    for item in items:
        item['lane_count'] = lane_count
    return lane_count


def _build_block(appointment, tzinfo, window_start):
    """One rendered appointment block."""
    start_min, end_min = _block_span(appointment, tzinfo)
    visible_end = min(end_min, MINUTES_IN_DAY)
    return {
        'appointment': appointment,
        'start_min': start_min,
        'end_min': visible_end,
        'top_px': _px(start_min - window_start),
        # At least one slot tall, or a very short booking renders as an
        # unclickable hairline.
        'height_px': max(SLOT_PX, _px(visible_end - start_min)),
        # True when the booking really runs past the end of the day and has been
        # clipped, so the template can say so rather than lying about the end.
        'clipped': end_min > MINUTES_IN_DAY,
    }


def _render_column(*, head, blocks, click_date, click_param, clickable,
                   show_now, is_unassigned=False, is_today=False):
    """One column, shaped so the template needs no logic of its own.

    Every branch a grid column can take is decided HERE. A template that has to
    work out whether a cell is clickable, which query parameter to append, or
    whether the now-line belongs in this column ends up doing it with filters
    like `default_if_none`, which silently resolve missing keys to '' and produce
    a column that renders but never works.
    """
    return {
        'head': head,
        'blocks': blocks,
        'click_date': click_date,
        'click_param': click_param,
        'clickable': clickable,
        'show_now': show_now,
        'is_unassigned': is_unassigned,
        'is_today': is_today,
    }


def _column_key(appointment, mode, member_ids):
    """Which column this appointment belongs in. See docstring note 3."""
    fk_id = (
        appointment.resource_id if mode == BY_RESOURCE else appointment.provider_id
    )
    return fk_id if fk_id in member_ids else None


def _parse_mode(request):
    """`?by=` validated against the known modes; anything else is the default."""
    raw = (request.GET.get('by') or '').strip().lower()
    return raw if raw in COLUMN_MODES else BY_RESOURCE


def _columns_for(request, mode):
    """`(list_of_column_objects, set_of_their_ids)` for the chosen mode."""
    if mode == BY_RESOURCE:
        columns = list(bookable_resources(request))
    else:
        columns = list(bookable_providers(request))
    return columns, {column.pk for column in columns}


def _slot_rows(window_start, window_end):
    """The clickable background rows, one per slot granularity step."""
    return [
        {
            'minute': minute,
            'hh': minute // 60,
            'mm': minute % 60,
            'is_hour': minute % 60 == 0,
        }
        for minute in range(window_start, window_end, SLOT_MINUTES)
    ]


def _now_line(location, day, window_start, window_end):
    """Pixel offset of the current-time line, or None when it is off-window.

    A now-line outside the window would render at a negative offset, drawing over
    the sticky column heads.
    """
    now_local = location.local_now()
    if now_local.date() != day:
        return None
    minutes = now_local.hour * 60 + now_local.minute
    if not (window_start <= minutes < window_end):
        return None
    return _px(minutes - window_start)


@login_required  # noqa: F405
def calendar_day_view(request):
    """One day, one column per resource or provider."""
    if request.location is None:
        # Every line below dereferences the location. Without this the page is an
        # AttributeError 500 rather than the empty state the banner explains.
        messages.info(  # noqa: F405
            request, 'Choose a location to see its calendar.'
        )
        return render(request, 'scheduling/calendar/day.html', {  # noqa: F405
            'no_location': True,
        })

    location = request.location
    tzinfo = location.tzinfo
    day = parse_local_date(request.GET.get('date')) or location.local_now().date()
    mode = _parse_mode(request)
    columns, member_ids = _columns_for(request, mode)

    lo, hi = local_day_bounds_utc(location, day)
    appointments = list(
        location_appointments(request)
        .filter(start_at__gte=lo, start_at__lt=hi)
        .order_by('start_at')
    )

    # Only blocking statuses occupy the grid. A cancelled or no-show booking has
    # freed its slot (see `availability.BLOCKING_STATUSES`), so it must not sit on
    # top of time someone else can now book.
    live = [a for a in appointments if a.status in BLOCKING_STATUSES]
    freed = [a for a in appointments if a.status not in BLOCKING_STATUSES]

    spans = [_block_span(a, tzinfo) for a in live]
    window_start, window_end = _visible_window(spans)

    buckets = {None: []}
    for column in columns:
        buckets[column.pk] = []
    for appointment in live:
        key = _column_key(appointment, mode, member_ids)
        buckets.setdefault(key, []).append(
            _build_block(appointment, tzinfo, window_start)
        )

    for blocks in buckets.values():
        _pack_lanes(blocks)

    now_px = _now_line(location, day, window_start, window_end)
    day_iso = day.isoformat()
    param = 'resource' if mode == BY_RESOURCE else 'provider'

    rendered = [
        _render_column(
            head=str(column),
            blocks=buckets.get(column.pk, []),
            click_date=day_iso,
            click_param=f'{param}={column.pk}',
            clickable=True,
            show_now=now_px is not None,
        )
        for column in columns
    ]
    # Always present, even when empty: it is the only place a booking whose
    # resource or provider has no column can appear, and hiding it would hide
    # those bookings entirely. Not clickable — there is nothing to book INTO.
    rendered.append(_render_column(
        head='Unassigned',
        blocks=buckets.get(None, []),
        click_date=day_iso,
        click_param='',
        clickable=False,
        show_now=now_px is not None,
        is_unassigned=True,
    ))

    return render(request, 'scheduling/calendar/day.html', {  # noqa: F405
        'day': day,
        'mode': mode,
        'columns': rendered,
        'column_count': len(rendered),
        'slot_rows': _slot_rows(window_start, window_end),
        'hour_labels': _hour_labels(window_start, window_end),
        'grid_height_px': _px(window_end - window_start),
        'window_start_min': window_start,
        'now_px': now_px,
        'freed': freed,
        'total_count': len(appointments),
        'prev_date': day - timedelta(days=1),
        'next_date': day + timedelta(days=1),
        'today': location.local_now().date(),
        'is_today': day == location.local_now().date(),
    })


@login_required  # noqa: F405
def calendar_week_view(request):
    """One resource or provider, seven days across.

    Deliberately NOT a week x N-columns matrix: with several resources that grid
    is unreadable at any realistic width, and every product surveyed narrows the
    week to a single column for the same reason.
    """
    if request.location is None:
        messages.info(  # noqa: F405
            request, 'Choose a location to see its calendar.'
        )
        return render(request, 'scheduling/calendar/week.html', {  # noqa: F405
            'no_location': True,
        })

    location = request.location
    tzinfo = location.tzinfo
    anchor = parse_local_date(request.GET.get('date')) or location.local_now().date()
    # Monday-based week, matching `WEEKDAY_BY_INDEX` in tenants.services.
    week_start = anchor - timedelta(days=anchor.weekday())
    days = [week_start + timedelta(days=offset) for offset in range(7)]

    mode = _parse_mode(request)
    columns, _member_ids = _columns_for(request, mode)
    chosen = authorised_pk(
        bookable_resources(request) if mode == BY_RESOURCE
        else bookable_providers(request),
        request.GET.get('column'),
    ) or (columns[0] if columns else None)

    lo, _ = local_day_bounds_utc(location, days[0])
    _, hi = local_day_bounds_utc(location, days[-1])

    queryset = location_appointments(request).filter(
        start_at__gte=lo, start_at__lt=hi
    )
    if chosen is not None:
        # NEVER `.filter(resource=None)` — Django compiles that to
        # `resource_id IS NULL`, which would present every unassigned booking as
        # the chosen room's week. `chosen is None` means there are no columns at
        # all, and the template renders an empty state instead.
        queryset = queryset.filter(
            **{('resource' if mode == BY_RESOURCE else 'provider'): chosen}
        )
    else:
        queryset = queryset.none()

    appointments = list(queryset.order_by('start_at'))
    live = [a for a in appointments if a.status in BLOCKING_STATUSES]

    # ONE window for all seven columns — they share a single gutter.
    spans = [_block_span(a, tzinfo) for a in live]
    window_start, window_end = _visible_window(spans)

    by_day = {day: [] for day in days}
    for appointment in live:
        local_day = appointment.start_at.astimezone(tzinfo).date()
        if local_day in by_day:
            by_day[local_day].append(
                _build_block(appointment, tzinfo, window_start)
            )
    for blocks in by_day.values():
        _pack_lanes(blocks)

    today = location.local_now().date()
    param = 'resource' if mode == BY_RESOURCE else 'provider'
    chosen_param = f'{param}={chosen.pk}' if chosen is not None else ''

    rendered = [
        _render_column(
            head=day.strftime('%a %d %b'),
            blocks=by_day[day],
            click_date=day.isoformat(),
            click_param=chosen_param,
            clickable=chosen is not None,
            # The now-line belongs only in today's column, and only when today
            # is actually in the displayed week.
            show_now=(day == today and _now_line(
                location, day, window_start, window_end) is not None),
            is_today=day == today,
        )
        for day in days
    ]

    return render(request, 'scheduling/calendar/week.html', {  # noqa: F405
        'mode': mode,
        'chosen': chosen,
        'column_options': columns,
        'columns': rendered,
        'now_px': _now_line(location, today, window_start, window_end),
        'column_count': 7,
        'slot_rows': _slot_rows(window_start, window_end),
        'hour_labels': _hour_labels(window_start, window_end),
        'grid_height_px': _px(window_end - window_start),
        'window_start_min': window_start,
        'week_start': week_start,
        'week_end': days[-1],
        'prev_date': week_start - timedelta(days=7),
        'next_date': week_start + timedelta(days=7),
        'today': today,
        'total_count': len(appointments),
    })
