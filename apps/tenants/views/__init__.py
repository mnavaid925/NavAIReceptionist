"""View package for Module 1 — Business & Locations.

Foundation apps are FLAT: entity files sit at the package root.

Every view MUST be re-exported here — the URLconf refers to them as
`views.<name>`, and the `crud()` factory resolves them by attribute, so a view
that is not re-exported fails with an AttributeError at import time.
"""
from apps.tenants.views.Business import (
    business_settings_edit_view,
    business_settings_view,
)
from apps.tenants.views.Location import (
    location_create_view,
    location_delete_view,
    location_detail_view,
    location_edit_view,
    location_list_view,
)
from apps.tenants.views.StaffAssignment import (
    staff_locations_view,
    toggle_provider_view,
)
from apps.tenants.views.WorkingHours import (
    provider_hours_report_view,
    provider_hours_view,
)

__all__ = [
    # 1.1 — Business Settings.
    'business_settings_view',
    'business_settings_edit_view',
    # 1.2 — Location Directory.
    'location_list_view',
    'location_create_view',
    'location_detail_view',
    'location_edit_view',
    'location_delete_view',
    # 1.3 — Staff & Location Assignment.
    'staff_locations_view',
    'toggle_provider_view',
    # 1.4 — Provider Working Hours.
    'provider_hours_view',
    'provider_hours_report_view',
]
