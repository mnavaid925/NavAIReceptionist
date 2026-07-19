"""Service catalogue routes (sub-module 4.2).

Literals ahead of `<int:pk>`, as everywhere — `services/create/` would otherwise
be parsed as a primary key.
"""
from django.urls import path

from apps.scheduling import views

__all__ = ['urlpatterns']

urlpatterns = [
    path('services/', views.service_list_view, name='service_list'),
    path('services/create/', views.service_create_view, name='service_create'),
    path('services/<int:pk>/', views.service_detail_view, name='service_detail'),
    path('services/<int:pk>/edit/', views.service_edit_view, name='service_edit'),
    path('services/<int:pk>/delete/', views.service_delete_view, name='service_delete'),
]
