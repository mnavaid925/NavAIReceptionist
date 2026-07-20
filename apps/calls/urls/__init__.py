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
from apps.calls.urls.CallLogList.CallSessions import (
    urlpatterns as call_session_urlpatterns,
)

app_name = 'calls'

# -- 5.1 Call Log List ------------------------------------------------------ #
# The only patterns in the app: the list at the root and one `<int:pk>` detail.
# Nothing here can shadow anything, because there is nothing else here yet — but
# the entity module's own docstring records what a later sub-module must check.
urlpatterns = list(call_session_urlpatterns)
