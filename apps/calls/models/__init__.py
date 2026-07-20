"""Model package for Module 5 — Call Logs.

Re-exports every model this app owns so `from apps.calls.models import X` works
regardless of which sub-module folder X actually lives in. Adding a model without
adding it here is a bug: Django's app registry finds it (it walks the package),
but every import site in the project fails with an ImportError.

Sub-module folders:

* `CallLogList/` — 5.1  CallSession

There is exactly one, and there will not be a second. Sub-modules 5.2
(transcript), 5.3 (cost breakdown) and 5.4 (recording and transfer outcome) are
reading surfaces over `CallSession`'s JSON columns and add NO model — a
`Transcript`, `TranscriptTurn`, `ToolCall` or `CallEvent` table here is an
Invariant 2 violation. See `CallLogList/CallSessions.py` for why the schema is
one row rather than three tables.
"""
from apps.calls.models.CallLogList.CallSessions import CallSession

__all__ = ['CallSession']
