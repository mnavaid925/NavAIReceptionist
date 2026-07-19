"""Shared model toolkit for Module 1 — Business & Locations.

Re-exports the cross-app abstract bases from `apps.accounts.models._base` rather
than redefining them, so the `tenant` / `location` FK declaration exists exactly
once in the project. Entity modules pull it with
`from apps.tenants.models._base import *`.
"""
from apps.accounts.models._base import *  # noqa: F401,F403
from apps.accounts.models._base import __all__ as _base_all

__all__ = list(_base_all)
