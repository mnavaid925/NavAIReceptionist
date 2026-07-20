"""Shared form toolkit for Module 5 — Call Logs.

Re-exports the cross-app bases from `apps.accounts.forms._common` rather than
redefining them, so `TenantModelForm`'s tenant-stamping and FK-narrowing exist
once in the project. Entity modules pull it with
`from apps.calls.forms._common import *`.

Present for symmetry with every other app, and currently unused — see
`forms/__init__.py` for why this app ships no model form.
"""
from apps.accounts.forms._common import *  # noqa: F401,F403
from apps.accounts.forms._common import __all__ as _base_all

__all__ = list(_base_all)
