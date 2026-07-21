# Research — Sub-module 5.4: Recording & Transfer Outcome (Module 5 — Call Logs, calls)

## Repo state checked first

- **`LIVE_LINKS`** (`apps/accounts/navigation.py`): `'5.1': {'Call Logs': 'calls:callsession_list'}`, `'5.2': {}`,
  `'5.3': {}`. No `'5.4'` key exists — **5.4 is the correct next sub-module**, and it is the **last** sub-module in
  Module 5 and in the whole catalog's "view" category. Every other module (0–4) and every earlier sub-module of
  Module 5 is built.
- **Models verified to exist** (`grep -rn "^class " apps/calls/models/` → exactly one hit, same as 5.1–5.3 found):
  `apps/calls/models/CallLogList/CallSessions.py:70: class CallSession(TenantLocationOwned)`. **No `Recording`,
  `TransferAttempt`, `MediaAsset` or any second model exists anywhere in `apps/calls/`.** This sub-module's whole
  surface is three fields already on that one row: `recording_blob`, `waveform_peaks`, `transfer`.
- **Exact field shapes, read directly from the model file (`apps/calls/models/CallLogList/CallSessions.py`):**
  - `recording_blob` — `CharField(max_length=512, blank=True, default='')`. Docstring, verbatim: *"PRIVATE storage
    path; `""` = no recording. Served only through a short-lived signed URL — never rendered as a `src` against a
    public media path. Must not be set without a consent basis in `metadata`."* The migration
    (`0003_alter_callsession_recording_blob.py`) carries the identical help_text — this rule has been stated **twice**
    in code before any view existed to enforce it.
  - `waveform_peaks` — `JSONField(null=True, blank=True)`. Docstring: *"`{caller, bot, bins}` for the call-detail
    waveform. NULL rather than empty-by-default: absent means 'never computed', which is not the same as a recording
    that is genuinely silent."* **`bins` is a count (`len(caller)`), not an array** — confirmed against the seeder's
    `_build_waveform` (`return {'caller': caller, 'bot': bot, 'bins': len(caller)}`, two 12-element float lists).
  - `transfer` — `JSONField(default=dict)`. Docstring: *"`{result, reason, destination, initiated_at,
    duration_seconds, attempts}`. `result` and `destination` are the FINAL outcome and the number that produced it.
    `attempts` is an optional `[{destination, result}]` list recording each number tried in order — `AgentSetting`
    carries a `transfer_secondary_number`, so 'primary rang out, secondary answered' is a designed path... Empty dict
    = no transfer was ever attempted, the common case."*
  - `metadata` — `JSONField(default=dict)`. Docstring: *"including the recording consent basis and its retention
    window, which live on the row that was actually recorded because the policy that applies is the policy at the
    time of the call."* The seeder's `_build_metadata` confirms the concrete keys in use today:
    `consent_basis` (`'announced_notice'` / `'not_recorded'`), `consent_announced` (bool), `retention_days` (int,
    `90` when recorded, `0` when not).
  - A code comment directly above `recording_blob` states the validation contract explicitly: *"A NON-EMPTY
    `recording_blob` REQUIRES A CONSENT BASIS IN `metadata`, and nothing here can enforce that... It has to be
    application-level validation in the write path, not a `CheckConstraint`."* That obligation belongs to Module 3
    (the writer); 5.4 is a reader and must render whatever consent basis is actually stored, defensively.

- **Two already-shipped, pre-authored partials this sub-module wires** — read in full, not re-authored:
  - **`templates/partials/_audio_player.html`.** Context contract: `session`, `recording_url`,
    `consent_basis_label`, `retention_date`, `can_download` (all named in its own `{% comment %}`). Renders nothing
    if `session.recording_blob` is empty. If `recording_url` is falsy it shows *"This recording is no longer
    available"* instead of a broken `<audio>` tag — **this is the built-in graceful degradation path this
    sub-module should lean on**, not re-invent. It never touches `session.recording_blob` directly (correct — the
    raw path is never meant to reach the template).
    **Found a load-bearing defect while reading it that 5.4 must fix before wiring it in:** its waveform block does
    `{% for peak in session.waveform_peaks.bins %}` — but per the model's own docstring and the seeder,
    `waveform_peaks.bins` is an **integer** (a bin *count*, `len(caller)` = 12), not a list. Django's `{% for %}`
    tag calls `list(values)` on anything without `__len__` before iterating; `list(12)` raises
    `TypeError: 'int' object is not iterable`, uncaught by the template engine. **Wiring this partial in as-is
    would 500 the detail page for every one of the six seeded "recorded" call sessions the moment 5.4 lands** — a
    concrete regression, not a hypothetical. It also only renders a single generic `.waveform` div and never
    references `caller`/`bot` individually, so even fixed to iterate a real list it still would not distinguish
    the caller channel from the agent channel the bullet asks for ("a caller/agent waveform"). See the Waveform
    Player entry below for the concrete fix.
  - **`templates/partials/_transfer_outcome.html`.** Context contract: `transfer` (i.e.
    `{% include "partials/_transfer_outcome.html" with transfer=session.transfer %}`). Renders nothing for an empty
    dict (the common no-transfer case). Branches on `transfer.result` into five badge colours
    (`connected`→green, `off_hours`→amber, `disabled`→muted, `failed`→red, `no_answer`→amber, else→muted+raw value)
    — already an exhaustive, defensively-`{% else %}`-guarded map. Shows `reason`, `destination` (through
    `phone_e164`, never raw), `initiated_at`, `duration_seconds`. **Already carries the `attempts` trail** (a `2+`
    guarded `<ol>` of `{destination, result}` pairs) — this was built ahead of any seed data that populates it (see
    the seeder gap below). This partial needs **zero code changes** — 5.4's only job here is one `{% include %}`
    line.
- **`templates/calls/calllog/callsession/detail.html`** already marks exactly where 5.4 lands, verbatim in its own
  comment: *"Still to land in this column: 5.4 the recording player and the transfer outcome
  (partials/_audio_player.html, partials/_transfer_outcome.html)."* The header (5.1), "What this call produced"
  (5.1), transcript/analysis (5.2), event log/cost (5.3) panels are already built and untouched by this pass. The
  view (`callsession_detail_view` in `apps/calls/views/CallLogList/CallSessions.py`) currently passes only `obj` —
  5.4 is the first sub-module here that needs the VIEW to compute and pass **new context** (`recording_url`,
  `consent_basis_label`, `retention_date`, `can_download`) rather than only adding template markup, because the
  signed URL cannot be computed inside a template.
- **`.claude/skills/calls/SKILL.md`** confirms 5.4 is a view sub-module — ZERO models, ZERO migrations — and
  explicitly pre-names it: *"5.4 — the recording player and the transfer outcome (`partials/_audio_player.html`,
  `partials/_transfer_outcome.html` — exist but wired by 5.4, not yet)."* Its worked-examples note for "Add a view
  sub-module" states 5.2 needed a new route (print) plus two `detail.html` panels, and 5.3 needed no backend layer
  at all. **5.4 is the third pattern**: it needs a new route too (the signed-recording serve endpoint) — like 5.2,
  not like 5.3 — because streaming a private file behind a signature check cannot be done from inside a template.
- **`.claude/skills/voice-agent-runtime/SKILL.md`** — §12 states per-location Twilio credentials are
  **encrypted, write-only**, never rendered/logged; §14 states `recording_blob`/`waveform_peaks` are what Module 3's
  consumer writes in `disconnect()`, and *"a recording without a recorded consent basis must not be creatable"* and
  *"where the location's jurisdiction requires two-party consent the announcement is played before recording
  begins, and the `logs` entry proving it is the evidence."* §13 confirms cost has exactly four components
  (`stt_usd`/`llm_usd`/`tts_usd`/`telephony_usd`) in `usage.cost_breakdown` — **there is no recording-storage cost
  line today**, relevant to the Compliance section below.
- **An existing in-repo precedent for the signed-URL mechanism itself, found in `apps/accounts/views/Auth.py`
  (0.2 Change Email):** `django.core.signing.dumps({...}, salt=EMAIL_CHANGE_SALT)` to mint a token,
  `django.core.signing.loads(token, salt=EMAIL_CHANGE_SALT, max_age=settings.EMAIL_CHANGE_TOKEN_MAX_AGE)` to verify
  it, catching the single exception `signing.BadSignature` (which covers tampering **and** expiry — `SignatureExpired`
  subclasses it) and failing closed. `EMAIL_CHANGE_TOKEN_MAX_AGE` is declared in `config/settings.py` via the
  project's `env_int(...)` helper. **This is the exact mechanism to reuse for the recording URL — not a new
  library, not Twilio's own signed-media feature (there is no Twilio recording in this app; the file is served
  from this app's own storage), and not JWT** — the codebase already has one signing convention and 5.4 should be
  its second user, not a third pattern.
- **`config/settings.py`** confirms `MEDIA_URL = 'media/'` / `MEDIA_ROOT = BASE_DIR / 'media'` — Django's
  standard, **web-servable** media location. This is precisely the "public media path" `recording_blob`'s own
  docstring says a recording must never sit under. No `PRIVATE_MEDIA_ROOT` or private storage class exists yet
  anywhere in the codebase (`grep` for `PRIVATE_MEDIA|FileSystemStorage` returns nothing under `apps/` or
  `config/`) — 5.4 is what introduces it.
- **Seeder** (`apps/calls/management/commands/seed_calls.py`), read in full:
  - **6 of the 11 seeded sessions have `recorded: True`** (Downtown #1 Dana Whitfield-completed, Downtown #2
    unidentified-transferred, Uptown #1 Priya Raman-completed, Uptown #2 Owen Baptiste-completed, Riverside #2
    unidentified-completed, Lakeside #1 Theo Nakamura-completed) — each gets a synthetic
    `recording_blob = f'private/calls/{tenant.slug}/{location_slug}/{sid}.mp3'` path and a real
    `_build_waveform()` result (`{caller: [...12 floats...], bot: [...12 floats...], bins: 12}`, a fixed
    deterministic pattern, not random). **No actual audio bytes exist anywhere on disk at that path** — this app
    has no provider adapter and never will (Module 3 owns that); the path is hand-authored fiction, same as every
    other field in this seeder. So the demo data exercises the waveform (real JSON, once the partial's iteration
    bug above is fixed) but **cannot exercise real audio playback** without an additional fixture — see the
    Signed Media Access entry below for the recommended, safe way to close that gap.
  - **5 of the 11 sessions have a non-empty `transfer` dict**, and between them they cover **all five** `result`
    values the partial branches on: Downtown #2 `connected`, Uptown #2 `disabled`, Riverside #2 `no_answer`,
    Riverside #3 `off_hours`, Lakeside #2 `failed`. The demo data is excellent coverage for the outcome panel's
    colour/label map.
  - **Concrete gap found: no seeded row ever populates `transfer.attempts`.** `_build_transfer()` only ever
    returns `{result, reason, destination, initiated_at, duration_seconds}` — the `attempts` key is never present,
    so the partial's whole "numbers tried, in order" `<ol>` branch (already built, already tested against `2+`
    entries) has **no seeded row to render it against**. `apps/agents/management/commands/seed_agents.py` confirms
    Downtown is the one demo location configured with **both** a primary (`transfer_phone_number = +13125550101`)
    **and** a secondary (`transfer_secondary_number = +13125550102`) number — matching
    `TRANSFER_DESTINATIONS['downtown']` in `seed_calls.py`. Downtown's own `connected` row (call #2, the
    `transferred`-status one) is the natural candidate to extend with a two-attempt trail
    (`[{destination: '+13125550101', result: 'no_answer'}, {destination: '+13125550102', result: 'connected'}]`) —
    it is precisely the *"primary rang out, secondary answered"* path the model's own docstring names as the
    reason this list exists.
  - `_build_metadata()` already writes `consent_basis`/`consent_announced`/`retention_days` correctly and
    differently for recorded vs. unrecorded rows (`'announced_notice'`/`True`/`90` vs. `'not_recorded'`/`False`/`0`)
    — no seeder change needed for the consent badge or the retention date.

## Leaders surveyed (with source links)

1. **Retell AI** — the clearest documented match for the Waveform Player bullet: the call-detail page plays the
   recording on a waveform, with the speaker-labelled transcript synced alongside it and the AI summary in the same
   view — "listen on the waveform, read the synced transcript... all in one view" —
   [Get Call](https://docs.retellai.com/api-references/get-call),
   [What is Call Transcription?](https://www.retellai.com/glossary/call-transcription)
2. **Vapi** — the clearest documented match for Signed Media Access done the *provider-hosted* way: recordings,
   transcripts and logs are all exposed as **fields on the Get-Call response** (`call.artifact.recording`,
   `.transcript`, `.logUrl`), i.e. behind an authenticated API call rather than a static asset — plus a
   configurable custom-storage option (S3/GCS) with per-artifact plans, which is the closest documented analogue to
   "never a public or guessable path" —
   [Call recording, logging and transcribing](https://docs.vapi.ai/assistants/call-recording)
3. **Bland AI** — ships recording access as an explicit, separate, **authenticated GET endpoint keyed by call id**
   (`GET /v1/recordings/{call_id}`, API-key gated, format negotiable via header) rather than a static file link —
   directly confirms the "serve through a route, not a raw path" pattern this bullet requires, and its
   "Call recording not found" error response is the same graceful-miss shape this sub-module needs when a file is
   absent —
   [Get Call Recording](https://docs.bland.ai/api-v1/get/calls-id-recording)
4. **Dialpad AI** — the clearest documented match for transcript-position sync: a "Call Review" page combines a
   Transcript tab (searchable) with inline audio playback controls, and lets a user hover a specific part of the
   transcript to jump to it — the transcript-as-scrubber pattern this sub-module should emulate with the
   `transcript` JSON's existing per-turn `offset` field —
   [AI Call Summary](https://help.dialpad.com/docs/ai-call-summary),
   [Call Transcript API](https://developers.dialpad.com/reference/transcriptsget)
5. **Smith.ai / Ruby Receptionists** — the clearest documented match for the Transfer Outcome Panel's *purpose*
   rather than its UI: both describe "warm transfer" as a staffed, narrated handoff where the receptionist confirms
   availability before connecting, i.e. the same reason→destination→outcome narrative this product's `transfer`
   JSON already encodes (minus the human warmth, since this product's transfer is a cold redirect per the runtime
   skill) —
   [Warm Live Call Transfer](https://smith.ai/features/warm-transfer-answering-service),
   [What is a Warm Transfer?](https://smith.ai/blog/what-is-a-warm-transfer)
6. **PolyAI** — "Call Handoff" documentation is the single closest match to this exact bullet's wording: handoff
   destinations are configured per scenario, and the feature explicitly exists to "remove guesswork when
   diagnosing handoffs" and "give QA teams full visibility into the exact wording customers heard" — i.e. a
   reason/destination/outcome record reviewable after the fact, exactly what `_transfer_outcome.html` already
   renders —
   [Handoff — PolyAI Platform](https://docs.poly.ai/call-handoff/introduction),
   [Agent handover: how to get the transfer right every time](https://poly.ai/blog/agent-handover)
7. **Twilio** (the underlying carrier, not a competitor, but the direct source of both the media legality and the
   security posture this sub-module must reflect) — Twilio's own support docs state the two-party-consent
   disclosure obligation ("obtain consent from all participants before recording," "disclose... that you are using
   a third-party communication provider") and separately recommend **securing the Recording API endpoint with HTTP
   authentication** because "recording URLs are visible to any service that consumes... events" — the exact
   "never a public or guessable path" rationale this bullet is built around —
   [Best Practices for Recording Communications](https://support.twilio.com/hc/en-us/articles/360011435554-Best-Practices-for-Using-Twilio-to-Manage-and-Record-Communications-Between-Users),
   [Legal Considerations with Recording](https://support.twilio.com/hc/en-us/articles/360011522553-Legal-Considerations-with-Recording-Voice-and-Video-Communications)

## Feature catalog (this sub-module only)

### Waveform Player
- **Recording playback synced to a visual waveform** — Retell's headline pattern (waveform + synced transcript +
  summary in one view) · seen in: Retell, Dialpad (playback controls alongside transcript) · priority: **REQUIRED**
  — named bullet · model: reuses `CallSession.recording_blob` (existence gate) + `CallSession.waveform_peaks`
  (visual data), **zero new fields** · realtime: **post-call** (this is playback of an already-finalized
  recording; the runtime that RECORDS and computes peaks during the live call is Module 3's hot path — 5.4 only
  reads) · tool-surface: pure UI, no tool, no prompt change · **buildable now, but only after fixing the partial's
  iteration bug** (see Repo state above) — feed `session.waveform_peaks.caller` and `.bot` to two waveform lanes
  (e.g. one rendered above a center line, one mirrored below, or two stacked `<div class="waveform">` rows each
  looping its own array) instead of the current `.bins` loop. This satisfies the bullet's own wording — "a
  caller/agent waveform" — which the shipped single-lane markup does not yet distinguish.
- **Transcript-position sync (click a transcript line to seek; highlight the active line during playback)** —
  Dialpad's "hover a specific part of the call" jump-to-position pattern, Retell's synced-view description ·
  priority: differentiator (this is the feature that turns "a waveform image" into "a waveform *player*") · model:
  none — the data needed already exists: each `CallSession.transcript` entry already carries an `offset` (seconds
  from call start, per 5.2's contract) which is exactly the seek anchor an `<audio>` element's `currentTime` needs
  · realtime: post-call, pure client-side · tool-surface: pure UI — a small scoped `<script>` (or a
  `static/calls/recording-sync.js` file, consistent with this product's plain-HTML-first, no-SPA-framework
  pattern elsewhere) that (a) on a transcript row click, sets `audio.currentTime = offset` and calls `.play()`, and
  (b) on the `<audio>` element's `timeupdate` event, toggles an "active" class on the transcript row whose
  `offset`–next-`offset` window contains `audio.currentTime`. No new backend surface, no new tool, no realtime
  infrastructure — genuinely a post-call, static-page enhancement · buildable now.
- **Waveform gated on recording presence** — the shipped partial already wraps everything in
  `{% if session.recording_blob %}` and separately guards the waveform block on `{% if session.waveform_peaks %}`
  (`null` on an unrecorded call, per the field's own docstring) · priority: table-stakes (every leader implicitly
  assumes this — none of them show a waveform for a call with no recording) · model: same fields, no changes ·
  realtime: post-call · tool-surface: pure UI · buildable now, already correct as shipped.

### Signed Media Access
- **Recordings served through an authenticated, non-static route — never a direct file/media-root URL** —
  Vapi's artifact-URL-on-the-API-response pattern, Bland's dedicated authenticated `GET /recordings/{call_id}`
  endpoint, Twilio's own explicit recommendation to secure the Recording API endpoint because "recording URLs are
  visible to any service that consumes... events" · seen in: Vapi, Bland, Twilio (guidance) · priority:
  **REQUIRED** — named bullet, reinforced twice in this model's own code (docstring + migration help_text) before
  any view existed · model: **new backend surface, zero new model** — a signed-URL-minting step in the existing
  detail view plus one new serve view/route (see Recommended build scope) · realtime: post-call · tool-surface:
  pure UI/backend, no LLM tool — the caller-facing runtime never touches this route; it exists purely for the
  staff-facing detail page · **buildable now, fully Django-native, no external dependency**:
  1. **Reuse the codebase's own signing convention** (`django.core.signing.dumps`/`.loads`, exactly as
     `apps/accounts/views/Auth.py`'s email-change flow already does) rather than inventing a second pattern. Mint
     `token = signing.dumps({'session_id': obj.pk}, salt=RECORDING_ACCESS_SALT)` in `callsession_detail_view`,
     only when `obj.recording_blob` is non-empty; build `recording_url = reverse('calls:callsession_recording',
     kwargs={'pk': obj.pk}) + '?sig=' + token`. A **query-string** token, not a path segment — unlike
     `email_change_confirm_view`'s path-embedded token, a query string never participates in URL *resolution*, so
     it carries zero of the `<str:token>` route-ordering risk this app's own URL-package docstring warns about
     (*"check any new greedy `<str:...>` route against the whole concatenated list"*) — the route itself stays a
     plain `<int:pk>/recording/` literal, exactly like 5.2's `<int:pk>/print/`.
  2. **The new serve view** (`callsession_recording_view`) is `@login_required`, `@never_cache`,
     `@require_http_methods(['GET'])` — same posture as every other view in this module. It verifies
     `signing.loads(token, salt=RECORDING_ACCESS_SALT, max_age=settings.RECORDING_URL_MAX_AGE)` FIRST (cheap,
     no DB), catching the single `signing.BadSignature` exception (covers tampering **and** expiry, same as the
     email-change precedent) and 404ing on failure — then, independently, re-scopes via
     `get_object_or_404(location_sessions(request), pk=pk)` (the SAME helper 5.1–5.3 already use) and confirms
     `payload['session_id'] == obj.pk`. **Three independent gates, not one**: the Django session cookie (who is
     logged in), the tenant+location re-check against `request.tenant`/`request.location` (which site this call
     belongs to), and the signature's freshness (how long the link has been alive) — a valid signature for the
     wrong tenant/location still 404s, and a correctly-scoped user's stale link (past `max_age`) still fails even
     though their session is otherwise valid. **The raw `recording_blob` path is never rendered anywhere in a
     template** — only this freshly-minted, per-page-load URL is.
  3. **Private storage, not `MEDIA_ROOT`.** `settings.py` currently defines `MEDIA_ROOT`/`MEDIA_URL` as Django's
     standard, web-servable location — exactly the "public media path" this field's own docstring forbids.
     Introduce a distinct `PRIVATE_MEDIA_ROOT` setting (e.g. `BASE_DIR / 'private_media'`) with **no corresponding
     URL mapping registered anywhere** (nothing in `config/urls.py` ever serves it, in dev or prod), and a small
     dedicated `FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT, base_url=None)` instance — `base_url=None`
     deliberately disables `.url()` so nothing can accidentally produce a public-looking link from it. House this
     in a new flat module `apps/calls/storage.py` (Backend Package Structure rule 8 — single-purpose modules stay
     flat at the app root, promoted to a package only when it outgrows one file).
  4. **Serve via `FileResponse`** (Django 4.2 supports HTTP Range requests on `FileResponse` natively, needed so
     `<audio>` scrubbing does not have to download the whole clip first), with `Content-Type` derived from the
     stored extension and `Content-Disposition: inline` for normal playback vs. `attachment` when the same
     signed URL is requested with an additional **unsigned** `?dl=1` flag (safe to leave unsigned — it changes a
     response header, not what is authorized). Add `Cache-Control: no-store` on the response — this is PII audio,
     not a cacheable asset.
  5. **A missing file degrades to the partial's existing "no longer available" branch** — do not raise. Whether
     the miss is because `recording_blob == ''`, or because the referenced path genuinely has no bytes (true for
     every seeded row today — see Repo state above), the detail view passes `recording_url=None` and the shipped
     partial already renders the graceful message. This is the **required baseline behaviour** regardless of
     whether a demo fixture (below) is ever added.
  6. **X-Accel-Redirect / X-Sendfile — explicitly not needed for this pass.** Those headers require a reverse
     proxy (nginx's `internal` location, or Apache's `mod_xsendfile`) sitting in front of the app server; this
     project's dev server is Daphne serving ASGI directly (CLAUDE.md), and recordings are bounded by
     `MAX_CALL_SECONDS` (15 minutes default per the runtime skill) — small enough that a plain Django
     `FileResponse` is entirely adequate. Note this as the natural place to revisit **if** a future production
     topology puts nginx in front of Daphne — the `recording_url` context variable and the partial's contract do
     not change either way, only what produces the bytes behind the route does.
  7. **The natural evolution if Module 3 later stores recordings in S3/GCS**: the signed-URL *mechanism* migrates
     from this Django view to a provider-minted presigned URL, produced by a storage adapter under
     `apps/runtime/providers/` (consistent with "every external dependency sits behind an adapter" per the runtime
     skill). `detail.html` and the partial need **no change** either way — they only ever see `recording_url`, a
     string, never the storage mechanism behind it.
- **Never render the raw storage path** — Twilio's own guidance ("recording URLs are visible to any service that
  consumes... events... securing the endpoint is a good practice") is the direct analogue: this product's
  equivalent leak would be printing `session.recording_blob` (a stable, guessable-by-pattern path —
  `private/calls/{tenant}/{location}/{sid}.mp3`) anywhere a template or a log line could pick it up · priority:
  **REQUIRED** · model: none, a rendering/logging discipline · realtime: post-call · tool-surface: pure UI ·
  buildable now.

### Transfer Outcome Panel
- **Reason, destination, timing and final result for any call that attempted a handoff** — PolyAI's Handoff
  feature ("removes guesswork... full visibility into the exact wording"), Smith.ai/Ruby's warm-transfer framing
  (the narrative the outcome panel exists to preserve, minus the human warmth this product's cold-transfer flow
  does not have) · seen in: PolyAI, Smith.ai, Ruby · priority: **REQUIRED** — named bullet · model: reuses
  `CallSession.transfer` (JSON dict) — **zero new fields** · realtime: post-call (the runtime that DECIDES and
  EXECUTES the transfer, per `voice-agent-runtime` §9, is Module 3's hot path; 5.4 only displays the recorded
  outcome) · tool-surface: pure UI, no tool of its own — this sub-module defines no LLM tool; it displays the
  result of `transfer_call`/`transfer_call_spanish`, which Module 3's dispatcher will one day execute · **buildable
  now, and requires literally zero code changes to the partial** — `{% include "partials/_transfer_outcome.html"
  with transfer=obj.transfer %}` is the entire wiring task.
- **The multi-attempt trail ("primary rang out, secondary answered")** — directly named in the model's own
  docstring as the reason the `attempts` list exists; PolyAI's handoff-diagnosis framing is the closest external
  analogue (seeing exactly what happened across a multi-step handoff, not just the final state) · priority:
  **REQUIRED** for the demo to actually prove the feature exists — the partial already renders this branch
  correctly, but **no seeded row populates it today** (see Repo state gap above) · model: same field, a seeder
  content edit only (`transfer.attempts`, an existing documented sub-key — no schema change) · realtime: post-call
  · tool-surface: pure UI · buildable now, pending the seeder edit named in Recommended build scope.
- **The destination shown is always the location's CONFIGURED number, never a caller- or model-supplied one** —
  this is this product's own Invariant-3-adjacent design decision (stated verbatim in the partial's own
  `{% comment %}`), not copied from a leader — none of the surveyed products document this distinction explicitly,
  which makes it worth restating here as a **REQUIRED** security property rather than a UI nicety: rendering a
  caller-supplied number as if it were "the destination" would misrepresent what the agent is actually configured
  to dial, and could be used to make a bogus number look authoritative on an audit trail · priority: **REQUIRED**
  · model: same field · realtime: post-call · tool-surface: pure UI, but load-bearing for Module 3 (the *writer*
  must only ever put the configured `AgentSetting.transfer_phone_number`/`transfer_secondary_number` into this
  field — never anything the model or caller produced) · buildable now, already correctly implemented in the
  partial and in the seeder's `_build_transfer` (`destination` comes from `TRANSFER_DESTINATIONS`, a location
  lookup table, never from the call spec).

### PII Handling
- **Never render the raw recording path, never log recording/transfer/caller content at INFO** — this product's
  own stated convention (CLAUDE.md Vulnerability rules 3 & 5; the SKILL's "this module has no logger,
  deliberately") rather than a leader-specific feature; Twilio's guidance to secure the Recording endpoint is the
  closest external analogue for the recording half · priority: **REQUIRED** · model: none — a discipline every
  new surface this sub-module adds must honour · realtime: post-call · tool-surface: pure UI/backend ·
  applies to: (a) the two existing panels (already correct — `_transfer_outcome.html` renders `destination` only
  through `phone_e164`, never raw; `_audio_player.html` never touches `recording_blob`), and (b) the **new**
  signed-recording serve view, which must not log the pk, the signature, the `from_number`, or the file path
  together at any level ≥ INFO — extending 5.1–5.3's "no module logger" convention to this sub-module's one new
  view rather than introducing the first logger in this app · buildable now.
- **The consent basis and retention window are displayed, not silently dropped** — this product's own
  `metadata.consent_basis`/`consent_announced`/`retention_days` keys (already correctly seeded, see Repo state)
  exist so the recording card can show *which policy applied at the time of the call* — the partial already
  reserves a `consent_basis_label` badge slot and a `retention_date` line for exactly this · priority:
  **REQUIRED** (this is the recording-consent disclosure obligation, not a display nicety) · model: reuses
  `CallSession.metadata` — zero new fields; add one small template filter (e.g. `consent_basis_label`, alongside
  `level_badge`/`dict_get`/`redact_args` in `apps/accounts/templatetags/ui.py`) mapping the known values
  (`announced_notice`→"Recorded — consent announced", `not_recorded`→"Not recorded") to a human label, defaulting
  to the raw value for anything unrecognized rather than crashing or silently omitting it (Module 3 may introduce
  new consent-basis values later; this page must never assume the closed set it knows about today is final) ·
  realtime: post-call · tool-surface: pure UI · buildable now.

## Compliance & provider constraints

- **REQUIRED — recording consent basis and disclosure.** `metadata.consent_basis` / `consent_announced` are the
  record of the policy that applied *at the time of the call* (the model's own docstring is explicit that this
  must not be read off the location's *current* settings). 5.4 surfaces both on the recording card via the badge
  and the retention line named above. This sub-module does not create the obligation (Module 3's write path does,
  by refusing to persist a `recording_blob` without a consent basis already in `metadata` — a rule this pass
  cannot enforce, only display faithfully) but it is the one surface where a tenant/location owner can actually
  *see* what was recorded and under what consent basis.
- **REQUIRED — two-party-consent announcement.** Where a location's jurisdiction requires an announce-before-record
  notice, the runtime skill (§14) states *"the announcement is played before recording begins, and the `logs`
  entry proving it is the evidence."* 5.4 does not need a new surface for this — the event log (5.3, already
  built) is where that `logs` entry would already render, category `call` or `consent`, once Module 3 writes one.
  No action needed this pass beyond noting that the consent badge and the event log are two views of the same
  underlying fact, and neither should contradict the other.
- **REQUIRED — retention window is DISPLAYED here, ENFORCED elsewhere.** CLAUDE.md's Vulnerability rule 4 states
  the retention window is enforced by a scheduled job — that is Module 3.5's territory (unbuilt), not 5.4's. This
  sub-module computes and shows `retention_date` (derived from `created_at` + `metadata.retention_days`, mirroring
  the existing derive-don't-store discipline `duration_display`/`total_cost_usd` already established twice on
  this model — no new stored field) purely for transparency. **5.4 adds no purge job and must not be mistaken for
  one.**
- **REQUIRED — never log transcript/recording/caller-number content at INFO** (CLAUDE.md Vulnerability rule 5,
  restated for this sub-module's one new view above). No new HIPAA/GDPR retention or subject-rights obligation is
  introduced beyond what 5.1 already flagged on the same row — 5.4 reads three more fields off the same
  already-governed `CallSession` record, it does not open a second one.
- **Twilio / provider cost-line observation (not a change this pass makes).** `usage.cost_breakdown` today has
  exactly four keys (`stt_usd`, `llm_usd`, `tts_usd`, `telephony_usd`, per §13 of the runtime skill) — there is
  **no** recording-storage or recording-minute cost line. A real Twilio deployment bills recording storage and
  duration separately from voice-minute charges; if Module 3 ever meters that, it would need a fifth
  `cost_breakdown` key (e.g. `recording_usd`) on `usage` entries — that is 5.3/Module-3 territory, out of scope
  for this VIEW sub-module to add, noted here only so the gap is not lost.
- **No new rate-limit or concurrency exposure.** This sub-module's one new route serves a **local/private-storage**
  file behind Django's own auth + signature check — it makes no outbound call to Twilio, S3 or any other provider,
  so it introduces no new external rate limit, retry policy or per-unit billing dimension. (Contrast: Bland AI's
  and Vapi's recording endpoints are themselves rate-limited SaaS API calls; this product's equivalent route is a
  same-process file read.)

## Recommended build scope (this pass)

**VIEW sub-module — ZERO models and ZERO migrations.** `makemigrations calls --check` must report "No changes
detected." Everything below reads `CallSession.recording_blob` / `.waveform_peaks` / `.transfer` / `.metadata`
already on the row; a `Recording`, `TransferAttempt` or `MediaAsset` table here would be an Invariant 2 violation.

- **Tables READ:** `calls.CallSession` only (`recording_blob`, `waveform_peaks`, `transfer`, `metadata`,
  `created_at`). The existing `location_sessions(request)` helper (`apps/calls/views/_helpers.py`) is reused
  unchanged by both the detail view and the new serve view below — no second scoping helper.
- **Pages:** extend the existing `templates/calls/calllog/callsession/detail.html` inside its comment-marked slot
  with the two panels its own comment already names:
  1. `{% include "partials/_audio_player.html" with session=obj recording_url=recording_url
     consent_basis_label=consent_basis_label retention_date=retention_date can_download=can_download %}`
  2. `{% include "partials/_transfer_outcome.html" with transfer=obj.transfer %}`
  Neither partial needs its markup rewritten except the waveform-loop fix named above (a genuine bug fix on
  pre-existing scaffolding, not a re-author of its design).
- **One new backend surface (not a model): the signed-recording serve route.**
  - `apps/calls/views/RecordingTransferOutcome/CallSessions.py` — new entity file under a new sub-module folder
    named for this sub-module's heading (mirrors 5.2's `CallDetailTranscript/CallSessions.py` precedent exactly),
    containing `callsession_recording_view` (`@login_required`, `@never_cache`, `@require_http_methods(['GET'])`).
  - `apps/calls/urls/RecordingTransferOutcome/CallSessions.py` — `path('<int:pk>/recording/',
    views.callsession_recording_view, name='callsession_recording')`, concatenated into
    `apps/calls/urls/__init__.py` after 5.1/5.2's lists (order-safe: a literal `recording/` suffix cannot be
    swallowed by `<int:pk>/`, same reasoning already documented for `<int:pk>/print/`).
  - Both packages' `__init__.py` re-export blocks updated (`views/__init__.py`, `urls/__init__.py`) — required or
    the URLconf's `views.<name>` lookup `AttributeError`s at import time, per Backend Package Structure rule 3.
  - `callsession_detail_view` (existing, `apps/calls/views/CallLogList/CallSessions.py`) gains the token-minting
    logic and passes the four new context keys named above — the one place in this sub-module where a "view sub
    -module" still needs a genuine, non-trivial code change to an existing view, because a signed URL cannot be
    computed inside a template.
  - `apps/calls/storage.py` (new, flat — Backend Package Structure rule 8) — the private `FileSystemStorage`
    instance and small helpers (`recording_exists(path)`, `open_recording(path)`).
  - `config/settings.py` additions (no model/migration impact): `PRIVATE_MEDIA_ROOT`, `RECORDING_ACCESS_SALT`,
    `RECORDING_URL_MAX_AGE` (`env_int`, e.g. default `600` seconds — long enough to listen through/scrub a full
    15-minute call recording in one page visit, short enough that a copied link stops working shortly after,
    mirroring `EMAIL_CHANGE_TOKEN_MAX_AGE`'s naming and `env_int` pattern exactly).
- **One new template filter**: `consent_basis_label` in `apps/accounts/templatetags/ui.py`, alongside the
  already-shipped `level_badge`/`dict_get`/`redact_args`/`pretty_json`/`iso_time`/`error_log_count` (5.1–5.3's
  filters) — reuse that module, do not start a second one.
- **`LIVE_LINKS["5.4"]`**: add `{}` (empty dict) to `apps/accounts/navigation.py` — same posture as `'5.2': {}` /
  `'5.3': {}` — this sub-module's surfaces are reached through the existing `calls:callsession_detail` page 5.1's
  link already leads to; no new sidebar row. (The new `callsession_recording` route is not a page a user
  navigates to directly — it is the `<audio>`/download target embedded in the detail page.)
- **Seeder edits (content only, no schema change):**
  1. **Fix nothing structurally** — `_build_waveform`'s two 12-element arrays are already correct data; the bug is
     in the partial's consumption of them, not in what the seeder produces.
  2. **Add an `attempts` list to Downtown's `connected` transfer row** (call #2, `transferred` status) —
     `[{'destination': '+13125550101', 'result': 'no_answer'}, {'destination': '+13125550102', 'result':
     'connected'}]`, using Downtown's own real `seed_agents` primary/secondary numbers (confirmed:
     `transfer_phone_number='+13125550101'`, `transfer_secondary_number='+13125550102'`) — extend
     `_build_transfer()`'s spec handling with an optional `attempts` key on the per-row dict, defaulting to
     omitted for every other row.
  3. **Optional, nice-to-have — a shared placeholder audio fixture**, so the player is demoable with real bytes
     rather than only a graceful "not available" message: one small checked-in silent/tone audio file (a few
     seconds, a few KB) stored under the new `PRIVATE_MEDIA_ROOT`, with every `recorded: True` seeded row's
     `recording_blob` pointed at that **same shared file** (not a distinct file per row — there is no real audio
     pipeline to synthesize one). This is explicitly **not required** for the four bullets to be satisfied: the
     existence-check-and-degrade-gracefully behaviour (item 5 under Signed Media Access above) is the REQUIRED
     baseline and is correct with or without this fixture. Add it only if there is appetite for a fuller demo.

## Belongs to sibling sub-modules (parked, not scoped here)

- Session header, transcript panel, analysis panel, transcript print view → **5.2 Call Detail & Transcript**
  (already built).
- Event log, tool-call trace, per-turn cost breakdown → **5.3 Event Log & Cost** (already built).
- Populating `recording_blob`/`waveform_peaks`/`transfer` from a real call (the recorder, the waveform-peak
  computation, the cold-transfer execution and outcome-capture logic CLAUDE.md and the runtime skill describe) →
  **Module 3 (Call Runtime)**, unbuilt. 5.4 is a pure reading surface over columns Module 3 will one day write; it
  fixes the display contract (and, via the storage/signing scaffolding, part of the *serving* contract) those
  writes must honor.
- The retention-window **purge job** → **Module 3.5** (unbuilt) — 5.4 only displays the date, never enforces it.

## Out of scope for this product (outside the seven capabilities)

- **Cloud storage adapter selection / S3 presigned URLs as a first-class feature** (Vapi's custom-storage option) —
  this product's provider adapters live in `apps/runtime/providers/` and are Module 3's territory; 5.4 ships the
  Django-native signed-serve-view that works today, and notes the S3-adapter path as a future evolution that would
  not require any template change, but does not build it now — no S3/GCS integration exists anywhere in this
  codebase yet and none of the seven capabilities calls for one.
- **A human-reviewed call-quality workflow** (Smith.ai/Ruby's "reviewed by AI and humans, fed back into training")
  — this product has no reviewer role or QA feedback loop among its seven capabilities; a tenant user reading
  their own call's recording is not a vendor QA process.
- **Warm transfer (a human on the line confirming availability before connecting)** (Smith.ai/Ruby) — this
  product's transfer, per the runtime skill's §9, is an explicit **cold** redirect (`<Dial answerOnBridge="true">`)
  with no human pre-screening step; the outcome panel narrates that cold-transfer's result faithfully and does not
  imply warm-transfer semantics it cannot produce.

## Deferred (later passes / integrations)

- **A logged, queryable `consent_announced` event inline on the recording card** (beyond the badge already
  planned) — the event log (5.3) is where that `logs` entry will render once Module 3 writes one; no duplicate
  surface needed on the recording card itself.
- **A `recording_usd` cost-breakdown key** — noted under Compliance as a real gap in the current four-key
  `cost_breakdown` shape, but adding a field to `usage` entries is Module 3's/5.3's write-path decision, not a
  change this VIEW sub-module makes.
- **X-Accel-Redirect / X-Sendfile offload** — revisit only if a production topology puts nginx (or Apache's
  `mod_xsendfile`) in front of Daphne; not needed for the current dev/XAMPP + Daphne-direct topology, and the
  `recording_url` contract does not change if it is added later.
- **Per-caller/per-tier download permission gating** (e.g. only `owner`/`manager` tiers may download, `staff` may
  only stream inline) — not named by any of this sub-module's four bullets; `can_download` is recommended as
  unconditionally `True` for any authorized viewer of the call this pass, revisit only if a later access-control
  pass asks for it explicitly.
