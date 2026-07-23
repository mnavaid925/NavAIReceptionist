"""The one tool-result envelope — sub-module 3.3.

**Every tool returns this shape, no exceptions** (``voice-agent-runtime`` §8.3):

    {"ok": true,  "data": {...}, "error": null}
    {"ok": false, "data": null,  "error": {"code": "slot_unavailable",
                                           "message": "That time was just booked."}}

Never prose, never a bare ``{"id": ...}``, never a different success key per tool.
``ok`` is what the log recorder, the diagnostics page and the "did it actually
succeed" rules key off, so it has to mean the same thing everywhere.

``error.code`` is **always lower_snake_case and drawn from one closed set**. The
code is what callers branch on, so it is never prose and never re-cased per tool;
the human-readable string goes in ``message`` — and on this product's voice path
that message is SPOKEN to a caller, so it is written as a sentence a receptionist
would say, not as an exception string.

The closed set is asserted rather than merely documented: a typo'd or invented
code is a code the runtime has never seen and cannot branch on, and it should fail
loudly in dev instead of shipping silently. This mirrors the identical assert in
``apps/scheduling/availability.py``'s ``SlotError`` — whose four codes are a
subset of these eight, which is what lets the dispatcher pass a ``SlotError``
straight through with zero translation.
"""

__all__ = ['ERROR_CODES', 'ok', 'err']

#: The CLOSED set of error codes any tool may emit (skill §8.3).
#:
#: ``provider_error`` and ``rate_limited`` are declared but unreachable today —
#: every 3.3 tool is a local DB read/write with no external provider round-trip
#: and no per-tool rate limit. They stay in the set so the first tool that does
#: call out has a code waiting rather than inventing one.
ERROR_CODES = frozenset({
    'not_found',
    'invalid_argument',
    'slot_unavailable',
    'slot_expired',
    'not_permitted',
    'provider_error',
    'rate_limited',
    'internal_error',
})


def ok(data=None):
    """A successful tool result. ``data`` defaults to an empty dict, never None.

    Tools that genuinely return nothing (``transfer_call``, ``end_call``) still
    carry ``{}`` rather than ``null``, so a caller can always index ``data``
    without a None-check.
    """
    return {'ok': True, 'data': {} if data is None else data, 'error': None}


def err(code, message):
    """A failed tool result carrying a closed-set ``code`` and a spoken ``message``.

    Raises ``ValueError`` on a code outside :data:`ERROR_CODES` — an invented code
    is a bug in the calling branch, and failing here surfaces it in dev and in the
    test suite rather than emitting something the model and the diagnostics page
    cannot branch on.
    """
    if code not in ERROR_CODES:
        raise ValueError(
            f'{code!r} is not a member of the closed tool-error code set. '
            f'Use one of: {sorted(ERROR_CODES)}.'
        )
    return {'ok': False, 'data': None, 'error': {'code': code, 'message': message}}
