"""The signed, short-TTL, opaque stream token — the media stream's credential.

There are two websocket surfaces in this product and they authenticate
differently (``voice-agent-runtime`` skill §1, §3). The **carrier media stream**
has no Django session and no user: Twilio's cloud opens it, so it is authenticated
by a token this webhook mints into the connect TwiML and the 3.2 consumer verifies
in ``connect()``. This module is that token.

Why a signed token rather than putting ids in the URL or the stream parameters:

* **Invariant 3.** The consumer must never trust ``tenant_id`` / ``location_id`` /
  ``session_id`` read from the websocket URL or a cleartext parameter — that is a
  cross-tenant, cross-location vulnerability. The token is signed with the
  project ``SECRET_KEY``, so its contents cannot be forged or altered; the
  consumer resolves identity FROM the verified token, not from anything the caller
  or the URL supplied.
* **Short TTL.** A token is minted at answer time and is only useful for the few
  seconds until the stream connects. ``verify_stream_token`` enforces a max age,
  so a leaked or replayed token from an old call is rejected as expired.

3.1 only mints the token (into the TwiML). 3.2's consumer imports
``verify_stream_token`` to authorize the socket. Both live here so the shape is
defined once.
"""
from django.core import signing

__all__ = ['STREAM_TOKEN_SALT', 'STREAM_TOKEN_TTL_SECONDS',
           'mint_stream_token', 'verify_stream_token']

#: Namespacing salt — distinct from any other signed value in the project, so a
#: token minted for one purpose can never validate for another.
STREAM_TOKEN_SALT = 'apps.runtime.providers.tokens.stream'

#: How long a minted token stays valid. Generous enough to cover the answer →
#: stream-connect handshake with carrier jitter, short enough that a replayed
#: token from a finished call is useless. 5 minutes.
STREAM_TOKEN_TTL_SECONDS = 300


def mint_stream_token(session_id, tenant_id, location_id):
    """Sign an opaque token binding this stream to one session/tenant/location.

    The values are carried INSIDE the signed blob, never as readable URL or
    parameter fields — the consumer reads them back only after the signature
    verifies. Timestamped by ``signing.dumps`` so ``verify_stream_token`` can
    enforce the TTL.
    """
    payload = {'sid': session_id, 'ten': tenant_id, 'loc': location_id}
    return signing.dumps(payload, salt=STREAM_TOKEN_SALT, compress=True)


def verify_stream_token(token, max_age=STREAM_TOKEN_TTL_SECONDS):
    """Return the payload dict for a valid, unexpired token, else ``None``.

    Fails closed: a tampered signature (``BadSignature``), an expired token
    (``SignatureExpired``), a non-string input, or any malformed blob all return
    ``None`` rather than raising — the consumer treats ``None`` as "reject the
    socket with an explicit close code", never as "accept and hope".
    """
    if not token or not isinstance(token, str):
        return None
    try:
        return signing.loads(token, salt=STREAM_TOKEN_SALT, max_age=max_age)
    except signing.BadSignature:
        # SignatureExpired subclasses BadSignature, so this catches both tamper
        # and expiry. Never log the token — it is a bearer credential.
        return None
