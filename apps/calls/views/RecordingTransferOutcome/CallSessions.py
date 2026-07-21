"""The signed-media recording serve view (sub-module 5.4).

This is the whole reason 5.4 has a backend at all. `recording_blob` is a PRIVATE
storage path holding caller PII, and the "Signed Media Access" bullet is explicit:
it is served through a short-lived signed URL, never a public or guessable path. A
plain `<audio src="/media/…">` at the raw path is the exact vulnerability this view
exists to prevent.

Three INDEPENDENT gates, cheapest first, mirroring `email_change_confirm_view`'s
own order:

  1. the SIGNATURE — a `django.core.signing` token with a dedicated salt and a
     short max-age, so a link that was leaked or shared stops working on its own,
     checked BEFORE any database hit;
  2. tenant + location SCOPE — resolved through the same `location_sessions`
     helper the detail page uses, so a signed-in user at another site 404s exactly
     as they would on the detail page (the signature proves freshness, not
     authorisation — a token minted for a call this user CAN see must not serve a
     call they cannot);
  3. the token is bound to THIS session id — a valid token minted for a different
     call does not serve this one.

`FileResponse` streams the bytes and answers HTTP Range natively, so `<audio>`
scrubbing does not force a full download. `no-store` unconditionally — this is PII
audio, not a cacheable asset.
"""
import mimetypes

from django.conf import settings
from django.core import signing
from django.http import FileResponse
from django.views.decorators.cache import never_cache

from apps.calls.storage import open_recording, recording_exists
from apps.calls.views._common import *  # noqa: F401,F403
from apps.calls.views._helpers import location_sessions

# No module logger, and the reasoning is sharper here than anywhere else in this
# app: a recording fetch is the single most sensitive READ in the product, so the
# one thing that must never happen is a log line naming the caller's number, the
# storage path or the signed token. There is nothing safe to say at INFO that the
# request log does not already carry, so there is no logger to misuse.

__all__ = ['callsession_recording_view']


@login_required  # noqa: F405
@never_cache
@require_http_methods(['GET'])  # noqa: F405
def callsession_recording_view(request, pk):
    """Stream one call's recording, behind a fresh signature and the site's scope."""
    # 1. Signature first — no DB work for a stale or forged link. `BadSignature`
    #    is the base class, so it also covers `SignatureExpired`.
    try:
        payload = signing.loads(
            request.GET.get('sig', ''),
            salt=settings.RECORDING_ACCESS_SALT,  # noqa: F405
            max_age=settings.RECORDING_SIGNED_URL_TTL,  # noqa: F405
        )
    except signing.BadSignature:
        raise Http404  # noqa: F405

    # 2. Scope — the SAME queryset the detail page resolves through, so a foreign
    #    tenant or foreign location 404s here identically. A fresh signature is not
    #    authorisation.
    obj = get_object_or_404(location_sessions(request), pk=pk)  # noqa: F405

    # 3. The token must have been minted for THIS call.
    if payload.get('session_id') != obj.pk:
        raise Http404  # noqa: F405

    # An empty path is "no recording", not an error; a set-but-fileless path (every
    # seeded row on a fake-provider database) is a 404, never a 500.
    if not obj.recording_blob or not recording_exists(obj.recording_blob):
        raise Http404  # noqa: F405

    content_type = mimetypes.guess_type(obj.recording_blob)[0] or 'application/octet-stream'
    response = FileResponse(open_recording(obj.recording_blob), content_type=content_type)
    # `?dl=1` only flips the disposition header — it changes nothing about what is
    # authorised, so it is safe to leave off the signed payload.
    if request.GET.get('dl') == '1':
        response['Content-Disposition'] = 'attachment'
    response['Cache-Control'] = 'no-store'
    return response
