"""Slot search and race-safe booking (sub-module 4.3).

Flat at the app root because it is shared plumbing, not an entity's CRUD, and
because **Module 3.3's LLM tools call these functions directly**. Everything here
is therefore written to be safe when its caller is a voice agent acting on what a
stranger said on the phone: no function trusts a caller-supplied id, and every one
re-authorises against tenant and location before it writes.

Named `availability.py`, NOT `services.py`, even though CLAUDE.md lists
`services.py` among the flat app-root modules: this app already has a `Service`
MODEL, and `from apps.scheduling.services import ...` next to
`from apps.scheduling.models import Service` reads as the same thing twice.

## The three things that are easy to get wrong here

**1. Buffer is asymmetric.** `Service.buffer_minutes` is held AFTER an
appointment, so no single `[start, end)` predicate expresses it. An appointment
occupies `[start_at, end_at + its own service's buffer)`; a candidate slot needs
`[start, start + service.total_minutes)`. `end_at` is therefore
`start + duration_minutes` — the buffer is NOT stored in `end_at`, or every
appointment would render longer than it really is.

**2. Wall-clock arithmetic is not instant arithmetic.** Adding a `timedelta` to a
zone-aware datetime moves the WALL CLOCK, not the instant, so on a DST transition
day `01:45 + 30min` can be a garbage instant or silently skip an hour. Every span
here is therefore computed by converting the start to UTC FIRST and adding the
delta there. Spring-forward gaps produce local times that do not exist at all —
`make_aware` raises on them — so the grid skips them rather than 500ing a live
call.

**3. A range lock over zero rows does not serialise.** `SELECT ... FOR UPDATE` on
a query matching no rows takes only gap locks in InnoDB, and gap locks are
mutually compatible — two callers booking the same empty slot BOTH pass and both
insert. So the lock is taken on the concrete contended row (the `Resource`, the
provider `User`), which exists and therefore serialises properly.
"""
import logging
from datetime import datetime, time as dt_time, timedelta

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.utils import timezone as dj_timezone

from apps.tenants.services import WEEKDAY_BY_INDEX, get_provider_intervals

logger = logging.getLogger(__name__)

__all__ = [
    'SLOT_TOKEN_SALT',
    'SLOT_TOKEN_TTL_SECONDS',
    'MAX_OFFERED_SLOTS',
    'SLOT_GRANULARITY_MINUTES',
    'MIN_BOOKING_NOTICE_MINUTES',
    'SEARCH_HORIZON_DAYS',
    'MAX_SEARCH_SPAN_DAYS',
    'SLOT_ERROR_CODES',
    'SlotError',
    'local_day_bounds_utc',
    'mint_slot_token',
    'redeem_slot_token',
    'find_available_slots',
    'overlapping_appointments',
    'book_slot',
    'reschedule_appointment',
    'cancel_appointment',
]

#: Namespace for `django.core.signing`. A token minted for a slot must never be
#: loadable as, say, an email-change token — the salt is what keeps the two
#: token families from being interchangeable.
SLOT_TOKEN_SALT = 'scheduling.slot.v1'

#: Short enough that the world cannot change much underneath an offer, long
#: enough for a caller to think about it and say yes out loud.
SLOT_TOKEN_TTL_SECONDS = 300

#: Server-side cap on how many slots are offered. A voice agent reading ten
#: options aloud is unusable; three to five is the researched norm. This is
#: enforced HERE rather than in the prompt, because a prompt is a suggestion.
MAX_OFFERED_SLOTS = 5

#: Candidate starts are generated on this grid — :00, :15, :30, :45.
SLOT_GRANULARITY_MINUTES = 15

#: Nothing may be booked closer than this to now. Stops the agent offering a slot
#: that starts before the caller can physically arrive.
MIN_BOOKING_NOTICE_MINUTES = 60

#: How far ahead a search may look, whatever the caller asks for.
SEARCH_HORIZON_DAYS = 60

#: The widest span a SINGLE search may scan. Bounds the work a caller can cause
#: on a fully-booked calendar, where the "stop once we have enough slots"
#: early-exit never fires.
MAX_SEARCH_SPAN_DAYS = 21


#: The CLOSED SET of error codes this module emits.
#:
#: Module 3.3 drops `SlotError.code` straight into the tool-result envelope's
#: `error.code`, so the set has to be small, stable and lower_snake_case. An
#: ad-hoc code invented at a raise site is a code the runtime has never seen and
#: cannot branch on.
SLOT_ERROR_CODES = frozenset({
    'invalid_argument',   # the request itself is malformed
    'not_permitted',      # right shape, wrong tenant/location/contact
    'slot_expired',       # the offer aged out, or the time has passed
    'slot_unavailable',   # someone else got there first
})


class SlotError(Exception):
    """A booking could not proceed.

    Carries a lower_snake_case `code` from `SLOT_ERROR_CODES` so Module 3.3 can
    drop it straight into the tool-result envelope without re-deriving one from
    prose, and a `message` written to be SPOKEN — these strings reach a caller
    through a voice agent, so they say what happens next rather than naming an
    internal failure.
    """

    def __init__(self, code, message):
        super().__init__(message)
        # Loud in development, harmless in production: a typo'd code silently
        # becomes an envelope the runtime cannot branch on.
        assert code in SLOT_ERROR_CODES, f'unknown SlotError code: {code!r}'
        self.code = code
        self.message = message


def _assert_scope(appointment, tenant, location):
    """Refuse an appointment that is not this tenant's and this location's.

    Both HTTP call sites already fetch through a scoped queryset, so today this
    is belt-and-braces. It exists for the caller that does NOT: Module 3.3's
    tools receive an `appointment_id` the MODEL supplied, and Invariant 3 says
    any model-supplied id is authorised server-side against tenant, location and
    the identified contact. Putting the check in the service function means that
    holds however the function is reached.
    """
    if appointment.tenant_id != tenant.pk or appointment.location_id != location.pk:
        logger.warning(
            'Appointment scope mismatch appointment_id=%s tenant_id=%s '
            'location_id=%s', appointment.pk, tenant.pk, location.pk,
        )
        raise SlotError('not_permitted', 'That appointment is not available here.')


# --------------------------------------------------------------------------- #
# Timezone-safe primitives
# --------------------------------------------------------------------------- #

def _local_naive_to_utc(naive_local, tzinfo):
    """Convert a naive local wall time to an aware UTC datetime, or None.

    Returns None for a wall time that DOES NOT EXIST — the hour skipped by a
    spring-forward transition. The caller drops those candidates; raising would
    turn a DST Sunday into a 500 in the middle of a phone call.

    Ambiguous times (the hour repeated by a fall-back transition) resolve to
    `fold=0`, the FIRST occurrence, which is the earlier real instant.
    """
    try:
        aware = naive_local.replace(tzinfo=tzinfo, fold=0)
    except (ValueError, OverflowError):
        return None

    # A non-existent local time is detectable by round-tripping: convert to UTC
    # and back, and a skipped time comes back as something else entirely.
    utc = aware.astimezone(dj_timezone.utc)
    if utc.astimezone(tzinfo).replace(tzinfo=None) != naive_local:
        return None
    return utc


def _advance(utc_start, minutes):
    """Add `minutes` to an aware UTC datetime.

    Deliberately takes and returns UTC. Adding a timedelta to a zone-aware LOCAL
    datetime is wall-clock arithmetic and silently produces the wrong instant
    across a DST boundary; adding it in UTC is always true elapsed time.
    """
    return utc_start + timedelta(minutes=minutes)


def local_day_bounds_utc(location, day):
    """The half-open UTC range `[start, end)` covering one local calendar day.

    Used by every date filter in this module instead of `start_at__date=...`.
    `__date` converts using Django's ACTIVE timezone rather than the location's,
    and on MySQL it compiles to `CONVERT_TZ()`, which returns NULL unless the
    server's timezone tables have been loaded — so a `__date` filter passes on
    SQLite in the test settings and silently returns zero rows in production.
    It also cannot use the `(tenant, location, start_at)` index.
    """
    tzinfo = location.tzinfo
    start = _local_naive_to_utc(datetime.combine(day, dt_time.min), tzinfo)
    if start is None:
        # A location whose day begins inside a DST gap: step forward until a real
        # instant exists rather than returning nothing for the whole day.
        for minutes in range(15, 24 * 60, 15):
            start = _local_naive_to_utc(
                datetime.combine(day, dt_time.min) + timedelta(minutes=minutes),
                tzinfo,
            )
            if start is not None:
                break
    end = _local_naive_to_utc(
        datetime.combine(day + timedelta(days=1), dt_time.min), tzinfo
    )
    if end is None:
        end = (start or dj_timezone.now()) + timedelta(days=1)
    return start, end


# --------------------------------------------------------------------------- #
# Slot tokens
# --------------------------------------------------------------------------- #

def mint_slot_token(*, tenant_id, location_id, start_utc, service_id,
                    provider_id=None, resource_id=None):
    """Return one opaque signed token describing a single offered slot.

    OPAQUE BY CONTRACT. The model is given this string and hands it back; it is
    never asked to echo a time, a provider name or a resource. That is what stops
    a caller talking the agent into booking 3am, or into someone else's room —
    the only bookable slots are ones the server minted.

    The payload holds internal surrogate pks. Those are not secrets (they leak
    nothing a tenant user cannot already see) but they ARE re-authorised on
    redemption, because within the TTL a resource can be deactivated or a
    provider's assignment revoked.
    """
    return signing.dumps(
        {
            't': tenant_id,
            'l': location_id,
            # UTC isoformat, never a naive local string: the token may be redeemed
            # by a different process with a different active timezone.
            's': start_utc.astimezone(dj_timezone.utc).isoformat(),
            'sv': service_id,
            'p': provider_id,
            'r': resource_id,
        },
        salt=SLOT_TOKEN_SALT,
    )


def redeem_slot_token(token, *, tenant, location):
    """Validate a slot token and return its payload, or raise `SlotError`.

    `tenant` and `location` come from SERVER-SIDE state — `request.tenant` on the
    HTTP path, the dialed number's `AgentSetting` on the runtime path — and the
    token must agree with them. A token minted at one location and replayed at
    another is refused even though its signature is perfectly valid.
    """
    try:
        payload = signing.loads(
            token, salt=SLOT_TOKEN_SALT, max_age=SLOT_TOKEN_TTL_SECONDS
        )
    except signing.SignatureExpired:
        raise SlotError(
            'slot_expired',
            'That time was offered a while ago and may no longer be free. '
            'Let me check what is available now.',
        )
    except signing.BadSignature:
        raise SlotError('invalid_argument', 'That is not a slot I offered.')

    if not isinstance(payload, dict):
        raise SlotError('invalid_argument', 'That is not a slot I offered.')

    if payload.get('t') != tenant.pk or payload.get('l') != location.pk:
        # Not merely wrong — this is the cross-tenant/cross-location replay case,
        # so it is refused without explaining which half did not match.
        logger.warning(
            'Slot token rejected: scope mismatch tenant_id=%s location_id=%s',
            tenant.pk, location.pk,
        )
        raise SlotError('not_permitted', 'That slot is not available here.')

    raw_start = payload.get('s')
    try:
        start_utc = datetime.fromisoformat(raw_start)
    except (TypeError, ValueError):
        raise SlotError('invalid_argument', 'That is not a slot I offered.')
    if start_utc.tzinfo is None:
        raise SlotError('invalid_argument', 'That is not a slot I offered.')

    payload['start_utc'] = start_utc.astimezone(dj_timezone.utc)
    return payload


# --------------------------------------------------------------------------- #
# Conflict detection
# --------------------------------------------------------------------------- #

#: Statuses that still occupy the calendar. A cancelled or no-show appointment
#: frees its slot; a completed one does not (it really happened).
BLOCKING_STATUSES = ('scheduled', 'confirmed', 'completed')


def overlapping_appointments(*, tenant, location, start_utc, end_utc,
                             provider=None, resource=None, exclude_pk=None,
                             for_update=False):
    """Appointments that would collide with `[start_utc, end_utc)`.

    **Returns `.none()` when neither a provider nor a resource is given.** With no
    exclusive entity to contend for there is nothing to conflict on — two
    resource-less, provider-less appointments at the same time are legitimately
    fine (a phone consultation needs neither). Leaving this undefined would make
    such a location either unbookable or unconflicted at random.

    `for_update=True` makes this a locking read. Under MySQL's REPEATABLE READ a
    plain re-check inside a transaction reads the transaction's own pinned
    snapshot and CANNOT see a row another transaction just committed — so the
    re-check would report "free" and double-book. The in-lock call must always
    pass True.
    """
    from apps.scheduling.models import Appointment

    if provider is None and resource is None:
        return Appointment.objects.none()

    contention = Q()
    if provider is not None:
        contention |= Q(provider=provider)
    if resource is not None:
        contention |= Q(resource=resource)

    queryset = (
        Appointment.objects.filter(
            tenant=tenant, location=location, status__in=BLOCKING_STATUSES
        )
        .filter(contention)
        # The existing row's own buffer extends how long it blocks, so the
        # service is needed per row. Without select_related this is an N+1 on the
        # latency-critical booking path.
        .select_related('service')
    )
    if exclude_pk is not None:
        # Rescheduling an appointment must not find ITSELF as the conflict —
        # moving 10:00-10:30 to 10:15-10:45 would otherwise always fail.
        queryset = queryset.exclude(pk=exclude_pk)
    if for_update:
        queryset = queryset.select_for_update()

    # The blocking span cannot be expressed as a pure SQL predicate without
    # duplicating the buffer into a column, so the coarse overlap is filtered in
    # SQL (indexed, narrow) and the buffer applied in Python over the handful of
    # rows that survive. `end_at + buffer` only ever EXTENDS a row's span, so the
    # SQL prefilter is widened by the largest buffer any service defines.
    widest_buffer = _widest_buffer_minutes(tenant)
    queryset = queryset.filter(
        start_at__lt=end_utc,
        end_at__gt=start_utc - timedelta(minutes=widest_buffer),
    )

    colliding = []
    for appointment in queryset:
        buffer_minutes = (
            appointment.service.buffer_minutes if appointment.service_id else 0
        )
        blocks_until = appointment.end_at + timedelta(minutes=buffer_minutes)
        if appointment.start_at < end_utc and blocks_until > start_utc:
            colliding.append(appointment.pk)

    if not colliding:
        return Appointment.objects.none()
    return Appointment.objects.filter(pk__in=colliding)


def _widest_buffer_minutes(tenant):
    """The largest buffer any of this tenant's services defines.

    Used only to widen the SQL prefilter so no row that could block is excluded
    before the exact Python check runs. Cheap (one aggregate) and correct even
    when it over-selects.
    """
    from django.db.models import Max

    from apps.scheduling.models import Service

    widest = Service.objects.filter(tenant=tenant).aggregate(
        widest=Max('buffer_minutes')
    )['widest']
    return widest or 0


# --------------------------------------------------------------------------- #
# Slot search
# --------------------------------------------------------------------------- #

def find_available_slots(*, tenant, location, service, date_from=None,
                         date_to=None, provider=None, resource=None,
                         limit=MAX_OFFERED_SLOTS, now=None):
    """Return up to `limit` bookable slots, soonest first.

    Each item is a dict carrying an aware UTC `start`/`end`, the resolved provider
    and resource, and a freshly minted opaque `token`.

    Availability is the intersection of four things: the provider's configured
    working hours at THIS location, a free provider, a free resource, and the
    minimum booking notice. A provider with no configured hours is UNAVAILABLE —
    `get_provider_intervals` returns `[]` and this yields nothing for them, which
    is the documented Module 1 contract and deliberately NOT "available all day".
    """
    if location is None or service is None:
        return []

    now = now or dj_timezone.now()
    tzinfo = location.tzinfo
    earliest = now + timedelta(minutes=MIN_BOOKING_NOTICE_MINUTES)

    today_local = now.astimezone(tzinfo).date()
    start_day = max(date_from or today_local, today_local)
    horizon = today_local + timedelta(days=SEARCH_HORIZON_DAYS)
    end_day = min(date_to or (start_day + timedelta(days=14)), horizon)
    if end_day < start_day:
        return []

    # Cap the SPAN, not just the far end. Without this a caller-supplied range
    # of `from=today&to=+60d` walks every day even though the result is capped
    # at five slots, and the early-exit below only helps when slots are actually
    # found — a fully-booked location would scan the lot.
    end_day = min(end_day, start_day + timedelta(days=MAX_SEARCH_SPAN_DAYS))

    # ONE query for the whole range, instead of one per candidate start.
    window_start, _ = local_day_bounds_utc(location, start_day)
    _, window_end = local_day_bounds_utc(location, end_day)
    booked = _BookedIndex(tenant, location, window_start, window_end)

    providers = _candidate_providers(tenant, location, provider)
    resources = _candidate_resources(tenant, location, service, resource)

    # A service that needs a room, at a location with no active rooms, has no
    # slots — never "book it anyway and sort the room out later".
    if service.requires_resource and not resources:
        return []
    if not service.requires_resource and not resources:
        resources = [None]
    if not providers:
        if provider is not None:
            # A SPECIFIC person was asked for and they are not bookable here —
            # suspended, unassigned, or not a provider at all. Falling through to
            # the no-provider branch would answer "yes, Tuesday at ten" for a
            # request that named someone who cannot take it, which is worse than
            # offering nothing.
            return []
        # Otherwise: no provider at all is a legitimate configuration, for
        # something like a phone consultation. It is NOT a fallback for a
        # misconfigured provider — that case is `get_provider_intervals`
        # returning [], which yields no windows and therefore no slots.
        providers = [None]

    span_minutes = service.duration_minutes
    block_minutes = service.total_minutes

    slots = []
    seen_starts = set()
    day = start_day

    while day <= end_day and len(slots) < limit:
        weekday_key = WEEKDAY_BY_INDEX.get(day.weekday())

        for candidate_provider in providers:
            if len(slots) >= limit:
                break

            windows = _windows_for(candidate_provider, location, weekday_key)
            if not windows:
                continue

            for window_start, window_end in windows:
                if len(slots) >= limit:
                    break

                for naive_start in _grid(day, window_start, window_end,
                                         block_minutes):
                    if len(slots) >= limit:
                        break

                    start_utc = _local_naive_to_utc(naive_start, tzinfo)
                    if start_utc is None:
                        # A wall time inside a spring-forward gap. Skip it.
                        continue
                    if start_utc < earliest:
                        continue

                    end_utc = _advance(start_utc, span_minutes)
                    block_end_utc = _advance(start_utc, block_minutes)

                    chosen_resource = _first_free_resource(
                        booked=booked, resources=resources,
                        start_utc=start_utc, end_utc=block_end_utc,
                        provider=candidate_provider,
                    )
                    if chosen_resource is _NO_RESOURCE_FREE:
                        continue

                    key = (start_utc, getattr(candidate_provider, 'pk', None),
                           getattr(chosen_resource, 'pk', None))
                    if key in seen_starts:
                        continue
                    seen_starts.add(key)

                    slots.append({
                        'start': start_utc,
                        'end': end_utc,
                        'provider': candidate_provider,
                        'resource': chosen_resource,
                        'service': service,
                        'token': mint_slot_token(
                            tenant_id=tenant.pk,
                            location_id=location.pk,
                            start_utc=start_utc,
                            service_id=service.pk,
                            provider_id=getattr(candidate_provider, 'pk', None),
                            resource_id=getattr(chosen_resource, 'pk', None),
                        ),
                    })

        day += timedelta(days=1)

    slots.sort(key=lambda item: item['start'])
    return slots[:limit]


#: Sentinel distinguishing "every resource is busy" from "no resource needed".
_NO_RESOURCE_FREE = object()


class _BookedIndex:
    """The whole search range's existing bookings, loaded ONCE.

    `find_available_slots` tests candidate starts on a 15-minute grid across
    every provider and every resource for up to 60 days. Asking the database
    per candidate turns one search into thousands of queries — measured at
    >9,000 queries and 37 seconds for a busy two-provider location, on a path
    a phone caller can trigger.

    So the range is fetched once, bucketed by the two things a booking actually
    contends for, and every candidate is tested in memory. The intervals stored
    are BLOCKING spans: `[start_at, end_at + that row's own service buffer)`.

    This is a read-side optimisation only. `book_slot` still re-checks under a
    real row lock with a fresh locking SELECT — an in-memory snapshot cannot
    serialise two concurrent writers, and must never be mistaken for something
    that can.
    """

    def __init__(self, tenant, location, window_start, window_end):
        from apps.scheduling.models import Appointment

        self.by_provider = {}
        self.by_resource = {}

        widest = _widest_buffer_minutes(tenant)
        rows = (
            Appointment.objects.filter(
                tenant=tenant, location=location,
                status__in=BLOCKING_STATUSES,
                start_at__lt=window_end,
                end_at__gt=window_start - timedelta(minutes=widest),
            )
            .select_related('service')
            .only('start_at', 'end_at', 'provider_id', 'resource_id',
                  'service__buffer_minutes')
        )

        for row in rows:
            buffer_minutes = (
                row.service.buffer_minutes if row.service_id else 0
            )
            span = (row.start_at, row.end_at + timedelta(minutes=buffer_minutes))
            if row.provider_id is not None:
                self.by_provider.setdefault(row.provider_id, []).append(span)
            if row.resource_id is not None:
                self.by_resource.setdefault(row.resource_id, []).append(span)

    def is_free(self, *, start_utc, end_utc, provider_id, resource_id):
        """Whether nothing booked blocks `[start_utc, end_utc)`.

        Mirrors `overlapping_appointments`: with neither a provider nor a
        resource there is no exclusive entity to contend for, so the span is
        free.
        """
        if provider_id is None and resource_id is None:
            return True
        for bucket, key in ((self.by_provider, provider_id),
                            (self.by_resource, resource_id)):
            if key is None:
                continue
            for booked_start, blocks_until in bucket.get(key, ()):
                if booked_start < end_utc and blocks_until > start_utc:
                    return False
        return True


def _first_free_resource(*, booked, resources, start_utc, end_utc, provider):
    """The first resource free for this span, or the no-free sentinel.

    Reads the prefetched index rather than the database — see `_BookedIndex`.
    """
    provider_id = getattr(provider, 'pk', None)
    for candidate in resources:
        if booked.is_free(
            start_utc=start_utc, end_utc=end_utc,
            provider_id=provider_id, resource_id=getattr(candidate, 'pk', None),
        ):
            return candidate
    return _NO_RESOURCE_FREE


def _candidate_providers(tenant, location, provider):
    """Providers bookable at this location, or `[provider]` when one is pinned."""
    from apps.accounts.models import User

    if provider is not None:
        # Even a PINNED provider is re-checked: a suspended user who cannot log
        # in must not have slots minted against them.
        if provider.status != User.STATUS_ACTIVE:
            return []
        return [provider]
    return list(
        # `user_locations` is User -> UserLocation; `user_assignments` is the
        # accessor from Location. Getting these backwards is a silent FieldError.
        User.objects.filter(
            tenant=tenant,
            is_provider=True,
            status=User.STATUS_ACTIVE,
            user_locations__location=location,
        ).distinct().order_by('pk')
    )


def _candidate_resources(tenant, location, service, resource):
    """Active resources at this location, or `[resource]` when one is pinned."""
    from apps.scheduling.models import Resource

    if resource is not None:
        return [resource]
    if not service.requires_resource:
        return []
    return list(
        Resource.objects.filter(
            tenant=tenant, location=location, is_active=True
        ).order_by('display_order', 'name')
    )


def _windows_for(provider, location, weekday_key):
    """This provider's working windows on one weekday, as naive local times.

    A `None` provider has no configured hours to read, so it falls back to a
    conservative default business day rather than the whole 24 hours — offering
    a 3am phone consultation because nobody configured hours would be worse than
    offering none.
    """
    if provider is None:
        return [(dt_time(9, 0), dt_time(17, 0))]

    intervals = get_provider_intervals(provider, location, weekday_key)
    return [(item['start_time'], item['end_time']) for item in intervals]


def _grid(day, window_start, window_end, block_minutes):
    """Candidate naive-local start times inside one window.

    The LAST candidate must leave room for the whole block (duration + buffer)
    before the window closes — a 30-minute service with a 10-minute buffer cannot
    start at 16:45 in a window ending 17:00.
    """
    cursor = datetime.combine(day, window_start)
    closes = datetime.combine(day, window_end)
    step = timedelta(minutes=SLOT_GRANULARITY_MINUTES)
    block = timedelta(minutes=block_minutes)

    while cursor + block <= closes:
        yield cursor
        cursor += step


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #

def _lock_contended_rows(*, tenant, location, provider_id, resource_id):
    """Take row locks on whatever this booking actually contends for.

    THE POINT: a range `SELECT ... FOR UPDATE` over an EMPTY result set takes only
    gap locks in InnoDB, and gap locks are mutually compatible. Two callers
    booking the same free slot would both pass and both insert. Locking the
    concrete `Resource` / provider `User` row — a row that exists — serialises
    them properly at any isolation level.

    Ordered by primary key so two bookings that contend for the same pair of rows
    always take them in the same order, which is what prevents a lock-order
    deadlock between them.
    """
    from apps.accounts.models import User
    from apps.scheduling.models import Resource

    if resource_id is not None:
        list(Resource.objects.select_for_update()
             .filter(pk=resource_id, tenant=tenant, location=location)
             .order_by('pk'))
    if provider_id is not None:
        list(User.objects.select_for_update()
             .filter(pk=provider_id, tenant=tenant)
             .order_by('pk'))


def book_slot(*, tenant, location, token, contact, reason='', notes='',
              source='manual', created_by=None, booked_by_session=None):
    """Book the slot described by `token`. Raises `SlotError` on any refusal.

    `booked_by_session` is the `calls.CallSession` the booking was made during —
    the provenance stamp `Appointment.booked_by_session` exists for and its help
    text calls "server-stamped by the runtime". Module 3.3's `book_appointment`
    tool passes it; the HTTP booking view passes nothing and the field stays null.
    It is a MODEL INSTANCE, not an id, and it is never taken from a tool argument:
    the runtime resolves it from server-side session state (Invariant 3).

    This is the function Module 3.3's `book_appointment` tool will call, so it
    re-authorises everything rather than trusting its caller:

    * the token must have been minted for THIS tenant and location,
    * the contact must belong to this tenant (Invariant 1 — one identity table),
    * the service, resource and provider are RE-FETCHED under tenant/location
      filters, because within the token's 5-minute life a resource can be
      deactivated, a service re-pinned, or a provider's assignment revoked,
    * the slot is re-checked for conflicts under a real row lock.
    """
    from django.db.utils import OperationalError

    from apps.scheduling.models import Appointment, Resource, Service

    payload = redeem_slot_token(token, tenant=tenant, location=location)

    if contact is None or contact.tenant_id != tenant.pk:
        # The token path bypasses the form, which is the only other place the
        # contact queryset is narrowed. A posted foreign-tenant contact pk would
        # otherwise never be checked at all.
        raise SlotError('not_permitted', 'That contact is not on file here.')

    start_utc = payload['start_utc']
    if start_utc < dj_timezone.now():
        raise SlotError('slot_expired', 'That time has already passed.')

    service = Service.objects.filter(
        pk=payload.get('sv'), tenant=tenant, is_active=True
    ).filter(Q(location=location) | Q(location__isnull=True)).first()
    if service is None:
        raise SlotError(
            'slot_unavailable',
            'That service is no longer offered here. Let me find another time.',
        )

    resource = None
    if payload.get('r') is not None:
        resource = Resource.objects.filter(
            pk=payload['r'], tenant=tenant, location=location, is_active=True
        ).first()
        if resource is None:
            raise SlotError(
                'slot_unavailable',
                'That room is no longer available. Let me find another time.',
            )

    provider = None
    if payload.get('p') is not None:
        from apps.accounts.models import User

        provider = User.objects.filter(
            pk=payload['p'], tenant=tenant, is_provider=True,
            status=User.STATUS_ACTIVE,
            user_locations__location=location,
        ).distinct().first()
        if provider is None:
            raise SlotError(
                'slot_unavailable',
                'That person is no longer available. Let me find another time.',
            )

    end_utc = _advance(start_utc, service.duration_minutes)
    block_end_utc = _advance(start_utc, service.total_minutes)

    try:
        with transaction.atomic():
            _lock_contended_rows(
                tenant=tenant, location=location,
                provider_id=getattr(provider, 'pk', None),
                resource_id=getattr(resource, 'pk', None),
            )

            # Idempotency FIRST, conflict check second. Reversed, a legitimate
            # retry would find its own already-committed booking as the conflict
            # and tell the caller it failed after it had actually succeeded.
            existing = Appointment.objects.filter(
                tenant=tenant, location=location, contact=contact,
                service=service, start_at=start_utc,
                status__in=BLOCKING_STATUSES,
            ).first()
            if existing is not None:
                return existing

            clash = overlapping_appointments(
                tenant=tenant, location=location,
                start_utc=start_utc, end_utc=block_end_utc,
                provider=provider, resource=resource,
                for_update=True,
            )
            if clash.exists():
                raise SlotError(
                    'slot_unavailable',
                    'Someone just took that time. Let me offer you another.',
                )

            appointment = Appointment.objects.create(
                tenant=tenant, location=location, contact=contact,
                provider=provider, resource=resource, service=service,
                start_at=start_utc, end_at=end_utc,
                status=Appointment.STATUS_SCHEDULED,
                reason=reason, notes=notes, source=source,
                booked_by_session=booked_by_session,
            )
    except OperationalError as exc:
        # 1213 deadlock, 1205 lock wait timeout. Both mean "another writer got
        # there"; neither should surface as a 500 on a live call.
        logger.warning('Booking lost a lock race: %s', exc)
        raise SlotError(
            'slot_unavailable',
            'Someone just took that time. Let me offer you another.',
        )

    logger.info(
        'Appointment booked appointment_id=%s tenant_id=%s location_id=%s '
        'source=%s', appointment.pk, tenant.pk, location.pk, source,
    )
    return appointment


def reschedule_appointment(*, tenant, location, appointment, token, reason='',
                           actor_contact=None):
    """Move an appointment onto a new slot token. Raises `SlotError`.

    `actor_contact`, when given, must be the contact the appointment is FOR.
    Module 3.3 passes the contact it identified on the call, so a caller cannot
    talk the agent into moving a stranger's booking by guessing an id.
    """
    from django.db.utils import OperationalError

    from apps.scheduling.models import Appointment, Resource, Service

    _assert_scope(appointment, tenant, location)

    if actor_contact is not None and appointment.contact_id != actor_contact.pk:
        raise SlotError(
            'not_permitted', 'That appointment is not available here.'
        )

    if appointment.status not in (Appointment.STATUS_SCHEDULED,
                                  Appointment.STATUS_CONFIRMED):
        raise SlotError(
            'invalid_argument',
            'That appointment can no longer be moved.',
        )

    payload = redeem_slot_token(token, tenant=tenant, location=location)
    start_utc = payload['start_utc']
    if start_utc < dj_timezone.now():
        raise SlotError('slot_expired', 'That time has already passed.')

    service = Service.objects.filter(
        pk=payload.get('sv'), tenant=tenant, is_active=True
    ).filter(Q(location=location) | Q(location__isnull=True)).first() \
        or appointment.service
    if service is None:
        raise SlotError('slot_unavailable', 'That service is no longer offered.')

    resource = None
    if payload.get('r') is not None:
        resource = Resource.objects.filter(
            pk=payload['r'], tenant=tenant, location=location, is_active=True
        ).first()

    provider = None
    if payload.get('p') is not None:
        from apps.accounts.models import User

        provider = User.objects.filter(
            pk=payload['p'], tenant=tenant, is_provider=True,
            status=User.STATUS_ACTIVE,
            user_locations__location=location,
        ).distinct().first()

    end_utc = _advance(start_utc, service.duration_minutes)
    block_end_utc = _advance(start_utc, service.total_minutes)

    try:
        with transaction.atomic():
            _lock_contended_rows(
                tenant=tenant, location=location,
                provider_id=getattr(provider, 'pk', None),
                resource_id=getattr(resource, 'pk', None),
            )
            clash = overlapping_appointments(
                tenant=tenant, location=location,
                start_utc=start_utc, end_utc=block_end_utc,
                provider=provider, resource=resource,
                exclude_pk=appointment.pk,
                for_update=True,
            )
            if clash.exists():
                raise SlotError(
                    'slot_unavailable',
                    'Someone just took that time. Let me offer you another.',
                )

            appointment.start_at = start_utc
            appointment.end_at = end_utc
            appointment.service = service
            appointment.provider = provider
            appointment.resource = resource
            if reason:
                appointment.reason = reason
            appointment.save(update_fields=[
                'start_at', 'end_at', 'service', 'provider', 'resource',
                'reason', 'updated_at',
            ])
    except OperationalError as exc:
        logger.warning('Reschedule lost a lock race: %s', exc)
        raise SlotError(
            'slot_unavailable',
            'Someone just took that time. Let me offer you another.',
        )

    logger.info('Appointment rescheduled appointment_id=%s', appointment.pk)
    return appointment


def cancel_appointment(*, appointment, tenant, location, reason='',
                       actor_contact=None):
    """Cancel, stamping the reason and the moment. Raises `SlotError`.

    Cancelling frees the slot (see `BLOCKING_STATUSES`) but keeps the row, so the
    calendar's history stays honest about what was booked and then dropped.

    `tenant` and `location` are REQUIRED even though the HTTP view already
    fetched through a scoped queryset: Module 3.3's `cancel_appointment` tool
    will pass an `appointment_id` the model supplied, and cancelling someone
    else's booking is exactly the damage Invariant 3 exists to prevent.
    """
    from apps.scheduling.models import Appointment

    _assert_scope(appointment, tenant, location)

    if actor_contact is not None and appointment.contact_id != actor_contact.pk:
        raise SlotError(
            'not_permitted', 'That appointment is not available here.'
        )

    if appointment.status in (Appointment.STATUS_CANCELLED,
                              Appointment.STATUS_COMPLETED):
        raise SlotError(
            'invalid_argument',
            'That appointment has already been closed out.',
        )

    appointment.status = Appointment.STATUS_CANCELLED
    appointment.cancelled_at = dj_timezone.now()
    appointment.cancellation_reason = (reason or '')[:255]
    appointment.save(update_fields=[
        'status', 'cancelled_at', 'cancellation_reason', 'updated_at',
    ])
    logger.info('Appointment cancelled appointment_id=%s', appointment.pk)
    return appointment
