"""Calendar routes (sub-module 4.4).

`calendar/week/` is a literal and sits ahead of nothing that could swallow it —
there is no `<int:pk>` in this sub-module at all, because a calendar addresses a
DATE through the query string rather than a primary key in the path. That keeps
`?date=`, `?by=` and `?column=` composable in one URL, which is what the
prev/next/today links and the column toggle need.
"""
from django.urls import path

from apps.scheduling import views

__all__ = ['urlpatterns']

urlpatterns = [
    path('calendar/', views.calendar_day_view, name='calendar_day'),
    path('calendar/week/', views.calendar_week_view, name='calendar_week'),
]
