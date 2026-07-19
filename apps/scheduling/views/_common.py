"""Shared view toolkit for Module 4 — Calendar & Bookings.

Re-exports `apps.accounts.views._common` so the paginate helper, the decorators
and the shortcut imports exist once in the project. Entity modules pull it with
`from apps.scheduling.views._common import *`.
"""
from apps.accounts.views._common import *  # noqa: F401,F403
from apps.accounts.views._common import __all__ as _base_all
from apps.accounts.views._common import paginate  # noqa: F401
from apps.accounts.views._helpers import safe_redirect_target, tier_required  # noqa: F401

#: Tiers allowed to destroy or anonymise a record. Reading and editing the
#: calendar is front-desk work; erasing a contact is not.
MANAGEMENT_TIERS = ('owner', 'manager')

# MANAGEMENT_TIERS must appear here or `import *` silently omits it and every
# view module fails with "name 'MANAGEMENT_TIERS' is not defined" at import time.
__all__ = list(_base_all) + [
    'tier_required',
    'safe_redirect_target',
    'MANAGEMENT_TIERS',
]
