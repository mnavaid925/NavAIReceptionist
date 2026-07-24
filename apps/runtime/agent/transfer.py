"""Transfer outcome shape + injection-safety checks — sub-module 3.4.

Pure module: no ORM, no Channels import, no provider import. It exists so the
transfer flow has **one** source of truth rather than ad-hoc dict literals
scattered across the two writers — the dispatcher's off-hours-gate-fail path
(``apps.runtime.agent.dispatcher``) and the consumer's post-redirect
outcome-capture path (``MediaStreamConsumer._execute_transfer``).

Two things live here:

1. ``build_transfer_record`` — the ONE builder of the ``calls.CallSession.transfer``
   JSON. Its shape is the reading contract two already-shipped sub-modules depend
   on: ``templates/partials/_transfer_outcome.html`` (5.4) renders exactly
   ``{result, reason, destination, initiated_at, duration_seconds, attempts}``,
   and ``seed_calls.py`` (5.1) seeds it. A second dict literal would drift from
   that the first time either writer was edited alone.

2. ``looks_like_e164`` / ``looks_like_call_sid`` — shape checks run BEFORE either
   value is interpolated into a Twilio REST call or a TwiML string. The transfer
   destination is dialed with the **tenant's own** Twilio credentials, so an
   unvalidated or corrupted value reaching that REST call is a real-money,
   real-carrier action — CLAUDE.md vulnerability rules 6/8 (toll fraud), plus
   XML/URL injection into the TwiML/REST string. These are a hygiene gate, not an
   authenticator: their job is to REFUSE an injection-shaped value, never to
   prove who issued the SID.

**The result vocabulary is NOT the tool-envelope error-code set.** ``result`` ∈
``{connected, no_answer, off_hours, disabled, failed}`` is the badge vocabulary
``_transfer_outcome.html`` renders; the envelope's ``code`` set
(``not_found`` / ``invalid_argument`` / …) is a different, separately-maintained
closed set. They are kept deliberately apart — no shared import, different
constant names — so an edit cannot wire one into the other's assertion.
"""
import re

from django.utils import timezone

from apps.scheduling.services import normalize_e164

__all__ = [
    'RESULT_CONNECTED',
    'RESULT_NO_ANSWER',
    'RESULT_OFF_HOURS',
    'RESULT_DISABLED',
    'RESULT_FAILED',
    'RESULT_CHOICES',
    'REASON_BY_KIND',
    'build_transfer_record',
    'looks_like_e164',
    'looks_like_call_sid',
]

#: The `CallSession.transfer.result` vocabulary `_transfer_outcome.html` badges.
#: `no_answer` is declared here (the reader renders it, the seeder seeds it) but is
#: NOT written by this pass's code — distinguishing no-answer from connected needs
#: the deferred Twilio `<Dial action>` status callback; until then a redirect that
#: Twilio accepts is recorded provisionally as `connected`. See todo.md 3.4.
RESULT_CONNECTED = 'connected'
RESULT_NO_ANSWER = 'no_answer'
RESULT_OFF_HOURS = 'off_hours'
RESULT_DISABLED = 'disabled'
RESULT_FAILED = 'failed'
RESULT_CHOICES = frozenset({
    RESULT_CONNECTED,
    RESULT_NO_ANSWER,
    RESULT_OFF_HOURS,
    RESULT_DISABLED,
    RESULT_FAILED,
})

#: Human-readable `reason` text for a transfer that was actually attempted, keyed
#: by `CallState.pending_transfer`'s value. Rendered verbatim by the reader, so it
#: is a short caller-neutral phrase, never caller speech.
REASON_BY_KIND = {
    'human': 'Caller asked to speak with a person.',
    'spanish': 'Caller asked for the Spanish-speaking line.',
}

#: Permissive-but-injection-safe. A Twilio call SID is `CA` + 32 hex in
#: production, but PROVIDER_MODE=fake never mints that shape — `simulate_call`
#: uses `SIM-…` and the test fixtures use `CA1` / `TURN-1`. So this accepts any
#: short opaque token of URL/XML-safe characters and REFUSES the injection-relevant
#: ones (`<`, `&`, `"`, `/`, whitespace). The job is stopping a corrupted value
#: from reaching a REST URL / TwiML body, not authenticating the SID's issuer; a
#: strict `^CA[0-9a-f]{32}$` here would make every fake/simulated transfer
#: untestable under PROVIDER_MODE=fake.
_CALL_SID_RE = re.compile(r'^[A-Za-z0-9_-]{2,64}$')


def looks_like_e164(value):
    """True iff ``value`` is ALREADY a strict E.164 string (``+`` then 7-15 digits).

    Defined as "``normalize_e164`` leaves it unchanged", reusing the canonical
    producer rather than re-declaring its digit bounds. A national number (normalize
    would prepend a country code) or anything carrying an injection character
    (normalize strips non-digits, so the value changes) both fail this equality —
    which is exactly the toll-fraud/injection guarantee this gate is here for.
    """
    return bool(value) and isinstance(value, str) and normalize_e164(value) == value


def looks_like_call_sid(value):
    """True iff ``value`` is a safe opaque call reference (see ``_CALL_SID_RE``)."""
    return bool(value) and isinstance(value, str) and bool(_CALL_SID_RE.match(value.strip()))


def build_transfer_record(*, result, reason='', destination='', initiated_at=None,
                          duration_seconds=0, attempts=None):
    """Build the one ``CallSession.transfer`` dict — the shared writer contract.

    ``initiated_at`` is stored as an ISO-8601 string (the reader renders it inside
    a ``<time datetime=…>``): a ``datetime`` is isoformatted, a string is kept, and
    ``None`` becomes now. ``attempts`` is included ONLY when supplied — the common
    single-try transfer omits it, matching ``seed_calls``'s own rows and the
    reader, which shows the trail only for 2+ attempts.

    Raises ``ValueError`` on an out-of-vocabulary ``result`` — loud rather than
    silent, because an unknown value breaks both the badge and the call-log
    outcome filter downstream. Callers always pass a ``RESULT_*`` constant.
    """
    if result not in RESULT_CHOICES:
        raise ValueError(
            f'unknown transfer result {result!r}; expected one of {sorted(RESULT_CHOICES)}'
        )
    moment = initiated_at if initiated_at is not None else timezone.now()
    record = {
        'result': result,
        'reason': reason or '',
        'destination': destination or '',
        'initiated_at': moment.isoformat() if hasattr(moment, 'isoformat') else str(moment),
        'duration_seconds': duration_seconds or 0,
    }
    if attempts:
        record['attempts'] = attempts
    return record
