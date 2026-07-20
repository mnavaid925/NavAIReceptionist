"""Callback request routes (sub-module 4.5).

ORDER IS BEHAVIOUR. `callbacks/create/` is a literal and MUST precede
`callbacks/<int:pk>/`, or Django would try to parse "create" as a primary key.
Checked against the whole concatenated list in `apps/scheduling/urls/__init__.py`,
not just this file: `callbacks/` is distinct from `contacts/`, `services/`,
`resources/`, `appointments/` and `calendar/`, and nothing above uses a greedy
`<str:...>` converter that could swallow it.
"""
from django.urls import path

from apps.scheduling import views

__all__ = ['urlpatterns']

urlpatterns = [
    path('callbacks/', views.callbackrequest_list_view,
         name='callbackrequest_list'),
    # -- literal, ahead of <int:pk> ----------------------------------------- #
    path('callbacks/create/', views.callbackrequest_create_view,
         name='callbackrequest_create'),
    # -- member routes ------------------------------------------------------ #
    path('callbacks/<int:pk>/', views.callbackrequest_detail_view,
         name='callbackrequest_detail'),
    path('callbacks/<int:pk>/edit/', views.callbackrequest_edit_view,
         name='callbackrequest_edit'),
    path('callbacks/<int:pk>/resolve/', views.callbackrequest_resolve_view,
         name='callbackrequest_resolve'),
    path('callbacks/<int:pk>/delete/', views.callbackrequest_delete_view,
         name='callbackrequest_delete'),
]
