"""Model package for Module 0 — Accounts & Access.

Foundation apps (`accounts`, `tenants`) are FLAT: the entity file sits at the
package root, with no `<SubModule>/` level.

Every model this package owns MUST be re-exported here — that is what keeps
`from apps.accounts.models import X` working from other apps, from the admin and
from migrations. Adding a model without adding it to `__all__` below is a bug.
"""
from apps.accounts.models._base import (
    TenantLocationOwned,
    TenantNumbered,
    TenantOwned,
    TimeStamped,
)

__all__ = [
    'TimeStamped',
    'TenantOwned',
    'TenantLocationOwned',
    'TenantNumbered',
]
