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

__all__ = ['CallState']


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
    #: The 3.4 seam. 3.2 declares it and never sets it; 3.4's transfer tool does.
    pending_transfer: str = None
    #: Why the call ended, stamped at teardown ('hangup', 'idle_timeout',
    #: 'max_duration', 'error') — the seed of 3.5's ended-reason diagnostics.
    ended_reason: str = None
    #: Call start, read from CallSession.started_at, used for transcript offsets.
    started_at: object = None

    #: Monotonic sequence counters, NEVER reset. The buffers are cleared on every
    #: flush (they hold only un-persisted deltas), so a per-buffer `len()+1` would
    #: restart numbering at each flush and collide; these count across the whole
    #: call instead. init=False — internal, not a constructor argument.
    _transcript_seq: int = field(default=0, init=False)
    _log_seq: int = field(default=0, init=False)

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
