"""The printable transcript view (sub-module 5.2).

5.2 adds NO model and NO migration. The session header, the transcript panel and
the analysis panel it introduces are all edits to `detail.html` over JSON columns
5.1 already shipped — Invariant 2, one row, no table. The only Python this
sub-module needs is this one view: a second, print-oriented rendering of the same
transcript.

**It is PII-identical to the detail page, and scoped identically on purpose.** A
transcript is PII by definition, so this route is `@login_required`, tenant- AND
location-scoped through the very same `location_sessions` helper the detail view
uses, addressed by a plain incrementing `<int:pk>` — never a shareable token,
never a guessable public path, never a server-generated durably-stored PDF.
Printing is the browser's job over the `@media print` rules already in
`theme.css`; nothing here writes a file.
"""
from django.views.decorators.cache import never_cache

from apps.calls.views._common import *  # noqa: F401,F403
# Reused, not redefined. A second tenant+location-scoping helper over the same
# table would be a second place for a scoping bug to hide — so both this page and
# 5.1's list/detail pages pull the ONE `location_sessions` from `views/_helpers`.
from apps.calls.views._helpers import location_sessions

__all__ = ['callsession_transcript_print_view']


# `never_cache` for the same reason as the detail page — this is the same
# transcript, on a page whose whole purpose is to be printed and then left lying
# around. no-store keeps it out of the back-forward cache after logout.
@never_cache
@login_required  # noqa: F405
@require_http_methods(['GET'])  # noqa: F405
def callsession_transcript_print_view(request, pk):
    """A clean, printable transcript for records and disputes.

    `get_object_or_404(location_sessions(request), pk=pk)` — the identical
    scoping to `callsession_detail_view`, so a pk from another tenant or another
    location 404s here exactly as it does there. There is no wider door: this
    page shows nothing the detail page would not, to nobody the detail page would
    not.
    """
    obj = get_object_or_404(location_sessions(request), pk=pk)  # noqa: F405
    return render(request, 'calls/transcript/transcript_print.html', {  # noqa: F405
        'obj': obj,
    })
