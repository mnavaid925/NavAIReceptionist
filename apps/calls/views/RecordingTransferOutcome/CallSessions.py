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

**HTTP Range is implemented here, not inherited.** Django 4.2's `FileResponse`
does NOT answer Range — a `Range:` request gets the whole 200 body, so seeking in
`<audio>` (which the transcript-synced waveform depends on) would re-download from
byte 0 on every scrub. `_ranged_response` parses a single byte range, streams just
that slice as a `206`, and advertises `Accept-Ranges`. `no-store` unconditionally —
this is PII audio, not a cacheable asset.
"""
import mimetypes

from django.conf import settings
from django.core import signing
from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.views.decorators.cache import never_cache

from apps.calls.storage import open_recording, recording_exists, recording_size
from apps.calls.views._common import *  # noqa: F401,F403
from apps.calls.views._helpers import location_sessions

# No module logger, and the reasoning is sharper here than anywhere else in this
# app: a recording fetch is the single most sensitive READ in the product, so the
# one thing that must never happen is a log line naming the caller's number, the
# storage path or the signed token. There is nothing safe to say at INFO that the
# request log does not already carry, so there is no logger to misuse.

__all__ = ['callsession_recording_view']

# How much of a range slice to read per chunk when streaming a 206 — the same
# 8 KiB `FileResponse` uses, so a partial fetch stays as memory-frugal as a full one.
_RANGE_CHUNK = 8192


def _parse_single_range(range_header, size):
    """Parse one `bytes=start-end` range against a known file size.

    Returns `(start, end)` inclusive, `None` for no/invalid/unsupported range (the
    caller then serves the whole file 200), or the string `'unsatisfiable'` for a
    syntactically valid range that falls outside the file (416). Only a SINGLE
    range is honoured — a multi-range request (`bytes=0-9,20-29`) falls back to the
    full body, which is a legal response and all an `<audio>` element ever needs.
    """
    if not range_header:
        return None
    units, _, spec = range_header.partition('=')
    if units.strip().lower() != 'bytes' or ',' in spec:
        return None
    start_s, sep, end_s = spec.strip().partition('-')
    if not sep:
        return None
    try:
        if not start_s:
            # `bytes=-N` — the trailing N bytes.
            length = int(end_s)
            if length <= 0:
                return 'unsatisfiable'
            start, end = max(0, size - length), size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
    except ValueError:
        return None
    # `end < start` is an inverted range (`bytes=10-5`) — RFC 9110 says treat it as
    # invalid, and letting it through would compute a NEGATIVE length and stamp a
    # `Content-Length: -4` a proxy could desync on. Rejected the same way an
    # out-of-bounds range is.
    if start >= size or end < start:
        return 'unsatisfiable'
    return start, min(end, size - 1)


def _stream_range(fh, start, length):
    """Yield `length` bytes from `fh` starting at `start`, in bounded chunks.

    `close()` in a `finally`, not after the loop: `<audio>` scrubbing aborts the
    previous in-flight range constantly, and an abort raises `GeneratorExit` at the
    suspended `yield` — which skips a post-loop close and leaks the file handle
    until GC. Under real scrubbing that is a slow descriptor exhaustion.
    """
    try:
        fh.seek(start)
        remaining = length
        while remaining > 0:
            chunk = fh.read(min(_RANGE_CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        fh.close()


def _ranged_response(request, path, content_type):
    """A `FileResponse` (200) or a `StreamingHttpResponse` (206) honouring Range.

    Django 4.2's `FileResponse` ignores `Range` entirely, so this implements it:
    without it, every `<audio>` scrub re-downloads from byte 0. A `416` carries the
    `Content-Range: bytes */<size>` an unsatisfiable range requires. `Accept-Ranges`
    is advertised on every path so a client knows seeking is available.
    """
    size = recording_size(path)
    parsed = _parse_single_range(request.headers.get('Range', ''), size)

    if parsed == 'unsatisfiable':
        response = HttpResponse(status=416)
        response['Content-Range'] = f'bytes */{size}'
        response['Accept-Ranges'] = 'bytes'
        return response

    if parsed is None:
        response = FileResponse(open_recording(path), content_type=content_type)
        response['Accept-Ranges'] = 'bytes'
        return response

    start, end = parsed
    length = end - start + 1
    response = StreamingHttpResponse(
        _stream_range(open_recording(path), start, length),
        status=206,
        content_type=content_type,
    )
    response['Content-Range'] = f'bytes {start}-{end}/{size}'
    response['Content-Length'] = str(length)
    response['Accept-Ranges'] = 'bytes'
    return response


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

    # 2. Scope — the SAME helper the detail page resolves through, so a foreign
    #    tenant or foreign location 404s here identically. A fresh signature is not
    #    authorisation. `.prefetch_related(None)` drops the `booked_appointments`
    #    prefetch that helper carries for the PAGE — this endpoint renders no
    #    template and reads only `recording_blob`, so the prefetch would be a wasted
    #    query on every byte-range request. The tenant+location filter — the part
    #    that matters — is untouched, so there is still exactly one audited scope.
    obj = get_object_or_404(  # noqa: F405
        location_sessions(request).prefetch_related(None), pk=pk,
    )

    # 3. The token must have been minted for THIS call.
    if payload.get('session_id') != obj.pk:
        raise Http404  # noqa: F405

    # An empty path is "no recording", not an error; a set-but-fileless path (every
    # seeded row on a fake-provider database) is a 404, never a 500.
    if not obj.recording_blob or not recording_exists(obj.recording_blob):
        raise Http404  # noqa: F405

    content_type = mimetypes.guess_type(obj.recording_blob)[0] or 'application/octet-stream'
    try:
        response = _ranged_response(request, obj.recording_blob, content_type)
    except FileNotFoundError:
        # The retention job (or a manual purge) deleted the file between the
        # existence check above and the open here. A gone recording is a 404, and
        # the check-then-open race is exactly why `open_recording`'s docstring
        # promises this is catchable rather than a 500.
        raise Http404  # noqa: F405

    # `?dl=1` only flips the disposition header — it changes nothing about what is
    # authorised, so it is safe to leave off the signed payload.
    if request.GET.get('dl') == '1':
        response['Content-Disposition'] = 'attachment'
    response['Cache-Control'] = 'no-store'
    return response
