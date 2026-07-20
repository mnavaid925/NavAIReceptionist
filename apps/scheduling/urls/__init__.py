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
from apps.scheduling.urls.Bookings.Appointments import (
    urlpatterns as appointment_urlpatterns,
)
from apps.scheduling.urls.CalendarViews.Calendar import (
    urlpatterns as calendar_urlpatterns,
)
from apps.scheduling.urls.CallbackRequests.CallbackRequests import (
    urlpatterns as callback_request_urlpatterns,
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

# -- 4.3 Availability & Booking -------------------------------------------- #
# `appointments/` prefix, distinct from contacts/services/resources. Its own
# module keeps `slots/` and `book/` ahead of `<int:pk>`; nothing above uses a
# greedy converter that could swallow them.
urlpatterns += appointment_urlpatterns

# -- 4.4 Calendar Views ----------------------------------------------------- #
# `calendar/` prefix, distinct from everything above. No pk routes at all — a
# calendar addresses a date through the query string.
urlpatterns += calendar_urlpatterns

# -- 4.5 Bookings List & Callback Requests --------------------------------- #
# `callbacks/` prefix, distinct from every prefix above. Its own module keeps
# `create/` ahead of `<int:pk>`; nothing above uses a greedy converter that could
# swallow it. The sub-module's appointment enrichment adds no prefix of its own —
# `appointments/<int:pk>/mark/<str:new_status>/` is a member route inside 4.3's
# list, where the `mark/` literal segment already distinguishes it.
urlpatterns += callback_request_urlpatterns
