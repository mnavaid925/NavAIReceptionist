"""View package for Module 5 — Call Logs.

`calls` is a DOMAIN app, so entity files sit one folder per sub-module
(`CallLogList/CallSessions.py` for 5.1). Every view MUST be re-exported here or
the URLconf's `views.<name>` lookup fails with an AttributeError at import time.

`CallSession` gets a list view and a detail view and NOTHING ELSE. There is no
`callsession_create_view`, no `callsession_edit_view` and no
`callsession_delete_view`, and their absence is correct rather than pending: a
completed call is a record of what happened, and CLAUDE.md names this exact model
as the carve-out to the CRUD Completeness Rules. Sub-modules 5.2–5.4 add further
READING surfaces over the same row — never a writer.

Sub-module folders, in build order:

* `CallLogList/`         — 5.1  call log list + detail
* `CallDetailTranscript/` — 5.2  the printable transcript view
"""
from apps.calls.views.CallDetailTranscript.CallSessions import (
    callsession_transcript_print_view,
)
from apps.calls.views.CallLogList.CallSessions import (
    callsession_detail_view,
    callsession_list_view,
)

__all__ = [
    'callsession_list_view',
    'callsession_detail_view',
    'callsession_transcript_print_view',
]
