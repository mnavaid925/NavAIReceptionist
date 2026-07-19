"""Shared form toolkit for Module 4 — Calendar & Bookings.

Re-exports the cross-app bases from `apps.accounts.forms._common` rather than
redefining them, so `TenantModelForm`'s tenant-stamping and FK-narrowing exist
once in the project. Entity modules pull it with
`from apps.scheduling.forms._common import *`.
"""
from apps.accounts.forms._common import *  # noqa: F401,F403
from apps.accounts.forms._common import __all__ as _base_all

__all__ = list(_base_all)
