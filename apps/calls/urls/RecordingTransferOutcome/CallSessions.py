"""The recording serve route (sub-module 5.4).

One member route, `<int:pk>/recording/`, hanging off the same call the detail page
does. The freshness token rides the QUERY STRING (`?sig=…`), not a path segment —
a query string never participates in URL resolution, so this route stays a plain
`<int:pk>/recording/` literal with none of the greedy-`<str:token>` ordering risk
this app's URLconf docstring warns about. The literal `recording/` suffix cannot
be swallowed by 5.1's bare `<int:pk>/` — `IntConverter` ends at the trailing slash
— exactly as 5.2's `<int:pk>/print/` is safe.
"""
from django.urls import path

from apps.calls import views

__all__ = ['urlpatterns']

urlpatterns = [
    path('<int:pk>/recording/', views.callsession_recording_view,
         name='callsession_recording'),
]
