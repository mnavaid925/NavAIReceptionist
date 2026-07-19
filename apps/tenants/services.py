"""Provider working-hours services (sub-module 1.4).

Two contracts live here:

* `get_provider_intervals(user, location, weekday=None)` — the READ contract that
  Module 4's availability search will import. Named and stabilised now so the
  storage shape can change later without touching the caller.
* `validate_provider_hours(...)` — the WRITE guard used by the hours form.

**Storage.** Hours live in `accounts.User.provider_hours`, a JSON dict keyed by
LOCATION ID as a string::

    {"7": [{"start_time": "09:00", "end_time": "12:30", "days": ["mon", "tue"]},
           {"start_time": "13:30", "end_time": "17:00", "days": ["mon", "tue"]}]}

There is no working-hours table, and adding one would breach the eleven-model
ceiling in NavAIReceptionist-ERD.md. The same person works different days at
different sites, which is exactly why the dict is keyed by location.

**Timezone.** Every interval is wall-clock time AT THE LOCATION. Resolving it uses
`Location.tzinfo`, never the server's timezone and never the browser's — a 9am
start means 9am where the site is.

**Absent vs closed.** A location key that is missing means "never configured"; a
key present with an empty list means "explicitly no hours". Both yield zero
bookable intervals, but the editor distinguishes them so a provider can tell the
difference between untouched and deliberately cleared.
"""
from datetime import time as dt_time

WEEKDAYS = [
    ('mon', 'Monday'),
    ('tue', 'Tuesday'),
    ('wed', 'Wednesday'),
    ('thu', 'Thursday'),
    ('fri', 'Friday'),
    ('sat', 'Saturday'),
    ('sun', 'Sunday'),
]

WEEKDAY_KEYS = [key for key, _ in WEEKDAYS]

#: Python's `date.weekday()` is Monday=0 — this maps it onto our keys.
WEEKDAY_BY_INDEX = {index: key for index, (key, _) in enumerate(WEEKDAYS)}


def parse_hhmm(value):
    """Parse `"HH:MM"` into a `datetime.time`, or None if unusable.

    Never raises: this reads a JSON blob that a migration, a fixture or an older
    version of the editor may have written, and one malformed row must not take
    down a calendar render.
    """
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


def format_hhmm(value):
    """Render a `time` as `"HH:MM"`.

    Uses the zero-padded form deliberately: the `%-H` / `%-I` no-padding
    directives are a glibc extension that the Windows C runtime rejects outright.
    """
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    return f'{value.hour:02d}:{value.minute:02d}'


def get_provider_intervals(user, location, weekday=None):
    """Return this provider's configured intervals at one location.

    THIS IS THE CONTRACT MODULE 4 IMPORTS. Its signature is stable; the JSON
    behind it is not.

    Args:
        user: an `accounts.User`. A non-provider returns [].
        location: a `tenants.Location`, or its integer pk.
        weekday: optionally filter to one of `WEEKDAY_KEYS`, or a
            `date.weekday()` integer.

    Returns:
        A list of `{"start_time": time, "end_time": time, "days": [key, ...]}`
        dicts, sorted by start time, with unusable entries dropped.

    Never raises. An unconfigured provider yields [], and "no configured hours"
    must be read as UNAVAILABLE — never as "available all day", which would let
    the agent offer slots nobody is there for.
    """
    if user is None or not getattr(user, 'is_provider', False):
        return []

    location_id = getattr(location, 'pk', location)
    if location_id is None:
        return []

    raw = getattr(user, 'provider_hours', None) or {}
    if not isinstance(raw, dict):
        return []

    entries = raw.get(str(location_id)) or []
    if not isinstance(entries, list):
        return []

    if isinstance(weekday, int):
        weekday = WEEKDAY_BY_INDEX.get(weekday)

    intervals = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        start = parse_hhmm(entry.get('start_time'))
        end = parse_hhmm(entry.get('end_time'))
        if start is None or end is None or end <= start:
            continue
        days = [d for d in (entry.get('days') or []) if d in WEEKDAY_KEYS]
        if not days:
            continue
        if weekday is not None and weekday not in days:
            continue
        intervals.append({'start_time': start, 'end_time': end, 'days': days})

    intervals.sort(key=lambda item: item['start_time'])
    return intervals


def is_provider_available(user, location, weekday, at_time):
    """True when `at_time` falls inside a configured interval on `weekday`.

    A convenience over `get_provider_intervals` for Module 4; the boundary rule is
    start-inclusive, end-exclusive, so back-to-back intervals do not both match.
    """
    for interval in get_provider_intervals(user, location, weekday):
        if interval['start_time'] <= at_time < interval['end_time']:
            return True
    return False


def validate_provider_hours(intervals, *, location_id, assigned_location_ids):
    """Validate a set of intervals for one location. Returns a list of errors.

    Three rules, all from the sub-module's own scope:

    1. An interval must end after it starts.
    2. Intervals must not overlap on any shared weekday — the same provider cannot
       be in two places at one site at once, and overlapping windows make
       availability search ambiguous.
    3. Hours may only be set at a location the provider is actually assigned to.
       `accounts.UserLocation` is the assignment authority, so hours at an
       unassigned site would be unreachable data at best and a cross-location
       leak at worst.
    """
    errors = []

    if int(location_id) not in {int(pk) for pk in assigned_location_ids}:
        errors.append(
            'This provider is not assigned to that location, so hours cannot be '
            'set there.'
        )
        return errors

    cleaned = []
    for index, entry in enumerate(intervals, start=1):
        start = parse_hhmm(entry.get('start_time'))
        end = parse_hhmm(entry.get('end_time'))
        days = [d for d in (entry.get('days') or []) if d in WEEKDAY_KEYS]

        if start is None or end is None:
            errors.append(f'Interval {index}: enter a start and end time.')
            continue
        if end <= start:
            errors.append(f'Interval {index}: the end time must be after the start time.')
            continue
        if not days:
            errors.append(f'Interval {index}: choose at least one day.')
            continue
        cleaned.append({'start_time': start, 'end_time': end, 'days': days, 'index': index})

    # Overlap check, per weekday.
    for day in WEEKDAY_KEYS:
        same_day = sorted(
            (item for item in cleaned if day in item['days']),
            key=lambda item: item['start_time'],
        )
        for earlier, later in zip(same_day, same_day[1:]):
            if later['start_time'] < earlier['end_time']:
                label = dict(WEEKDAYS)[day]
                errors.append(
                    f'Intervals {earlier["index"]} and {later["index"]} overlap on '
                    f'{label}.'
                )

    return errors


def serialise_intervals(intervals):
    """Turn validated intervals into the JSON shape stored on the user."""
    return [
        {
            'start_time': format_hhmm(item['start_time']),
            'end_time': format_hhmm(item['end_time']),
            'days': [d for d in WEEKDAY_KEYS if d in item['days']],
        }
        for item in sorted(intervals, key=lambda i: parse_hhmm(i['start_time']) or dt_time(0, 0))
    ]


def set_provider_hours(user, location_id, intervals, *, commit=True):
    """Write one location's intervals onto the user, leaving other sites alone."""
    hours = dict(getattr(user, 'provider_hours', None) or {})
    hours[str(location_id)] = serialise_intervals(intervals)
    user.provider_hours = hours
    if commit:
        user.save(update_fields=['provider_hours', 'updated_at'])
    return hours


def clear_provider_hours(user, location_id, *, commit=True):
    """Record an explicit "no hours here" for one location.

    Stores an empty list rather than removing the key, so the editor can tell
    "deliberately closed" from "never configured".
    """
    hours = dict(getattr(user, 'provider_hours', None) or {})
    hours[str(location_id)] = []
    user.provider_hours = hours
    if commit:
        user.save(update_fields=['provider_hours', 'updated_at'])
    return hours


def has_configured_hours(user, location_id):
    """True when this location has ever been configured, even if cleared."""
    hours = getattr(user, 'provider_hours', None) or {}
    return isinstance(hours, dict) and str(location_id) in hours


def weekly_summary(user, location):
    """A day-by-day summary for display: `[(key, label, [intervals]), ...]`."""
    intervals = get_provider_intervals(user, location)
    summary = []
    for key, label in WEEKDAYS:
        day_intervals = [i for i in intervals if key in i['days']]
        summary.append((key, label, day_intervals))
    return summary
