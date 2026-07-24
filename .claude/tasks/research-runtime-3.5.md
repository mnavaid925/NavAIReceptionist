# Research — Sub-module 3.5: Recording, Teardown & Diagnostics (Module 3 — Call Runtime, `runtime`)

## Repo state checked first

**LIVE_LINKS built so far in module 3:** `3.1` → `runtime:diagnostics` (the one navigable page — Module 3's
observable surface). `3.2`, `3.3`, `3.4` are BUILT with **empty** dicts (consumer/dispatcher/transfer are not
pages; their outputs render through Module 5's pages). `3.5` is the module's last sub-module — after it, Module 3
is complete and `LIVE_LINKS['3.5']` will most likely stay `{}` too (its outputs extend the *existing* `3.1`
diagnostics page rather than adding a new one) unless the build finds a reason to split the page.

**Sibling models available to reuse (verified by grep):**
- `calls.CallSession` (`apps/calls/models/CallLogList/CallSessions.py`) — the one call log (Invariant 2). Already
  carries every JSON column 3.5 needs: `transcript`, `logs`, `analysis`, `usage`, `transfer`, `waveform_peaks`
  (`{caller, bot, bins}`, nullable), `metadata` (dict — **this is where the docstring explicitly says the
  recording consent basis and retention window live**), and `recording_blob` (private storage path string, `''` =
  none). The model docstring states in so many words: *"A NON-EMPTY `recording_blob` REQUIRES A CONSENT BASIS IN
  `metadata`... Module 3.5 does [validate this]... before persisting a recording path, confirm `metadata` already
  carries a resolved consent basis, and refuse the write... if it does not."* This sub-module is named by the
  model it will write into.
- `agents.AgentSetting` (`apps/agents/models/AgentConfiguration/AgentSettings.py`) — one row per location. **No
  recording-consent or recording-enabled field exists on it today.** Any "should this location record at all"
  toggle would be a new field — a 2.1/2.3 decision, not 3.5's to add unasked (the same posture `todo.md` already
  took for a custom decline message).
- `tenants.Location` (`apps/tenants/models/Location.py`) — already carries `state` (Char, blank) and `country`
  (Char, default `'US'`), plus `timezone`/`tzinfo`. This is exactly what a two-party-consent jurisdiction lookup
  needs, with **zero new field**.
- `apps/calls/storage.py` (5.4, already shipped) — `PrivateRecordingStorage` rooted at `PRIVATE_MEDIA_ROOT`
  (never `MEDIA_ROOT`), plus `recording_exists`, `open_recording`, `recording_size` (read side, used by the
  signed serve view) and **`save_recording(name, content)`**, whose docstring says outright: *"The paved write
  path for Module 3's recorder (unbuilt)... 5.4 reads; this is the symmetric write it says Module 3 owns."* 3.5's
  recorder calls this function — it does not reinvent file placement.
- `apps/calls/views/RecordingTransferOutcome/CallSessions.py` (5.4) — the signed-URL serve view
  (`calls:callsession_recording`), Range-request streaming, `RECORDING_ACCESS_SALT` / `RECORDING_SIGNED_URL_TTL`
  (`config/settings.py`) already resolved. 3.5 never touches this view; it only has to leave a valid
  `recording_blob` path behind for it to find.
- `apps/calls/management/commands/seed_calls.py` (5.1) — `_build_metadata()` **already seeds the exact shape**
  3.5 must produce for real: `{'recorded': bool, 'consent_basis': 'announced_notice' | 'not_recorded',
  'consent_announced': bool, 'retention_days': int}`, plus `direction`, `location_timezone`, `agent_version`,
  `provider_mode`. `_build_waveform()` seeds `{caller: [...], bot: [...], bins: N}`. These were written **ahead
  of any 3.5 code**, as the intended contract — 3.5's real writer must match this shape, not invent a new one.
  `recording_exists`'s own docstring notes 6 of 11 seeded rows have a `recording_blob` path with **no real file
  behind it** — a seeding gap 3.5 does not have to fix (seeding is Module 5's), but the real runtime path must not
  repeat it: a non-empty `recording_blob` from the live/fake recorder must always resolve to real bytes.
- `apps/runtime/agent/state.py` — `CallState.ended_reason`, whose own comment already calls it *"the seed of
  3.5's ended-reason diagnostics."* `apps/runtime/consumers/MediaStreamTurnLoop/MediaStream.py` — the closed
  `_STATUS_BY_REASON` map (`hangup`, `max_duration`, `idle_timeout`, `end_call`, `transferred`, `disabled`,
  `capacity`, `error`) and `_finalize()`/`_finalize_session()`, the ONE guaranteed-teardown path (idempotent via
  `self.finalized`, releases the capacity slot, flushes buffers, stamps `status`/`ended_at`/`metadata.ended_reason`
  inside `select_for_update()` — never overwriting a status 3.4 already advanced past `in_progress`).
- `apps/runtime/providers/audio.py` — `PlaybackTracker`, whose docstring says outright: *"3.2 only tracks this —
  the trimmed audio is persisted into `CallSession.recording_blob` by 3.5."* `frame_energy()` (RMS per PCM16
  frame) is the same primitive a waveform-peak binner needs.
- `apps/runtime/agent/turn.py` — already logs **per-stage timing** (`state.add_log('debug', 'asr', 'STT
  complete', {'ms': ...})`, same for `'llm'`/`'tts'`) and **per-turn cost** (`_cost_breakdown`,
  `state.add_usage(...)`) on every turn. 3.5 does not add a new cost/latency *write* — it reads what 3.2–3.4
  already wrote and renders it.
- `apps/runtime/views/InboundWebhook/Diagnostics.py` + `templates/runtime/diagnostics.html` (3.1, extended by
  3.4 with the transfer-outcome tally) — the diagnostics view's own docstring says it is *"the seed of the fuller
  diagnostics page 3.5 grows (per-stage latency, ended-reason codes, live-call count)."* 3.5 extends this exact
  view/template; it does not create a second page.
- `apps/runtime/management/commands/simulate_call.py` — `--script chat|booking|transfer`; 3.5 is the natural
  home for a `recording`/`diagnostics`-flavoured extension or scripted flag exercising the consent-gate and
  recorder path end to end under `PROVIDER_MODE=fake`.

**Models confirmed NOT to exist:** `apps/runtime/models/` does not exist (`grep "^class " apps/runtime/models/`
→ nothing); `manage.py makemigrations runtime --check` has reported "No changes detected" through 3.1–3.4 and
must keep doing so through 3.5. No `Recording`, `WaveformBin`, `LatencySample`, `RuntimeError` or `WebhookAttempt`
model exists anywhere in the repo, and none should be added by this pass.

## Leaders surveyed (with source links)

1. **Retell AI** — voice-agent platform with per-agent data-retention controls (1 day–2 years), selective PII
   redaction, and a documented zero-retention mode — [Data Storage Settings](https://docs.retellai.com/accounts/privacy-disable), [Legally Recording Phone Calls in the US](https://www.retellai.com/blog/legally-recording-phone-calls-in-the-us-how-does-it-work), [Enterprise Voice AI Compliance Guide](https://www.retellai.com/blog/enterprise-voice-ai-compliance-guide)
2. **Vapi** — call-analysis pipeline (`call.analysis.{summary, structuredData, successEvaluation}`) and a closed,
   documented `endedReason` enum surfaced in the call-log UI and API — [Call analysis](https://docs.vapi.ai/assistants/call-analysis), [Call ended reasons](https://docs.vapi.ai/calls/call-ended-reason), [Troubleshoot call errors](https://docs.vapi.ai/calls/troubleshoot-call-errors)
3. **Bland AI** — post-call status webhook firing on every terminal state (timeout, end-call node, opt-out) with
   the full transcript/duration/metadata attached — [Post Call Webhooks](https://docs.bland.ai/tutorials/post-call-webhooks)
4. **Twilio Voice Insights** — the reference implementation for a per-call, per-stage quality/latency dashboard
   (jitter, packet loss, latency, time-series views) — [Call Insights Dashboard](https://www.twilio.com/docs/voice/voice-insights/call-insights-dashboard), [Voice Insights: Advanced Features](https://www.twilio.com/docs/voice/voice-insights/advanced-features)
5. **Smith.ai** — call-detail view combining recording + speaker-labelled transcript + summary + disposition in
   one panel; 90-day recording retention with a manual download option — [Call Recording & Transcription](https://smith.ai/features/call-recording-transcription), [Using the Call Dashboard](https://docs.smith.ai/article/n40myw0flr-using-and-accessing-the-smith-ai-call-dashboard)
6. **Dialpad Ai** — AI Recaps (summary + outcome + action items) plus a transcript-synced player that jumps
   directly to a speaker's turn in the audio — [Call Summary: Transcript, Snippets, and Notes](https://www.dialpad.com/features/call-summary/), [AI Transcription](https://www.dialpad.com/features/ai-transcription/)
7. **Synthflow** — per-minute cost line broken out by voice engine vs. LLM tier, call duration/outcome tagging in
   a basic analytics dashboard — [Synthflow Pricing](https://zeeg.me/en/blog/post/synthflow-ai-pricing)
8. **PolyAI** — enterprise usage-based billing per minute; observability is largely an external-platform concern
   (own dashboard is thin) — same posture Vapi documents for its own product — [PolyAI Pricing vs. Alternatives](https://www.getvocal.ai/blog/polyai-pricing-vs-alternatives)
9. **Ruby Receptionists** — every conversation recorded by default, recordings/transcripts reviewable
   immediately in-app or via the mobile app — [Ruby FAQs](https://www.ruby.com/faqs/)
10. **Recording-consent case law / carrier guidance** (not a product, but the compliance bar every one of the
    above is built against) — [Twilio: Legal Considerations with Recording Voice and Video Communications](https://support.twilio.com/hc/en-us/articles/360011522553-Legal-Considerations-with-Recording-Voice-and-Video-Communications), [Two-Party Consent States (2026 Guide)](https://www.recordinglaw.com/party-two-party-consent-states/), [HIPAA Call Recording Requirements 2026](https://www.cloudtalk.io/blog/hipaa-call-recording-requirements/)

## Feature catalog (this sub-module only)

### Consent-Gated Recording
- **Jurisdiction-based consent-basis resolution** — decides one-party vs. two-party consent from the answering
  location's `state`/`country`, before the recorder is allowed to start · seen in: Retell AI (region-adaptive
  consent prompting), the recording-law compliance references (two-party-consent state list) · priority:
  **REQUIRED** · model: reuses `tenants.Location.state`/`.country` (read-only, no new field) + writes the
  resolved basis into `calls.CallSession.metadata.consent_basis` (tenant+location scoped via the row) · realtime:
  **live-call hot path** — must resolve before the recorder captures its first frame, in `_authorize_and_start`
  or the greeting step, alongside the existing `open_intervals`/`variables` setup · tool-surface: **no LLM tool**
  — this is a runtime/consumer decision, not something the model requests or sees · buildable now — a static
  two-party-consent state table (~12 US states) plus the existing `Location.state`/`.country` fields; no external
  dependency.
- **Announcement-before-record, and proof the announcement played** — plays a deterministic recording-consent
  line (same discipline as the deterministic greeting: 0 LLM tokens, server-rendered) before capture begins where
  the resolved basis requires it, and records that it was said · seen in: Retell AI (documented FCC-shaped
  recording-notice requirement), the two-party-consent "implied consent by continuing" doctrine every
  recording-law source describes, Smith.ai (recorded-call disclosure norm) · priority: **REQUIRED** · model:
  `CallSession.metadata.consent_announced` (bool, matches `seed_calls.py`'s own seeded shape) + the spoken line
  itself lands as a normal `assistant` row in `CallSession.transcript` (no new column — it is a turn like any
  other) · realtime: **live-call hot path** — gates the recorder, so it must complete (or be skipped where
  one-party consent applies) before any audio frame is captured for storage · tool-surface: prompt/runtime
  change — a new deterministic utterance analogous to `AgentSetting.greeting`, not a tool · buildable now.
- **Per-location "record calls" toggle** — whether this location records at all, distinct from the jurisdictional
  consent *basis* (a location may choose not to record even where one-party consent would allow it) · seen in:
  Retell AI (per-agent recording/storage settings), Smith.ai (opt-in/opt-out framing) · priority: common · model:
  would need a **new field on `agents.AgentSetting`** — flagged explicitly as **belonging to 2.1/2.3, not 3.5**
  (the same posture `todo.md` already recorded for a custom decline message) · realtime: n/a (config, read once
  per call) · tool-surface: none · **parked, not this pass** — 3.5 should default to "always record when consent
  allows" rather than block on a field it cannot add.
- **Consent-basis validation gate on the write path** — refuses to persist a non-empty `recording_blob` unless
  `metadata` already carries a resolved `consent_basis` · seen in: no single competitor documents this exact
  server-side invariant, but it is the direct, load-bearing instruction already written into the `CallSession`
  model's own docstring (quoted above) · priority: **REQUIRED** · model: application-level check in the finalize
  path (MySQL cannot portably assert on a JSON sub-key, so this is Python, not a `CheckConstraint`) · realtime:
  hot path (the check must run before the write that sets `recording_blob`) · tool-surface: none, pure runtime
  invariant · buildable now, zero dependencies.

### Guaranteed Teardown
- **Closed ended-reason vocabulary, formalized and surfaced** — `_STATUS_BY_REASON`'s eight keys
  (`hangup`/`max_duration`/`idle_timeout`/`end_call`/`transferred`/`disabled`/`capacity`/`error`) already exist as
  ad hoc strings written by 3.2–3.4; 3.5's job is to name them as a shared constant (so a ninth ended-reason
  string typo'd somewhere does not silently fall through `_STATUS_BY_REASON.get(reason,
  STATUS_COMPLETED)`'s default) and tally them on the diagnostics page · seen in: Vapi's documented `endedReason`
  enum with a dedicated reference page, Bland AI's terminal-webhook reason field · priority: table-stakes (every
  surveyed platform reports *some* closed end-reason) · model: reuses `CallSession.metadata.ended_reason`
  (already written by `_finalize_session`) — **no new column** · realtime: the write is already hot-path
  (`_finalize_session`); the tally/render is post-call, following the exact `Counter`-over-a-bounded-slice pattern
  `Diagnostics.py` already uses for `transfer_outcomes` (`_TRANSFER_RESULT_DISPLAY` / `_TRANSFER_TALLY_LIMIT`) ·
  tool-surface: pure UI · buildable now.
- **Recorder/teardown interaction: finalize a partial recording rather than losing it** — an abnormal
  disconnect (worker restart, unhandled carrier drop) must still leave whatever audio was captured on
  `recording_blob`/`waveform_peaks`, not silently discard it, mirroring the transcript/log/usage
  "flush-at-checkpoints, not buffer-to-the-end" discipline the model docstring already states · seen in: no
  competitor publishes this internal detail, but it is the direct extension of `_finalize()`'s own guarantee
  (idempotent, `self.finalized` latch, never raises) to a fourth artifact class · priority: REQUIRED for this
  product's own reliability bar (CLAUDE.md realtime rule 9) · model: writes into the same `CallSession` row
  inside `_finalize_session`'s existing `select_for_update()` transaction · realtime: hot path · tool-surface:
  none · buildable now, no new dependency — this is hardening existing code, not new infrastructure.
- **Stream-token single-use / replay claim** — closes the tracked 3.2 deferral: a still-valid signed stream token
  presented twice currently authorizes a second stream on one `CallSession`. The reviewer's own fix note says it
  needs *either* a `CallSession` field (a migration this service sub-module must not add) *or* a shared-cache
  SETNX claim · seen in: no consumer-facing competitor doc addresses this (it is Twilio-protocol-specific), but
  it is the load-bearing security fix this exact sub-module was named as the owner of · priority: **REQUIRED**
  (security) · model: **no new field** — a cache-backed SETNX claim (Django's cache framework, already a
  dependency; works with the locmem cache in tests and a real cache in prod) keyed on the token's `jti`/`sid`,
  TTL'd to the token's own short lifetime · realtime: hot path (`_authorize_and_start`, before the row is bound)
  · tool-surface: none · buildable now with the existing cache framework — explicitly the right design per the
  tracked deferral's own reasoning, since a `CallSession` field is the wrong answer for a zero-migration pass.
- **Cross-worker `MAX_CONCURRENT_CALLS`** — the per-process `_active_calls` counter only bounds one Daphne worker;
  the tracked deferral calls for a shared Redis/DB counter for the true fleet-wide ceiling · seen in: Vapi's own
  admission that agent-performance/capacity monitoring needs an external platform (Grafana/Datadog) once you
  outgrow the built-in dashboard · priority: common (an operational maturity feature, not consent/compliance) ·
  model: none owned by this app — needs a shared counter store · realtime: hot path gate · tool-surface: none ·
  **integration/later** — needs a cache backend this project has not yet chosen (Redis) beyond Django's default
  locmem/DB cache; flagged, not solved, in this pass.

### Waveform & Cost Capture
- **Caller/bot waveform peak-binning during the call** — accumulate RMS energy bins per channel as audio flows
  (reusing `audio.frame_energy` for the caller's inbound PCM and extending `PlaybackTracker`'s "frames actually
  sent" accounting to the bot channel, so a barge-in-truncated reply's peaks reflect only what was really played)
  and finalize into `{caller, bot, bins}` at teardown · seen in: Dialpad's audio-scrubbing player (implies
  binned peaks under the hood), the generic call-center waveform player pattern Smith.ai/Ruby's audio widgets
  use · priority: differentiator (few voice-AI-specific platforms document this explicitly; it is closer to a
  call-center-suite feature) · model: reuses `CallSession.waveform_peaks` (already exists, already read by 5.4's
  template) — **no new column** · realtime: **live-call hot path** for the incremental accumulation (cheap CPU,
  no I/O — same class of work as VAD's `frame_energy`), **post-call** for the final write in `_finalize_session`
  · tool-surface: none, pure DSP extension of `providers/audio.py` · buildable now, zero external dependency.
- **Per-turn cost breakdown — already shipped, this pass renders it, does not add fields** — `turn.py`'s
  `_cost_breakdown`/`state.add_usage` already appends the full native-audio vs. cascaded shape every turn; Vapi
  (line-itemized "Structured Output and Analysis fees"), Synthflow (per-minute engine + model cost) and PolyAI
  (usage-based per-minute billing) all confirm this is the table-stakes shape a voice-AI platform reports · seen
  in: Vapi, Synthflow, PolyAI · priority: table-stakes (already built in 3.2/3.3) · model: reuses
  `CallSession.usage` and the derived `.total_cost_usd` property — **no new work for 3.5 beyond surfacing an
  aggregate on the diagnostics page** (e.g. today's/this-location's total spend, mirroring the existing
  `stats.active`/`stats.total` aggregate pattern) · realtime: write already hot-path; the diagnostics aggregate is
  post-call · tool-surface: pure UI.
- **Structured call analysis (`summary` / `success_evaluation` / `extracted_data`)** — Vapi's documented
  `call.analysis.{summary, structuredData, successEvaluation}` is value-for-value the same shape as
  `CallSession.analysis` (`{summary, success_evaluation, extracted_data}`), confirming the existing column design
  matches the market's own convention · seen in: Vapi (Call analysis docs) · priority: table-stakes · model:
  `CallSession.analysis` already exists — **belongs to Module 5's rendering (5.2), not 3.5's write path**; 3.5 has
  no LLM-driven post-call analysis job in this pass (no such job exists yet anywhere in the runtime app) — noted
  for completeness, not scoped to build here.
- **Transcript-synced "jump to speaker turn" playback** — Dialpad's documented ability to "skip directly to
  different parts of the call audio" from the transcript · seen in: Dialpad AI, Smith.ai · priority:
  differentiator · model: pure UI reading `transcript` + `waveform_peaks` + the 5.4 recording stream — **belongs
  to Module 5 (5.2/5.4 rendering)**, not 3.5, which only has to make sure `transcript[].offset` (already written)
  and `waveform_peaks` line up on the same time axis so a later Module-5 pass CAN build this without a schema
  change.

### Runtime Diagnostics Page
- **Per-stage latency (STT / LLM / TTS), p50/p95 over recent calls** — `turn.py` already logs `{'ms': ...}` per
  stage into `CallSession.logs` (`category='asr'|'llm'|'tts'`); 3.5's job is to aggregate that into a rolled-up
  diagnostics stat for the active location, the same "bounded most-recent slice, computed in Python" discipline
  the existing transfer-outcome tally already uses (a JSON-key aggregate is not portably expressible across MySQL
  and SQLite) · seen in: Twilio Voice Insights (the reference per-call-quality dashboard: jitter/latency/packet
  loss with time-series and percentile framing), Vapi (community-documented ~550–800 ms end-to-end latency
  figures it surfaces per assistant) · priority: differentiator (Twilio Insights sets a high bar few AI-agent
  platforms match on their own dashboard; CLAUDE.md's own **≤1.5 s p50 / ≤3 s p95** budget makes this the natural
  metric to prove against) · model: reuses `CallSession.logs` — **no new column, no new table** · realtime: the
  writes are already hot-path; the percentile computation is **post-call**, read-time, bounded · tool-surface:
  pure UI.
- **Ended-reason breakdown tally** — see "Guaranteed Teardown" above; also belongs here as a diagnostics-page
  section, in the same `Counter`-over-`values_list(...)[:_LIMIT]` shape as the existing transfer-outcome card ·
  priority: table-stakes · model: reuses `CallSession.metadata.ended_reason` · realtime: post-call · tool-surface:
  pure UI.
- **Recent runtime errors panel** — a bounded, most-recent list of `logs` entries at `level='error'`/`'warning'`
  across the active location's sessions (STT/LLM/TTS failures, fallback-spoken events, finalize errors) · seen
  in: Vapi's dedicated "Troubleshoot call errors" doc/UI, Twilio's per-call Debugger/error surface · priority:
  common · model: reuses `CallSession.logs` — **no new table** (this is exactly the trap CLAUDE.md's "Flag any
  researched feature that would tempt a second call-log table" warns about: a `RuntimeError`/`ErrorLog` model is
  an Invariant 2 violation; the right shape is a bounded read over `logs` across recent sessions, matching what
  5.3 already does per-session) · realtime: writes already hot-path; the panel read is post-call · tool-surface:
  pure UI · buildable now.
- **Webhook / signature-failure health, made queryable** — 3.1's tracked deferral: today a closed reason-code set
  (`unmapped`, `disabled`, `signature_invalid`, `duplicate_delivery`, `provider_error`) is logged via structured
  `logging` only, because a **declined** call never creates a `CallSession` row to query. `todo.md` explicitly
  flags this as folding into 3.5's diagnostics *"once there is a model-worthy reason to query it."* · priority:
  common, but **explicitly the feature most likely to tempt a new model** (a `WebhookAttempt`/`InboundCallLog`
  table) — flagged here so it is not built that way. This pass's answer: **stay on structured `logging`**; if a
  UI panel is wanted, an in-process bounded ring buffer (non-persistent, per-worker, diagnostics-page-only,
  cleared on restart) is the ceiling, not a database table. Model: **none, deliberately** · realtime: the log
  write is already hot-path (webhook handler); a ring-buffer read is post-call, in-process only · tool-surface:
  none · **Deferred** — the research does not find this worth a persistent store yet; revisit only if a real
  operational need (not a dashboard nicety) appears.
- **Worker/process health (queue depth, thread/CPU)** — Vapi's own admission that this needs an external
  observability platform (Grafana/Datadog) once a deployment outgrows the built-in dashboard · seen in: Vapi ·
  priority: differentiator, and explicitly **out of this product's stated stack** (no Redis/Prometheus dependency
  exists anywhere in `config/settings.py` today) · model: none · realtime: n/a · tool-surface: none ·
  **integration/later** — the honest answer researched competitors themselves give: punt to infra tooling, don't
  build a bespoke one here.

### Fake Provider Path
- **`simulate_call` recording/consent script** — extends the existing `--script chat|booking|transfer` set with a
  path that exercises the consent gate, the announcement, and the fake recorder end to end, printing the
  resulting `recording_blob`/`waveform_peaks`/`metadata.consent_basis` the way the existing scripts print
  transcript/usage/status · seen in: every surveyed platform ships an analogous no-cost test/sandbox call path
  (Retell's playground test call, Bland's sandbox numbers, Vapi's test suite) — this product's own version is
  `simulate_call`, already the pattern to extend, not replace · priority: table-stakes for this product's own dev
  loop · model: none · realtime: n/a (dev-time only) · tool-surface: management-command flag · buildable now.
- **Fake recording backend** — a `FakeTelephonyBackend`-shaped adapter (same posture: it inherits/extends rather
  than reimplements) that, under any non-`live` `PROVIDER_MODE`, writes a small deterministic stub file through
  `apps.calls.storage.save_recording()` (so `recording_exists`/`open_recording` behave identically to the live
  path) rather than capturing real carrier audio — mirroring Retell AI's own "temporary recording, 10-minute
  expiry" zero-retention-mode framing as the nearest real-world analogue to "a fake mode that produces *something*
  playable without a real recording pipeline" · priority: **REQUIRED** (CLAUDE.md vulnerability rule 7: a non-live
  mode must never place/answer/record a real call) · model: none — a new adapter module
  (`apps/runtime/providers/recording.py`, `FakeRecordingBackend`/`LiveRecordingBackend`, resolved by a
  `get_recording_backend()` the same shape as `get_stt_backend`/`get_tts_backend`/`get_backend`) · realtime: hot
  path (buffers accumulate during the call; the backend's `finalize()` writes bytes + returns the stored path at
  teardown) · tool-surface: none, adapter method · buildable now, no external dependency for the fake; the live
  backend is the integration/later half (actual carrier-side recording, e.g. Twilio's `<Record>`/media-fork
  capture or transcoding the already-buffered PCM to a real audio file).

## Compliance & provider constraints

- **Recording-consent basis and disclosure — REQUIRED.** Every recorded call must have a resolved basis
  (`metadata.consent_basis`) before `recording_blob` is written, matching the model's own enforced-in-code
  invariant. The basis is jurisdiction-derived from `Location.state`/`.country` at the time of the call (recorded
  on the row, not recomputed later, per the model docstring's "the policy that applies is the policy at the time
  of the call").
- **Two-party-consent announcement — REQUIRED** in any location resolved to a two-party-consent jurisdiction
  (~12 US states per the recording-law references, e.g. CA, CT, FL, IL, MD, MA, MT, NV, NH, PA, WA — verify the
  exact list against `recordinglaw.com`'s current guide at build time, since state lists are occasionally
  revised). The spoken announcement and the fact that it played are both retained (`transcript` +
  `metadata.consent_announced`), giving an auditable record that "continued participation after disclosure"
  implied consent under the doctrine researched sources describe.
- **HIPAA retention — REQUIRED where a call touches PHI** (which, for this product, is *every* call — the agent
  books medical/dental/salon-style appointments and reads back a caller's name/DOB). HIPAA's own rule is "have a
  retention plan," not a fixed number; researched guidance puts practical retention at 6 years minimum (state law
  can extend it further). `metadata.retention_days` (already the seeded shape) is where the resolved window
  lives, per-recording, at the policy in force when the call happened.
- **GDPR retention & subject rights — REQUIRED for any EU-resident caller.** No product research found an EU-
  specific override needed beyond what `metadata.retention_days` + a purge job already model; the "subject rights"
  half (erasure/export on request) is a `Contact`-level concern already covered by `CallSession.contact`'s
  `SET_NULL` on delete (the call row survives; the identity link does not) — 3.5 adds nothing new here beyond
  making sure the retention window is actually enforced (see below).
- **Retention enforcement is currently unimplemented anywhere in the repo** — `metadata.retention_days` is
  written (by the seeder) and read by nothing. No Celery/beat exists in this stack
  (`grep -i celery config/settings.py` → nothing), so the right shape is a plain **management command**
  (`manage.py purge_expired_recordings`, tenant+location scoped, deleting the file via `recording_storage` and
  clearing `recording_blob` once `started_at + retention_days` has passed) runnable via OS-level cron/Task
  Scheduler — consistent with every other one-shot job in this project. **REQUIRED, buildable now, no new
  dependency** — flagged here so it does not get silently dropped as "just a dashboard feature."
- **Twilio rate limits / concurrency caps / per-unit cost.** No new Twilio REST calls are introduced by this
  sub-module (recording capture reuses the already-open media-stream websocket; it does not call Twilio's
  `<Record>` verb or the Recordings REST resource). The per-unit costs this sub-module's features append to
  `calls.CallSession.usage` are **none new** — `usage` is already fully populated by 3.2/3.3's STT-second /
  LLM-token / TTS-character / native-audio-second cost lines. Waveform binning and recording capture are local
  CPU/disk work with no external per-unit billing line, so they add no new `usage` entry — they write
  `waveform_peaks` and `recording_blob` instead, which is why they are separate columns and not folded into cost.

## Recommended build scope (this pass)

**SERVICE sub-module (Module 3) — ZERO models, ZERO migrations.** `manage.py makemigrations runtime --check` must
keep reporting "No changes detected." Confirmed by grep: `apps/runtime/models/` does not exist and none of this
pass's features need a field that is not already on `calls.CallSession` (its docstring literally names 3.5 as the
sub-module that fills `recording_blob`/`metadata`/`waveform_peaks` in) or `tenants.Location` (`.state`/`.country`,
already there). The features most likely to tempt a new model — the webhook-health log and the per-attempt
diagnostics list — are explicitly flagged above and answered with "stay on structured `logging` / an in-process
ring buffer," not a table.

**Services / adapters to name instead of models:**
- **`apps/runtime/providers/recording.py`** (new flat module, per the provider-package convention) —
  `get_recording_backend()` resolved by `PROVIDER_MODE` (mirrors `get_stt_backend`/`get_tts_backend`/
  `telephony.get_backend`); `FakeRecordingBackend` (buffers frames in memory, writes a small deterministic stub
  via `apps.calls.storage.save_recording()` under any non-`live` mode — never a real carrier recording);
  `LiveRecordingBackend` (deferred to integration — the actual audio-encode-and-store implementation, refusing to
  initialize unless `PROVIDER_MODE == 'live'`, per the standing fail-safe rule).
- **Consent-basis resolver** — a small pure function (e.g. `apps/runtime/agent/consent.py` or folded into
  `providers/recording.py`) taking `Location.state`/`.country` and returning `(consent_basis,
  requires_announcement)`. No model — a static two-party-consent state constant + the two existing `Location`
  fields.
- **Waveform binner** — an extension of `apps/runtime/providers/audio.py` (a `WaveformAccumulator` alongside the
  existing `PlaybackTracker`, reusing `frame_energy`) — pure DSP, no model.
- **`_finalize_session` extension** (`apps/runtime/consumers/MediaStreamTurnLoop/MediaStream.py`) — inside the
  same `select_for_update()` transaction that already stamps `status`/`ended_at`/`metadata.ended_reason`, also
  stamp `recording_blob` (from the recording backend's finalize call), `waveform_peaks`, and
  `metadata.{consent_basis, consent_announced, recorded, retention_days}`. One writer, same guaranteed-teardown
  path — not a second finalize step.
- **Diagnostics-page extension** (`apps/runtime/views/InboundWebhook/Diagnostics.py` +
  `templates/runtime/diagnostics.html`) — new sections following the exact pattern the transfer-outcome tally
  already established: (1) ended-reason tally, (2) per-stage latency p50/p95 over the bounded recent-session
  slice, (3) a recent-errors panel reading `logs` at `level in {error, warning}`, (4) a total-cost-today stat
  reusing `total_cost_usd`. `LIVE_LINKS['3.5']` stays pointed at (or is added as, if not already present)
  `runtime:diagnostics` — no new page.
- **`manage.py purge_expired_recordings`** (new management command, `apps/runtime/management/commands/`) —
  tenant+location scoped, enforces `metadata.retention_days` against `started_at`, idempotent (skips a row with
  no `recording_blob` or already past-purged), the observable retention-compliance surface.
- **`simulate_call --script recording`** (or a `--recording` flag on the existing scripts) — the fake-mode,
  no-carrier observable proof this whole path runs under `PROVIDER_MODE=fake`.
- **Cache-backed stream-token single-use claim** — closes the 3.2 tracked deferral using Django's existing cache
  framework (SETNX-equivalent `cache.add`), not a new model.

**Deferred/parked, so nothing here is lost:**
- Per-location "record calls" toggle (needs a new `AgentSetting` field) → **2.1/2.3**'s call.
- Cross-worker `MAX_CONCURRENT_CALLS` (needs a shared Redis/DB counter) → **integration/later**.
- The `<Dial action>` Twilio status-callback webhook for a true `no_answer`/`connected`/real `duration_seconds`
  → carried from **3.4**, still open.
- Worker/process health dashboard (queue depth, CPU) → **integration/later**, needs infra this stack doesn't have.
- A queryable webhook-health/per-attempt log → **deliberately not built as a model**; stays `logging` +
  optional in-process ring buffer.
- The actual `LiveRecordingBackend` audio encode/store implementation and any real vendor-side call-recording
  API → **integration/later**, once live credentials exist.
- LLM-driven post-call `analysis` generation (summary/success-evaluation/extracted-data) — the column exists,
  Vapi's docs confirm the shape is right, but no job populates it anywhere in this repo yet → **not scoped to
  this pass**, no research finding demands it be 3.5's.

## Belongs to sibling sub-modules (parked, not scoped here)

- Transcript-synced "jump to speaker turn" playback UI, the recording player itself, the call-detail transfer
  outcome card → **5.2 / 5.4** (already shipped as view sub-modules reading `CallSession`'s JSON columns — 3.5
  only has to keep producing data on the same time axis they already read).
- A per-location "record calls" toggle field → **2.1 / 2.3** (a new `AgentSetting` field, not this sub-module's
  to add).
- The `<Dial action>` status-callback webhook for a true transfer outcome → **3.4** (already tracked there).
- Seeding real recording bytes (today's `seed_calls.py` writes a path with no file behind it for some rows) →
  **Module 5 (`calls`)'s** seeder, if it is ever extended to call `save_recording()` for real bytes — not 3.5's
  file to edit.

## Out of scope for this product (outside the seven capabilities)

- **Post-call outbound webhooks to third-party systems** (Bland AI's and Retell's webhook-driven integration
  model) — this product has no documented external-integration capability among the seven; nothing in
  NavAIReceptionist calls for notifying an outside system when a call ends.
- **Worker/process/infrastructure health monitoring as a first-class product surface** (Grafana/Datadog-style
  dashboards) — outside the seven capabilities; the "Runtime Diagnostics Page" bullet is scoped to *call*
  diagnostics (latency, ended-reason, errors), not infra ops.
- **A full call-quality (jitter/packet-loss) telemetry dashboard** the way Twilio Voice Insights ships it for raw
  PSTN legs — this product's media leg is the Twilio-to-Django websocket, not a raw SIP trunk; per-stage
  *application* latency (STT/LLM/TTS) is the in-scope analogue, not carrier-level RTP quality metrics.

## Deferred (later passes / integrations)

- Live `LiveRecordingBackend` (actual audio capture/encode/store against a real vendor path) and any live
  telephony-side recording API — needs real credentials, an integration exercise once `PROVIDER_MODE=live` is a
  real target.
- Cross-worker `MAX_CONCURRENT_CALLS` shared counter — needs a chosen cache/queue backend (Redis) this stack
  does not yet declare.
- Worker/process health dashboard — explicitly the answer researched competitors themselves give ("connect to an
  external observability platform"), not a bespoke build here.
- A queryable, persistent webhook-attempt/per-request health log — deliberately kept off the model list; revisit
  only on a real operational need, not a dashboard nicety.
- LLM-driven `CallSession.analysis` population (summary/success-evaluation/extracted-data) — the column and its
  shape are already right (matches Vapi's own convention), but no job writes it yet anywhere in the repo; not
  this pass's job to add without a clearer trigger (which turn/event fires the analysis job is itself a design
  question for whichever pass takes it on).
- Exact two-party-consent state list validation against the live legal reference at build time (state consent
  laws are occasionally amended) — implementation detail for the build pass, not a research finding to freeze
  here.
