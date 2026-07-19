"""Shared view toolkit for Module 2 — Agent Setup & Telephony."""
from apps.accounts.views._common import *  # noqa: F401,F403
from apps.accounts.views._common import __all__ as _base_all
from apps.accounts.views._common import paginate  # noqa: F401
from apps.accounts.views._helpers import safe_redirect_target, tier_required  # noqa: F401

#: Configuring the agent changes what callers hear and what the business is
#: billed, so it is not staff-tier work.
MANAGEMENT_TIERS = ('owner', 'manager')

__all__ = list(_base_all) + [
    'tier_required',
    'safe_redirect_target',
    'MANAGEMENT_TIERS',
]
