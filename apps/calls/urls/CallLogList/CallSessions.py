"""Call session routes (sub-module 5.1).

The list is mounted at the app's ROOT (`''`), not under a `calls/` prefix: the
whole app is already included under a prefix in the root URLconf, so a second one
would produce `calls/calls/`. That makes the list route empty, which cannot
shadow anything, and the detail route the only pattern in the app.

ORDER IS BEHAVIOUR. There is no literal route to keep ahead of `<int:pk>` yet —
5.1 ships exactly two patterns and this app has no other routes at all, so there
is no collision to check against today. That changes the moment 5.2-5.4 land:
their transcript, cost and recording surfaces all hang off the SAME `<int:pk>`
call, so every one of them adds a literal trailing segment that must be checked
against the whole concatenated list in `apps/calls/urls/__init__.py` — and a
future collection-level literal (an `export/` say) must be declared ABOVE
`<int:pk>/`, or Django will try to parse "export" as a primary key.
"""
from django.urls import path

from apps.calls import views

__all__ = ['urlpatterns']

urlpatterns = [
    path('', views.callsession_list_view, name='callsession_list'),
    # -- member routes ------------------------------------------------------ #
    path('<int:pk>/', views.callsession_detail_view, name='callsession_detail'),
]
