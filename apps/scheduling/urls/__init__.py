"""URLconf for Module 4 — Calendar & Bookings.

A PACKAGE rather than the flat module `tenants` and `accounts` use, because this
app is headed for five entities across sub-modules 4.1–4.5. Each sub-module
contributes its own `urlpatterns` list and this file concatenates them.

ORDER IS BEHAVIOUR ACROSS THE WHOLE CONCATENATED LIST, not just within one file.
Django resolves first-match-wins, so a greedy pattern added by a later sub-module
can swallow an earlier one's literal route. Check any new `<str:...>` route
against everything below, not only against its own module.
"""
from apps.scheduling.urls.ContactDirectory.Contacts import (
    urlpatterns as contact_directory_urlpatterns,
)
from apps.scheduling.urls.ServicesResources.Resources import (
    urlpatterns as resource_urlpatterns,
)
from apps.scheduling.urls.ServicesResources.Services import (
    urlpatterns as service_urlpatterns,
)

app_name = 'scheduling'

# -- 4.1 Contact Directory ------------------------------------------------- #
urlpatterns = list(contact_directory_urlpatterns)

# -- 4.2 Services & Resources ---------------------------------------------- #
# Distinct path prefixes (`contacts/`, `services/`, `resources/`), so nothing
# here can shadow 4.1. Check that again before adding any `<str:...>` route.
urlpatterns += service_urlpatterns
urlpatterns += resource_urlpatterns
