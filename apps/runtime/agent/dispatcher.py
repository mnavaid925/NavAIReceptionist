"""``apply_tool_call`` — the one tool dispatcher — sub-module 3.3.

**Invariant 3 lives here.** *Server owns identity; the model owns wording.*
``tenant_id``, ``location_id``, ``contact_id`` and ``session_id`` are read **only**
from the server-held ``CallState`` and are never tool parameters. Any key in the
model's ``args`` that collides with an identity name is **stripped before a handler
sees it** — a caller's speech reaches the model, so anything the model emits is
untrusted input. Every id the model *is* allowed to supply (``appointment_id``,
``slot_token``, ``service_id``, ``provider_ids``, ``resource_ids``) is
re-authorised server-side against tenant, location **and** the identified contact.
This is an IDOR with an LLM in the middle; it is treated as one.

**Transport-agnostic** (skill §8.2): a pure function of ``state``, with no
knowledge of which LLM backend produced the call, so the turn-based path and any
future realtime speech-to-speech path get identical behaviour by construction.

**It wraps an engine it does not own.** ``apps/scheduling/availability.py`` (4.3)
already implements slot search, the opaque signed slot tokens, and the race-safe
book / reschedule / cancel writes — each re-authorising tenant, location and
``actor_contact`` itself. Its ``SlotError.code`` values are a subset of this
module's closed envelope codes, so a ``SlotError`` passes straight through with
**zero translation**. Nothing here re-implements booking.

**Nothing here can kill the call.** Every branch runs under a guard that turns an
unexpected exception into ``err('internal_error', …)``; a tool failure is a spoken
apology, never a dropped call.

**Every handler is a plain SYNC function** ``(state, args) -> envelope``. The
dispatcher runs the ORM-touching ones through
``database_sync_to_async(..., thread_sensitive=False)`` (3.2's established
discipline — the ``True`` default serialises every concurrent call onto one
thread), and runs the three pure state mutations inline. Sync handlers are far
easier to read and test than a tree of awaits, and the async boundary stays in one
place.
"""
import logging
from datetime import datetime

from channels.db import database_sync_to_async
from django.db.models import Q

from apps.runtime.agent.envelope import err, ok
from apps.runtime.agent.prompt import format_local_date, format_local_time
from apps.runtime.agent.tools import TOOL_NAMES

logger = logging.getLogger(__name__)

__all__ = ['apply_tool_call', 'TOOL_HANDLERS', 'IDENTITY_KEYS']

#: Identity is server state, never a tool argument (Invariant 3). Any of these
#: appearing in the model's `args` is dropped before a handler runs — not merely
#: ignored downstream, actually removed, so no branch can accidentally read one.
IDENTITY_KEYS = frozenset({'tenant_id', 'location_id', 'contact_id', 'session_id'})

#: Tools that touch no ORM — pure `state` mutations, run on the event loop.
_NO_ORM_TOOLS = frozenset({'transfer_call', 'transfer_call_spanish', 'end_call'})

#: How many of a contact's appointments to hand back. A voice agent cannot read a
#: long list aloud, and an unbounded payload bloats the prompt every later turn.
_MAX_APPOINTMENTS = 10
#: Bounds the provider x resource fan-out in `get_open_slots` (see that handler).
_MAX_FANOUT = 4

_DATE_FORMAT = '%m/%d/%Y'
_TIME_FORMAT = '%H:%M'


# --------------------------------------------------------------------------- #
# Redaction — PII must not be persisted into CallSession.logs
# --------------------------------------------------------------------------- #

#: Dropped outright. CLAUDE.md vulnerability rule 5 names a `create_contact`
#: payload — "a full name and a date of birth" — as the example of what never to
#: log; the date of birth has no diagnostic value at all, so it simply goes.
_REDACT_DROP = frozenset({'date_of_birth'})
#: Replaced with a length marker: free text a caller dictated.
_REDACT_LENGTH = frozenset({'notes', 'reason', 'cancellation_reason'})
#: Reduced to initials — a name is PII, and the transcript already records what
#: the caller actually said, so the log does not need to duplicate it.
_REDACT_NAME = frozenset({'first', 'last', 'first_name', 'last_name', 'caller_name'})


def _mask_phone(value):
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    return f'***{digits[-4:]}' if len(digits) >= 4 else '***'


def _redact_args(args):
    """A log-safe copy of the model's tool arguments.

    Applied generically to every tool rather than special-cased per branch, so a
    tool added later inherits the redaction instead of having to remember it.
    """
    redacted = {}
    for key, value in (args or {}).items():
        lowered = str(key).lower()
        if lowered in _REDACT_DROP:
            continue
        if 'phone' in lowered:
            redacted[key] = _mask_phone(value)
        elif lowered in _REDACT_LENGTH:
            redacted[key] = f'<{len(str(value))} chars>' if value else ''
        elif lowered in _REDACT_NAME:
            text = str(value or '').strip()
            redacted[key] = f'{text[:1]}***' if text else ''
        elif 'token' in lowered:
            # A slot token is a signed bearer credential — never log the value.
            redacted[key] = '<token>'
        else:
            redacted[key] = value
    return redacted


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #

class _ScopeMissing(RuntimeError):
    """The call's location row could not be resolved — treated as internal_error."""


def _scope(state):
    """Resolve ``(tenant, location)`` for this call in ONE query.

    Scoped by tenant AND location together, both taken from the verified stream
    token via ``CallState`` — never from a tool argument. `select_related('tenant')`
    means the tenant comes back on the same row, so no handler pays a second query.
    """
    from apps.tenants.models import Location

    location = (
        Location.objects
        .select_related('tenant')
        .filter(pk=state.location_id, tenant_id=state.tenant_id)
        .first()
    )
    if location is None:
        raise _ScopeMissing(
            f'location_id={state.location_id} not found under tenant_id={state.tenant_id}'
        )
    return location.tenant, location


def _identified_contact(state, tenant):
    """The contact this call has identified, re-authorised against the tenant.

    ``state.contact_id`` is server state, but the row is re-fetched under the
    tenant filter every time rather than trusted — it could have been erased or
    anonymised mid-call.
    """
    from apps.scheduling.models import Contact

    if not state.contact_id:
        return None
    return Contact.objects.filter(pk=state.contact_id, tenant=tenant).first()


def _parse_date(value):
    """``MM/DD/YYYY`` → ``date``, or None when absent/unparseable."""
    text = str(value or '').strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, _DATE_FORMAT).date()
    except ValueError:
        return None


def _parse_time(value):
    """24-hour ``HH:MM`` → ``time``, or None when absent/unparseable."""
    text = str(value or '').strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, _TIME_FORMAT).time()
    except ValueError:
        return None


def _appointment_payload(appointment):
    return {
        'appointment_id': appointment.pk,
        'start_at': appointment.start_at.isoformat() if appointment.start_at else None,
        'service': appointment.service.name if appointment.service_id else None,
        'status': appointment.status,
    }


def _resolve_appointment(tenant, location, appointment_id):
    """An appointment scoped by tenant AND location. pk alone is never enough."""
    from apps.scheduling.models import Appointment

    try:
        pk = int(appointment_id)
    except (TypeError, ValueError):
        return None
    return (
        Appointment.objects
        .select_related('service')
        .filter(pk=pk, tenant=tenant, location=location)
        .first()
    )


# --------------------------------------------------------------------------- #
# Handlers — identity/contact tools
# --------------------------------------------------------------------------- #

def _get_contact_appointments(state, args):
    from apps.scheduling.models import Appointment, Contact
    from apps.scheduling.services import normalize_e164

    tenant, location = _scope(state)
    # Default to the number this call came from. A caller-supplied number is
    # allowed (they may be calling about a different line) but is normalised the
    # same way, so a repeat caller deduplicates however they phrase it.
    raw = args.get('phone') or (state.variables or {}).get('from_e164') or ''
    phone = normalize_e164(raw)
    if not phone:
        return ok({'contact_id': None, 'is_new': True, 'appointments': []})

    # Contact is tenant-scoped ONLY — a caller belongs to the business and may
    # book at any of its locations (Invariant 1).
    matches = list(Contact.objects.filter(tenant=tenant, phone_e164=phone)[:2])
    if not matches:
        return ok({'contact_id': None, 'is_new': True, 'appointments': []})
    if len(matches) > 1:
        # Ambiguous: do NOT identify anyone. The model should fall back to
        # search_contact rather than guess which person is on the phone.
        return ok({'contact_id': None, 'is_new': False, 'appointments': []})

    contact = matches[0]
    state.contact_id = contact.pk
    # Appointments are scoped by tenant AND location. The CONTACT deliberately
    # spans locations (Invariant 1), but their appointments do not: `Appointment`
    # is a location-scoped model and CLAUDE.md admits no exception. Reading a
    # caller's bookings at other branches out to whoever dialled THIS number —
    # identified only by a caller-ID match — widens what a spoofed number learns.
    # It would also be incoherent: `reschedule_appointment`/`cancel_appointment`
    # resolve strictly within this location, so an appointment listed from another
    # branch could be named but never acted on.
    appointments = (
        Appointment.objects
        .select_related('service')
        .filter(tenant=tenant, location=location, contact=contact)
        .order_by('-start_at')[:_MAX_APPOINTMENTS]
    )
    return ok({
        'contact_id': contact.pk,
        'is_new': False,
        'name': contact.display_name,
        'appointments': [_appointment_payload(a) for a in appointments],
    })


def _search_contact(state, args):
    from apps.scheduling.models import Contact

    tenant, _location = _scope(state)
    first = str(args.get('first') or '').strip()
    last = str(args.get('last') or '').strip()
    dob = _parse_date(args.get('date_of_birth'))
    if not first or not last or dob is None:
        return err('invalid_argument',
                   "I need a first name, last name and date of birth to look "
                   "someone up.")

    matches = list(Contact.objects.filter(
        tenant=tenant, first_name__iexact=first, last_name__iexact=last,
        date_of_birth=dob,
    )[:5])

    data = {
        'contact_id': None,
        'matches': [{'contact_id': c.pk, 'name': c.display_name} for c in matches],
    }
    if len(matches) == 1:
        # The disambiguation path that makes search_contact -> book_appointment work.
        state.contact_id = matches[0].pk
        data['contact_id'] = matches[0].pk
    return ok(data)


def _create_contact(state, args):
    from apps.scheduling.models import Contact

    tenant, _location = _scope(state)
    first = str(args.get('first_name') or '').strip()
    last = str(args.get('last_name') or '').strip()
    # Deliberately laxer than the declaration, which marks both names required:
    # EITHER name is enough to file someone. A caller who gives only one name (or
    # goes by one) still gets recorded, the same reasoning as the date-of-birth
    # leniency below — a receptionist would write down what they were given rather
    # than refuse the caller. Only a wholly nameless call is refused.
    if not first and not last:
        return err('invalid_argument', "I need a name to put this under.")

    # A malformed date of birth does NOT refuse the whole tool — a receptionist
    # would still write the person down and move on.
    phone = str(args.get('phone') or '').strip() \
        or (state.variables or {}).get('from_e164') or ''
    contact = Contact.objects.create(
        tenant=tenant,
        first_name=first,
        last_name=last,
        date_of_birth=_parse_date(args.get('date_of_birth')),
        phone_e164=phone,          # Contact.save() normalises this itself
        source=Contact.SOURCE_AI_PHONE,
    )
    state.contact_id = contact.pk
    return ok({'contact_id': contact.pk, 'name': contact.display_name})


# --------------------------------------------------------------------------- #
# Handlers — availability and booking (thin wrappers over scheduling.availability)
# --------------------------------------------------------------------------- #

def _resolve_providers(tenant, location, provider_ids):
    """Model-supplied provider ids → User rows bookable at THIS location.

    An id that does not resolve under this tenant+location is **silently dropped**,
    never reported as "not found": a prompt-injected foreign id must degrade to
    "no slots for that one", not confirm that the id exists somewhere else.
    """
    from apps.accounts.models import User

    ids = [i for i in (provider_ids or []) if isinstance(i, int)]
    if not ids:
        return None            # no filter — search everyone bookable here
    # A supplied-but-unresolvable id yields an EMPTY pool, not None: the caller's
    # filter matched nobody here, so the answer is "no slots", never "here is
    # everyone's" (which would ignore the filter and hint the id exists elsewhere).
    return list(User.objects.filter(
        pk__in=ids, tenant=tenant, is_provider=True,
        status=User.STATUS_ACTIVE, user_locations__location=location,
    ).distinct()[:_MAX_FANOUT])


def _resolve_resources(tenant, location, resource_ids):
    """Model-supplied resource ids → active Resources at THIS location (see above)."""
    from apps.scheduling.models import Resource

    ids = [i for i in (resource_ids or []) if isinstance(i, int)]
    if not ids:
        return None            # no filter — let the service decide
    return list(Resource.objects.filter(
        pk__in=ids, tenant=tenant, location=location, is_active=True,
    )[:_MAX_FANOUT])


def _get_open_slots(state, args):
    from apps.scheduling import availability
    from apps.scheduling.models import Service
    from apps.tenants.services import WEEKDAY_BY_INDEX, WEEKDAY_KEYS

    tenant, location = _scope(state)

    service_id = args.get('service_id')
    if service_id in (None, ''):
        return err('invalid_argument', 'Which service would you like to check?')
    try:
        service_pk = int(service_id)
    except (TypeError, ValueError):
        return err('invalid_argument', 'Which service would you like to check?')

    # A Service is either pinned to this location or available at all of them.
    service = (
        Service.objects
        .filter(pk=service_pk, tenant=tenant, is_active=True)
        .filter(Q(location=location) | Q(location__isnull=True))
        .first()
    )
    if service is None:
        return err('not_found', "I don't have that service on file here.")

    # A supplied-but-unparseable date/time is a real misunderstanding worth
    # surfacing, unlike an unresolvable id — the caller said something we could
    # not read, so ask again rather than silently searching the wrong window.
    for key, parser in (('date_from', _parse_date), ('date_to', _parse_date),
                        ('time_from', _parse_time), ('time_to', _parse_time)):
        if args.get(key) and parser(args.get(key)) is None:
            return err('invalid_argument',
                       "I didn't catch that date or time — could you say it again?")
    date_from = _parse_date(args.get('date_from'))
    date_to = _parse_date(args.get('date_to'))
    time_from = _parse_time(args.get('time_from'))
    time_to = _parse_time(args.get('time_to'))

    wanted_days = {
        str(d).strip().lower() for d in (args.get('weekdays') or [])
        if str(d).strip().lower() in WEEKDAY_KEYS
    }

    limit = availability.MAX_OFFERED_SLOTS
    try:
        page_size = min(int(args.get('page_size') or limit), limit)
    except (TypeError, ValueError):
        page_size = limit
    page_size = max(1, page_size)
    try:
        page = max(1, int(args.get('page') or 1))
    except (TypeError, ValueError):
        page = 1

    # The tool schema takes ARRAYS of provider/resource ids; `find_available_slots`
    # takes pools and walks them internally against a SINGLE appointment-window
    # query. So resolve the ids (bounded by _MAX_FANOUT each) and call it ONCE —
    # calling it per (provider, resource) pair would re-run that same
    # provider-independent query for every pair, mid-call, inside the turn budget.
    # A resolved-but-empty pool correctly yields no slots (see _resolve_providers).
    slots = availability.find_available_slots(
        tenant=tenant, location=location, service=service,
        date_from=date_from, date_to=date_to, limit=limit,
        providers=_resolve_providers(tenant, location, args.get('provider_ids')),
        resources=_resolve_resources(tenant, location, args.get('resource_ids')),
    )

    tzinfo = location.tzinfo
    chosen = []
    for slot in sorted(slots, key=lambda item: item['start']):
        local = slot['start'].astimezone(tzinfo)
        if wanted_days and WEEKDAY_BY_INDEX.get(local.weekday()) not in wanted_days:
            continue
        if time_from and local.time() < time_from:
            continue
        if time_to and local.time() > time_to:
            continue
        chosen.append((slot, local))

    window = chosen[(page - 1) * page_size:(page - 1) * page_size + page_size]
    return ok({'slots': [
        {
            'slot_token': slot['token'],
            'display': f'{format_local_date(local)} at {format_local_time(local)}',
            'provider_name': (slot.get('provider').full_name
                              if slot.get('provider') is not None else None),
            'resource_label': (slot.get('resource').name
                               if slot.get('resource') is not None else None),
        }
        for slot, local in window
    ]})


def _book_appointment(state, args):
    from apps.calls.models import CallSession
    from apps.scheduling import availability
    from apps.scheduling.models import Appointment

    tenant, location = _scope(state)
    contact = _identified_contact(state, tenant)
    if contact is None:
        return err('not_permitted', "I need to know who I'm speaking with first.")

    token = str(args.get('slot_token') or '').strip()
    if not token:
        return err('invalid_argument',
                   "Could you tell me which of those times you'd like?")

    # The provenance stamp is resolved from SERVER state, never from an argument.
    session = CallSession.objects.filter(
        pk=state.session_id, tenant=tenant, location=location).first()

    try:
        appointment = availability.book_slot(
            tenant=tenant, location=location, token=token, contact=contact,
            reason=str(args.get('reason') or '')[:255],
            notes=str(args.get('notes') or ''),
            source=Appointment.SOURCE_AI_PHONE,
            booked_by_session=session,
        )
    except availability.SlotError as exc:
        # SlotError codes are a subset of the envelope's closed set — no translation.
        return err(exc.code, exc.message)
    return ok(_appointment_payload(appointment))


def _reschedule_appointment(state, args):
    from apps.scheduling import availability

    tenant, location = _scope(state)
    contact = _identified_contact(state, tenant)
    if contact is None:
        return err('not_permitted', "I need to know who I'm speaking with first.")

    appointment = _resolve_appointment(tenant, location, args.get('appointment_id'))
    if appointment is None:
        return err('not_found', "I couldn't find that appointment.")

    token = str(args.get('slot_token') or '').strip()
    if not token:
        return err('invalid_argument',
                   "Could you tell me which of those times you'd like instead?")

    try:
        # actor_contact is what makes a cross-CONTACT id come back not_permitted
        # from availability.py's own check — not a rule re-written here.
        appointment = availability.reschedule_appointment(
            tenant=tenant, location=location, appointment=appointment,
            token=token, reason='', actor_contact=contact,
        )
    except availability.SlotError as exc:
        return err(exc.code, exc.message)
    return ok(_appointment_payload(appointment))


def _cancel_appointment(state, args):
    from apps.scheduling import availability

    tenant, location = _scope(state)
    contact = _identified_contact(state, tenant)
    if contact is None:
        return err('not_permitted', "I need to know who I'm speaking with first.")

    appointment = _resolve_appointment(tenant, location, args.get('appointment_id'))
    if appointment is None:
        return err('not_found', "I couldn't find that appointment.")

    try:
        availability.cancel_appointment(
            appointment=appointment, tenant=tenant, location=location,
            reason=str(args.get('cancellation_reason') or '')[:255],
            actor_contact=contact,
        )
    except availability.SlotError as exc:
        return err(exc.code, exc.message)
    return ok({'appointment_id': appointment.pk, 'status': appointment.status})


# --------------------------------------------------------------------------- #
# Handlers — callback and information
# --------------------------------------------------------------------------- #

def _create_callback_request(state, args):
    from apps.scheduling.models import CallbackRequest

    tenant, location = _scope(state)
    # Deliberately NO identified-contact precondition: a callback for a caller
    # nobody identified is a normal outcome, and `contact` is simply left null
    # (Invariant 1 holds — no second identity table is invented for them).
    contact = _identified_contact(state, tenant)
    phone = str(args.get('caller_phone') or '').strip() \
        or (state.variables or {}).get('from_e164') or ''

    callback = CallbackRequest.objects.create(
        tenant=tenant, location=location, contact=contact,
        caller_name=str(args.get('caller_name') or '')[:255],
        caller_phone=phone,
        reason=str(args.get('reason') or ''),
        status=CallbackRequest.STATUS_PENDING,
        source=CallbackRequest.SOURCE_AI_PHONE,
    )
    return ok({'callback_id': callback.pk})


def _get_location_hours(state, args):
    from apps.tenants.services import WEEKDAYS

    _tenant, location = _scope(state)
    # No new hours query: `state.open_intervals` is the same provider-hours union
    # 3.2 already gathered once at connect().
    by_day = {}
    for interval in (state.open_intervals or []):
        for day in interval.get('days', []):
            by_day.setdefault(day, []).append({
                'start': interval['start_time'].strftime(_TIME_FORMAT),
                'end': interval['end_time'].strftime(_TIME_FORMAT),
            })

    hours = [
        {'weekday': label, 'windows': sorted(by_day[key], key=lambda w: w['start'])}
        for key, label in WEEKDAYS if key in by_day
    ]
    return ok({
        'location_name': location.name,
        'address': location.full_address,
        'hours': hours,
    })


# --------------------------------------------------------------------------- #
# Handlers — deferred transport signals (no ORM, no side effect here)
# --------------------------------------------------------------------------- #

def _transfer_call(state, args):
    """Set the deferred human-transfer signal and acknowledge (skill §9).

    Sets a flag; it does NOT dial. The working-hours gate, the single-fire guard,
    the drain interval and the actual Twilio redirect are 3.4's, executed by the
    transport after this turn's audio has finished playing. The destination is
    always the configured `AgentSetting.transfer_phone_number` — this tool takes
    no arguments precisely so nothing the caller says can influence where it goes.
    """
    state.pending_transfer = 'human'
    return ok({'transfer': 'human'})


def _transfer_call_spanish(state, args):
    """Same as `_transfer_call`, routed to the configured secondary line."""
    state.pending_transfer = 'spanish'
    return ok({'transfer': 'spanish'})


def _end_call(state, args):
    """Set the deferred hangup signal — the transport closes after the goodbye."""
    state.pending_hangup = True
    state.ended_reason = 'end_call'
    return ok({'ending': True})


# --------------------------------------------------------------------------- #
# The dispatch table + entry point
# --------------------------------------------------------------------------- #

#: name -> handler. This MUST equal `tools.TOOL_NAMES`: a declared-but-undispatched
#: tool fails silently mid-call, and a dispatched-but-undeclared one is dead code
#: the model can never reach. The dispatcher suite asserts the set equality.
TOOL_HANDLERS = {
    'get_contact_appointments': _get_contact_appointments,
    'search_contact': _search_contact,
    'create_contact': _create_contact,
    'get_open_slots': _get_open_slots,
    'book_appointment': _book_appointment,
    'reschedule_appointment': _reschedule_appointment,
    'cancel_appointment': _cancel_appointment,
    'create_callback_request': _create_callback_request,
    'get_location_hours': _get_location_hours,
    'transfer_call': _transfer_call,
    'transfer_call_spanish': _transfer_call_spanish,
    'end_call': _end_call,
}


async def apply_tool_call(state, name, args):
    """Apply one tool call against server-held ``state``. Returns the envelope.

    Never raises: an unknown tool, a bad argument or an unexpected exception all
    come back as a well-formed ``{ok: false, …}`` so the turn loop can speak an
    apology and carry on.
    """
    # Invariant 3: strip identity keys the model tried to supply, before any
    # handler can read them.
    safe_args = {k: v for k, v in (args or {}).items() if k not in IDENTITY_KEYS}

    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        result = err('invalid_argument', "I can't do that one, sorry.")
    else:
        try:
            if name in _NO_ORM_TOOLS:
                result = handler(state, safe_args)
            else:
                result = await database_sync_to_async(
                    handler, thread_sensitive=False)(state, safe_args)
        except Exception as exc:  # noqa: BLE001 — a tool must never kill the call
            # Type only: an ORM/driver error's text can embed a PII fragment.
            logger.error('Tool %s failed (%s)', name, type(exc).__name__)
            result = err('internal_error',
                         "Sorry, I hit a problem doing that. Let me try another way.")

    # The tool-call trace: a row in CallSession.logs (Invariant 2 — no ToolCall
    # table), with the arguments REDACTED before they are ever persisted.
    #
    # The payload shape is the ENVELOPE plus the tool name — `{tool, arguments,
    # ok, error}` — which is deliberately the shape Module 5.3's already-shipped
    # event-log template reads (`raw_json.tool`, `.arguments`, `.error.code`,
    # `.error.message`). 5.3 was built first and is the reader; the new writer
    # conforms to it rather than the other way round, so the trace renders in the
    # panel that exists for it instead of only in the raw-payload fallback.
    # `error` is the envelope's own object (or None), so the spoken failure reason
    # travels with the code — those strings are ours, never caller text.
    state.add_log('info', 'tool', f'Tool call: {name}', {
        'tool': name,
        'arguments': _redact_args(safe_args),
        'ok': result['ok'],
        'error': result['error'],
    })
    return result
