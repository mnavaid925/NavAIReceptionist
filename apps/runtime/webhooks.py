"""Twilio inbound-voice webhook — Module 3.1, the HTTP half of the call path.

This is the one place tenant and location are discovered from scratch; everything
downstream inherits them. The order below is load-bearing and is the contract in
``.claude/skills/voice-agent-runtime/SKILL.md`` §2:

1. **Resolve the dialed number first.** ``To`` → ``agents.AgentSetting`` (globally
   unique ``inbound_phone_number``) → tenant + location + agent config in one
   lookup. An unmapped or disabled number gets a spoken decline and a hangup, and
   never reaches the stream — never dead air.
2. **Verify ``X-Twilio-Signature`` before any side effect**, using THAT resolved
   row's credentials. Invalid or missing → 403, zero writes. ``@csrf_exempt`` is
   correct here only because this verification replaces it.
3. **Idempotently** create the ``calls.CallSession`` keyed on the unique
   ``provider_call_sid``. Twilio redelivers; a retry must not mint a second
   session.
4. Return ``<Connect><Stream>`` TwiML carrying an **opaque signed stream token** —
   never ``tenant_id`` / ``location_id`` as cleartext (Invariant 3).

**Never** a redirect (Twilio wants TwiML, not POST-redirect-GET). **Never** a
caller number, a signature, or a request body logged at INFO — a voice webhook's
POST params are PII.

**Rate limiting bounds UNVERIFIED traffic only.** 3.1 deferred this because the
obvious shapes are all wrong for a telephony endpoint: Twilio redelivers a failed
webhook, a busy location takes concurrent calls, and Twilio's egress IPs are
shared across its whole customer base — so a requests-per-minute cap keyed on any
of those blocks real calls.

The resolution is to count only what legitimate traffic never produces. The
counter increments on a request that fails to resolve a dialed number or fails
signature verification, and is CLEARED by any request whose signature verifies.
Real Twilio traffic always verifies, so it never increments the counter and can
never be throttled — burst concurrency and redelivery are structurally immune
rather than merely tuned around. What is left bounded is the scanner: the gate is
checked BEFORE the `AgentSetting` lookup, so a throttled source stops costing a
database query at all.

The counter lives in its own key namespace (`accounts.throttling.scoped_ip_keys`),
never the login one — otherwise a scanner on this public endpoint could lock real
users out of signing in.
"""
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts import throttling
from apps.accounts.views._helpers import get_client_ip
from apps.agents.models import AgentSetting
from apps.calls.models import CallSession
from apps.runtime.agent.transfer import looks_like_call_sid
from apps.runtime.providers.telephony import (
    build_decline_twiml,
    build_stream_twiml,
    media_stream_ws_url,
    verify_twilio_signature,
    webhook_public_url,
)
from apps.runtime.providers.tokens import mint_stream_token

logger = logging.getLogger(__name__)

#: Twilio sends its request-authenticity signature in this header.
SIGNATURE_HEADER = 'HTTP_X_TWILIO_SIGNATURE'

#: `application/xml` is what Twilio parses TwiML from. A wrong content type makes
#: Twilio treat the body as opaque and hang up — the caller hears nothing.
TWIML_CONTENT_TYPE = 'application/xml'

# Closed set of webhook termination reasons. Logged as a bare code — NEVER with
# the dialed/caller number, the signature or the body — so the diagnostics page
# (and 3.5's fuller one) can answer "why was this call not answered?" without a
# log line ever carrying PII. `provider_call_sid` is a Twilio SID, not PII, but is
# still left out to keep every one of these lines uniformly number-free.
REASON_UNMAPPED = 'unmapped'
REASON_DISABLED = 'disabled'
REASON_SIGNATURE_INVALID = 'signature_invalid'
REASON_MISSING_CALLSID = 'missing_callsid'
REASON_DUPLICATE = 'duplicate_delivery'
REASON_THROTTLED = 'throttled'

#: Namespace for the webhook's own failure counter. NEVER the login namespace —
#: see the module docstring.
THROTTLE_SCOPE = 'webhook'


def _is_throttled(keys):
    """Whether this source has exhausted its unverified-attempt budget.

    FAILS OPEN. If the cache is unreachable, the call is allowed through rather
    than refused: every side effect downstream is still gated on Twilio signature
    verification, so the worst case of failing open is that an abusive source
    keeps costing us one indexed query — while the worst case of failing closed is
    refusing every real inbound call in the business, on a telephony endpoint,
    because a cache node blipped. The rate limit is a cost control; the signature
    is the security control, and it is unaffected.
    """
    if not keys:
        return False
    try:
        return throttling.is_throttled(keys, limit=settings.WEBHOOK_FAILURE_LIMIT)
    except Exception as exc:  # noqa: BLE001 — a cache outage must not drop calls
        logger.error('Webhook throttle unavailable (%s); allowing the request.',
                     type(exc).__name__)
        return False


def _clear_failures(keys):
    """Reset the counter after a verified request. Never raises (see above)."""
    if not keys:
        return
    try:
        throttling.clear(keys)
    except Exception as exc:  # noqa: BLE001
        logger.error('Webhook throttle counter unavailable (%s).', type(exc).__name__)


def _register_failure(keys):
    """Count one unverified attempt against the webhook's own IP counter.

    A cache hiccup must never take the voice webhook down with it: failing to
    record an attempt degrades the rate limit, which is a bounded loss, whereas
    raising here would drop a real inbound call — a far worse outcome than the
    one this counter exists to prevent.
    """
    if not keys:
        return
    try:
        throttling.register_failure(
            keys, window=settings.WEBHOOK_FAILURE_WINDOW_SECONDS)
    except Exception as exc:  # noqa: BLE001 — never fail a call over the counter
        logger.error('Webhook throttle counter unavailable (%s).', type(exc).__name__)


def _twiml(body, status=200):
    return HttpResponse(body, content_type=TWIML_CONTENT_TYPE, status=status)


def _resolve_setting(to_number):
    """The AgentSetting for a dialed number, or None. Resolution is by number ONLY.

    tenant and location come from the row this returns — never from a query-string
    or body parameter the caller controls. That is the whole reason
    ``inbound_phone_number`` is globally unique.
    """
    if not to_number:
        return None
    return (
        AgentSetting.objects
        .filter(inbound_phone_number=to_number)
        .select_related('tenant', 'location')
        .first()
    )


@csrf_exempt
@require_POST
def voice_webhook(request):
    """Answer an inbound Twilio call and connect it to the media stream."""
    params = request.POST
    to_number = (params.get('To') or params.get('Called') or '').strip()
    from_number = (params.get('From') or params.get('Caller') or '').strip()
    call_sid = (params.get('CallSid') or '').strip()

    # 0. Throttle gate, BEFORE the AgentSetting lookup — so a source that has
    #    already failed repeatedly stops costing a database query, which is the
    #    whole point of bounding an unauthenticated endpoint. Only unverified
    #    traffic ever reaches the counter (see the module docstring), so a real
    #    Twilio request cannot be refused here.
    throttle_keys = throttling.scoped_ip_keys(THROTTLE_SCOPE, get_client_ip(request))
    if _is_throttled(throttle_keys):
        logger.warning('Inbound webhook rejected (%s).', REASON_THROTTLED)
        response = HttpResponse('Too many requests.', status=429)
        response['Retry-After'] = str(settings.WEBHOOK_FAILURE_WINDOW_SECONDS)
        return response

    # 1. Resolve the dialed number. Unmapped OR disabled → decline, ZERO writes.
    #    Both take the same branch on purpose: the decline reveals nothing about
    #    which of the two it was, and neither has a verified caller yet, so
    #    nothing is persisted. (Disabled is mapped, so verifying its signature and
    #    logging a `failed` row for the diagnostics page was considered and
    #    deferred — 3.1 keeps the two paths identical and side-effect-free.)
    setting = _resolve_setting(to_number)
    if setting is None or not setting.enabled:
        logger.info(
            'Inbound webhook declined (%s).',
            REASON_UNMAPPED if setting is None else REASON_DISABLED,
        )
        # Counted: this is the scanner's path. It is also a real caller dialling a
        # decommissioned number, which is why the ceiling is generous — a handful
        # of genuine calls to an unmapped line must never reach it.
        _register_failure(throttle_keys)
        return _twiml(build_decline_twiml())

    # 2. Verify the signature against THIS location's token, before any side
    #    effect. Fails closed on a missing/tampered signature or a missing token.
    signature = request.META.get(SIGNATURE_HEADER, '')
    public_url = webhook_public_url(request)
    if not verify_twilio_signature(public_url, params.dict(), signature,
                                   setting.twilio_auth_token):
        # No number, no body — logging either would defeat the point.
        logger.warning('Rejected an inbound webhook (%s).', REASON_SIGNATURE_INVALID)
        _register_failure(throttle_keys)
        return HttpResponseForbidden('Invalid signature.')

    # VERIFIED: this is genuinely Twilio. Clear the counter, so a location that was
    # briefly unmapped or disabled — every one of whose calls counted as a failure
    # above — is not left throttled for the rest of the window once it is fixed.
    # Nothing legitimate accumulates failures, so there is normally nothing here to
    # clear; this exists for the recovery case, not the steady state.
    _clear_failures(throttle_keys)

    # A genuine Twilio voice request always carries a CallSid; without it there is
    # no idempotency key. Malformed → 400, not a 500 and not a silent write.
    #
    # SHAPE-CHECKED, not merely present: this value is persisted as
    # `provider_call_sid` and then reused downstream as data in contexts that give
    # it authority — interpolated into the transfer REST path (3.4) and into the
    # recording's storage path (3.5, `providers.recording.recording_path_for`). A
    # SID carrying `../` would write a recording outside its own
    # `private/calls/{tenant}/{location}/` prefix: `safe_join` only guards the
    # PRIVATE_MEDIA_ROOT boundary, not the tenant/location partition inside it.
    # Validating once here, at the point the value enters the system, is what
    # keeps every later consumer of it safe. A real Twilio SID is `CA` + 32 hex.
    if not looks_like_call_sid(call_sid):
        logger.info('Inbound webhook rejected (%s).', REASON_MISSING_CALLSID)
        return HttpResponseBadRequest('Missing or malformed CallSid.')

    # 3. Idempotent create. get_or_create + the unique provider_call_sid lets a
    #    redelivered webhook lose the race and return the existing row unchanged.
    session, created = CallSession.objects.get_or_create(
        provider_call_sid=call_sid,
        defaults={
            'tenant': setting.tenant,
            'location': setting.location,
            'from_number': from_number,
            'to_number': to_number,
            'status': CallSession.STATUS_IN_PROGRESS,
            # MODE_CHOICES mirrors AgentSetting.VOICE_PROVIDER_CHOICES value-for-
            # value, so the location's configured stack is recorded on the call.
            'mode': setting.voice_provider,
            'started_at': timezone.now(),
        },
    )
    if not created:
        # Twilio redelivered; the unique provider_call_sid made get_or_create
        # return the existing row unchanged. Same stream TwiML goes back.
        logger.info('Inbound webhook (%s).', REASON_DUPLICATE)

    # 4. Connect to the media stream. The signed token is the ONLY identity that
    #    crosses to the (session-less, user-less) stream; the consumer resolves
    #    tenant/location/session from it, never from the URL. session.pk is passed
    #    too, but as an opaque parameter the consumer cross-checks against the
    #    token — it is not trusted on its own. Bind the token to the PERSISTED
    #    session's tenant/location (identical to the setting's on a fresh row, and
    #    authoritative on a redelivery) rather than the just-resolved setting.
    token = mint_stream_token(session.pk, session.tenant_id, session.location_id)
    twiml = build_stream_twiml(
        media_stream_ws_url(),
        {'streamToken': token, 'sessionId': session.pk},
    )
    return _twiml(twiml)
