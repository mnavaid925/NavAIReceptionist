"""View package for Module 0 — Accounts & Access.

Foundation apps are FLAT: entity files sit at the package root.

Every view MUST be re-exported here — the URLconf refers to them as
`views.<name>`, and the `crud()` factory looks them up by attribute, so a view
that is not re-exported fails with an AttributeError at import time.
"""
from apps.accounts.views.Auth import (
    change_email_request_view,
    change_password_view,
    email_change_confirm_view,
    login_view,
    logout_view,
    password_reset_confirm_view,
    password_reset_request_view,
)
from apps.accounts.views.Dashboard import dashboard_view
from apps.accounts.views.LocationSwitcher import switch_location_view
from apps.accounts.views.Users import (
    profile_view,
    user_create_view,
    user_delete_view,
    user_detail_view,
    user_edit_view,
    user_list_view,
)

__all__ = [
    # 0.1 — Authentication & Session.
    'login_view',
    'logout_view',
    'password_reset_request_view',
    'password_reset_confirm_view',
    'dashboard_view',
    # 0.2 — Credential Management.
    'change_password_view',
    'change_email_request_view',
    'email_change_confirm_view',
    # 0.3 — User Profile & Directory.
    'user_list_view',
    'user_create_view',
    'user_detail_view',
    'user_edit_view',
    'user_delete_view',
    'profile_view',
    # 0.4 — Active Location Switcher.
    'switch_location_view',
]
