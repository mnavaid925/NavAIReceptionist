"""Contact directory routes (sub-module 4.1).

ORDER IS BEHAVIOUR. Django resolves first-match-wins, so `contacts/create/` sits
ahead of `contacts/<int:pk>/` — reversed, the literal would be swallowed and
`create` would be parsed as a primary key.
"""
from django.urls import path

from apps.scheduling import views

__all__ = ['urlpatterns']

urlpatterns = [
    path('contacts/', views.contact_list_view, name='contact_list'),
    path('contacts/create/', views.contact_create_view, name='contact_create'),
    path('contacts/<int:pk>/', views.contact_detail_view, name='contact_detail'),
    path('contacts/<int:pk>/edit/', views.contact_edit_view, name='contact_edit'),
    path('contacts/<int:pk>/delete/', views.contact_delete_view, name='contact_delete'),
    # Erasure, not deletion — the path that still works once Appointment.contact
    # (PROTECT) makes a contact with bookings undeletable.
    path('contacts/<int:pk>/forget/', views.contact_forget_view, name='contact_forget'),
]
