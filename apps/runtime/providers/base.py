"""``PROVIDER_MODE`` resolution and the one rule every adapter obeys.

``PROVIDER_MODE`` ∈ ``fake | sandbox | live`` (validated and clamped in
``config/settings.py``). The rule, stated once here so no adapter re-derives it:

* **``fake`` is the default** for dev, tests and seeders.
* Anything that is **not exactly** ``'live'`` must fail SAFE to the fake path —
  never toward a carrier. An unrecognised mode is a fake mode.
* A live adapter must **refuse to initialise** unless ``PROVIDER_MODE == 'live'``,
  and live additionally requires real credentials — missing credentials in live
  mode is the hard failure, never a silent fall back to the fake.

3.1 has no live carrier call to make (the voice webhook only returns TwiML, which
places nothing), so it uses none of the guards below directly — but the seam is
declared here so 3.2's media path and 3.4's transfer redirect inherit one
definition of "are we allowed to touch a real provider" rather than re-inventing
it at each call site. Mirrors the already-shipped ``apps/agents/telephony.py``.
"""
from django.conf import settings

__all__ = ['LiveModeError', 'active_mode', 'is_live', 'require_live']


class LiveModeError(RuntimeError):
    """Raised when a live-only adapter is constructed outside live mode.

    Structural guard, checked at construction rather than per call, so an
    instance that could reach a carrier cannot exist in a non-live process at
    all — the same posture as ``LiveTelephonyBackend.__init__``.
    """


def active_mode():
    """The resolved provider mode, always one of ``fake`` / ``sandbox`` / ``live``.

    Reads from settings, which has already clamped an unknown value to ``fake``;
    this re-clamps defensively so a monkeypatched or stale setting still fails
    safe rather than toward the carrier.
    """
    mode = (getattr(settings, 'PROVIDER_MODE', 'fake') or 'fake').strip().lower()
    return mode if mode in {'fake', 'sandbox', 'live'} else 'fake'


def is_live():
    """True only when ``PROVIDER_MODE`` is EXACTLY ``'live'``."""
    return active_mode() == 'live'


def require_live(what='this operation'):
    """Assert live mode or raise. The gate a live adapter calls before reaching out.

    ``what`` names the operation in the error so a stack trace says which live
    call was blocked. Never bypassed by ``DEBUG`` or a test flag — a path that can
    reach a real provider from a test or a seeder is a Critical defect.
    """
    if not is_live():
        raise LiveModeError(
            f'{what} requires PROVIDER_MODE == "live" (currently '
            f'"{active_mode()}"). This guard stops a test, a seeder or a dev run '
            'from reaching a real provider.'
        )
