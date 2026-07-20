"""Form package for Module 5 — Call Logs.

**Empty on purpose, and expected to stay that way.** `CallSession` ships NO model
form: a completed call is a record of what happened, so this app has a list view
and a detail view and nothing else — no create, no edit, no delete. CLAUDE.md
names this exact model as the carve-out to the CRUD Completeness Rules ("A
completed `calls.CallSession` is a record of what happened and has no edit view.
Its absence is correct; its unguarded presence is the bug"). The same posture
`agents/forms/__init__.py` already documents for 2.4's Test Call — precedent, not
a new pattern.

Every field on the model is either server-scoped (`tenant`, `location`),
provider-supplied (the numbers, the SID, the JSON columns, the timestamps) or
workflow-controlled (`status`, `contact`). There is nothing a user could
legitimately type into it.

If a form ever does land here, it gets re-exported below or
`from apps.calls.forms import X` fails.
"""

__all__ = []
