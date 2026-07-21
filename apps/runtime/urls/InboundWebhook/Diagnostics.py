"""The runtime diagnostics route — 3.1's observable, navigable surface.

Mounted at ``diagnostics/`` (public ``/runtime/diagnostics/``) and pointed at by
``LIVE_LINKS["3.1"]`` in ``apps/accounts/navigation.py``, so the sub-module shows
as Live in the sidebar. A signed-in user's page, unlike the webhook next to it.
"""
from django.urls import path

from apps.runtime import views

__all__ = ['urlpatterns']

urlpatterns = [
    path('diagnostics/', views.runtime_diagnostics_view, name='diagnostics'),
]
