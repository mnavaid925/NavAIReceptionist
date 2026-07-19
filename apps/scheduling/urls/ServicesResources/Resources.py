"""Resource routes (sub-module 4.2)."""
from django.urls import path

from apps.scheduling import views

__all__ = ['urlpatterns']

urlpatterns = [
    path('resources/', views.resource_list_view, name='resource_list'),
    path('resources/create/', views.resource_create_view, name='resource_create'),
    path('resources/<int:pk>/', views.resource_detail_view, name='resource_detail'),
    path('resources/<int:pk>/edit/', views.resource_edit_view, name='resource_edit'),
    path('resources/<int:pk>/delete/', views.resource_delete_view,
         name='resource_delete'),
]
