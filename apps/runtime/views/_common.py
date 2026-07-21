"""Shared view toolkit for Module 3 — Call Runtime.

Re-exports the accounts base toolkit (``login_required``, ``render``, ``timezone``,
``paginate``, the http-method decorators, …) so an entity view module pulls it
all with ``from apps.runtime.views._common import *``, exactly like every other
app. Runtime adds nothing app-specific here yet; the import indirection is what
keeps a later shared helper a one-line addition rather than a churn across views.
"""
from apps.accounts.views._common import *  # noqa: F401,F403
from apps.accounts.views._common import __all__ as _base_all

__all__ = list(_base_all)
