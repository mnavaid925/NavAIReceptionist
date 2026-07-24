"""``CallState`` — the per-call conversation state — sub-module 3.2.

One instance per call, owned by the media consumer. It holds everything the turn
loop reasons over — identity, the conversation history, the buffered transcript /
log / usage entries, and the deferred-transport seam — but **not** the transport
flags (``turn_busy``, ``pending_utterance``, ``is_playing``, the idle clock),
which live on the consumer because they are websocket-transport concerns, not
conversation ones. Keeping the two apart is what stops audio bookkeeping from
leaking into conversation logic.

**Identity comes only from the verified stream token** (Invariant 3): ``tenant_id``
/ ``location_id`` / ``session_id`` are set from ``verify_stream_token()``'s
payload in ``connect()`` and never from the websocket URL. ``contact_id`` is the
slot 3.3's ``create_contact`` / ``search_contact`` tools fill; 3.2 only carries it.

**Buffers are flushed onto ``CallSession`` at checkpoints, not held to the end.**
The three ``add_*`` helpers append PII-bearing rows in memory; the consumer flushes
them through ``database_sync_to_async`` at start / per turn / disconnect, per the
model's own docstring on worker-restart risk (a whole call buffered for one closing
UPDATE loses everything on a mid-call restart). ``usage`` is appended per turn as a
delta and never re-aggregated (skill §13).
"""
from dataclasses import dataclass, field

from django.utils import timezone

from apps.runtime.agent.consent import CONSENT_NOT_RECORDED, CONSENT_TWO_PARTY

__all__ = ['CallState', 'ENDED_REASON_DISPLAY', 'ENDED_REASON_KEYS']

#: The closed set of ended-reason codes, with a staff-facing label and a
#: ``theme.css`` badge class for 3.5's diagnostics tally. Display order is
#: rough frequency order — the ordinary endings first, the failures last.
#:
#: This is the SHARED vocabulary: the consumer's ``_STATUS_BY_REASON`` maps the
#: same keys to a terminal ``CallSession.status`` (a different concern — one is
#: "why did it end", the other "what does the row read as"), and a test asserts
#: the two key sets are identical. Without that, a ninth reason string typo'd into
#: ``ended_reason`` would fall through ``_STATUS_BY_REASON``'s default AND vanish
#: from the tally, silently, on both sides at once.
ENDED_REASON_DISPLAY = [
    ('hangup', 'Caller hung up', 'badge-slate'),
    ('end_call', 'Agent ended the call', 'badge-green'),
    ('transferred', 'Transferred', 'badge-info'),
    ('idle_timeout', 'Idle timeout', 'badge-muted'),
    ('max_duration', 'Max duration reached', 'badge-amber'),
    ('capacity', 'Declined — at capacity', 'badge-red'),
    ('disabled', 'Declined — number disabled', 'badge-red'),
    ('error', 'Runtime error', 'badge-red'),
]

#: Just the keys, for membership checks and the drift guard.
ENDED_REASON_KEYS = frozenset(key for key, _label, _badge in ENDED_REASON_DISPLAY)


@dataclass
class CallState:
    """Mutable conversation state for one live call."""

    # -- identity (from the verified stream token only) --------------------- #
    tenant_id: int
    location_id: int
    session_id: int
    agent_setting_id: int
    voice_provider: str

    # -- conversation ------------------------------------------------------- #
    #: The caller once identified/created (3.3). Null until then — a call can run
    #: its whole length as an unknown caller.
    contact_id: int = None
    #: Turn-role dicts resent to the LLM every turn ({'role', 'text'}), trimmed on
    #: long calls (skill §7) so input tokens do not grow quadratically.
    history: list = field(default_factory=list)
    #: The merged {{variable}} map — AgentSetting.variables plus the runtime vars,
    #: recomputed each turn for the time-sensitive ones (skill §10).
    variables: dict = field(default_factory=dict)
    #: Provider working intervals at this location, gathered once in connect(), so
    #: `is_open_now` is a pure in-memory check each turn rather than a per-turn
    #: query. Shape: [{'start_time', 'end_time', 'days': [weekday_key, ...]}].
    open_intervals: list = field(default_factory=list)

    # -- buffered writes (flushed onto CallSession at checkpoints) ----------- #
    transcript_buffer: list = field(default_factory=list)
    logs_buffer: list = field(default_factory=list)
    usage_buffer: list = field(default_factory=list)

    # -- accounting / flow -------------------------------------------------- #
    turn_sequence: int = 0
    #: Failed `search_contact` attempts on this call. That tool verifies identity
    #: on name + date of birth, so without a ceiling a caller who knows a name
    #: (easy to get) could use it as a yes/no oracle to brute-force the date of
    #: birth across a 15-minute call. The per-turn tool-iteration cap does not
    #: bound this — it resets every turn.
    search_attempts: int = 0
    #: Set once the off-hours transfer fallback has logged its CallbackRequest, so a
    #: model that calls `transfer_call` several times in one call (the tool-iteration
    #: cap allows up to 4/turn) cannot spam near-duplicate callback rows — the same
    #: per-call single-fire discipline `search_attempts` and the consumer's
    #: `_transfer_started` use. 3.4 sets it; nothing else reads it.
    offhours_callback_logged: bool = False
    #: Deferred transport signals. 3.3's `transfer_call`/`transfer_call_spanish`
    #: and `end_call` tools SET these and return an ack; the transport acts only
    #: after the turn's audio has finished playing (skill §9). 3.4 executes the
    #: transfer (hours gate, single-fire guard, Twilio redirect); the consumer
    #: handles the hangup, which needs no REST call.
    pending_transfer: str = None
    pending_hangup: bool = False
    #: Why the call ended, stamped at teardown — one of ENDED_REASON_DISPLAY's
    #: keys, which 3.5's diagnostics tally reads back off the finalized row.
    ended_reason: str = None
    #: 3.5 recording consent. Resolved ONCE at authorization from the location's
    #: jurisdiction (`agent.consent.resolve_consent`) and never recomputed
    #: mid-call — the policy that applies is the policy at the time of the call,
    #: which is exactly why CallSession stores it per row. None means consent was
    #: never resolved at all (a declined call), which finalize records as
    #: `not_recorded` rather than leaving the key absent.
    consent_basis: str = None
    #: Whether the two-party announcement actually PLAYED. Deliberately separate
    #: from `consent_basis`: the basis is what the jurisdiction requires, this is
    #: what the caller really heard, and a TTS failure makes them differ. Recording
    #: the difference honestly is the point — a row claiming an announcement that
    #: never played would be worse than no claim at all.
    consent_announced: bool = False
    #: Call start, read from CallSession.started_at, used for transcript offsets.
    started_at: object = None

    #: Monotonic sequence counters, NEVER reset. The buffers are cleared on every
    #: flush (they hold only un-persisted deltas), so a per-buffer `len()+1` would
    #: restart numbering at each flush and collide; these count across the whole
    #: call instead. init=False — internal, not a constructor argument.
    _transcript_seq: int = field(default=0, init=False)
    _log_seq: int = field(default=0, init=False)

    # -- derived ------------------------------------------------------------ #

    @property
    def requires_announcement(self):
        """Whether this call owes the caller a spoken recording notice.

        DERIVED from ``consent_basis`` rather than stored as a third flag: two
        booleans describing one policy are two things that can drift apart, and
        the one that matters (did we announce?) is already
        ``consent_announced``.
        """
        return self.consent_basis == CONSENT_TWO_PARTY

    @property
    def should_record(self):
        """Whether a recording may be persisted for this call.

        The structural half of the model's own rule that a non-empty
        ``recording_blob`` REQUIRES a resolved consent basis: finalize computes
        the recording path and the ``consent_basis`` metadata key from THIS one
        boolean, in one ``save()``, so no code path can write a recording without
        the basis that justified it landing in the same write.
        """
        return bool(self.consent_basis) and self.consent_basis != CONSENT_NOT_RECORDED

    # -- buffer helpers (in-memory only; no ORM) ---------------------------- #

    def _offset_seconds(self, now):
        """Seconds since the call started, for a transcript entry. 0 if unknown."""
        if not self.started_at:
            return 0.0
        delta = (now - self.started_at).total_seconds()
        return round(delta, 3) if delta >= 0 else 0.0

    def add_transcript(self, role, text):
        """Append one transcript turn: {sequence, role, text, at, offset}."""
        now = timezone.now()
        self._transcript_seq += 1
        self.transcript_buffer.append({
            'sequence': self._transcript_seq,
            'role': role,
            'text': text,
            'at': now.isoformat(),
            'offset': self._offset_seconds(now),
        })

    def add_log(self, level, category, title, raw_json=None):
        """Append one event-log row: {sequence, level, category, title, raw_json,
        occurred_at}.

        ``raw_json`` must already be redacted by the caller — a tool-call argument
        blob is a full name and a date of birth (skill §14). 3.2 logs provider
        events, barge-ins, turn latency and errors, none of which carry raw caller
        PII, but the redaction contract is stated here so 3.3 inherits it.
        """
        self._log_seq += 1
        self.logs_buffer.append({
            'sequence': self._log_seq,
            'level': level,
            'category': category,
            'title': title,
            'raw_json': raw_json or {},
            'occurred_at': timezone.now().isoformat(),
        })

    def add_usage(self, cost_breakdown, cost_usd):
        """Append one per-turn cost delta: {turn_sequence, cost_breakdown, cost_usd}.

        Appended as the turn completes and NEVER re-aggregated — the call total is
        summed from this list at read time by Module 5 (skill §13).
        """
        self.usage_buffer.append({
            'turn_sequence': self.turn_sequence,
            'cost_breakdown': cost_breakdown,
            'cost_usd': cost_usd,
        })
