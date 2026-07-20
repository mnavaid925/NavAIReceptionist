"""The printable-transcript route (sub-module 5.2).

One member route, `<int:pk>/print/`, hanging off the same call the detail page
does. It is a LITERAL suffix (`print/`) after the pk segment, and Django's
`IntConverter` requires the `<int:pk>` to end at its trailing slash — so
5.1's bare `<int:pk>/` cannot swallow `<pk>/print/` regardless of which module's
`urlpatterns` is concatenated first. The general first-match-wins rule still
governs anything a LATER sub-module adds, so a future `<pk>/<str:...>/` segment
must be checked against this route too, not only against its own file.
"""
from django.urls import path

from apps.calls import views

__all__ = ['urlpatterns']

urlpatterns = [
    path('<int:pk>/print/', views.callsession_transcript_print_view,
         name='callsession_transcript_print'),
]
