"""Shared model toolkit for Module 5 — Call Logs.

Re-exports the cross-app abstract bases from `apps.accounts.models._base` rather
than redefining them, so the `tenant` / `location` FK declaration exists exactly
once in the project. Entity modules pull it with
`from apps.calls.models._base import *`.

This app owns exactly one model, `CallSession`, and it takes
`TenantLocationOwned`: a call arrives on ONE location's Twilio number, so the
dialed number determines the location before anything else about the call is
known. Sub-modules 5.2–5.4 add no model at all — they read this same row.
"""
from apps.accounts.models._base import *  # noqa: F401,F403
from apps.accounts.models._base import __all__ as _base_all

__all__ = list(_base_all)
