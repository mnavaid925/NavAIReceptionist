"""View package for Module 4 — Calendar & Bookings.

Re-exports every view this app owns. The URLconf resolves views as
`views.<name>_<suffix>_view`, so a view missing from this block fails with
`AttributeError` the moment Django builds the URL table — at startup, not on
first request.

Sub-module folders, in build order:

* `ContactDirectory/`  — 4.1  contact CRUD
"""
from apps.scheduling.views.ContactDirectory.Contacts import (
    contact_create_view,
    contact_delete_view,
    contact_detail_view,
    contact_edit_view,
    contact_forget_view,
    contact_list_view,
)

__all__ = [
    'contact_list_view',
    'contact_create_view',
    'contact_detail_view',
    'contact_edit_view',
    'contact_delete_view',
    'contact_forget_view',
]
