"""Views for sub-module 3.1 — Inbound Webhook & Call Resolution.

The webhook itself is a flat handler at ``apps/runtime/webhooks.py`` (it is not a
page). This package holds the sub-module's one observable HTTP surface: the
runtime diagnostics view, which reads how inbound calls are being resolved at the
active location. The parent ``views/__init__.py`` re-exports it.
"""
