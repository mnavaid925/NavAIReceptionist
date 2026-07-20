# Research — Sub-module 5.3: Event Log & Cost (Module 5 — Call Logs, calls)

## Repo state checked first

- **`LIVE_LINKS`** (`apps/accounts/navigation.py`): `'5.1': {'Call Logs': 'calls:callsession_list'}`, `'5.2': {}`
  (empty dict — built, no sidebar link of its own). No `'5.3'` key exists yet — **5.3 is the correct next
  sub-module** in Module 5. Every other module (0–4) is fully built. No sibling models to FK — Module 5 has one
  model total.
- **Models verified to exist** (`grep -rn "^class " apps/calls/models/` → exactly one hit):
  `apps/calls/models/CallLogList/CallSessions.py:70: class CallSession(TenantLocationOwned)`. **No `CallEvent`,
  `ToolCall`, `LogEntry` or `CostLine` model exists anywhere in `apps/calls/`** — confirming the grep-before-you-FK
  rule: this sub-module's whole surface is two JSON columns already on that one row.
- **Exact columns this sub-module reads, read directly from the model file:**
  - `logs` — `JSONField(default=list)`, shape **`[{sequence, level, category, title, raw_json, occurred_at}]`**.
    Docstring: *"Tool-call arguments are redacted BEFORE they are persisted here; a `create_contact` payload is a
    full name and a date of birth."* — the redaction contract is a Module 3 WRITE-path obligation; 5.3 is a reader
    that must never assume it and must never bypass it with `|safe`.
  - `usage` — `JSONField(default=list)`, shape **`[{turn_sequence, cost_breakdown, cost_usd}]`**. Docstring:
    *"Cost is derived from this list at read time, never stored as a column, so a corrected rate card re-prices
    history."* Matches `NavAIReceptionist-ERD.md` line 395 verbatim: *"A call's cost |
    `sum(turn["cost_usd"] for turn in session.usage)` | A `cost_usd` column on `CallSession` that a view can write
    independently of `usage`"* is explicitly named as the anti-pattern.
  - There is **no separate `disconnection_reason` or `error_message` field** on `CallSession` — a call-level
    runtime error is simply a `logs` entry whose `level` is `error` (or `critical`). "Runtime Error Surface" is a
    **rendering emphasis over the same list**, not a new field.
- **`templates/calls/calllog/callsession/detail.html` already marks exactly where 5.3 lands**, verbatim in its own
  comment: *"Still to land in this column: 5.3 the event log and the cost breakdown; 5.4 the recording player and
  the transfer outcome."* That comment already frames 5.3 as **two** additions (event log, cost breakdown) — the
  Tool-Call Trace and Runtime Error Surface bullets are folded into the *event log* rendering, not separate cards,
  which matches how the single `logs` list actually holds all three kinds of entry. The header (5.1), "What this
  call produced" (5.1) and the transcript/analysis panels (5.2) are already built and untouched by this pass.
- **`apps/accounts/templatetags/ui.py` already ships `level_badge`** — *"Map a call event-log level onto the fixed
  badge inventory... this filter exists so an event level never reaches a template as an invented
  `badge-<level>`."* Mapping: `debug→badge-muted, info→badge-info, warning→badge-amber, error→badge-red,
  critical→badge-red`. **This was clearly pre-built for 5.3** — it is not used anywhere yet (grepped: 5.1/5.2
  templates never reference it). 5.3 should consume this filter directly rather than inventing a second map. It
  also already has `dict_get` (silent-miss dict access, used by 5.2's analysis panel) and no redaction helper of
  any kind — that has to be authored by 5.3.
- **No redaction helper exists anywhere in the codebase.** `grep -rn "redact" apps/` hits only the model docstring,
  the seeder's hand-authored `'[redacted]'` string literals, and the migration. **5.3 must author the display-side
  redaction helper** — see Compliance below.
- **`.claude/skills/calls/SKILL.md`** confirms 5.3 is a **view sub-module — ZERO models, ZERO migrations** exactly
  like 5.2; names the "Add a view sub-module" recipe (`views/<SubModule>/<Entity>.py` + `urls/…`, re-export blocks,
  templates under `templates/calls/<submodule>/<entity>/`, a `LIVE_LINKS["5.M"]` entry, no model/migration, extend
  `seed_calls` idempotently only if richer JSON is needed) and states the module has **no logger, deliberately** —
  that convention carries into 5.3 unchanged: no new logging is added even to help debug the debugging page.
- **Sibling research files** (`research-calls-5.1.md`, `research-calls-5.2.md`) both independently park the exact
  same four things into 5.3: *"Structured event log, tool-call trace, per-turn cost breakdown, runtime error
  surface → 5.3 Event Log & Cost (reads `CallSession.logs`/`.usage`, no new model)"* — and 5.1 additionally parks
  *"Issue/quality severity badges (Bland's Issues column) → parked to 5.3."* That item is folded into the Runtime
  Error Surface group below.
- **Seeder** (`apps/calls/management/commands/seed_calls.py`) — read in full. It already seeds, across 11 sessions
  and every one of the five statuses:
  - **Multiple log levels** (`info`, `warning`, `error`) and **multiple categories** (`call`, `agent`, `tool`,
    `tts`, `stt`, `transfer`).
  - **Tool-call entries** for `find_availability`, `book_appointment`, `transfer_call`, `create_callback_request`,
    `get_location_hours`, `get_location_info` — each `raw_json` already shaped `{tool, arguments, ok, ...}`, and
    already **pre-redacted at the string-literal level** (`'slot_token': '[redacted]'`,
    `'reason': '[redacted]', 'caller_phone': '[redacted]'`) — the seeder is modelling what Module 3's write path
    is required to do, not what 5.3 renders.
  - **A failed tool call** (Lakeside, `transfer_call`) shaped `{'ok': False, 'error': {'code':
    'transfer_not_configured', 'message': '...'}}}` — already matching this product's closed tool-result envelope
    shape (`{ok, data, error:{code, message}}`), which is exactly the reference shape 5.3's Tool-Call Trace panel
    should render a result column from.
  - **Error-level entries that do NOT end the call** (Downtown's `transferred` row has an `error`-level `stt`
    timeout that recovers) alongside **error-level entries that DO end the call** (Uptown's and Lakeside's
    `failed` rows) — real coverage of both "recovered mid-call error" and "fatal error" for the Runtime Error
    Surface bullet.
  - **Usage cost lines** already shaped `[{turn_sequence, cost_breakdown: {stt_usd, llm_usd, tts_usd,
    telephony_usd}, cost_usd}]`, with `cost_usd` **summed from its own breakdown in `_build_usage`**, exactly
    mirroring the read-time-derivation rule this sub-module must also follow for the call TOTAL.
  - **One genuine gap**: **no tool-call log entry carries a duration figure anywhere in the seed data** — every
    `raw_json` for a `category == 'tool'` entry has `tool`/`arguments`/`ok` (and sometimes `slots_returned` or
    `error`), but never a `duration_ms` or equivalent. The Tool-Call Trace bullet explicitly names **"arguments,
    result, and duration"** as the three facts to show — duration is the one fact the current seed cannot
    demonstrate. **The seeder needs a small extension**: add a `duration_ms` key to each tool-call `raw_json` in
    `DEMO_CALL_SESSIONS` (a JSON-content edit, not a schema change — `raw_json` is already a free-form dict).
    Everything else 5.3 needs (levels, categories, error rows, redacted args, cost breakdown) is already present
    and does not need extending.

## Leaders surveyed (with source links)

1. **Retell AI** — the clearest documented match for this exact slice: per-component **latency percentiles**
   (p50/p90/p95/p99 for end-to-end, ASR, LLM, TTS, knowledge-base retrieval), a `transcript_with_tool_calls` array
   that interleaves each tool invocation (id, function name, arguments, success) into the transcript timeline, an
   itemized `call_cost` object (per-product line items — e.g. `elevenlabs_tts` — with unit price × duration,
   summed to a total), and a 40+ value `disconnection_reason` enum for exactly how/why a call ended —
   [Get Call](https://docs.retellai.com/api-references/get-call),
   [Top 6 AI Call Metrics](https://www.retellai.com/blog/top-6-ai-voice-agent-customer-service-metrics)
2. **Vapi** — the clearest documented **per-component cost model** (platform/hosting fee + STT + LLM + TTS billed
   and reported as separate line items per call/minute), which is exactly the four-way split
   (`stt_usd/llm_usd/tts_usd/telephony_usd`) this product's `usage.cost_breakdown` already uses —
   [Pricing](https://vapi.ai/pricing), [Cost breakdown](https://pxlpeak.com/blog/ai-tools/vapi-pricing-breakdown)
3. **Bland AI** — `error_message` (null unless something failed) plus a `queue_status` stage enum
   (`pre_queue_error`/`queue_error`/`call_error`/`complete_error`) that narrates **which stage of the call
   pipeline** failed, a `variables` object capturing tool/dynamic-data inputs and outputs **without any documented
   redaction** (used below as a negative example — this product's redaction rule is stricter on purpose), and a
   flat `price` field (aggregate, not per-turn) —
   [Call Details](https://docs.bland.ai/api-v1/get/calls-id)
4. **Synthflow** — a **unified logging system** (Call / Chat / API / Webhook logs) with an "Actions" tab per call
   showing every tool/knowledge-base action as a name + timestamp + status + **expandable request/response
   detail** — almost exactly the "raw payload expandable inline" bullet wording — and cross-links a failed action
   to the matching API-log entry for deeper inspection. **No cost figures are exposed anywhere in this surface**
   (used below as a negative example for the Cost Breakdown bullet, where this product does better) —
   [Logs](https://docs.synthflow.ai/logs), [Telephony Errors](https://docs.synthflow.ai/telephony-errors)
5. **ElevenLabs Agents** (Conversational AI) — conversation history exposes the full transcript **interleaved with
   tool usage** per turn, plus a separate "debug logs" surface, and a mock-tool-call testing mode for observing
   "how the agent decides to make tool calls and react to different tool call results" — the same
   arguments/result shape this sub-module needs, without a documented cost or duration breakdown —
   [Conversation analysis](https://elevenlabs.io/docs/eleven-agents/customization/agent-analysis),
   [Get conversation details](https://elevenlabs.io/docs/api-reference/conversations/get)
6. **Dialpad AI** — mainly a **contrast/negative example** for this sub-module: its observability surface is
   network-quality monitoring (MOS score, jitter, packet loss, latency via a "Quality of Service" dashboard and a
   "System Test" tool), which is a *transport* health surface, not an *application* event/tool/cost trace. Useful
   for confirming what this sub-module should **not** try to be (this product has no telephony QoS metrics to
   show; Twilio's own console owns that) —
   [System Test](https://help.dialpad.com/docs/system-test),
   [Call Recording & Transcription](https://help.dialpad.com/docs/understanding-call-recording-transcription)
7. **Smith.ai / Ruby Receptionists** — the human-hybrid-receptionist contrast: call "quality" here is a **human QA
   review process** (voice quality, transcription accuracy and conversational UX reviewed by AI *and* humans, fed
   back into training) rather than a machine-emitted tool-call/cost trace — confirming that a per-turn
   cost-and-tool trace is a **differentiator specific to LLM-pipeline products**, not something every inbound
   answering competitor ships —
   [Call Analytics & Intelligence](https://smith.ai/features/call-intelligence-and-metadata)

## Feature catalog (this sub-module only)

### Structured Event Log
- **Levelled, categorised timeline with an expandable raw payload per entry** — the universal shape: Synthflow's
  Actions tab (name/timestamp/status/expandable request-response), Retell's log of "all the requests and
  responses... latency tracking for each turn-taking," ElevenLabs' separate "debug logs" surface · seen in:
  Synthflow, Retell, ElevenLabs · priority: **REQUIRED** — named bullet, and it is the only place a non-technical
  location owner can see what actually happened without asking an engineer to read server logs · model: reuses
  `CallSession.logs` (JSON list, already shaped `{sequence, level, category, title, raw_json, occurred_at}`) — zero
  new fields · realtime: **post-call** (batch/UI; the runtime that WRITES entries during the live call is Module
  3's hot path, this sub-module only reads) · tool-surface: pure UI, no tool, no prompt change — reads a column
  Module 3 will one day write; identity (tenant/location/session) comes entirely from the already-scoped
  `location_sessions(request)` queryset + the URL's `pk`, never from anything in `logs` itself · buildable now.
- **Level badge via the fixed inventory** — render every entry's `level` through the **already-shipped**
  `level_badge` template filter (`debug→badge-muted, info→badge-info, warning→badge-amber, error→badge-red,
  critical→badge-red`) rather than inventing a second map — this filter was pre-authored (confirmed unused by any
  template yet) specifically for this sub-module · priority: **REQUIRED** (CLAUDE.md's Filter/Badge conventions:
  "always include an `{% else %}` fallback... the canonical map lives in exactly one file") · model: none, pure
  template wiring · realtime: post-call · tool-surface: pure UI · buildable now.
- **Category label, chronological ordering by `sequence`** — every log entry already carries `category` (`call`,
  `agent`, `tool`, `tts`, `stt`, `transfer` in the seed data) and a stable `sequence`; render in that order (the
  list is already append-only and ordered by the writer, per the model's own concurrency-note) · priority:
  table-stakes · model: same column · realtime: post-call · tool-surface: pure UI · buildable now.
- **Expandable raw JSON, never dumped `|safe`** — Synthflow's "expandable request/response details" is the closest
  documented match to the bullet's own wording ("raw payload expandable inline"). Implement as a native
  `<details>/<summary>` per row (zero JS dependency, matches this product's plain-HTML-first pattern elsewhere) —
  the payload text is always escaped Django output of a Python-formatted (indented) JSON string, never
  `mark_safe`/`|safe`, and always passed through the redaction helper first (see Tool-Call Trace group) · priority:
  **REQUIRED** — the bullet's own wording plus CLAUDE.md's blanket "nothing caller-controlled is ever `|safe`" rule
  (already stated as this module's own convention in the SKILL) · model: none · realtime: post-call · tool-surface:
  pure UI · buildable now.
- **Empty state for a call with no logs yet** — an `in_progress` call has whatever the runtime has appended so
  far, and a hypothetical row with `logs == []` (none in the current seed, but a real possible state — e.g. the
  moment right after webhook creation, before the media stream opens) must render an explicit "No events recorded
  yet" message rather than an empty `<table>` — matching the same defensive-rendering discipline 5.2 already
  established for `analysis == {}` · priority: **REQUIRED** (this product's own established convention, not
  copied from a leader — none of the leaders' docs describe this edge case either) · model: same column, empty
  branch only · realtime: post-call · tool-surface: pure UI · buildable now.

### Tool-Call Trace
- **Tool invocations surfaced in the same event stream, with name, arguments, result and duration** — Retell's
  `transcript_with_tool_calls` ("when... the tool was invoked and what was the result"), ElevenLabs' tool-usage
  interleaving, Synthflow's Actions tab · seen in: Retell, ElevenLabs, Synthflow · priority: **REQUIRED** — named
  bullet · model: reuses `CallSession.logs` filtered/highlighted where `category == 'tool'` (or `raw_json.tool` is
  present) — **no new field**; render `raw_json.tool` as the call name, `raw_json.arguments` (redacted) as
  parameters, `raw_json.ok` + `raw_json.error.{code,message}` as the result (already shaped as this product's own
  tool-result envelope in the seeded failed-transfer row), and a `raw_json.duration_ms` as elapsed time · realtime:
  post-call · tool-surface: pure UI — **this sub-module defines no LLM tool of its own**; it is the display
  surface over tool calls Module 3's dispatcher (`apply_tool_call(state, name, args)`) will make and log · **the
  seeder needs a `duration_ms` key added to each tool-call `raw_json`** — the one concrete gap found (see Repo
  state above) · buildable now (pending that seeder addition).
- **Visually distinguish a tool entry from a plain narrative entry** — none of Synthflow/Retell's docs specify
  exact visual treatment, so this is this product's own design decision: a small icon/badge (e.g. a wrench glyph)
  or a distinct `category == 'tool'` row style, so a reader scanning the timeline can find "what did the agent
  actually DO" versus "what happened to the call" without reading every row · priority: common (implied by every
  leader's decision to give tool calls their own tab/column rather than mixing them anonymously into a generic
  log) · model: none, pure CSS/markup · realtime: post-call · tool-surface: pure UI · buildable now.
- **Sensitive argument redaction — REQUIRED, display-time defense-in-depth.** CLAUDE.md states plainly: *"a
  `create_contact` args payload is a full name and date of birth... Redact the tool-call payload before
  persisting"* — that is Module 3's WRITE-path obligation (already modelled by the seeder's `'[redacted]'`
  literals), but **this sub-module must not blindly trust that the stored `raw_json` is already safe**: Module 3
  does not exist yet, a future bug in its redaction step or a historical row written before a fix would otherwise
  leak PII straight onto this page. **5.3 must add its own display-time redaction pass** as a second, independent
  line of defense — see the concrete filter design under Compliance below · seen in: this product's own
  CLAUDE.md rule (none of the surveyed leaders document redacting tool arguments at display time — Bland's
  `variables` object is shown undocumented-for-redaction, which is exactly the negative example that makes this
  product's stricter rule REQUIRED rather than optional) · priority: **REQUIRED** · model: none — a pure
  presentation-layer helper, never persisted · realtime: post-call · tool-surface: pure UI, but load-bearing for
  every other bullet in this group (nothing in this sub-module renders `raw_json` without going through it first)
  · buildable now.

### Per-Turn Cost Breakdown
- **Per-turn cost lines with a component breakdown, and a call total** — Vapi's own pricing model documents
  exactly the same four cost components this product already stores (`stt_usd`/`llm_usd`/`tts_usd`/
  `telephony_usd`); Retell's `call_cost` itemizes per-product line items with unit price × duration summed to a
  total · seen in: Vapi, Retell · priority: **REQUIRED** — named bullet, and it is literally the only place in the
  product an owner can see "why did this call cost so much" · model: reuses `CallSession.usage` (JSON list,
  already shaped `[{turn_sequence, cost_breakdown, cost_usd}]`) — **zero new fields**; render one table row per
  turn (`turn_sequence`, then one column per key present in `cost_breakdown` — treat it as an open dict, not a
  fixed 4-column schema, since a future provider swap could add/remove a cost dimension without a migration — plus
  `cost_usd`), and a footer row for the call total · realtime: post-call · tool-surface: pure UI — 5.3 **appends
  nothing** to `usage`; that JSON is written by Module 3's turn loop, and this sub-module only fixes the *display*
  contract, which in turn documents the *write* contract Module 3 must honor (see Compliance) · buildable now.
- **Call total derived at read time, never stored** — `NavAIReceptionist-ERD.md` line 395 states this by name:
  *"A call's cost | `sum(turn["cost_usd"] for turn in session.usage)` |* [never] *a `cost_usd` column... a view can
  write independently."* The seeder already follows the identical rule one level down (`cost_usd` per turn is
  summed from `cost_breakdown`, never typed twice) · priority: **REQUIRED** — an explicit anti-pattern named in the
  ERD, not a style preference · model: **recommended (optional) addition** — a `total_cost_usd` **`@property`** on
  the existing `CallSession` model, mirroring the already-existing `duration_display` property exactly (same file,
  same pattern, **no migration**: a Python property generates no schema change) — sums `usage[].cost_usd`,
  returns `0` (not `None`) for an empty list so a template can format it unconditionally · realtime: post-call ·
  tool-surface: pure UI · buildable now.
- **A slow/expensive turn is traceable, not just visible** — the bullet's own wording ("so a slow or expensive
  call can be traced to its turn") — satisfied by nothing more than the per-turn table itself (`turn_sequence` +
  its own `cost_usd`), since this product's `usage` schema has no separate latency/duration-per-turn field to sort
  or highlight by; a highest-cost-turn visual callout (e.g. bold the max `cost_usd` row) is a reasonable,
  zero-schema polish · priority: common · model: none, template-only (compute the max in the view alongside the
  total, or client-side) · realtime: post-call · tool-surface: pure UI · buildable now, optional polish.

### Runtime Error Surface
- **Call-level runtime errors surfaced on the page itself, not only in the server log** — Bland's `error_message` +
  `queue_status` stage enum (narrating exactly which pipeline stage failed: `pre_queue_error`/`queue_error`/
  `call_error`/`complete_error`), Retell's 40+-value `disconnection_reason` enum · seen in: Bland, Retell ·
  priority: **REQUIRED** — named bullet, and this product deliberately has **no separate error field**: the
  bullet is satisfied entirely by rendering `logs` entries where `level` is `error` or `critical` with enough
  visual weight that they don't require scrolling the whole timeline to find · model: reuses `CallSession.logs`
  (filter/highlight only, same column as the event log — **not a second read**) · realtime: post-call ·
  tool-surface: pure UI · buildable now.
- **A short "errors on this call" summary, separate from the full timeline** — folds in 5.1's own parked item
  ("Bland's Issues column... overlaps with 5.3's Runtime Error Surface bullet"): a small count/callout at the top
  of the event-log card (e.g. "2 errors on this call" linking to the first one, or an explicit "No runtime errors"
  when the filtered set is empty) rather than requiring a reader to scan every row for a red badge · priority:
  common (no leader ships an identical UI, but Bland's stage-enum and Retell's disconnection-reason both exist
  precisely so a reader doesn't have to infer failure from a raw transcript) · model: same column, filtered view
  · realtime: post-call · tool-surface: pure UI · buildable now.
- **A `failed`-status call's errors are the first thing shown, not buried** — the seeder already gives two
  concrete cases to build and test against: Uptown's `failed` row (media-stream close + unclean-hangup, both
  `error`-level `call` category) and Lakeside's `failed` row (a failed `transfer_call` tool invocation followed by
  an `error`-level `transfer` entry and an `error`-level `call` entry) — both should visibly explain "why this call
  is marked failed" without requiring the reader to already know to look in the event log · priority: **REQUIRED**
  — directly named by the bullet's own wording ("rather than only in the server log") · model: same column,
  ordering/emphasis only · realtime: post-call · tool-surface: pure UI · buildable now — **no seeder change
  needed**, both cases already exist.

### Beyond the bullets
- **Per-component / percentile latency (p50/p90/p95/p99 for ASR, LLM, TTS, end-to-end)** — Retell's dashboard-level
  feature · priority: differentiator · model: would require a new `latency_ms` figure per turn (not currently in
  `usage` or `logs`) and cross-call aggregation, which is an **analytics surface no module in this product owns**
  · realtime: post-call · tool-surface: pure UI · **not adopted this pass** — not named by any of the four
  bullets, and percentile aggregation across many calls is reporting/analytics, which is outside the seven
  capabilities (see Out of scope) · deferred.
- **Cross-referencing a failed tool call to a separate "API log" surface** — Synthflow's design (a distinct API-log
  entity a call-log row links out to) · priority: differentiator · model: **would require a second table** — an
  explicit Invariant-2 violation for this product, where the tool call already lives as one more entry in the same
  `logs` list · **not adopted, ever** — this is exactly the pattern Invariant 2 forbids, kept here only to name why
  Synthflow's shape does not transfer.
- **Disconnection-reason enum as a first-class field** (Retell, Bland) — real and well-documented, but this
  product's `status` (five values) + the last `error`/`critical` log entry's `title`/`raw_json` already narrates
  the same fact without a new column; adding a dedicated enum field would be a schema change this VIEW sub-module
  must not make · priority: differentiator · model: none — render the existing signals instead · deferred.

## Compliance & provider constraints

- **REQUIRED — display-time redaction of tool-call arguments, independent of the write-path redaction Module 3
  will perform.** Author a small template filter (e.g. `redact_args`, alongside `level_badge`/`dict_get` in
  `apps/accounts/templatetags/ui.py`) that: takes a dict (`raw_json`, or its `arguments`/`variables` sub-key),
  returns a **new** dict, and for every key whose name **case-insensitively contains** one of a fixed denylist of
  substrings (`name`, `dob`, `birth`, `ssn`, `social`, `phone`, `email`, `address`, `zip`, `postal`, `card`, `cvv`,
  `credit`, `insurance`, `medical`, `diagnosis`, `symptom`, `password`, `secret`, `token`, `auth`) replaces the
  value with the literal string `[redacted]` — recursing one level into any nested dict (so `arguments.reason`,
  `arguments.caller_phone` etc. are caught even though the seeder already redacts them upstream). Every entry
  point that renders `raw_json` runs it through this filter first; **the raw stored value is never interpolated
  directly into a template, never `|safe`, and never logged** (this module's own "no logger, deliberately"
  convention holds — a debug page must not become the leak it exists to prevent).
- **REQUIRED — never log at INFO.** This sub-module adds no new logger, matching 5.1/5.2's stated convention;
  the one thing worth naming in a log line about this page (which tool ran, what argument it saw, which error
  fired) is exactly the PII/security-relevant content that must never reach INFO.
- **No NEW HIPAA/GDPR retention or subject-rights obligation.** `logs`/`usage` are read off the same
  `CallSession` row 5.1 already flagged for retention (Module 3.5's scheduled job, not a 5.x view concern); this
  sub-module introduces no second copy and no second retention clock.
- **No two-party-consent/recording-announcement obligation is triggered here** — that governs `recording_blob` and
  is 5.4's territory. `logs`/`usage` carry no recording-consent content.
- **Twilio / provider cost-line mapping.** `usage[].cost_breakdown`'s four keys map directly onto this product's
  four billable dimensions: `telephony_usd` ⇄ the Twilio voice-minute charge, `stt_usd` ⇄ the speech-to-text
  provider's per-second rate, `tts_usd` ⇄ the text-to-speech provider's per-character rate, `llm_usd` ⇄ the LLM's
  per-token rate. **This sub-module appends nothing to `usage`** — it is a pure reader — but by fixing the display
  contract (four named keys, summed to `cost_usd` per turn, summed again to the call total) it is also fixing the
  **write** contract Module 3's turn loop must honor when it starts appending real cost lines. No new provider call
  originates here, so no new rate-limit or concurrency exposure is introduced by this pass.

## Recommended build scope (this pass)

**VIEW sub-module — ZERO models and ZERO migrations.** `makemigrations calls --check` must report "No changes
detected." Everything below reads `CallSession.logs` / `.usage` already on the row; a `CallEvent`, `ToolCall`,
`LogEntry` or `CostLine` table here would be an Invariant 2 violation.

- **Tables READ:** `calls.CallSession` only (`logs`, `usage`). No other table is touched. (The existing
  `location_sessions(request)` helper in `apps/calls/views/_helpers.py` already provides the tenant+location-scoped
  queryset the detail view uses — nothing new to add there.)
- **Pages:** extend the existing `templates/calls/calllog/callsession/detail.html` inside its comment-marked slot
  with exactly the two cards its own comment already names:
  1. **Event log card** — implements Structured Event Log + Tool-Call Trace + Runtime Error Surface as ONE
     chronological timeline over `obj.logs` (ordered by `sequence`): a small "N error(s) on this call" / "No
     runtime errors" callout at the top, then one row per entry (`level_badge` for the level, `category`, `title`,
     `occurred_at`), tool-category rows visually distinguished, and a `<details>/<summary>` per row for the
     redacted, indented `raw_json`. Explicit "No events recorded yet" empty state for `logs == []`.
  2. **Cost breakdown card** — a table over `obj.usage` ordered by `turn_sequence`, one column per key present in
     `cost_breakdown` (open dict, not hard-coded to today's four keys) plus `cost_usd`, and a footer total row
     using the new `total_cost_usd` property (or a view-computed `sum()` if the property is deferred). Explicit
     "No usage recorded" empty state for `usage == []` (an abandoned call with a single greeting turn may still
     have exactly one row — not truly empty in the seed data today, but the template must not assume at least one
     row exists).
  - **No new route, no new view function** — both cards render inside the existing `callsession_detail_view` /
    `detail.html`, exactly like 5.2's transcript and analysis panels. No filters, no export — this is a read-only
    addition to an existing detail page, not a new list page.
- **One optional, zero-migration model addition:** `CallSession.total_cost_usd` — an `@property` in the existing
  `apps/calls/models/CallLogList/CallSessions.py`, same file, same pattern as the already-existing
  `duration_display` — `sum(turn.get('cost_usd', 0) for turn in self.usage)`, defaulting to `0` for an empty list.
  Purely a Python property; generates no migration.
- **New template filter(s)** in `apps/accounts/templatetags/ui.py`: `redact_args` (the denylist-based redaction
  helper described in Compliance above). **Reuse, don't duplicate,** the already-shipped `level_badge` and
  `dict_get` filters.
- **`LIVE_LINKS["5.3"]`**: add `{}` (empty dict) to `apps/accounts/navigation.py` — same posture as `'5.2': {}` —
  this sub-module's surfaces are reached through the existing `calls:callsession_detail` page 5.1's link already
  leads to; no new sidebar row.
- **Seeder extension (the one gap found):** add a `duration_ms` key to every `category == 'tool'` log entry's
  `raw_json` in `DEMO_CALL_SESSIONS` (`apps/calls/management/commands/seed_calls.py`) — a JSON-content edit to
  existing dict literals, no new spec rows, no schema change. Everything else (levels, categories, redacted
  arguments, the failed-tool-call envelope shape, error-level entries both recovered and fatal, cost breakdowns)
  is already present and needs no further seeding work. Note for whoever runs it: because the dedupe key is
  `provider_call_sid` and these are edits to EXISTING rows' content, a plain re-run of `seed_calls` will not pick
  up the new `duration_ms` values — `seed_calls --flush` is needed to see them on an already-seeded dev database
  (this is normal for editing hardcoded seed content, not a defect).

## Belongs to sibling sub-modules (parked, not scoped here)

- Session header, transcript panel, analysis panel, transcript print view → **5.2 Call Detail & Transcript**
  (already built).
- Waveform player, signed media access, the transfer-outcome panel → **5.4 Recording & Transfer Outcome** (reads
  `CallSession.waveform_peaks` / `.recording_blob` / `.transfer` — a different set of columns on the same row).
- Populating `logs`/`usage` from a real call (the turn loop, the tool dispatcher `apply_tool_call`, the write-path
  redaction step CLAUDE.md names) → **Module 3 (Call Runtime)**, unbuilt. 5.3 is a pure reading surface over
  columns Module 3 will one day write; it fixes the display contract those writes must honor.

## Out of scope for this product (outside the seven capabilities)

- **Cross-call latency percentile analytics (p50/p90/p95/p99 dashboards)** (Retell) — this is a reporting/BI
  surface over many calls, not one call's debugging page, and no module in this six-module catalog owns an
  analytics capability; would need its own explicit scoping pass if the product ever grows one.
- **Network-quality (QoS) monitoring — MOS score, jitter, packet loss** (Dialpad's System Test / QoS dashboard) —
  that is Twilio's own console's job (the transport layer), not an application-level call log; none of the seven
  capabilities calls for a telephony-quality diagnostics surface.
- **Human QA review workflow for AI call quality** (Smith.ai's "reviewed by humans, fed back into training") — this
  product has no human-reviewer role or feedback-loop workflow among its seven capabilities; call review here is a
  tenant user reading their own data, not a vendor's internal QA process.

## Deferred (later passes / integrations)

- **Per-turn/per-component latency figures** (would need a new `latency_ms`-shaped key in `usage` or `logs`,
  written by Module 3) — not named by any of this sub-module's four bullets; revisit only if Module 3's runtime
  ends up emitting timing data naturally and a later pass wants to surface it.
- **Highlight/sort by the most expensive turn** — a small polish item once the cost-breakdown table exists; no
  schema impact, safe to add later without touching this pass's scope.
- **A cross-referenced "API log" entity a tool call links out to** (Synthflow) — explicitly rejected as an
  Invariant 2 violation, not merely deferred; noted so nobody re-proposes it later as a "nice to have."
