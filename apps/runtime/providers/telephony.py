"""Twilio telephony helpers for the inbound webhook (3.1) — pure, no network.

Everything here is a pure function: signature verification is HMAC-SHA1 over the
request, and the TwiML builders emit XML strings. **Nothing here opens a socket or
reaches a carrier**, so importing it does not violate the "the fake path reaches
no provider" rule — returning TwiML from a webhook places no call.

We use the installed ``twilio`` SDK's ``RequestValidator`` and ``VoiceResponse``
rather than hand-rolling the HMAC and the XML: request-signature verification is
exactly the code where a subtle hand-rolled bug becomes an authentication bypass,
and the SDK's implementation is the reference one Twilio signs against.

**Why there is no ``get_backend()`` here (yet).** ``apps/agents/telephony.py``
already import-guards for ``from apps.runtime.providers.telephony import
get_backend`` and delegates to it once it exists. 3.1 deliberately does **not**
define that name: the import of a missing name raises ``ImportError``, which that
guard catches, so Module 2's connection-check and test-call keep using their own
backends unchanged. The real backend handoff — with the media redirect and hangup
the live path needs — lands with 3.4; wiring an incomplete ``get_backend`` now
would silently reroute Module 2 through a backend that cannot yet place a call.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

__all__ = [
    'webhook_public_url',
    'media_stream_ws_url',
    'verify_twilio_signature',
    'build_stream_twiml',
    'build_decline_twiml',
]

#: The default spoken line for a number that reaches us but is not in service —
#: unmapped, or mapped to a location whose agent is switched off. Short, and it
#: never leaks whether the number is unknown vs. disabled.
DEFAULT_DECLINE_MESSAGE = (
    "Thanks for calling. This number isn't taking calls right now. Goodbye."
)


def webhook_public_url(request):
    """The exact absolute URL Twilio signed — what the signature is checked against.

    Twilio computes its signature over the **public** URL it POSTed to, which
    behind a tunnel (ngrok in dev, a load balancer in prod) is NOT the internal
    host Django sees. So we build it from ``TWILIO_WEBHOOK_BASE_URL`` — the setting
    that must equal the public base exactly, or every signature fails and the
    agent looks broken. Only when that setting is unset (a local run with no
    tunnel, and the test client) do we fall back to the request's own host, which
    is fine there because nothing is proxying.

    Voice webhooks POST to a fixed path with no query string, so the path alone is
    appended — no query to fold in.
    """
    base = (getattr(settings, 'TWILIO_WEBHOOK_BASE_URL', '') or '').rstrip('/')
    if base:
        return f'{base}{request.path}'
    return request.build_absolute_uri(request.path)


def media_stream_ws_url():
    """The ``wss://`` URL Twilio should open the media stream to.

    Derived from the same public base as the webhook, with the scheme swapped to
    the websocket one — Twilio's cloud dials this from the outside, so it must be
    the public URL, never an internal ``127.0.0.1``. The ``/ws/media-stream/``
    route itself is added by 3.2; 3.1 only needs to name it correctly in the
    connect TwiML. Falls back to a relative path when no tunnel is configured.
    """
    base = (getattr(settings, 'TWILIO_WEBHOOK_BASE_URL', '') or '').rstrip('/')
    path = '/ws/media-stream/'
    if base.startswith('https://'):
        return f'wss://{base[len("https://"):]}{path}'
    if base.startswith('http://'):
        return f'ws://{base[len("http://"):]}{path}'
    return path


def verify_twilio_signature(url, params, signature, auth_token):
    """True iff ``signature`` is a valid Twilio signature for ``(url, params)``.

    HMAC-SHA1 over the exact public URL plus the sorted POST params, keyed by the
    **resolving location's** ``auth_token`` (decrypted from the encrypted field by
    the caller). ``RequestValidator.validate`` uses ``hmac.compare_digest``
    internally, so this is constant-time.

    **Fails closed on every missing input.** No token, no signature, or a bad
    input type all return ``False`` — never ``True``, never an exception. A
    location with no auth token stored simply cannot be called, which is the safe
    outcome: the alternative (skipping verification when a token is absent) would
    turn a misconfiguration into an open, unauthenticated webhook.
    """
    if not auth_token or not signature or url is None:
        return False
    try:
        from twilio.request_validator import RequestValidator

        return RequestValidator(auth_token).validate(url, params or {}, signature)
    except Exception as exc:  # noqa: BLE001 - never let a validator quirk 500 the webhook
        # Log the TYPE only — the params carry the caller's number (PII) and the
        # signature is a credential-derived value. Neither belongs in a log line.
        logger.warning('Twilio signature validation errored: %s', type(exc).__name__)
        return False


def build_stream_twiml(ws_url, parameters=None):
    """TwiML that connects the call to the bidirectional media stream.

    ``<Connect><Stream url="wss://…"><Parameter …/></Stream></Connect>``. The
    ``parameters`` become opaque ``<Parameter>`` custom values on the stream —
    this is where the signed stream token rides (see ``providers.tokens``). They
    are **opaque on purpose**: tenant, location and session identity never travel
    as cleartext parameters a caller could read or forge (Invariant 3); the token
    is the only thing that crosses, and the consumer verifies it.
    """
    from twilio.twiml.voice_response import Connect, Stream, VoiceResponse

    response = VoiceResponse()
    connect = Connect()
    stream = Stream(url=ws_url)
    for name, value in (parameters or {}).items():
        # str() so an int pk or None does not blow up the XML serializer.
        stream.parameter(name=name, value='' if value is None else str(value))
    connect.append(stream)
    response.append(connect)
    return str(response)


def build_decline_twiml(message=DEFAULT_DECLINE_MESSAGE):
    """TwiML that says one line and hangs up — the never-silence decline.

    Used for an unmapped or disabled number: the caller hears a short spoken
    notice and a clean hangup instead of dead air. It performs no side effect and
    reveals nothing about the account, so it is safe to return without having
    verified a signature (there is no per-location token to verify against for an
    unmapped number, and nothing is written).
    """
    from twilio.twiml.voice_response import VoiceResponse

    response = VoiceResponse()
    response.say(message)
    response.hangup()
    return str(response)
