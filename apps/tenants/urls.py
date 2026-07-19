"""URLconf for Module 1 — Business & Locations.

A FLAT module, not a package, matching `accounts` — a compact `crud()` factory
beats per-entity `urlpatterns` lists with duplicated `path()` calls.

ORDER IS BEHAVIOUR. Django resolves first-match-wins, so every literal route sits
ahead of the `<int:pk>` routes that could swallow it. `crud()` emits its own
literals before its member routes for the same reason.
"""
from django.urls import path

from apps.tenants import views

app_name = 'tenants'


def crud(base, name, view_module=views):
    """The five standard CRUD routes for one entity.

        crud('locations', 'location')  ->  location_list / location_create
                                           location_detail / location_edit
                                           location_delete

    `base` is the URL path segment (plural), `name` the url-name stem (singular).
    Views are resolved as `<name>_list_view`, `<name>_create_view`, and so on.
    """
    def view(suffix):
        return getattr(view_module, f'{name}_{suffix}_view')

    return [
        path(f'{base}/', view('list'), name=f'{name}_list'),
        path(f'{base}/create/', view('create'), name=f'{name}_create'),
        path(f'{base}/<int:pk>/', view('detail'), name=f'{name}_detail'),
        path(f'{base}/<int:pk>/edit/', view('edit'), name=f'{name}_edit'),
        path(f'{base}/<int:pk>/delete/', view('delete'), name=f'{name}_delete'),
    ]


urlpatterns = [
    # -- 1.1 Business Settings -------------------------------------------- #
    # No pk: there is one Tenant per business and request.tenant IS it.
    path('business/', views.business_settings_view, name='business_settings'),
    path('business/edit/', views.business_settings_edit_view, name='business_settings_edit'),

    # -- 1.3 Staff & Location Assignment ---------------------------------- #
    path('staff/', views.staff_locations_view, name='staff_locations'),
    path('staff/<int:pk>/provider/', views.toggle_provider_view, name='toggle_provider'),

    # -- 1.4 Provider Working Hours --------------------------------------- #
    path('hours/', views.provider_hours_report_view, name='provider_hours_report'),
    path('hours/<int:pk>/<int:location_pk>/', views.provider_hours_view,
         name='provider_hours'),
]

# -- 1.2 Location Directory ----------------------------------------------- #
# After the literals above, so `locations/create/` is never eaten by `<int:pk>`.
urlpatterns += crud('locations', 'location')
