"""Shared model toolkit for Module 4 — Calendar & Bookings.

Re-exports the cross-app abstract bases from `apps.accounts.models._base` rather
than redefining them, so the `tenant` / `location` FK declaration exists exactly
once in the project. Entity modules pull it with
`from apps.scheduling.models._base import *`.

Note which base each of this module's five models takes, because it is not
uniform: `Contact` is `TenantOwned` (a caller belongs to the business and may
book at any of its sites), while `Resource`, `Appointment` and `CallbackRequest`
are `TenantLocationOwned`. `Service` is tenant-scoped with a NULLABLE location,
which no abstract base expresses — it declares its own FK.
"""
from apps.accounts.models._base import *  # noqa: F401,F403
from apps.accounts.models._base import __all__ as _base_all

__all__ = list(_base_all)
