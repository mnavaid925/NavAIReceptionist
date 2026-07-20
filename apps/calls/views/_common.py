"""Shared view toolkit for Module 5 — Call Logs.

Re-exports `apps.accounts.views._common` so the paginate helper, the decorators
and the shortcut imports exist once in the project. Entity modules pull it with
`from apps.calls.views._common import *`.
"""
from apps.accounts.views._common import *  # noqa: F401,F403
from apps.accounts.views._common import __all__ as _base_all
from apps.accounts.views._common import paginate  # noqa: F401

__all__ = list(_base_all)
