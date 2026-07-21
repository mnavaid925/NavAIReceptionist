"""View helpers for Module 3's observable surfaces.

The runtime diagnostics page reads the SAME ``calls.CallSession`` rows the Call Log
owns, scoped to the active location. Rather than write a second
tenant+location filter over ``CallSession`` — a second place for a cross-location
leak to hide, over rows that carry caller PII — this delegates to the single
audited scoping surface in ``apps.calls.views._helpers.location_sessions``, which
already returns ``.none()`` when no location is active. Runtime just names and
slices it.
"""
from apps.calls.views._helpers import location_sessions

__all__ = ['location_sessions', 'recent_location_sessions']


def recent_location_sessions(request, limit=15):
    """The newest ``limit`` call sessions at the active location.

    Tenant AND location scoped via ``location_sessions`` (empty when no location
    is active), newest first. ``limit`` bounds the diagnostics table so the page
    cost does not grow with a busy location's call volume.
    """
    return location_sessions(request).order_by('-created_at')[:limit]
