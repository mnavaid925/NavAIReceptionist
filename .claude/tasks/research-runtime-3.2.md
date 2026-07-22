# Research — Sub-module 3.2: Media Stream & Turn Loop (Module 3 — Call Runtime, `runtime`)

## Repo state checked first

- **`LIVE_LINKS` in `apps/accounts/navigation.py`**: `'3.1'` is the only Module 3 entry
  (`{'Runtime Diagnostics': 'runtime:diagnostics'}`). `'3.2'`…`'3.5'` are absent — 3.2 is the next unbuilt
  sub-module in Module 3, confirmed by resolving "3.2" directly against the real `### 3.2 Media Stream & Turn Loop`
  heading in `NavAIReceptionist.md`.
- **`apps/runtime/` already exists** (built by 3.1) — verified by `Glob`. What's there today:
  - `apps/runtime/webhooks.py` — the voice webhook (3.1), unaffected by this pass.
  - `apps/runtime/providers/base.py` — `PROVIDER_MODE` resolution (`active_mode()`, `is_live()`, `require_live()`,
    `LiveModeError`) — 3.2's STT/TTS/LLM adapters reuse this unchanged, no new mode logic.
  - `apps/runtime/providers/telephony.py` — pure Twilio TwiML/signature helpers. **No `get_backend()` yet**
    (deliberately deferred to 3.4) — 3.2 does not need it; the consumer never redirects a call, it only serves the
    stream.
  - `apps/runtime/providers/tokens.py` — `mint_stream_token` (3.1) / `verify_stream_token` (consumed here, in 3.2,
    for the first time) — the signed, short-TTL, opaque `{sid, ten, loc}` blob that authenticates the media socket.
  - `apps/runtime/routing.py` — **empty stub** (`websocket_urlpatterns = []`), and `config/asgi.py` is **not**
    wired to it yet. This is exactly the gap 3.2 fills.
  - `apps/runtime/consumers/`, `apps/runtime/agent/`, `apps/runtime/providers/audio.py`, `providers/vad.py`,
    `providers/stt.py`, `providers/tts.py`, `providers/llm.py` — **none of these exist yet** (grep returns nothing
    under `apps/runtime/consumers` or `apps/runtime/agent`). This sub-module builds them.
- **Sibling models verified to exist** (grepped, not assumed from the ERD):
  - `agents.AgentSetting` — `apps/agents/models/AgentConfiguration/AgentSettings.py`. Confirmed
    `voice_provider` choices are exactly `[('live', 'Live (realtime speech)'), ('google', 'Google'),
    ('gemini', 'Gemini')]`, default `'live'` — this is the field the consumer reads to pick which LLM/voice
    adapter to construct for the call. `greeting`, `prompt_text`, `variables` also confirmed present and are 2.1's
    fields this sub-module renders, not owns.
  - `calls.CallSession` — confirmed fields exactly as the ERD states: `transcript`, `logs`, `analysis`, `usage`,
    `transfer`, `waveform_peaks` (all JSON), `recording_blob` (Char, blank = no recording), `status`
    (`in_progress`/`completed`/`abandoned`/`transferred`/`failed`), `started_at`/`ended_at`. Created by 3.1's
    webhook with `status='in_progress'`; **this sub-module is the first writer of `transcript`, `logs`, `usage`**
    and the first to transition `status` away from `in_progress`.
  - `scheduling.Contact` — confirmed to exist. 3.2 does not create or query it directly (that's 3.3's
    `create_contact`/`search_contact` tool territory); the consumer only carries a `contact_id | None` in its
    per-call state for 3.3 to fill in later.
- **Conclusion for scope:** 3.2 is a **SERVICE sub-module**, same as 3.1. It adds **zero models**. Its job is the
  Channels consumer, the audio codec chain, the VAD/barge-in state machine, the off-loop discipline, and the
  bounded STT/TTS/LLM adapter calls — the mechanics that make the media socket a working, if toolless, phone call.
  The **12-tool declarations and `apply_tool_call` dispatcher are explicitly 3.3's**, not this pass's — 3.2 wires
  the turn loop to call an LLM adapter whose `tools` argument is an empty list for now, with the iteration-cap
  plumbing already in place so 3.3 only has to populate the tool table and the dispatcher branch.
- **`.claude/skills/voice-agent-runtime/SKILL.md` is the binding architecture contract** for this whole layer,
  authored during 3.1 and already fully specifying §3 (consumer lifecycle), §4 (audio chain), §5 (VAD/barge-in),
  §7 (turn loop), §11 (latency/cost budgets) and §12 (providers/fakes) — ahead of any 3.2 code existing. This
  research file does not re-invent that architecture; it grounds it against what the leading commercial products
  actually ship, confirms nothing there contradicts the market, and calls out the two or three places market
  practice suggests a refinement (turn-eagerness tuning, backchannel filler, multi-provider STT/TTS fallback) that
  the skill deliberately keeps out of this pass.

---

## Leaders surveyed (with source links)

1. **Vapi** — telephony-infrastructure voice-agent platform; publishes the most explicit turn-detection/barge-in
   internals of the group (a fusion audio+text model deciding true-interruption vs. backchannel, energy + voice
   classifiers, `user-interrupted` server events). The closest direct analogue to this sub-module's own barge-in
   job. — [How Vapi Works](https://github.com/VapiAI/docs/blob/main/fern/how-vapi-works.mdx),
   [Server events](https://docs.vapi.ai/server-url/events)
2. **Retell AI** — voice-agent platform with a named, tunable "Interruption Sensitivity" control and a shipped
   "Backchanneling" feature (short acknowledgement sounds during caller speech), plus public writing on its
   acoustic+LLM turn-taking fusion model. — [Retell AI's Turn-Taking Model](https://www.retellai.com/blog/how-retell-ais-turn-taking-model-ensures-seamless-calls),
   [Backchanneling changelog](https://www.retellai.com/changelog/latest-features-call-analysis-backchanneling-and-python-custom-llm-update),
   [Turn-Taking Endpoints glossary](https://www.retellai.com/glossary/turn-taking-endpoints)
3. **Bland AI** — a directly named "Interruption Threshold" (0–200, higher = more patient before responding) and
   a "Wait for Greeting" toggle (agent speaks first vs. waits for the caller), settable per node in a call
   pathway. — [Handling Inbound and Outbound Numbers](https://university.bland.ai/modules/2/lesson-4),
   [Advanced Pathway Features](https://university.bland.ai/modules/3/lesson-2)
4. **Synthflow** — ships a "Fade Out at Interruption" frame-count control (how abruptly the agent's own audio
   cuts vs. fades on barge-in) and a "Patience level" response-timing control, plus filler-word toggling —
   directly analogous to this sub-module's echo/playback-cancel behaviour and idle-prompt design. —
   [Call Configuration](https://docs.synthflow.ai/call-configuration),
   [Voice Configuration](https://docs.synthflow.ai/voice-configuration)
5. **PolyAI** — enterprise inbound-call platform (banks, hotels, healthcare); documents barge-in handling and
   sub-second-latency ASR/TTS orchestration as core claims, with independent evaluation putting real-world
   latency at 700–900 ms — useful ground-truth that even a well-funded enterprise platform sits near this
   product's own documented p95 budget, not far below it. — [PolyAI Developers](https://poly.ai/developers),
   [Latency Barrier analysis](https://cxfoundation.com/news/polyai-ravenv2-llm)
6. **ElevenLabs Conversational AI** — ships a named "Turn eagerness" control (`eager`/`normal`/`patient`), starts
   TTS after a comma rather than a full sentence to shave latency, and documents its turn-taking model reading
   filler tokens ("um", "ah") as continuation signals rather than end-of-turn. — [Conversation flow](https://elevenlabs.io/docs/eleven-agents/customization/conversation-flow),
   [How do you optimize latency for Conversational AI?](https://elevenlabs.io/blog/how-do-you-optimize-latency-for-conversational-ai)
7. **Dialpad AI** — the human-in-the-loop analogue (live transcription assisting a human agent rather than
   driving one) — its own docs emphasize adaptive jitter/packet-loss buffering to keep audio intelligible over a
   telephony leg, the same carrier-audio-quality problem this sub-module's codec chain solves for a fully
   automated call. — [Real-time Call Center Transcription](https://www.dialpad.com/features/call-center-transcription/)

**Supporting technical references** (not receptionist-market competitors, but the concrete mechanics several of
the leaders above build on top of, and the most precise public documentation of the exact primitives this
sub-module implements):

8. **Twilio Media Streams** — the actual wire format this sub-module decodes: μ-law (G.711) mono, 8 kHz,
   base64-encoded 20 ms frames in, and the identical encoding required going back out, with an explicit warning
   against including file-type header bytes in outbound payloads. — [Media Streams – WebSocket Messages](https://www.twilio.com/docs/voice/media-streams/websocket-messages)
9. **Deepgram** — the most precisely documented commercial VAD/endpointing parameter set available: `endpointing`
   (silence-duration threshold before finalizing), `utterance_end_ms` (a second, LLM-context-aware end-of-speech
   signal independent of endpointing) — the exact two-signal shape (energy-silence vs. sustained-end) this
   sub-module's own VAD state machine reproduces locally rather than via an ASR vendor flag. — [Understanding
   End of Speech Detection](https://developers.deepgram.com/docs/understanding-end-of-speech-detection),
   [Endpointing](https://developers.deepgram.com/docs/endpointing), [Utterance End](https://developers.deepgram.com/docs/utterance-end)
10. **LiveKit Agents** — publishes fallback-provider chaining for STT/LLM/TTS as a first-class primitive
    ("Fallback strategies") and a standalone open-weights turn-detector model layered on top of VAD — both direct
    inputs to this sub-module's "Bounded Provider Calls" and "VAD & Barge-In" bullets, and to the
    "Beyond the bullets" group below. — [Fallback strategies](https://docs.livekit.io/agents/logic/fallback-strategies/),
    [LiveKit turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector/)

---

## Feature catalog (this sub-module only)

### ASGI Media Consumer

- **One consumer instance owns all per-call state** (VAD counters, resampler state, playback bookkeeping, the
  turn task, deferred-transport flags) · seen in: every platform surveyed implicitly (none of Vapi/Retell/Bland/
  Synthflow expose a "session object" publicly, but their documented per-call settings — interruption threshold,
  fade frames, patience — are only coherent if scoped per active call, not global) · priority: table-stakes ·
  model: none — a Python object, `apps/runtime/consumers/MediaStreamTurnLoop/MediaStream.py`, holding a
  `CallState` dataclass; touches `calls.CallSession` (tenant + location scoped) only at defined checkpoints
  (start, per-turn flush, disconnect) · realtime: **live-call hot path** · tool-surface: none (infrastructure) ·
  buildable now — Channels/ASGI is already a project dependency, no external provider needed to accept a socket.
- **`connect()` authorizes via the signed stream token, never the URL** — resolves `tenant_id`/`location_id`/
  `session_id` from `providers.tokens.verify_stream_token()` (minted by 3.1), re-fetches the `AgentSetting` and
  `CallSession` rows, and joins a **tenant-and-location-namespaced** group before accepting · priority:
  **REQUIRED** — this is Invariant 3 applied to the one websocket surface with no Django session at all; a
  consumer trusting `tenant_id`/`location_id` read from the connect URL is the textbook cross-tenant vulnerability
  the skill and CLAUDE.md both call out by name · model: reuses `agents.AgentSetting` (read) and
  `calls.CallSession` (read then write), no new model · realtime: hot path, and it is the **first** gate — reject
  before accept, never accept-then-check · tool-surface: none · buildable now (no external dependency; the token
  scheme from 3.1 is already fully testable).
- **Re-check the number is still served at the `start` frame** — a number disabled between webhook-answer and
  stream-connect must not get served (this was flagged as belonging to 3.2 in the 3.1 research file) · priority:
  table-stakes (Synthflow's/Vapi's own active/inactive toggles imply the same TOCTOU window exists in every
  platform surveyed) · model: reuses `agents.AgentSetting.enabled`, re-read via the shared resolver function 3.1
  already exposes · realtime: hot path · tool-surface: none · buildable now.
- **Frame handling stays cheap; a completed utterance dispatches as a background task** (`asyncio.create_task`),
  guarded by a `turn_busy` flag with a **single-slot pending queue** for an utterance captured mid-turn · seen in:
  Gladia's own published guidance on concurrent voice pipelines names exactly this race — "uncoordinated updates
  [to shared conversation state] can lead to inconsistent state" — and recommends atomic/event-sourced state
  handling, which a single-slot pending queue satisfies without a full event-sourcing rewrite · priority:
  table-stakes (Vapi's `user-interrupted` event semantics — "no further events fire for the interrupted turn" —
  only make sense if the platform already has this exact single-in-flight-turn discipline) · realtime: hot path ·
  tool-surface: none · buildable now.
- **`disconnect()` is guaranteed teardown**: cancel the outbound playback task and the in-flight turn task, close
  provider sessions, flush buffered `transcript`/`logs`/`usage` onto `CallSession`, stamp `ended_at`/`status`. Runs
  on abnormal termination too (a carrier drop is the normal case) · priority: **REQUIRED** — CLAUDE.md's realtime
  rule 9 states this plainly, and it is the only place a call's data ever reaches the database in this design ·
  model: writes `calls.CallSession` (tenant + location scoped) · realtime: the flush is triggered by the hot path
  ending, but the write itself is not itself latency-sensitive (the call is already over) · tool-surface: none ·
  buildable now.

### Audio Codec Chain

- **μ-law 8 kHz ⇄ PCM16 16 kHz (STT) / 24 kHz-or-16 kHz (TTS, provider-dependent) with persistent inbound
  resampler state** · seen in: Twilio's own Media Streams spec confirms the wire format this sub-module must
  match exactly (8-bit μ-law mono, 8 kHz, 20 ms/160-byte frames, no header bytes on the outbound payload); the
  16/24 kHz internal rates are this product's own choice (matches native-audio "live" mode vs. cascaded
  "google"/"gemini" modes on `AgentSetting.voice_provider`) rather than a vendor requirement · priority:
  table-stakes (every platform surveyed transcodes somewhere in its stack; only Twilio's own doc states the exact
  wire contract this sub-module must satisfy on the carrier leg) · model: none — pure functions in
  `apps/runtime/providers/audio.py` (`mulaw_to_pcm16`, `pcm16_to_mulaw`, a stateful `Resampler` class) · realtime:
  hot path, on every 20 ms frame in both directions · tool-surface: none · buildable now — no external provider
  needed, this is DSP math.
- **Thread resampler state across inbound frames; give each outbound synthesis a fresh resampler** — a fresh
  state per inbound frame produces an audible click at every 20 ms boundary · priority: table-stakes engineering
  detail, not something any competitor markets but one every one of them must have solved (an audible click every
  20 ms would be an instantly-noticed defect in a product like Vapi/Retell/PolyAI) · model: none · realtime: hot
  path · buildable now.
- **Pace outbound frames — one 20 ms frame, `await asyncio.sleep(0.020)`, repeat** rather than dumping the whole
  synthesized blob at once · priority: table-stakes (this is *why* barge-in works at all on every platform
  surveyed — Synthflow's own "Fade Out at Interruption / N frames" setting is only meaningful if outbound audio is
  already frame-paced and therefore cancellable mid-stream) · realtime: hot path · buildable now.
- **Account only for audio actually played when writing the recording** — barge-in cancels the outbound task
  mid-blob; the played prefix (cut on an even frame boundary, proportional to frames actually sent) is what gets
  recorded, not the full synthesized blob · priority: differentiator (a subtle correctness point none of the
  surveyed products document publicly, but the failure mode — a QA reviewer hearing agent audio that was actually
  cut off mid-word on the call — is exactly the kind of defect a two-party-consent playback review would surface)
  · model: none in 3.2 itself (3.2 tracks "frames actually sent" in its own playback state; **3.5 is what
  persists the trimmed audio into `recording_blob`** — see the sibling-scope note below) · realtime: hot path
  (the tracking), post-call (the eventual write) · buildable now for the tracking; the persistence is 3.5's.

### VAD & Barge-In

- **Energy-threshold VAD with named, tunable constants — never magic numbers inline** (energy threshold, minimum
  speech duration, end-of-speech silence window, maximum utterance cap, echo cooldown, barge-in grace, barge-in
  sustain) · seen in: Deepgram's `endpointing` parameter (silence-duration-before-finalize, default 10 ms,
  developer-tunable) and `utterance_end_ms` (a second, independent end-of-speech signal) are the most precisely
  published commercial version of this exact two-signal design; LiveKit's Silero-VAD-based turn detector is the
  open-source analogue · priority: table-stakes · model: none — constants + a small state machine in
  `apps/runtime/providers/vad.py` · realtime: hot path, evaluated on every inbound frame · tool-surface: none ·
  buildable now — this is local DSP/heuristics, no external provider call.
- **Utterance end = speech seen for ≥ minimum duration AND silence for the end-silence window, OR the hard
  utterance cap fires** · seen in: Deepgram's `endpointing` + `utterance_end_ms` combination is exactly this
  two-condition design, expressed as two independently tunable timers · priority: table-stakes · realtime: hot
  path · buildable now.
- **Pre-roll buffering** — keep a bounded window of pre-speech audio so the first syllable is never clipped, and
  trim it while idle so a silent line cannot grow the buffer unbounded · priority: table-stakes (an un-buffered
  VAD clipping the caller's first word is one of the most commonly cited voice-AI defects in the barge-in
  literature surveyed) · realtime: hot path · buildable now.
- **Barge-in fires only on SUSTAINED speech past a grace window after playback starts** — a cough, a click or a
  line pop must not cut the agent off · seen in: Vapi's own description of a "custom fusion audio-text model to
  know when there is a true interruption" and industry benchmarks citing a 2026 production bar of "barge-in
  latency < 400 ms, false-barge-in rate < 2%, missed true interruptions < 1%"; Bland AI's tunable "Interruption
  Threshold" (0–200, higher = more patient) is the same knob exposed as a slider; Synthflow's "Fade Out at
  Interruption" frame count tunes how the cutoff *sounds* once triggered, a related but distinct knob · priority:
  **table-stakes among the named leaders, closer to differentiator in its exact tuning** (every platform surveyed
  ships SOME form of this control; the specific threshold values are proprietary and iteratively tuned in
  production, which is exactly why the skill mandates named constants in one module rather than hardcoded inline
  numbers — they are expected to move) · model: none · realtime: hot path · tool-surface: none · buildable now
  with a first, conservative constant set; **tuning against real production audio is an integration/later
  activity**, not something a first pass can get "right" without traffic.
- **Echo guard: suppress listening while the agent is playing and for a short cooldown after** — without it the
  agent's own synthesized audio arrives back as caller speech and the call devolves into the agent interviewing
  itself · priority: table-stakes (an unaddressed defect class in any cascaded pipeline; native-audio "live" mode
  is somewhat more resistant but this product supports `google`/`gemini` cascaded modes too, so the guard is
  needed regardless of `voice_provider`) · realtime: hot path · buildable now.
- **Idle handling**: a configured idle prompt after a period of caller silence, then a bounded no-response
  timeout (45 s per CLAUDE.md) ends the call with an explicit ended-reason · seen in: Bland's "Wait for Greeting"
  toggle and every surveyed platform's own no-input handling · priority: table-stakes · model: writes
  `calls.CallSession.status` (`'abandoned'`) and an ended-reason into `.logs` at teardown · realtime: hot path
  (the timer), the resulting write is post-call · buildable now.

### Off-Loop Work

- **No sync ORM, no sync `requests`/`httpx.Client`, no `time.sleep`, no file I/O, no blocking SDK call inside an
  `async def`** — `database_sync_to_async`, `sync_to_async(thread_sensitive=False)` or `asyncio.to_thread` for
  every one · seen in: Gladia's own published production-lessons piece names this exact class of defect
  ("race conditions in conversation state," "timeout and retry feedback loops") as the dominant failure mode in
  concurrent voice pipelines, and prescribes event-sourced/atomic state updates plus exponential backoff with
  jitter — directly informing both this bullet and "Bounded Provider Calls" below; LiveKit's worker-per-job
  process isolation is the more extreme version of the same principle (isolate a call's blocking risk from every
  other concurrent call) · priority: **REQUIRED** — a blocking call on the event loop freezes audio for *every*
  concurrent call on that worker, not just one caller's; CLAUDE.md's realtime rule 1 states this as a hard rule,
  not a style preference · model: none · realtime: this bullet exists *because of* the hot path — its violation
  degrades every other concurrent call, which is the single most expensive bug class named in the skill · tool-
  surface: none · buildable now.
- **WAV assembly and recording upload run in a thread** (`asyncio.to_thread`), not on the event loop · priority:
  table-stakes engineering discipline · this specific piece is **3.5's territory** (consent-gated recording), but
  the *rule* it follows is 3.2's to establish and enforce project-wide, so it is named here for completeness and
  parked below.
- **Post-call analysis (`analysis.summary`/`success_evaluation`/`extracted_data`) is enqueued, not computed
  inline** — an LLM call to summarize the transcript is itself an external provider call and must not block
  `disconnect()` · priority: common among the platforms surveyed (every one of Vapi/Retell/Synthflow ships a
  post-call analysis feature, universally computed after the call ends, never synchronously in the hang-up path)
  · model: writes `calls.CallSession.analysis` (JSON dict) — the *trigger* is 3.2's (enqueue at disconnect); full
  analysis-quality tuning is out of this pass's depth and noted under Deferred.

### Bounded Provider Calls

- **Explicit timeout + bounded retry on every STT/TTS/LLM call, degrading to a spoken fallback, never dead air**
  · seen in: LiveKit's "Fallback strategies" doc states the pattern precisely — "fallback adapters trigger on any
  error from the primary provider, including connection failures, timeouts, HTTP errors, and mid-stream
  disconnects" — and Gladia's concurrency piece independently arrives at "exponential backoff with jitter,
  circuit breakers, and load shedding" for the same problem · priority: **REQUIRED** — CLAUDE.md's realtime rule
  4 and the skill's §11 latency table both state this as non-negotiable, and it is this sub-module's own named
  bullet · model: none — a small retry/timeout wrapper per adapter interface (`stt.transcribe`, `tts.synthesize`,
  `llm.generate`), living in `apps/runtime/providers/{stt,tts,llm}.py` · realtime: hot path · tool-surface: none ·
  buildable now for the timeout/retry/fallback mechanics themselves (pure `asyncio.wait_for` + bounded loop, no
  live credential needed to test against a fake that can be made to fail on command); the **live** adapter
  implementations are integration/later (need real STT/TTS/LLM credentials).
- **Cross-vendor fallback chaining (not just retry-the-same-provider)** — "a Claude-to-Claude fallback won't help
  during an Anthropic outage because both calls hit the same upstream" (LiveKit's own stated constraint); TTS
  fallback across providers when using a cloned voice · priority: differentiator among the infra platforms
  surveyed (Vapi/Retell/Synthflow do not publicly document multi-vendor STT/TTS/LLM chaining as a customer-facing
  feature — LiveKit is the one that names it explicitly) · model: reuses `agents.AgentSetting.voice_provider`
  (currently one of `live`/`google`/`gemini`, a single choice, not a chain) — a genuine cross-vendor fallback
  chain would need a **new field** on `AgentSetting` to name a secondary provider, which is a 2.1 decision, not
  this sub-module's to make unasked · realtime: hot path if it existed · tool-surface: none · **deferred** — this
  pass implements retry-with-backoff against the *same* configured provider plus a spoken-fallback degrade path
  (matches the mandatory bullet exactly); a true secondary-vendor failover is parked, see Deferred below.
- **Filler speech only when a genuinely slow lookup is starting, never as a standalone stall** ("let me check that
  for you") · seen in: this is the skill's own §7 rule, and it matches the market's general practice of only
  inserting a filler utterance tied to an actual pending operation rather than a fixed delay · priority:
  table-stakes · model: none · realtime: hot path, and it is itself zero-provider-cost if the filler line is a
  pre-recorded/canned TTS clip rather than a fresh synthesis call · tool-surface: none (a runtime behaviour, not
  an LLM tool — the model never asks for a filler) · buildable now.
- **Per-call cost ceilings (max duration, max turns) as a security control, not just a UX one** · seen in: this
  is CLAUDE.md's own explicit framing ("Cost is a security control") and matches the skill's §11 budget table
  (`MAX_TOOL_ITERATIONS=4`, `IDLE_TIMEOUT_SECONDS=45`, `MAX_CALL_SECONDS` default 900) · priority: **REQUIRED** —
  a looping or prompt-injected agent must not be able to burn unbounded provider spend on a single inbound call ·
  model: writes `calls.CallSession.usage` (per-turn `{turn_sequence, cost_breakdown, cost_usd}`, appended, never
  re-aggregated) · realtime: hot path (the ceiling check), post-call (the persisted total is a sum over the list,
  never stored) · tool-surface: none · buildable now.

### Beyond the bullets

- **Tunable turn-eagerness / interruption-sensitivity as a first-class per-agent setting** · seen in: Retell's
  "Interruption Sensitivity" slider, ElevenLabs' "Turn eagerness" (`eager`/`normal`/`patient`), Bland's
  "Interruption Threshold" (0–200), Synthflow's "Patience level" — **four of the seven leaders surveyed expose
  this as a customer-configurable control**, not just an internal constant · priority: differentiator (strong
  signal, but a genuine product decision, not just an engineering one) · model: this pass ships it as **named
  constants in `apps/runtime/providers/vad.py`** (per the skill's own instruction), tenant/location-invariant;
  making it *configurable per location* would need a new field on `agents.AgentSetting` — a 2.1 decision · realtime:
  hot path · tool-surface: none · **deferred** as a configurable surface — the underlying mechanism (a tunable
  grace/sustain window) is buildable now as constants; exposing it as a form field belongs to a future pass on
  2.1, noted so the research is not lost.
- **Backchannel filler ("uh-huh", "I see") spoken WHILE the caller is still talking**, distinct from the
  slow-lookup filler above · seen in: Retell's shipped "Backchanneling" feature ("small noises… to improve
  engagement… configurable how often and what words") · priority: differentiator (only one of the seven leaders
  surveyed ships this explicitly) · model: none · realtime: hot path — and a genuinely risky one: injecting agent
  audio *during* active caller speech directly interacts with the echo guard (which exists precisely to prevent
  the agent's own audio from being mis-read as caller speech) and could re-trigger VAD in a way that corrupts
  the utterance being captured · tool-surface: none · **deferred** — the interaction with the echo guard needs its
  own design pass once the base VAD/barge-in state machine is proven in production; shipping it in the same pass
  as the base VAD implementation is exactly the kind of scope creep this research step exists to catch.
- **Cascade (STT→LLM→TTS) vs. native-audio speech-to-speech as two distinct provider-call shapes to bound** ·
  seen in: `AgentSetting.voice_provider = 'live'` reads as this product's native-audio mode (one combined
  provider leg, matching the skill's "24 kHz for native-audio models" note), while `'google'`/`'gemini'` are
  cascaded modes (three separately boundable legs: STT, LLM, TTS) — the general market debate ("cascade vs.
  speech-to-speech," surfaced independently in the research) is a direct, concrete input to how "Bounded Provider
  Calls" must be implemented: the native-audio adapter has ONE timeout/retry envelope per turn, the cascaded
  adapters have THREE, each independently boundable and independently able to degrade to a fallback · priority:
  table-stakes engineering consequence of a decision `agents.AgentSetting` already made in 2.1, not a new feature
  to build, but the concrete reason the adapter interfaces (`stt.transcribe`, `tts.synthesize`, `llm.generate`)
  must stay separable rather than being collapsed into one "generate audio reply" call · model: reuses
  `AgentSetting.voice_provider` (read-only here) · realtime: hot path · buildable now.
- **A management command that drives a full fake call through the real consumer path end-to-end** —
  `manage.py simulate_call`, opening a `WebsocketCommunicator` against `config.asgi.application` with
  `PROVIDER_MODE=fake`, sending synthesized Twilio-shaped `start`/`media`/`stop` frames, and printing the
  resulting `CallSession.transcript`/`.logs`/`.usage` · seen in: none of the surveyed commercial platforms
  publish an equivalent (they are all closed SaaS), but it is the direct analogue of Vapi's/Retell's own
  "test call" / "simulate a call in the dashboard" UX, expressed here as the CLI-first tool this project's own
  conventions favour · priority: differentiator (this project's own observable-surface obligation for a service
  sub-module, satisfied concretely) · model: none, reads/writes `calls.CallSession` through the real path ·
  realtime: exercises the hot path under test conditions, itself run post-call/administratively · tool-surface:
  none · buildable now — this is the concrete shape of 3.2's contribution to the CLAUDE.md-mandated "at least one
  observable surface."
- **Active-call count on the diagnostics page becomes meaningful once 3.2 ships** — 3.1's diagnostics page
  already computes `CallSession.objects.filter(tenant=t, location=l, status='in_progress').count()` (the
  "derived, never stored" pattern from the ERD §5); it reads as zero today because nothing transitions a session
  out of `in_progress` yet. 3.2 makes that number real by being the first code that sets `status` to a terminal
  value at `disconnect()` · priority: table-stakes (Retell's "Live Monitoring," Vapi's in-progress call view) ·
  model: no new counter — reuses the existing query · realtime: post-call/administrative (the query), hot path
  (what makes it correct) · buildable now, and requires no new page — 3.1's existing diagnostics template already
  renders it.

---

## Compliance & provider constraints

- **PII discipline is REQUIRED and this sub-module is where it first bites for real.** 3.1 only ever logged a
  closed reason-code enum; 3.2 is the first code in this project that actually holds raw audio, live transcript
  text and tool-adjacent caller data in memory on every frame. Never log a transcript body, a raw audio payload,
  or a caller number at INFO — CLAUDE.md's vulnerability rule 5 and the skill's §14 PII paragraph both state this
  identically. `logs` entries persisted onto `CallSession` carry redacted argument blobs, never raw ones.
- **No synchronous work on the event loop is REQUIRED**, not a style preference — CLAUDE.md's realtime rule 1
  and the skill's §3 "async discipline" both frame a blocking call here as the single most expensive bug class in
  the product (it degrades *every* concurrent call on the worker, not just the offending one). Treated with the
  same non-optional weight the 3.1 research file gave signature verification.
- **The deterministic greeting must still never wait on an LLM** — this sub-module is what actually *plays* the
  greeting `AgentSetting.greeting` renders (2.1 authored the field; 3.2 is the first code path to speak it), so it
  is the enforcement point for CLAUDE.md's realtime rule 5 and the skill's §6, not just an inherited property.
  Zero LLM tokens, first audio immediate, non-interruptible until it finishes playing.
- **Recording consent, the two-party-consent announcement and its retention window remain explicitly NOT this
  sub-module's concern** — same scope boundary the 3.1 research file drew and this file reaffirms: 3.2 tracks
  "which audio frames were actually played" (needed for barge-in-accurate playback tracking) but does **not**
  persist `recording_blob`, does **not** gate on consent, and does **not** write `waveform_peaks`. That is 3.5's
  "Consent-Gated Recording" and "Waveform & Cost Capture" bullets. Naming it here only to be explicit that its
  absence in this file is deliberate, not an oversight — a recording capability shipped from 3.2 without a
  consent gate would be a live compliance violation, not a scoping shortcut.
- **AI-interaction disclosure** — 3.1 already established the pre-stream `<Say>` as one legitimate place to
  satisfy a jurisdiction's disclosure requirement; 3.2 must not undermine it by, e.g., letting the greeting
  interrupt or race that announcement. No new disclosure obligation is introduced by this sub-module itself.
- **Cost implication — what this sub-module appends to `calls.CallSession.usage`:** every completed turn appends
  one `{turn_sequence, cost_breakdown, cost_usd}` entry. `cost_breakdown` composition depends on `voice_provider`:
  native-audio (`live`) mode reports input/output **audio tokens** plus any text tokens; cascaded modes
  (`google`/`gemini`) additionally report **STT cost** (typically per audio-second) and **TTS cost** (typically
  per character synthesized) as separate line items within the same breakdown, alongside the LLM's input/output
  **text tokens**. This is the first sub-module to write *any* line into `.usage` — 3.1 appended nothing (see the
  3.1 research file's compliance section).
- **Twilio Media Streams / carrier constraints**: the wire format is fixed (μ-law 8 kHz, 20 ms/160-byte frames,
  no header bytes on outbound payloads) — a malformed outbound frame is a silently broken call, not an error
  Twilio surfaces clearly. Twilio itself continues metering the call leg by voice-minute regardless of what this
  sub-module does with the stream (per the ERD's "derived, never stored" table, this product does not meter
  minutes anywhere) — that carrier cost is real but out of this application's own accounting.
- **STT/TTS/LLM provider rate limits and concurrency caps** are a real constraint on the bounded-retry design:
  most commercial STT/TTS APIs (the class Deepgram/ElevenLabs represent) cap concurrent streaming connections per
  account/tier, and an aggressive retry-without-backoff on a rate-limited response (`429`) would compound an
  outage across every concurrent call on the tenant rather than isolate it. The retry wrapper must distinguish a
  `429`/rate-limited response (back off, do not hammer) from a `5xx`/timeout (retry per the bounded policy) —
  Gladia's own published guidance ("exponential backoff with jitter, circuit breakers, load shedding") is the
  concrete shape to follow, buildable and testable now against a fake that can be told to return either failure
  mode on command.

---

## Recommended build scope (this pass)

**This is a SERVICE sub-module — zero models, zero migrations attributable to 3.2.** It touches two already-built
models (`agents.AgentSetting` read-only, `calls.CallSession` written for the first time on `transcript`/`logs`/
`usage`/`status`/timestamps) and adds no table of its own. The build scope is the consumer, the audio chain, the
VAD/barge-in policy, the provider-adapter interfaces + their fakes, and the observable surface:

- **The media-stream consumer** — `apps/runtime/consumers/MediaStreamTurnLoop/MediaStream.py`, re-exported from
  `consumers/__init__.py`, one instance per call. `connect()` verifies the stream token (never the URL), resolves
  tenant + location + `AgentSetting` + `CallSession`, re-checks the number is still served, and joins a
  tenant-and-location-namespaced group before accepting. `receive()` decodes `connected`/`start`/`media`/`stop`/
  `mark` frames, feeds VAD, dispatches a completed utterance as a background task guarded by `turn_busy` + a
  single-slot pending queue, wraps the loop body so one bad frame cannot kill the call. `disconnect()` cancels
  in-flight tasks, closes provider sessions, flushes `transcript`/`logs`/`usage` onto `CallSession`, stamps
  `ended_at`/terminal `status`, and enqueues post-call analysis — never raises.
- **`routing.py` gains the media-stream route** (`/ws/media-stream/`), and `config/asgi.py`'s
  `ProtocolTypeRouter["websocket"]` is wired to `apps.runtime.routing.websocket_urlpatterns` for the first time.
- **The audio codec chain** — `apps/runtime/providers/audio.py`: μ-law ⇄ PCM16 conversion, a stateful `Resampler`
  threaded across inbound frames (fresh state per outbound synthesis), 20 ms outbound frame pacing, and
  played-prefix tracking for barge-in-accurate playback bookkeeping (the actual recording write stays 3.5's).
- **The VAD/barge-in state machine** — `apps/runtime/providers/vad.py`: named constants (energy threshold, min
  speech duration, end-silence window, max utterance cap, echo cooldown, barge-in grace, barge-in sustain), the
  utterance-end detector, pre-roll buffering, the sustained-speech-only barge-in trigger, the echo guard, and the
  45-second idle timeout → `'abandoned'` teardown path.
- **The provider adapter interfaces + fakes** — `apps/runtime/providers/stt.py`, `tts.py`, `llm.py`: narrow async
  interfaces (`stt.transcribe(pcm, rate)`, `tts.synthesize(text) -> (pcm, rate)`,
  `llm.generate(history, system, tools) -> (text, tool_calls, usage)`), each with an explicit `asyncio.wait_for`
  timeout and a bounded retry that distinguishes rate-limited (`429`, back off) from transient (`5xx`/timeout,
  retry) failures, degrading to a spoken fallback line on exhaustion. **Every adapter ships its fake in the same
  pass** — deterministic synthetic audio, canned transcripts, a scripted no-tool-calls response (since 3.3 has not
  landed the tool table yet) — never a mock, so the adapter contract itself is what tests exercise. The `llm`
  interface's `tools` parameter accepts an empty list cleanly today; 3.3 is what populates it and adds the
  dispatcher branch, without changing this interface's shape.
- **The turn loop**, wired to `MAX_TOOL_ITERATIONS = 4` and `IDLE_TIMEOUT_SECONDS = 45` /
  `MAX_CALL_SECONDS = 900` (both named constants, not inline literals): utterance → STT → history append → LLM
  generate → (no tools available yet, so this pass's loop always falls straight to) → TTS → paced outbound frames.
  The iteration-cap and deferred-transport check points are wired now so 3.3 (tools) and 3.4 (transfer) plug in
  without reshaping the loop.
- **The observable surface**: a `manage.py simulate_call` management command exercising the whole path end-to-end
  under `PROVIDER_MODE=fake` via `WebsocketCommunicator`, printing the resulting `CallSession` transcript/logs/
  usage — plus the fact that 3.1's existing `runtime:diagnostics` page's "active calls" stat becomes meaningful
  for the first time once this sub-module correctly transitions `CallSession.status` out of `in_progress`. No new
  `LIVE_LINKS["3.2"]` page is needed (same posture as 5.2–5.4: presence in the build-state ledger is what matters,
  not a fresh nav row) — but confirm with `todo` whether the sidebar entry should be added anyway as an empty
  dict, matching the `0.1`/`5.2`-style precedent, or left to 3.5 to fold the whole realtime story into one richer
  diagnostics page.
- **`PROVIDER_MODE` resolution**: `fake`/`sandbox` never construct a live STT/TTS/LLM client and never touch a
  carrier; the whole consumer path — connect, frame loop, turn loop, teardown — is fully exercisable by tests and
  by `simulate_call` with zero real credentials. `live` adapters refuse to initialize outside `PROVIDER_MODE ==
  'live'` and additionally require real credentials present.
- **Tests** (per the skill's own §16, which already specifies this precisely): consumer accepted with a valid
  stream token; rejected with no auth, another tenant's session id, and another **location's** session id; group
  name is tenant-and-location-namespaced; a synthetic audio frame round-trips through the codec chain unchanged
  bit-for-bit within tolerance; VAD correctly separates a scripted speech+silence fixture into one utterance; a
  sustained-speech fixture triggers barge-in and a brief-noise fixture does not; `disconnect()` finalizes the
  `CallSession` (status, timestamps, transcript, logs, usage) even when the socket closes abnormally; a
  `SynchronousOnlyOperation` in any test is a failure, never a flake; a provider adapter timeout produces the
  spoken-fallback path, never a raised exception into the frame loop; a rate-limited fake response backs off
  rather than hammering.

Deferred to later sub-modules, so nothing here is lost: the 12-tool declarations and `apply_tool_call` dispatcher
(3.3); the deferred-transfer signal's actual execution — the REST redirect, hours/target gating (3.4, though 3.2
wires the hook point the transport checks after a turn ends); consent-gated recording, `waveform_peaks`,
`recording_blob` persistence, and the *full* diagnostics page with per-stage latency (3.5).

---

## Belongs to sibling sub-modules (parked, not scoped here)

- Tool declarations, the `apply_tool_call` dispatcher, the `{ok, data, error}` envelope, the twelve-tool surface,
  opaque signed slot tokens for booking → **3.3** (3.2 ships the turn loop with an empty tool list so the LLM
  adapter interface never needs to change shape when 3.3 lands).
- Deferred transfer signal **execution** — hours/target gating, the actual Twilio REST redirect, single-fire
  guard, outcome capture onto `CallSession.transfer` → **3.4** (3.2 only wires the checkpoint the transport
  inspects after a turn's audio completes; it sets no transfer state of its own).
- Consent-gated recording, the two-party-consent announcement content and its `logs` proof, `waveform_peaks`
  computation and persistence, `recording_blob` writing, the *full* runtime diagnostics page (per-stage latency,
  ended-reason codes spanning the whole call, worker health) → **3.5**.
- A per-location configurable turn-eagerness/interruption-sensitivity field (Retell/ElevenLabs/Bland/Synthflow
  all expose this as a customer setting) → would need a new field on `agents.AgentSetting`, a **2.1** decision,
  not this sub-module's to make unasked.
- A per-location secondary voice-provider for true cross-vendor STT/TTS/LLM failover (LiveKit's "Fallback
  strategies" pattern) → same as above, needs a new `AgentSetting` field → **2.1**, not 3.2.

## Out of scope for this product (outside the seven capabilities)

- **Outbound call origination** — this product is inbound-only end to end; the telephony adapter interface has
  no dial-out method by design, and nothing in this sub-module's turn loop or provider adapters changes that.
- **Multi-channel/text chat turn-taking** (several platforms surveyed, notably PolyAI and ElevenLabs, also serve
  web/app chat) — telephony-only; not one of the seven capabilities.
- **Human-agent live-transcription assist** (Dialpad AI's core product, surfaced here only as a technical
  reference for jitter/packet-loss buffering) — this product's agent IS the conversant, not a human being
  assisted by a transcript; there is no "coach a live human" surface anywhere in the seven capabilities.
- **A customer-facing dashboard for tuning VAD/barge-in constants live** — the constants live in code
  (`apps/runtime/providers/vad.py`), not a settings page, in this pass; a future per-location exposure of a
  subset of them is a 2.1 decision (see Belongs to sibling sub-modules above), not a 3.2 UI to build now.

## Deferred (later passes / integrations)

- **Live-provider STT/TTS/LLM implementations against real vendor SDKs** — the adapter interfaces, timeout/retry
  wrapper and fakes are fully buildable and testable now; proving the live implementations against real
  credentials (Google/Gemini, or whichever vendor backs `voice_provider='live'`) is an integration exercise once
  real API keys exist, not a code gap in this pass.
- **Production tuning of the VAD/barge-in threshold constants** (energy threshold, grace/sustain windows) — a
  first, conservative constant set is buildable and testable against synthetic fixtures now; the 2026
  production bar surfaced in research (barge-in latency < 400 ms, false-positive rate < 2%, missed-interruption
  rate < 1%) is only provable against real call audio, which does not exist until real traffic does.
- **Backchannel filler during active caller speech** (Retell's shipped feature) — deferred specifically because
  of its interaction risk with the echo guard; needs its own design pass once the base VAD/barge-in machinery is
  proven, not bundled into the same pass that builds that machinery.
- **Cross-vendor STT/TTS/LLM fallback chaining** (LiveKit's pattern) — this pass implements retry-with-backoff
  against the same configured provider plus a spoken-fallback degrade, matching the mandatory bullet; a true
  secondary-vendor chain needs a new `AgentSetting` field, which is 2.1's call to make.
- **Per-location configurable turn-eagerness/interruption-sensitivity as a form field** — four of the seven
  leaders surveyed expose this to their customers; this pass ships it as fixed, named constants per the skill's
  own instruction, and exposing it as a tunable setting is a 2.1 decision to take on purpose later.
- **The `simulate_call` management command's fixture library** (canned multi-turn scripted conversations for QA)
  — a first minimal fixture (one greeting, one utterance, one reply, clean hangup) is enough to prove the path
  end-to-end for this pass; a richer fixture library (barge-in scenarios, idle-timeout scenarios, provider-failure
  scenarios) is a natural test-writer follow-up, not a blocker for this pass's completion.
