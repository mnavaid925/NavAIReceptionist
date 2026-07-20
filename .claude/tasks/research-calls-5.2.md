# Research — Sub-module 5.2: Call Detail & Transcript (Module 5 — Call Logs, calls)

## Repo state checked first

- `LIVE_LINKS` (`apps/accounts/navigation.py`): `'5.1': {'Call Logs': 'calls:callsession_list'}` is the only `5.*`
  entry — 5.2 is the correct next sub-module in Module 5. Every other module (0–4) is fully built.
- **Models verified to exist** (grepped directly, `apps/calls/models/CallLogList/CallSessions.py`):
  `calls.CallSession` — `TenantLocationOwned`, with the exact JSON columns this sub-module reads:
  `transcript` (list, default `list`, shape `{sequence, role, text, at, offset}`), `analysis` (dict, default
  `dict`, shape `{summary, success_evaluation, extracted_data}`), plus scalar header fields `from_number`,
  `to_number`, `contact` (FK `scheduling.Contact`, nullable, `SET_NULL`), `location` (FK), `mode`
  (`live`/`google`/`gemini`), `status` (five values), `started_at`, `ended_at`, and the derived
  `duration_display` property. **No model needs to change for 5.2.** `logs`, `usage`, `transfer`,
  `waveform_peaks` also exist on the same row but are out of this sub-module's four bullets (5.3/5.4's surfaces).
- **Views/URLs already built by 5.1** (`apps/calls/views/CallLogList/CallSessions.py`,
  `apps/calls/urls/CallLogList/CallSessions.py`): `callsession_list_view` and **`callsession_detail_view` already
  exist**. The detail view is deliberately thin — it does `get_object_or_404(_location_sessions(request), pk=pk)`
  (tenant+location scoped through the shared queryset helper, so a pk from another site 404s) and renders
  `{'obj': obj}` only, no `session` key. **5.2 does not need a new detail view** — it needs to (a) add panels to
  the existing `detail.html` template, wired against the existing `obj` context var, and (b) add one new route +
  view + template for the print page.
- **`templates/calls/calllog/callsession/detail.html` already ships the session header (5.1) and marks exactly
  where 5.2 lands**, verbatim in its own comment block: *"5.2 owns the transcript... `partials/_transcript.html`...
  all exist already — including them here would render work that no reviewer has read against a live row."* The
  header already covers all of this sub-module's "Session Header" bullet (numbers, contact, location, mode,
  status, started/ended, `duration_display`) — **that bullet is fully built already; 5.2 adds nothing to it**,
  confirmed by direct read of the template. The remaining three bullets land in the marked comment block inside
  the left column, in this fixed order: 5.2 transcript, 5.3 event log + cost, 5.4 recording + transfer outcome.
- **`templates/partials/_transcript.html` already exists, fully authored, unwired.** Its context contract, read
  directly from the file:
  - **Include as:** `{% include "partials/_transcript.html" with session=session %}` — note the variable name is
    `session`, not `obj`. Because `detail.html`'s own context key is `obj`, the wiring line 5.2 must add is
    `{% include "partials/_transcript.html" with session=obj %}` — passing the existing object under the name the
    partial expects. **This is the one concrete integration detail that would silently break the panel if missed**
    (the partial would render `session.transcript` against an undefined variable and show the empty state on
    every call, never erroring).
  - Renders `session.transcript` (a JSON list) as `.transcript-turn` blocks, one per entry, branching
    `turn.role == 'agent'` vs. anything else → `agent`/`user` CSS class, an `Agent`/`Caller` speaker label, an
    optional `<time>` element keyed on `turn.at` showing `turn.offset|default:0`s, and the turn's `turn.text` as
    plain escaped text (never `|safe`).
  - Already handles `turn.partial` (an `is-partial` CSS hook — for an in-progress call's still-streaming last
    turn; 5.2 doesn't need to add this, it is already there for when Module 3 writes partial turns).
  - Already has an explicit empty state (`partials/_empty_state.html`, icon `message-square-off`) for
    `{% if session.transcript %}...{% else %}...{% endif %}` — the "abandoned call has no transcript" case this
    sub-module's own Analysis Panel bullet calls out is **already solved on the transcript side too**, by the
    partial itself, not by anything 5.2 needs to author.
  - `.transcript-scroll` (the scrollable container) already has a dedicated `@media print` rule in
    `static/css/theme.css` (`max-height: none; overflow: visible;`) sitting alongside rules that hide
    `.app-sidebar`, `.app-topbar`, `.page-actions`, `.pagination`, `.table-actions` and force `.card { border: 0;
    box-shadow: none; }` on print. **The print stylesheet is already built and already targets this exact
    class** — the "Transcript Print View" bullet's job is a route + a clean template that extends the same chrome
    (so the existing `@media print` rules take effect), not a new stylesheet.
  - Usage note in its own docstring: caller speech is untrusted input reaching us through a phone line and a
    speech model, rendered as plain escaped text — never `|safe`, never inline style, never inline JS. This
    governs 5.2's print template identically: it is the same data, rendered a second time.
- **`apps/accounts/templatetags/ui.py` already ships a filter purpose-built for this sub-module's defensive
  rendering requirement**: `dict_get` — *"`mapping[key]` with a silent miss — for JSON blobs rendered
  defensively. CallSession's transcript/logs/analysis/usage columns are JSON written by the runtime; a detail page
  must render an abandoned call that has none of them without raising."* Its own docstring names `analysis`
  explicitly. 5.2's Analysis Panel should read `{{ obj.analysis|dict_get:"summary" }}` /
  `{{ obj.analysis|dict_get:"success_evaluation" }}` rather than `{{ obj.analysis.summary }}` — Django's dot
  lookup on a dict already degrades to empty string on a missing key without raising, so `dict_get` is not
  strictly required for *reading* a plain string key, but it is the house convention this app already committed
  to for JSON-column rendering (paired with `{% load ui %}`), and `extracted_data` is a dict-of-arbitrary-keys
  that needs `.items` iteration regardless (see catalog below).
- **`.claude/skills/calls/SKILL.md`** confirms: 5.2/5.3/5.4 are each a **view sub-module — ZERO models, ZERO
  migrations**; the shared partials `_transcript.html`, `_transfer_outcome.html`, `_audio_player.html` "exist but
  are wired by 5.2/5.4/5.4 respectively, not by 5.1"; the list defers the JSON columns while the detail page reads
  the whole row on purpose (Invariant 2's design — one document, fetched together); the module has **no logger,
  deliberately** (PII discipline); and the "Add a view sub-module" common task names the exact shape to follow:
  new `views/<SubModule>/<Entity>.py` + `urls/<SubModule>/…`, re-export blocks, templates under
  `templates/calls/<submodule>/<entity>/`, a `LIVE_LINKS["5.M"]` entry, **no model, no migration**, extend
  `seed_calls` idempotently if richer JSON is needed.
- **Sibling research file** (`research-calls-5.1.md`) explicitly parks four things into 5.2: *"Session header
  detail rendering, speaker-attributed transcript, analysis panel, transcript print view → 5.2 Call Detail &
  Transcript (reads `CallSession.transcript`/`.analysis`, no new model)"* — matches this sub-module's four bullets
  exactly, and confirms "session header" is considered done by 5.1 even though the words appear in both files
  (5.1 built the rendering; 5.2's bullet is satisfied by what already exists). It also separately parked *"An
  AI-generated one-line summary shown inline in the list row... explicitly 5.2's surface"* — real, but not one of
  this sub-module's four named bullets (it's a list-row feature, not a detail-page one) — kept in "Beyond the
  bullets" below as optional, not required.
- **Seeder** (`manage.py seed_calls`, `apps/calls/management/commands/seed_calls.py`): already seeds 11 sessions
  across all five statuses with **abandoned/failed/in-progress rows carrying an empty `analysis` on purpose** —
  per the skill's own words, "that is 5.2's defensive-rendering path." The transcript JSON is already
  hand-authored fiction across the seeded rows (confirmed by the skill: "Every transcript, log and cost figure is
  hand-authored fiction"). **5.2 likely needs no seeder changes at all** — the demo data to exercise all four
  panel states (populated analysis, empty analysis, populated transcript, empty transcript) already exists from
  5.1's seed. Verify at build time whether at least one row has a `success_evaluation` and `extracted_data`
  worth rendering (a boolean field + an object with two or three keys, mirroring Vapi's `structuredData` shape
  below) — if not, that is a one-line seeder extension, not a new table.

## Leaders surveyed (with source links)

1. **Retell AI** — voice-agent-native session dashboard with a dedicated Post-Call Analysis feature; closest
   domain match to this product — [Monitor sessions via dashboard](https://docs.retellai.com/features/session-history),
   [Post-Call Analysis](https://www.retellai.com/features/post-call-analysis)
2. **Vapi** — the clearest documented shape for a three-field analysis object (`summary`, `structuredData`,
   `successEvaluation`), each independently customizable and each attached to the call record for dashboard or
   API retrieval — [Call analysis](https://docs.vapi.ai/assistants/call-analysis)
3. **Synthflow** — tabbed call-detail drawer (Overview / Transcript / Analysis / Summary) with per-criterion
   Passed/Failed success badges and an explanatory sentence per criterion — [Logs](https://docs.synthflow.ai/logs),
   [Call analysis](https://docs.synthflow.ai/docs/call-analysis)
4. **Bland AI** — call-detail API surface exposing transcript + metadata + post-call metrics together, positioned
   explicitly as the record used for "warm-transfer to human agents" continuity and dispute review —
   [Call Details](https://docs.bland.ai/api-v1/get/calls-id)
5. **Smith.ai** — human-read call-detail page combining a line-by-line transcript, summary notes, the AI/human
   handling flag, and a searchable transcript archive — [Call Recording & Transcription](https://docs.smith.ai/article/fzv1b69n7t-call-recording-transcription-with-smith-ai),
   [Call Analytics & Intelligence](https://smith.ai/features/call-intelligence-and-metadata)
6. **Dialpad AI** — "Call Review Page" with a dedicated Transcript tab, per-speaker labels, per-turn timestamps,
   in-transcript search, and both a copyable URL and a CSV download for sharing/export —
   [Call Summary: Transcript, Snippets, and Notes](https://www.dialpad.com/features/call-summary/),
   [Call Transcript API](https://developers.dialpad.com/reference/transcriptsget)
7. **Ruby Receptionists** — click-through call detail with recording + full transcript, plus a distinct
   date-ranged **PDF export** flow from the activity list (not a per-call print button) —
   [Ruby's Online Portal](https://rubyhelpcenter.helpjuice.com/en_US/apponline-portal/rubys-online-portal),
   [Exporting Your Activity Records](https://rubyhelpcenter.helpjuice.com/en_US/call-activity/exporting-your-activity-records)
8. **Goodcall** — dashboard transcript + recording view driven by a no-code "Information Extractor" that defines
   exactly which structured fields populate the post-call summary — [Goodcall](https://www.goodcall.com/)
9. **PolyAI** — "Conversation Review" table with keyword-driven transcript search and visual "Best Calls /
   Problem Calls" triage cards — used mainly as a negative example: most of its value-add belongs to analytics
   (5.3), not a single call's detail page — [Conversational analytics](https://poly.ai/blog/conversational-analytics)

## Feature catalog (this sub-module only)

### Session Header
- **Numbers, contact, location, mode, status, start/end, total duration in one header** — every leader treats
  these as the non-negotiable baseline of a call-detail page (Bland's `Call Details` API response, Smith.ai's
  "whether the call was handled by AI or escalated," Synthflow's "Overview" tab covering "status, timing, and
  agent-related information") · seen in: Bland, Smith.ai, Synthflow, Dialpad · priority: table-stakes · model:
  reuses `CallSession` scalar fields + `duration_display` property, **already rendered by `detail.html` — built
  in 5.1, nothing to add** · realtime: post-call · tool-surface: pure UI · **already buildable / already built** —
  confirmed by direct template read, not inferred.

### Speaker-Attributed Transcript
- **Timestamped, speaker-labelled turns rendered from the transcript JSON column, no separate table** — the
  universal shape across every leader researched: Retell logs "full transcript (what was said, by whom)" per
  call; Dialpad's transcript is "broken down by speakers" with "speaker labels and timestamps"; Smith.ai gives "a
  line-by-line breakdown of the entire call"; Vapi's real-time transcription "generates transcripts... with
  speaker identification and timestamps" · seen in: Retell, Dialpad, Smith.ai, Vapi, Bland, Ruby · priority:
  **REQUIRED** — one of the sub-module's own four named bullets, and Invariant 2 makes the JSON-column shape
  mandatory rather than optional · model: reuses `CallSession.transcript` (JSON list, already shaped
  `{sequence, role, text, at, offset}`) via `templates/partials/_transcript.html`, **already authored — wiring
  only**: add `{% include "partials/_transcript.html" with session=obj %}` inside the marked comment block in
  `detail.html` · realtime: post-call (batch/UI; the runtime that WRITES these turns during the live call is
  Module 3's hot path, not this sub-module's) · tool-surface: pure UI, no tool, no prompt change — this sub-module
  reads a column Module 3 will write, it does not touch the turn loop · buildable now.
- **In-transcript search / jump-to-phrase** — Dialpad ("use the search bar to quickly find specific words") and
  PolyAI (keyword-driven transcript filtering) both offer this on long calls · priority: differentiator · model:
  none — pure client-side text search over already-rendered DOM, no new field · realtime: post-call · tool-surface:
  pure UI · **integration/later** — real leader feature, not named by this sub-module's bullets; genuinely
  optional polish once transcripts are long enough to need it.
- **In-transcript tool-call/function-result markers** ("Transcripts now include function call results" — Retell)
  — real, but this is explicitly **5.3's "Tool-Call Trace" bullet** (`logs`, not `transcript`) → parked, not built
  here, so the transcript panel stays a pure speaker-turn view and doesn't quietly absorb 5.3's surface before
  5.3 exists.

### Analysis Panel
- **Three-field analysis object — summary, success/outcome evaluation, extracted structured data — attached to
  the call record and read defensively** — this is the one place the researched leaders' shape maps almost
  field-for-field onto the already-built column: Vapi's analysis object is explicitly `summary` +
  `successEvaluation` + `structuredData`; Synthflow's detail drawer shows a Summary panel plus **per-criterion
  Passed/Failed badges with an explanatory sentence**; Retell's Post-Call Analysis ships the same three shapes
  (Boolean/Text/Number/Selector custom fields = `extracted_data`, plus a qualitative pass/fail =
  `success_evaluation`, plus a free-text `summary`) · seen in: Vapi, Retell, Synthflow · priority: **REQUIRED** —
  named bullet, and it is the one panel whose "rendered defensively" clause is explicit in the bullet text itself
  · model: reuses `CallSession.analysis` (JSON dict, already shaped `{summary, success_evaluation,
  extracted_data}`) — **zero new fields**; read with the existing `dict_get` filter (`{{ obj.analysis|dict_get:
  "summary" }}`) or plain dict access, and `{% for key, value in obj.analysis.extracted_data.items %}` for the
  open-ended structured-data dict, all guarded by `{% if obj.analysis %}` for the abandoned/failed/in-progress
  case the seeder already exercises · realtime: post-call · tool-surface: pure UI — this sub-module renders a
  column Module 3's post-call analysis step will populate later; it defines no tool and no prompt variable ·
  buildable now.
- **Explicit "why" per success criterion, not just pass/fail** — Synthflow's success-evaluation panel pairs each
  criterion's badge with a one-line AI-authored explanation, which is exactly the shape `success_evaluation` as a
  free-form value (rather than a fixed enum) already allows — render whatever the JSON contains (a string, or a
  dict with a verdict + rationale) rather than assuming one shape, since Module 3's post-call analysis step
  (unbuilt) is what decides the concrete internal shape and 5.2 must not pre-guess a schema that constrains it ·
  seen in: Synthflow · priority: common · model: reuses `CallSession.analysis.success_evaluation`, rendered
  generically (dump the value, don't destructure specific sub-keys the JSON isn't guaranteed to have) · realtime:
  post-call · tool-surface: pure UI · buildable now.
- **Defensive empty state distinct from a loading state** — an abandoned/failed/in-progress call's `analysis` is
  legitimately `{}` (the model's own docstring: *"Legitimately empty on an abandoned or failed call — nothing
  happened to analyse, and every reader must render `{}` without falling over"*) and the panel must say so in
  words ("no analysis — nothing happened on this call to analyse") rather than rendering three blank rows or a
  raw `None`. No leader's docs describe this exact edge case (Vapi's own docs "do not specify what happens when
  calls end prematurely" per this research), which makes it this product's own hardening on top of the pattern,
  not a copied feature · priority: **REQUIRED** — the sub-module bullet's own wording ("rendered defensively
  since an abandoned call has none") makes this non-optional, and it is exactly the gap the leaders leave
  undocumented · model: same column, empty-state branch only · realtime: post-call · tool-surface: pure UI ·
  buildable now.

### Transcript Print View
- **A clean, chrome-free, printable rendering of the transcript for records and disputes** — every leader with an
  export path frames it the same way: Ruby's PDF export is explicitly for "activity records," call-center
  transcription vendors position transcripts generally as "protection... in case of disputes... speeds up
  resolution and protects both customers and companies from fraudulent claims," and Dialpad ships a literal
  "download button if you want to download the transcript or share the link with a teammate" · seen in: Ruby,
  Dialpad (download/share), general call-center transcript-for-disputes framing · priority: **REQUIRED** — named
  bullet, and this product's own PII rules make the *clean/chrome-free/no-stray-link* framing load-bearing, not
  cosmetic (see Compliance below) · model: **zero new fields** — reuses the same `CallSession.transcript` (+
  header fields for context) already rendered on the detail page · realtime: post-call · tool-surface: pure UI ·
  **buildable now, and the CSS is already half-shipped**: `static/css/theme.css`'s existing `@media print` block
  already hides `.app-sidebar`/`.app-topbar`/`.page-actions`/`.pagination`/`.table-actions`, un-shadows `.card`,
  and expands `.transcript-scroll` to `overflow: visible` — confirmed by direct read. The remaining work is a new
  route (`calls:callsession_transcript_print`), a thin view (identical scoping to `callsession_detail_view`, just
  a different template), and a standalone template
  `templates/calls/transcript/transcript_print.html` (per CLAUDE.md's Template Folder Structure rule 6, which
  names this exact path as its own worked example: *"print pages
  (`calls/transcript/transcript_print.html`)"*) that extends `base.html`, includes the header facts + the
  transcript partial, and triggers `window.print()` on load or via a visible "Print" button guarded
  `.page-actions` (already hidden on print by the existing CSS).
- **Print, not a general "export" format menu (CSV/PDF/DOCX)** — Ruby's date-ranged multi-call PDF/Excel export
  is a *list-level bulk export*, a different feature from a *single call's* print view; Dialpad's CSV download is
  also a distinct action from its shareable "copy URL." Conflating these is the failure mode this sub-module must
  avoid: the bullet asks for one call's clean printable page, not a bulk-export feature, and not a generated PDF
  file the server has to render and store · priority: table-stakes among leaders that have *any* single-call
  export, but this product's named bullet is narrower (browser print via CSS, not a generated file) · model: none
  · realtime: post-call · tool-surface: pure UI · buildable now — **do not build server-side PDF generation**;
  the browser's native print-to-PDF over the already-shipped `@media print` CSS satisfies the bullet without a
  new dependency (WeasyPrint/wkhtmltopdf) this pass has no other reason to introduce.
- **A shareable link/URL to a transcript** — Dialpad explicitly offers "a URL to copy/paste... or share the link
  with a teammate." **This is the item to be most careful with**: Dialpad's own copy implies the URL is
  independently accessible, which is exactly the shape CLAUDE.md's PII/signed-media rules forbid for this
  product's recordings (*"Serves recordings through short-lived signed URLs, never a public or guessable path"*)
  — the identical reasoning applies to a transcript, which is PII "by definition" per this same document. **Do
  not build a standalone shareable/guessable transcript URL.** The print route this sub-module ships is scoped
  identically to the existing detail view — `@login_required`, tenant+location-scoped through
  `_location_sessions(request)`, a plain incrementing `<int:pk>` behind normal session auth, never a token in the
  URL and never `@csrf_exempt`/unauthenticated. "Print" here means "render a clean page in an authenticated
  session for the browser's own print dialog," not "mint a link anyone with the URL can open." See Compliance
  section below.

### Beyond the bullets
- **AI-generated one-line summary shown inline in the CALL LOG LIST row** (Dialpad's "AI recap," Rosie's "AI
  summary", parked here from 5.1's own research file) — reads `CallSession.analysis.summary`, the same field 5.2
  puts in its Analysis Panel · priority: common among leaders · model: reuses `CallSession.analysis` (no new
  field) · realtime: post-call · tool-surface: pure UI · **not one of this sub-module's four named bullets** (it
  is a list-row feature, 5.1's surface, not the detail page) — noted here only because it reads the identical
  column 5.2 unlocks; genuinely optional, left for a polish pass on 5.1's list template rather than built in this
  pass.
- **Tabbed detail layout (Overview / Transcript / Analysis / Summary as separate tabs)** — Synthflow's structure
  · priority: differentiator · model: none, pure layout · realtime: post-call · tool-surface: pure UI · **not
  adopted**: this product's `detail.html` is a single scrolling page with stacked cards (header → what this call
  produced → [5.2/5.3/5.4 panels] → sidebar actions/record), and the existing comment block in `detail.html`
  already commits to that shape ("They all read JSON columns... nothing here needs to change to make room for
  them beyond dropping the cards in"). Tabbing would be a layout change the sub-module's bullets don't ask for
  and would fight the already-shipped page structure.
- **Sentiment score / emotion labels per turn** (Dialpad's "sentiment scoring") — real leader feature, but not
  named by any of this sub-module's four bullets, and `CallSession.transcript`'s documented shape
  (`{sequence, role, text, at, offset}`) has no sentiment field. Adding one would be a schema change to a
  sub-module that must ship **zero migrations** → parked, not built.
- **CSV download of the transcript** (Dialpad) — real, but distinct from "print" (see above); not named by the
  bullet → parked.

## Compliance & provider constraints

- **REQUIRED — transcripts are PII by definition (CLAUDE.md, verbatim), and this sub-module is the surface that
  puts the fullest exposure of that PII on screen.** Every rendering path in this sub-module — the transcript
  panel, the analysis panel's `extracted_data` (which the model's own field docstring calls out can include a
  full name and date of birth via `create_contact`-style captured data), and the print view — must escape all
  caller-supplied text (never `|safe`, matching `_transcript.html`'s own stated convention) and must never be
  logged. This sub-module adds no view-level logger, consistent with 5.1's own "no logger, deliberately" stance
  (the calls module's only safe log line about a call is one that names no PII, and there isn't one worth adding
  here).
- **REQUIRED — the print view must not create a new unauthenticated or guessable access path to a transcript.**
  This is the single biggest risk this sub-module introduces, precisely because "print view" sounds like it wants
  a public/shareable link (several leaders — Dialpad explicitly — ship exactly that for their own transcripts).
  The print route in this product must be **session-authenticated and tenant+location scoped identically to
  `callsession_detail_view`** (`@login_required`, `_location_sessions(request)`, plain `<int:pk>`, no token
  parameter, no `@csrf_exempt`). A signed, time-limited, tokenized "share this transcript externally" link is
  explicitly **out of scope** for this pass (see below) — it is the recording-URL pattern
  (`agents`/Module 3.5/5.4's "Signed Media Access" bullet) applied to a different payload, and introducing it here
  would duplicate that mechanism ahead of its own sub-module and widen this pass's blast radius past "pages,
  panels and a print view."
- **REQUIRED — server-generated PDF export is explicitly declined this pass, and that is itself a compliance
  boundary, not just a scope one.** A server-side PDF renderer that writes a file to disk or object storage would
  create a second, un-signed, potentially longer-lived copy of PII outside the existing `recording_blob`
  private-path + signed-URL discipline this product already committed to for recordings. Relying on the browser's
  own print-to-PDF (over the already-shipped `@media print` CSS) keeps the transcript's only durable copy on the
  `CallSession` row it already lives on.
- **No new HIPAA/GDPR retention or subject-rights obligation is introduced by this sub-module** beyond what 5.1
  already flagged and deliberately deferred (`Contact.anonymize()`'s cascade is NOT extended to `CallSession`;
  the call record's retention window is Module 3.5's scheduled job, not a 5.2 concern). 5.2 reads the same
  `transcript`/`analysis` columns 5.1 already carries that obligation for — it does not introduce a second copy
  or a second retention clock.
- **No provider cost line originates in this sub-module.** 5.2 is pure ORM read + templates: no Twilio call, no
  STT/TTS/LLM token spend, and it appends nothing to `CallSession.usage` (that is 5.3's surface, and the runtime
  that writes it is Module 3, unbuilt). The one performance-relevant note: the detail view already reads the
  whole row (Invariant 2's design, confirmed by the view's own docstring — "the detail page reads the whole row
  on purpose... one document, fetched together") so 5.2 costs this page **zero additional queries** — it renders
  columns the existing `get_object_or_404` call already fetched.

## Recommended build scope (this pass)

**VIEW sub-module — ZERO models and ZERO migrations.** `makemigrations calls --check` must report "No changes
detected." Everything below reads `CallSession.transcript` / `.analysis` / the scalar header fields already on
the row; a `Transcript`, `TranscriptTurn` or `Analysis` table here would be an Invariant 2 violation.

- **Tables READ:** `calls.CallSession` only (`transcript`, `analysis`, plus the header scalars 5.1 already
  renders). No other table is touched.
- **Pages:**
  1. **Extend the existing `templates/calls/calllog/callsession/detail.html`** — inside the comment-marked slot,
     add `{% include "partials/_transcript.html" with session=obj %}` (transcript panel — note the `session=obj`
     rename, see Repo state above) and a new Analysis Panel card reading `obj.analysis` defensively (guarded
     `{% if obj.analysis %}` / else an explicit "no analysis for this call" empty state, using the existing
     `dict_get` filter or plain dict access for `summary`/`success_evaluation`, and `{% for k, v in
     obj.analysis.extracted_data.items %}` for the structured-data table). **No changes to the header** — it is
     already built and already correct against this sub-module's bullet.
  2. **New standalone print page** — `templates/calls/transcript/transcript_print.html` (per CLAUDE.md's
     Template Folder Structure rule 6's own named example), a minimal template extending `base.html` (so the
     already-shipped `@media print` rule in `static/css/theme.css` applies): renders the same header facts +
     `{% include "partials/_transcript.html" with session=obj %}`, with a visible (screen-only, hidden on print)
     "Print" button that calls `window.print()`.
  3. **New view + route**: `callsession_transcript_print_view(request, pk)` in
     `apps/calls/views/CallLogList/CallSessions.py` (same entity module 5.1 already owns — this is still the
     `CallSession` entity, not a new sub-module folder), scoped identically to `callsession_detail_view`
     (`get_object_or_404(_location_sessions(request), pk=pk)`, `@login_required`, `@require_http_methods(['GET'])`)
     — add its `path('<int:pk>/print/', ..., name='callsession_transcript_print')` to
     `apps/calls/urls/CallLogList/CallSessions.py`, **checked against the literal-before-`<int:pk>` ordering rule**
     (it is itself a suffix on an existing `<int:pk>` segment, so it must be added as its own literal-suffixed
     path, not a route that could be shadowed by or shadow the bare detail route).
  4. **No new `LIVE_LINKS["5.2"]` entry is required as a separate sidebar row** — the print view and the
     transcript/analysis panels are reached *through* the existing `calls:callsession_detail` page that
     `LIVE_LINKS["5.1"]` already links to (`Call Logs` → row → detail). Per `navigation.py`'s own stated rule,
     "presence of the key means BUILT; the links are optional" — 5.2 should still add a `'5.2': {}` entry (an
     empty dict, the same pattern already used for 0.1) so the sidebar's build-state ledger correctly reflects
     that 5.2 is finished, without duplicating a link the detail page's own breadcrumb already provides.
- **What's deferred:** everything under "Beyond the bullets" and "Deferred" below.

## Belongs to sibling sub-modules (parked, not scoped here)

- Structured event log, tool-call trace, per-turn cost breakdown, runtime error surface → **5.3 Event Log &
  Cost** (reads `CallSession.logs`/`.usage`).
- Waveform player, signed media access, the full transfer-outcome panel → **5.4 Recording & Transfer Outcome**
  (reads `CallSession.waveform_peaks`/`.recording_blob`/`.transfer`).
- Populating `analysis`/`transcript` from a real call (the post-call analysis step, the turn loop that appends
  transcript entries) → **Module 3 (Call Runtime)**, unbuilt. 5.2 is a pure reading surface over columns Module 3
  will one day write.
- An AI-generated one-line summary inline in the **call log list row** → **5.1's own list template** (a polish
  pass on an already-built page), not this sub-module — 5.2 owns the detail page's Analysis Panel, not the list.

## Out of scope for this product (outside the seven capabilities)

- **Bulk/date-ranged CSV or PDF export of many calls at once** (Ruby's Activity export, Dialpad's CSV download at
  scale) — this is a list-level reporting feature, not part of any of the seven capabilities and not named by any
  Module 5 sub-module bullet; would need its own explicit scoping pass if ever added.
- **Per-turn sentiment/emotion scoring** (Dialpad) — no sentiment field exists on `transcript`'s documented shape
  and none of the seven capabilities calls for conversational-quality scoring; adding one would be a schema
  change this VIEW sub-module must not make.
- **Tabbed/paginated detail-page layout** (Synthflow) — a UI-architecture choice this product's existing
  `detail.html` (single scrolling page, stacked cards) has already made differently; not something this pass
  should introduce mid-module.
- **Externally shareable/guessable transcript links** (Dialpad's "share the link with a teammate") — this product
  has no anonymous/external-recipient audience among its seven capabilities (every reader is an authenticated
  tenant user); building one would be a security regression against the same reasoning that governs recording
  access, not a feature gap.

## Deferred (later passes / integrations)

- **In-transcript keyword search / jump-to-phrase** (Dialpad, PolyAI) — real, client-side-only, no schema impact;
  not named by this sub-module's four bullets, worth a later polish pass once transcripts are long enough to
  need it.
- **CSV download of a single transcript** (Dialpad) — distinct from "print"; not named by the bullet.
- **List-row AI summary** (Dialpad, Rosie) — reads the same `analysis.summary` this sub-module unlocks, but is
  5.1's list template's polish item, not 5.2's detail-page scope.
- **Server-rendered PDF export with a durable, possibly-signed download link** — deliberately declined this pass
  (see Compliance); revisit only if a genuinely external-recipient use case ever gets scoped, and even then it
  should follow the existing signed-media-URL pattern (5.4's "Signed Media Access" bullet), not a new mechanism
  invented here.
