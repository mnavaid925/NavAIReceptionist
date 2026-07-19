"""View package for Module 4 — Calendar & Bookings.

Re-exports every view this app owns. The URLconf resolves views as
`views.<name>_<suffix>_view`, so a view missing from this block fails with
`AttributeError` the moment Django builds the URL table — at startup, not on
first request.

Sub-module folders, in build order:

* `ContactDirectory/`   — 4.1  contact CRUD
* `ServicesResources/`  — 4.2  service CRUD, resource CRUD
"""
from apps.scheduling.views.ContactDirectory.Contacts import (
    contact_create_view,
    contact_delete_view,
    contact_detail_view,
    contact_edit_view,
    contact_forget_view,
    contact_list_view,
)
from apps.scheduling.views.ServicesResources.Resources import (
    resource_create_view,
    resource_delete_view,
    resource_detail_view,
    resource_edit_view,
    resource_list_view,
)
from apps.scheduling.views.ServicesResources.Services import (
    service_create_view,
    service_delete_view,
    service_detail_view,
    service_edit_view,
    service_list_view,
)

__all__ = [
    'contact_list_view',
    'contact_create_view',
    'contact_detail_view',
    'contact_edit_view',
    'contact_delete_view',
    'contact_forget_view',
    'service_list_view',
    'service_create_view',
    'service_detail_view',
    'service_edit_view',
    'service_delete_view',
    'resource_list_view',
    'resource_create_view',
    'resource_detail_view',
    'resource_edit_view',
    'resource_delete_view',
]
