"""View package for Module 0 — Accounts & Access.

Foundation apps are FLAT: entity files sit at the package root.

Every view MUST be re-exported here — the URLconf refers to them as
`views.<name>`, so a view that is not re-exported fails with an AttributeError at
import time.
"""
from apps.accounts.views.Auth import (
    login_view,
    logout_view,
    password_reset_confirm_view,
    password_reset_request_view,
)
from apps.accounts.views.Dashboard import dashboard_view

__all__ = [
    # 0.1 — Authentication & Session.
    'login_view',
    'logout_view',
    'password_reset_request_view',
    'password_reset_confirm_view',
    'dashboard_view',
]
