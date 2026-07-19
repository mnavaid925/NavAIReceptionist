"""URLconf for Module 2 — Agent Setup & Telephony.

A FLAT module rather than a package. CLAUDE.md's backend rule 10 says to split
when a file is hard to navigate, not for symmetry — this app has ONE model and
nine literal routes, so four `urls/<SubModule>/` folders holding one `path()`
each would be harder to read, not easier.

**No route takes a pk.** Every view resolves its row from `request.tenant` and
`request.location`, so there is no id for a caller to tamper with and no
cross-tenant or cross-location IDOR surface on this module at all. That is why
there is no `crud()` block here.
"""
from django.urls import path

from apps.agents import views

app_name = 'agents'

urlpatterns = [
    # -- 2.1 Per-Location Agent Configuration ----------------------------- #
    path('', views.agent_setup_view, name='agent_setup'),
    path('edit/', views.agent_setup_edit_view, name='agent_setup_edit'),
    path('preview/', views.agent_preview_view, name='agent_preview'),

    # -- 2.2 Twilio Connection -------------------------------------------- #
    path('twilio/', views.twilio_connection_view, name='twilio_connection'),
    path('twilio/edit/', views.twilio_connection_edit_view, name='twilio_connection_edit'),
    path('twilio/check/', views.twilio_check_view, name='twilio_check'),

    # -- 2.3 Transfer Settings -------------------------------------------- #
    path('transfer/', views.transfer_settings_view, name='transfer_settings'),
    path('transfer/edit/', views.transfer_settings_edit_view, name='transfer_settings_edit'),

    # -- 2.4 Test Call ----------------------------------------------------- #
    path('test-call/', views.test_call_view, name='test_call'),
]
