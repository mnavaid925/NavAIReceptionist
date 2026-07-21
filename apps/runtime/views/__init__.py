"""View package for Module 3 — Call Runtime.

Re-exports every view the URLconf resolves by name (``views.<name>``). A view that
lives in a ``SubModule/Entity.py`` file but is not re-exported here is an
``AttributeError`` at URL-import time, not a runtime 404 — so every new view is
added to this block in the same change.
"""
from apps.runtime.views.InboundWebhook.Diagnostics import runtime_diagnostics_view

__all__ = ['runtime_diagnostics_view']
