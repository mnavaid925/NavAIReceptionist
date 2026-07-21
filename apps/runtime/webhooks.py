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
"""
import logging

from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.agents.models import AgentSetting
from apps.calls.models import CallSession
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

    # 1. Resolve the dialed number. Unmapped OR disabled → decline, ZERO writes.
    #    Both take the same branch on purpose: the decline reveals nothing about
    #    which of the two it was, and neither has a verified caller yet, so
    #    nothing is persisted. (Disabled is mapped, so verifying its signature and
    #    logging a `failed` row for the diagnostics page was considered and
    #    deferred — 3.1 keeps the two paths identical and side-effect-free.)
    setting = _resolve_setting(to_number)
    if setting is None or not setting.enabled:
        return _twiml(build_decline_twiml())

    # 2. Verify the signature against THIS location's token, before any side
    #    effect. Fails closed on a missing/tampered signature or a missing token.
    signature = request.META.get(SIGNATURE_HEADER, '')
    public_url = webhook_public_url(request)
    if not verify_twilio_signature(public_url, params.dict(), signature,
                                   setting.twilio_auth_token):
        # No number, no body — logging either would defeat the point.
        logger.warning('Rejected an inbound webhook with an invalid signature.')
        return HttpResponseForbidden('Invalid signature.')

    # A genuine Twilio voice request always carries a CallSid; without it there is
    # no idempotency key. Malformed → 400, not a 500 and not a silent write.
    if not call_sid:
        return HttpResponseBadRequest('Missing CallSid.')

    # 3. Idempotent create. get_or_create + the unique provider_call_sid lets a
    #    redelivered webhook lose the race and return the existing row unchanged.
    session, _created = CallSession.objects.get_or_create(
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

    # 4. Connect to the media stream. The signed token is the ONLY identity that
    #    crosses to the (session-less, user-less) stream; the consumer resolves
    #    tenant/location/session from it, never from the URL. session.pk is passed
    #    too, but as an opaque parameter the consumer cross-checks against the
    #    token — it is not trusted on its own.
    token = mint_stream_token(session.pk, setting.tenant_id, setting.location_id)
    twiml = build_stream_twiml(
        media_stream_ws_url(),
        {'streamToken': token, 'sessionId': session.pk},
    )
    return _twiml(twiml)
