"""Shared model toolkit for Module 2 — Agent Setup & Telephony.

Re-exports the cross-app abstract bases from `apps.accounts.models._base` rather
than redefining them, so the `tenant` / `location` FK declaration exists once in
the project. Entity modules pull it with `from apps.agents.models._base import *`.
"""
from apps.accounts.models._base import *  # noqa: F401,F403
from apps.accounts.models._base import __all__ as _base_all

__all__ = list(_base_all)
