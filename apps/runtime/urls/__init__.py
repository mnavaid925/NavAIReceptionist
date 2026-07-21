"""URLconf for Module 3 — Call Runtime.

A PACKAGE, like every non-foundation app: each sub-module contributes its own
entity ``urlpatterns`` list and this file sets ``app_name`` and concatenates them.

ORDER IS BEHAVIOUR across the whole concatenated list (Django resolves
first-match-wins), not just within one file. 3.1 mounts two literal routes
(``voice/`` and ``diagnostics/``) that cannot collide; a later sub-module adding a
greedy ``<str:…>`` segment must be checked against every route here, not only its
own module's.
"""
from apps.runtime.urls.InboundWebhook.Diagnostics import (
    urlpatterns as diagnostics_urlpatterns,
)
from apps.runtime.urls.InboundWebhook.Webhook import (
    urlpatterns as webhook_urlpatterns,
)

app_name = 'runtime'

# -- 3.1 Inbound Webhook & Call Resolution ---------------------------------- #
# The carrier webhook and the operator diagnostics page. Both literal, no
# collision; the webhook is POST-only + signature-verified, the diagnostics page
# is a login-gated GET.
urlpatterns = list(webhook_urlpatterns)
urlpatterns += list(diagnostics_urlpatterns)
