"""Model package for Module 1 — Business & Locations.

Foundation apps (`accounts`, `tenants`) are FLAT: the entity file sits at the
package root, with no `<SubModule>/` level.

Every model this package owns MUST be re-exported here — that is what keeps
`from apps.tenants.models import Location` working from every other app, the admin
and the migrations. Adding a model without adding it below is a bug that surfaces
as an ImportError at runtime.
"""
from apps.tenants.models.Location import Location
from apps.tenants.models.Tenant import Tenant

__all__ = ['Tenant', 'Location']
