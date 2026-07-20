"""Appointment routes (sub-module 4.3).

ORDER IS BEHAVIOUR. `appointments/slots/` and `appointments/book/` are literals
and MUST precede `appointments/<int:pk>/`, or Django would try to parse "slots"
as a primary key. Checked against the whole concatenated list in
`apps/scheduling/urls/__init__.py`, not just this file.
"""
from django.urls import path

from apps.scheduling import views

__all__ = ['urlpatterns']

urlpatterns = [
    path('appointments/', views.appointment_list_view, name='appointment_list'),
    path('appointments/create/', views.appointment_create_view,
         name='appointment_create'),
    # -- literals, ahead of <int:pk> --------------------------------------- #
    path('appointments/slots/', views.appointment_slots_view,
         name='appointment_slots'),
    path('appointments/book/', views.appointment_book_view,
         name='appointment_book'),
    # -- member routes ------------------------------------------------------ #
    path('appointments/<int:pk>/', views.appointment_detail_view,
         name='appointment_detail'),
    path('appointments/<int:pk>/edit/', views.appointment_edit_view,
         name='appointment_edit'),
    path('appointments/<int:pk>/delete/', views.appointment_delete_view,
         name='appointment_delete'),
    path('appointments/<int:pk>/reschedule/', views.appointment_reschedule_view,
         name='appointment_reschedule'),
    path('appointments/<int:pk>/cancel/', views.appointment_cancel_view,
         name='appointment_cancel'),
    # `<str:new_status>` is the only non-integer converter in the whole
    # concatenated scheduling URLconf, and it sits BEHIND the literal `mark/`
    # segment — so it cannot swallow `edit/`, `delete/`, `reschedule/` or
    # `cancel/`, all of which are three segments deep where this is four. The
    # view allow-lists the captured value; matching the route is not authorising
    # the status.
    path('appointments/<int:pk>/mark/<str:new_status>/', views.appointment_mark_view,
         name='appointment_mark'),
]
