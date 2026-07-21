"""Private storage for call recordings (sub-module 5.4).

`recording_blob` on a `CallSession` is a path INTO this storage — never a URL,
never a path under `MEDIA_ROOT`. `MEDIA_ROOT` is web-servable at `MEDIA_URL`, so a
recording under it would be a public, guessable link to caller PII; this storage
roots at `PRIVATE_MEDIA_ROOT` instead and is reached only through the signed,
tenant+location-scoped serve view.

`base_url=None` is deliberate: it makes `.url()` raise rather than mint a
public-looking link, so nothing can accidentally route around the signed view.
"""
import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateRecordingStorage(FileSystemStorage):
    """A `FileSystemStorage` that genuinely refuses to mint a URL.

    Passing `base_url=None` is NOT enough: Django's `FileSystemStorage.base_url`
    falls back to `settings.MEDIA_URL` when its own is None, so `.url()` would hand
    back a `/media/…`-shaped link — public-looking, and exactly the accidental
    exposure this storage exists to prevent. Overriding `url()` to raise makes the
    "served only through the signed view, never a URL" guarantee real rather than
    assumed, so any future code that reaches for `.url()` fails loudly instead of
    leaking a path.
    """

    def url(self, name):
        raise ValueError(
            'Call recordings are private — serve them through '
            'calls:callsession_recording, never a storage URL.'
        )


# One shared instance — rooted outside MEDIA_ROOT so nothing static-serves it.
recording_storage = PrivateRecordingStorage(location=settings.PRIVATE_MEDIA_ROOT)


def recording_exists(path):
    """Whether real bytes sit behind a `recording_blob` path.

    The path is data on a row Module 3 (unbuilt) writes, so it may be empty, or
    set to a file that a `PROVIDER_MODE=fake` database never actually produced —
    6 of the 11 seeded rows are exactly that. Never raises: an empty or malformed
    path is simply "no recording", which is a `False`, not an error, and a
    traversal attempt (`..`) is caught by the containment check rather than
    escaping the private root.
    """
    if not path:
        return False
    try:
        # `FileSystemStorage.exists` joins onto `location` and calls `os.path.exists`.
        # Guard the join against an absolute or `..`-bearing path escaping the
        # private root — the serve view already scopes WHICH session, but a path
        # is stored data, and stored data is not trusted to stay inside its box.
        full = os.path.realpath(os.path.join(settings.PRIVATE_MEDIA_ROOT, path))
        root = os.path.realpath(settings.PRIVATE_MEDIA_ROOT)
        if os.path.commonpath([full, root]) != root:
            return False
        return recording_storage.exists(path)
    except (ValueError, OSError):
        return False


def open_recording(path):
    """An open binary file handle for `FileResponse`, or raise `FileNotFoundError`.

    Callers check `recording_exists` first; this is the second line, so a race
    (the retention job deletes the file between the check and the open) surfaces
    as a catchable `FileNotFoundError` rather than a 500.
    """
    return recording_storage.open(path, 'rb')
