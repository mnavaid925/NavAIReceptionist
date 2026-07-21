"""URLconf for Module 5 — Call Logs.

A PACKAGE rather than the flat module `tenants` and `accounts` use. This app owns
one entity but is headed for several action routes across sub-modules 5.2–5.4 on
that same entity (transcript, costs, recording, transfer outcome), so each
sub-module contributes its own `urlpatterns` list and this file concatenates
them.

ORDER IS BEHAVIOUR ACROSS THE WHOLE CONCATENATED LIST, not just within one file.
Django resolves first-match-wins, so a greedy pattern added by a later sub-module
can swallow an earlier one's literal route. Because every route in this app hangs
off the same `<int:pk>` call, that risk is higher here than elsewhere: check any
new `<str:...>` segment against everything below, not only against its own
module.
"""
from apps.calls.urls.CallDetailTranscript.CallSessions import (
    urlpatterns as transcript_urlpatterns,
)
from apps.calls.urls.CallLogList.CallSessions import (
    urlpatterns as call_session_urlpatterns,
)
from apps.calls.urls.RecordingTransferOutcome.CallSessions import (
    urlpatterns as recording_urlpatterns,
)

app_name = 'calls'

# -- 5.1 Call Log List ------------------------------------------------------ #
# The list at the root and one `<int:pk>` detail. Kept FIRST so its literal `''`
# and its bare `<int:pk>/` are matched before anything a later sub-module hangs
# off the same pk.
urlpatterns = list(call_session_urlpatterns)

# -- 5.2 Call Detail & Transcript ------------------------------------------- #
# `<int:pk>/print/` — a literal `print/` suffix after the pk. It cannot be
# shadowed by 5.1's `<int:pk>/` (IntConverter ends at the trailing slash), and it
# shadows nothing above it. A future member route with a greedy `<str:...>` after
# the pk must be checked against THIS route as well as 5.1's.
urlpatterns += list(transcript_urlpatterns)

# -- 5.4 Recording & Transfer Outcome --------------------------------------- #
# `<int:pk>/recording/` — same literal-suffix-after-the-pk shape as 5.2's print
# route, and safe for the same reason. The freshness token rides the query string
# (`?sig=…`), so it never touches URL resolution.
urlpatterns += list(recording_urlpatterns)
