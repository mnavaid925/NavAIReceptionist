"""Twilio telephony helpers for the inbound webhook (3.1) — pure, no network.

Everything here is a pure function: signature verification is HMAC-SHA1 over the
request, and the TwiML builders emit XML strings. **Nothing here opens a socket or
reaches a carrier**, so importing it does not violate the "the fake path reaches
no provider" rule — returning TwiML from a webhook places no call.

We use the installed ``twilio`` SDK's ``RequestValidator`` and ``VoiceResponse``
rather than hand-rolling the HMAC and the XML: request-signature verification is
exactly the code where a subtle hand-rolled bug becomes an authentication bypass,
and the SDK's implementation is the reference one Twilio signs against.

**The ``get_backend()`` handoff (3.4).** ``apps/agents/telephony.py`` import-guards
for ``from apps.runtime.providers.telephony import get_backend`` and delegates to
it once it exists. 3.1 deliberately left it undefined so Module 2 kept its own
backends; **3.4 defines it here**, so ``apps.agents.telephony.get_backend()`` now
returns THIS module's backend. The runtime backends **subclass** Module 2's
(``check_connection`` / ``place_test_call`` inherited verbatim — Module 2's
connection-check and test-call are byte-for-byte unchanged) and **add**
``redirect_call``, the deferred human-transfer redirect the live call path needs.

The backend reports a redirect as a boolean ``TelephonyResult.ok`` — transport
success/failure — and never imports the transfer-outcome vocabulary
(``apps.runtime.agent.transfer``'s ``result`` set): the consumer maps ``ok`` onto
``connected`` / ``failed``. That keeps this module free of the conversation layer
and free of any import cycle back into ``apps.runtime.agent``.
"""
import asyncio
import logging

from django.conf import settings

from apps.agents.telephony import (
    FakeTelephonyBackend as _AgentsFakeBackend,
    LiveTelephonyBackend as _AgentsLiveBackend,
    TelephonyResult,
)

logger = logging.getLogger(__name__)

__all__ = [
    'webhook_public_url',
    'media_stream_ws_url',
    'verify_twilio_signature',
    'build_stream_twiml',
    'build_decline_twiml',
    'FakeTelephonyBackend',
    'LiveTelephonyBackend',
    'get_backend',
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


# --------------------------------------------------------------------------- #
# The transfer backend (3.4) — get_backend() + redirect_call
#
# `redirect_call(setting, call_sid, destination)` is what turns 3.3's deferred
# `pending_transfer` signal into an actual carrier handoff, executed by the
# consumer AFTER the turn's audio has played. The DESTINATION and the CALL SID
# are shape-validated by the CONSUMER (apps.runtime.agent.transfer.looks_like_e164
# / looks_like_call_sid) BEFORE they reach these methods — a value dialed with the
# tenant's own Twilio credentials must never be caller/model-influenced (toll
# fraud) nor carry an XML/URL-injection character (the destination is interpolated
# into a TwiML string). These methods trust that gate and do not re-run it.
# --------------------------------------------------------------------------- #


class FakeTelephonyBackend(_AgentsFakeBackend):
    """Simulated transfer — reaches nothing, like the base it extends.

    Inherits ``check_connection`` / ``place_test_call`` verbatim from Module 2's
    fake (so ``get_backend()`` returning this instance changes nothing for 2.2 /
    2.4) and adds ``redirect_call``. It imports no ``twilio`` and opens no socket:
    the safety property is that it COULD NOT reach a carrier, not that it chooses
    not to.
    """

    #: Test/diagnostic override, process-global like the fake-LLM script. ``None``
    #: → a successful (connected) redirect. Set to ``False`` to exercise the
    #: failed-redirect path under PROVIDER_MODE=fake without a real status
    #: callback. Set it in a test/`simulate_call` and clear it in a ``finally``.
    _scripted_ok = None

    @classmethod
    def script_redirect(cls, *, ok):
        """Force the next fake redirect(s) to succeed/fail. Diagnostic only."""
        cls._scripted_ok = ok

    @classmethod
    def clear_redirect_script(cls):
        """Drop the redirect override, so the next fake redirect succeeds."""
        cls._scripted_ok = None

    async def redirect_call(self, setting, call_sid, destination):
        ok = True if self._scripted_ok is None else bool(self._scripted_ok)
        return TelephonyResult(
            ok=ok,
            summary='Transfer redirect simulated'
                    + ('' if ok else ' (scripted failure)'),
            detail=(f'In live mode this would redirect the in-progress call to '
                    f'{destination}. PROVIDER_MODE is "{settings.PROVIDER_MODE}", '
                    'so no REST call was made and nothing was billed.'),
            mode=self.mode,
            data={'call_sid': call_sid, 'destination': destination},
        )


class LiveTelephonyBackend(_AgentsLiveBackend):
    """The real transfer redirect. Guarded on every side, like the base it extends.

    Inherits the ``__init__`` guard (refuses to initialise unless
    ``PROVIDER_MODE == 'live'``) and ``_client`` (which hard-fails on missing
    credentials) verbatim; adds ``redirect_call``.
    """

    async def redirect_call(self, setting, call_sid, destination):
        # `client.calls(...).update(...)` is a BLOCKING SDK/network call. It MUST
        # NOT run bare inside this `async def` — a blocking call on the event loop
        # freezes audio for every concurrent call on the worker (CLAUDE.md realtime
        # rule 1). Off-loop via a thread; the caller bounds it with a timeout.
        def _redirect():
            client = self._client(setting)  # inherited; raises if creds absent
            # answerOnBridge so the caller hears ringing, timeout=25 so a no-answer
            # gives up rather than ringing forever. `destination`/`call_sid` were
            # shape-validated by the consumer before this call — no injection path.
            twiml = ('<Response><Dial answerOnBridge="true" timeout="25">'
                     f'{destination}</Dial></Response>')
            return client.calls(call_sid).update(twiml=twiml)

        try:
            call = await asyncio.to_thread(_redirect)
        except Exception as exc:  # noqa: BLE001 — degrade to a failed outcome, never crash the call
            # Type only — the provider's exception text can carry the SID or the
            # request body. Neither belongs in a log line.
            logger.error('Twilio transfer redirect failed: %s', type(exc).__name__)
            return TelephonyResult(
                ok=False, summary='Transfer redirect failed',
                detail='Twilio would not redirect the call.',
                mode=self.mode, simulated=False,
            )
        return TelephonyResult(
            ok=True, summary='Transfer redirect placed',
            detail=f'Redirecting the call to {destination}.',
            mode=self.mode, simulated=False,
            data={'sid': getattr(call, 'sid', '')},
        )


def get_backend():
    """The transfer backend for the current ``PROVIDER_MODE``.

    Anything that is not exactly ``'live'`` resolves to the fake — an unrecognised
    mode must fail SAFE, never toward the carrier. This is the name
    ``apps.agents.telephony.get_backend()`` import-guards for; defining it here is
    the 3.4 handoff, and Module 2 now delegates its connection-check/test-call
    through this module's backend (the ``check_connection``/``place_test_call``
    inherited unchanged).
    """
    if settings.PROVIDER_MODE == 'live':
        return LiveTelephonyBackend()
    return FakeTelephonyBackend()
