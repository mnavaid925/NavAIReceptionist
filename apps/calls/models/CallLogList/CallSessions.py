"""`calls.CallSession` — THE call log (sub-module 5.1).

**Invariant 2 lives here.** A call is exactly one row of this table. Its
transcript, its event log, its per-turn usage, its analysis and its transfer
outcome are JSON COLUMNS ON THIS ROW — not `CallTurn`, not `CallEvent`, not
`ToolCall`, not `Transcript`. Adding any of those is an invariant violation, not
a refactor, and this docstring exists so that nobody "improves" the schema into
three tables without first reading why it is one.

**Why one table with JSON columns.** A call session is written by ONE process —
the media-stream consumer Module 3 will add, which owns the call for its whole
life — and read as a whole, on one detail page. Nothing in this application
queries ACROSS turns: there is no cross-call transcript search, no per-turn
billing rollup, no analytics surface. The transcript, the event log, the usage
list and the transfer outcome are all *documents about this one call*, and they
are always fetched together with it. So: one row, one read, no join, no ordering
bug, no second source of truth for "what happened on this call". A `Call` +
`CallTurn` + `CallEvent` split would buy query power nothing uses and cost a
database write PER TURN on the latency-critical realtime loop, which is the one
place in this product where a few milliseconds are audible.

**One WRITER is not one WRITE — do not read the above as "save it all at the
end".** The row is created when the inbound webhook resolves the dialed number,
appended to as the call proceeds, and finalized in the consumer's `disconnect()`.
Buffering a whole call in process memory for a single closing `UPDATE` would mean
a worker restart mid-call loses the entire transcript, event log and cost trail,
not merely the tail — and would leave the row stranded at `in_progress` with no
`ended_at` forever. `usage` in particular is APPENDED per turn as a delta
(`{turn_sequence, cost_breakdown, cost_usd}`) and never re-aggregated, which is
also why a call's cost is summed from the list at read time rather than stored.
The operational contract is `/voice-agent-runtime` §13–§14; this docstring must
not be read as contradicting it.

**Concurrent appends are the writer's problem, not the schema's.** These are
plain JSON documents with no version column, so two coroutines that each read a
list, append, and save will silently drop one entry. That is the accepted cost of
Invariant 2, and the guard belongs in Module 3 — a single writer task per call, or
`select_for_update()` inside a `transaction.atomic()` wrapped in
`database_sync_to_async`. Written down here because the schema cannot enforce it
and the failure is invisible.

**5.2, 5.3 and 5.4 add ZERO models.** The transcript viewer, the cost breakdown
and the recording/transfer panel are all reading surfaces over the JSON columns
below. When one of those sub-modules feels like it wants a table, that feeling is
the invariant firing.

**Written by Module 3, never by a form.** Nothing in Module 5 creates, edits or
deletes a row here — a completed call is a record of what happened, so this app
ships list + detail only and no `ModelForm` (CLAUDE.md names this exact model as
the carve-out to the CRUD Completeness Rules). `provider_call_sid` carries the
unique constraint that makes Module 3's webhook handler idempotent: Twilio
redelivers, and a retry must not mint a second session for the same call.

**Invariant 3 applies to everything that will one day read this row.** When
Module 3's tools arrive, `tenant_id`, `location_id`, `contact_id` and
`session_id` come from server-side session state — the tenant and location are
resolved from the DIALED NUMBER, not from anything the caller said and not from
anything the model emitted. The caller is speaking to the model, so any identity
the model supplies is caller-controlled input.

**PII.** `transcript`, `from_number`, `to_number` and the tool-call argument
blobs inside `logs` are PII by definition. Never log them at INFO; redact
tool-call arguments before persisting them into `logs`.
"""
from apps.calls.models._base import *  # noqa: F401,F403

__all__ = ['CallSession']


class CallSession(TenantLocationOwned):  # noqa: F405
    """One inbound phone call, start to finish."""

    MODE_LIVE = 'live'
    MODE_GOOGLE = 'google'
    MODE_GEMINI = 'gemini'

    #: Mirrors `agents.AgentSetting.VOICE_PROVIDER_CHOICES` value-for-value. The
    #: two lists are deliberately NOT shared through an import: this one records
    #: which stack actually handled THIS call, so it must keep its historical
    #: values even if the agent's own choice list is later changed or narrowed.
    MODE_CHOICES = [
        (MODE_LIVE, 'Live'),
        (MODE_GOOGLE, 'Google'),
        (MODE_GEMINI, 'Gemini'),
    ]

    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_COMPLETED = 'completed'
    STATUS_ABANDONED = 'abandoned'
    STATUS_TRANSFERRED = 'transferred'
    STATUS_FAILED = 'failed'

    #: FIVE values, against the ERD's stale three. Code is truth here twice over:
    #: `templates/partials/_call_status_badge.html` shipped before this model did
    #: and branches on exactly these five, and CLAUDE.md's Filter Implementation
    #: Rules name the identical five as the canonical call-status map. Building
    #: the ERD's literal three would leave the partial's `transferred` and
    #: `failed` branches as unreachable dead code — and would have no way to
    #: represent a call that ended by handing the caller to a human, which is one
    #: of the four things this product's agent is for.
    #: `no_show` spelling rules apply here too: `in_progress` with the
    #: underscore, matched literally by the partial.
    STATUS_CHOICES = [
        (STATUS_IN_PROGRESS, 'In progress'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_ABANDONED, 'Abandoned'),
        (STATUS_TRANSFERRED, 'Transferred'),
        (STATUS_FAILED, 'Failed'),
    ]

    contact = models.ForeignKey(  # noqa: F405
        'scheduling.Contact',
        on_delete=models.SET_NULL,  # noqa: F405
        null=True,
        blank=True,
        related_name='call_sessions',
        help_text='SET_NULL, not PROTECT and never CASCADE: an unknown or '
                  'withheld caller ID is routine, so null is a normal state, '
                  'and erasing a person must never delete the call record — '
                  'this row is the retention artefact of record.',
    )

    channel = models.CharField(  # noqa: F405
        max_length=32,
        default='agent_phone',
        help_text='How the call reached the agent. One value in practice — this '
                  'is an inbound-phone product — but the column exists so a '
                  'second channel does not need a migration on a table that '
                  'will be the largest in the database.',
    )
    mode = models.CharField(  # noqa: F405
        max_length=16,
        choices=MODE_CHOICES,
        default=MODE_LIVE,
    )
    status = models.CharField(  # noqa: F405
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_IN_PROGRESS,
        db_index=True,
    )

    # Real columns, not buried in `metadata` the way the OraOps reference had
    # them. The call log's search box matches on these, and a JSON key-transform
    # lookup cannot use an index.
    from_number = models.CharField(max_length=32, db_index=True)  # noqa: F405
    to_number = models.CharField(max_length=32, db_index=True)  # noqa: F405

    provider_call_sid = models.CharField(  # noqa: F405
        max_length=64,
        unique=True,
        help_text='The Twilio CallSid. UNIQUE because it is the idempotency key '
                  'for webhook redelivery: Twilio retries, and the constraint is '
                  'what stops a retry minting a second session for one call.',
    )

    # -- the JSON columns: Invariant 2's whole surface ----------------------- #
    # `default=list` / `default=dict` (the callables, never a shared literal —
    # a mutable default would be shared across every instance in the process).

    transcript = models.JSONField(  # noqa: F405
        default=list,
        help_text='[{sequence, role, text, at, offset}] — the turns, in order. '
                  'PII: never logged, never emitted at INFO.',
    )
    logs = models.JSONField(  # noqa: F405
        default=list,
        help_text='[{sequence, level, category, title, raw_json, occurred_at}] — '
                  'the event log. Tool-call arguments are redacted BEFORE they '
                  'are persisted here; a create_contact payload is a full name '
                  'and a date of birth.',
    )
    analysis = models.JSONField(  # noqa: F405
        default=dict,
        help_text='{summary, success_evaluation, extracted_data}. Legitimately '
                  'empty on an abandoned or failed call — nothing happened to '
                  'analyse, so every reader must render {} without falling over.',
    )
    usage = models.JSONField(  # noqa: F405
        default=list,
        help_text='[{turn_sequence, cost_breakdown, cost_usd}] — per-turn cost. '
                  'Cost is derived from this list at read time, never stored as '
                  'a column, so a corrected rate card re-prices history.',
    )
    transfer = models.JSONField(  # noqa: F405
        default=dict,
        help_text='{result, reason, destination, initiated_at, duration_seconds, '
                  'attempts}. `result` and `destination` are the FINAL outcome '
                  'and the number that produced it. `attempts` is an optional '
                  '[{destination, result}] list recording each number tried in '
                  'order — AgentSetting carries a transfer_secondary_number, so '
                  '"primary rang out, secondary answered" is a designed path, '
                  'and without this list it could only be narrated in `reason`, '
                  'where nothing can query it. Empty dict = no transfer was ever '
                  'attempted, the common case.',
    )
    waveform_peaks = models.JSONField(  # noqa: F405
        null=True,
        blank=True,
        help_text='{caller, bot, bins} for the call-detail waveform. NULL rather '
                  'than empty-by-default: absent means "never computed", which '
                  'is not the same as a recording that is genuinely silent.',
    )
    metadata = models.JSONField(  # noqa: F405
        default=dict,
        help_text='Call-level detail that needs no column of its own — including '
                  'the recording consent basis and its retention window, which '
                  'live on the row that was actually recorded because the policy '
                  'that applies is the policy at the time of the call.',
    )

    # A NON-EMPTY `recording_blob` REQUIRES A CONSENT BASIS IN `metadata`, and
    # nothing here can enforce that.
    #
    # 5.1 never writes either field, so there is nothing to validate yet — but
    # Module 3.5 does, and this is where the rule has to be honoured: before
    # persisting a recording path, confirm `metadata` already carries a resolved
    # consent basis, and refuse the write (recording nothing) if it does not. A
    # recorded call with no consent record is the failure that matters, and a
    # malformed or replayed webhook is exactly how one gets created.
    #
    # It has to be application-level validation in the write path, not a
    # `CheckConstraint`: MySQL cannot portably assert anything about a JSON
    # sub-key, so a database constraint here would be a comfort rather than a
    # guarantee.
    recording_blob = models.CharField(  # noqa: F405
        max_length=512,
        blank=True,
        default='',
        help_text='PRIVATE storage path; "" = no recording. Served only through '
                  'a short-lived signed URL — never rendered as a src against a '
                  'public media path. Must not be set without a consent basis '
                  'in `metadata` — see the comment above.',
    )

    # Null until the call actually starts / ends. Both are UTC (`USE_TZ = True`)
    # and are rendered in the LOCATION's timezone, never the server's.
    started_at = models.DateTimeField(null=True, blank=True)  # noqa: F405
    ended_at = models.DateTimeField(null=True, blank=True)  # noqa: F405

    class Meta:
        ordering = ['-created_at']
        indexes = [
            # The call log's own list query on every page load: one location's
            # calls, newest first. Synthflow's docs warn that an unfiltered
            # call-log scan is slow at volume, and this table grows per call —
            # faster than anything else in the product.
            models.Index(fields=['tenant', 'location', 'started_at'],  # noqa: F405
                         name='idx_call_tenant_loc_started'),
            # Cross-location, tenant-wide status rollups.
            models.Index(fields=['tenant', 'status'],  # noqa: F405
                         name='idx_call_tenant_status'),
            # "Every call from this person", from the contact detail page — which
            # spans locations, so location is deliberately not in this one.
            models.Index(fields=['tenant', 'contact'],  # noqa: F405
                         name='idx_call_tenant_contact'),
        ]

    def __str__(self):
        return f'{self.provider_call_sid} — {self.get_status_display()}'

    # -- derived ------------------------------------------------------------- #

    @property
    def duration_display(self):
        """How long the call ran, as a human label that is never empty.

        Derived, never stored — the same principle the ERD states for cost. A
        stored duration is a second source of truth that drifts the moment a
        timestamp is corrected.

        Both stamps set → the elapsed time. Only `started_at` → the call is
        still up. Neither → a dash, because a session row can exist before the
        media stream has produced its first frame. An `ended_at` with no
        `started_at` also lands on the dash: there is nothing to measure from,
        and inventing a zero would read as a real zero-second call.
        """
        if not self.started_at:
            return '—'
        if not self.ended_at:
            return 'In progress'

        seconds = int((self.ended_at - self.started_at).total_seconds())
        # Provider stamps arrive from two different clocks, so a skewed pair can
        # invert. Report the dash rather than a negative duration — a wrong
        # number that looks plausible is worse than an admitted gap.
        if seconds < 0:
            return '—'

        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f'{hours}h {minutes}m {secs}s'
        if minutes:
            return f'{minutes}m {secs}s'
        return f'{secs}s'

    @property
    def total_cost_usd(self):
        """The call's total cost, summed from `usage` at READ time — never stored.

        Mirrors `duration_display`'s derivation discipline and the ERD's named
        anti-pattern (a `cost_usd` COLUMN here would let a view write a total
        independently of `usage`, so a corrected rate card would leave a stale
        total behind instead of re-pricing history). The per-turn `cost_usd`
        the runtime writes is itself the sum of that turn's `cost_breakdown`;
        this is the sum of those sums.

        Guards the shape it does not fully trust: `usage` that is not a list at
        all (a bare number, a dict, `True`) contributes 0 rather than crashing the
        detail page — `for turn in 42` raises `TypeError`, and Django re-raises an
        exception from a property rather than swallowing it, so an unguarded loop
        here is a 500, not a blank cell. A malformed ROW inside a real list — a
        non-numeric `cost_usd`, an entry that is not a dict — is skipped the same
        way.
        """
        usage = self.usage if isinstance(self.usage, list) else []
        total = 0.0
        for turn in usage:
            try:
                total += float(turn.get('cost_usd', 0) or 0)
            except (AttributeError, TypeError, ValueError):
                continue
        return round(total, 4)
