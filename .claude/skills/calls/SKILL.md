---
name: calls
description: Work on the Call Logs module (call sessions, transcripts, event logs, per-turn cost, recordings, transfer outcome). Use when the user asks to add/change/debug anything under apps/calls or templates/calls, anything about CallSession, its JSON columns, the call log list or detail page, the transcript or event-log surfaces, the recording player, transfer outcome, or invokes /calls.
---

# calls — Call Logs (Module 5)

App path `apps/calls`, templates `templates/calls/`, mounted at **`/calls/`**, `app_name = 'calls'`.

This module is the **read surface over what the voice agent did**. It writes nothing at runtime — Module 3
does — and a completed call is a record of what happened, so this app has no create, edit or delete
anywhere. That absence is the design, not an unfinished edge.

## Build state

| Sub-module | Status | Adds |
|---|---|---|
| 5.1 Call Log List | **BUILT** | `CallSession` — the only model this module will ever own |
| 5.2 Call Detail & Transcript | **BUILT** | none — a **view** sub-module |
| 5.3 Event Log & Cost | **BUILT** | none — a **view** sub-module |
| 5.4 Recording & Transfer Outcome | not built | none — a **view** sub-module |

> **Update this file, never re-author it.** 5.1 authored it because `apps/calls` was a brand-new app.
> Every later sub-module APPENDS its routes / templates / seeder rows. Rewriting clobbers the previous
> sub-module's documentation.

## The one rule that governs this whole module

**Invariant 2: one call log.** A call is exactly one `CallSession` row. Its transcript, event log, per-turn
usage, analysis and transfer outcome are **JSON columns on that row** — not `CallTurn`, not `CallEvent`, not
`ToolCall`, not `Transcript`.

**5.2, 5.3 and 5.4 add ZERO models and ZERO migrations.** They are reading surfaces over the columns 5.1
already shipped. `makemigrations calls --check` reporting "No changes detected" is part of each one's
acceptance criteria. **When one of those sub-modules feels like it wants a table, that feeling is the
invariant firing** — the data is already on the row.

Why one table: a session is written by one process that owns the call for its whole life, and read whole on
one detail page. Nothing queries across turns — no cross-call transcript search, no per-turn billing rollup.
A `Call` + `CallTurn` + `CallEvent` split would buy query power nothing uses and cost a database write PER
TURN on the latency-critical realtime loop.

## Models

### `CallSession` — 5.1 · `models/CallLogList/CallSessions.py`

Base `TenantLocationOwned`. Reuses `scheduling.Contact` (Invariant 1 — never a `Caller` model).

* `contact` — FK `scheduling.Contact`, **nullable, `SET_NULL`**. An unknown or withheld caller ID is the
  normal case, not missing data. `SET_NULL` because erasing a person must never delete the call record —
  this row is the retention artefact of record.
* `provider_call_sid` — **`unique=True`, a real DB constraint.** This is Module 3's **webhook idempotency
  key**: Twilio redelivers, and a retry must not mint a second session. A plain
  `get_or_create(provider_call_sid=sid, defaults={...})` is the intended write.
* `status` — **FIVE values**: `in_progress` (default) / `completed` / `abandoned` / `transferred` /
  `failed`. The ERD's three-value list was stale; `templates/partials/_call_status_badge.html` was already
  shipped branching on all five, and CLAUDE.md names the same five as canonical. **Code is truth** — 5.1
  corrected the ERD rather than the other way round.
* `mode` — `live` / `google` / `gemini`, mirroring `AgentSetting.voice_provider`.
* `from_number`, `to_number` — real columns (not buried in `metadata`), indexed.
* JSON columns: `transcript` (list), `logs` (list), `analysis` (dict), `usage` (list), `transfer` (dict),
  `waveform_peaks` (null = never computed, which differs from a genuinely silent recording), `metadata`.
* `recording_blob` — a PRIVATE storage path, `''` = no recording. Served only through a short-lived signed
  URL, never as a `src` against a public media path.
* `duration_display` — derived, never stored. Returns `'—'` for a skewed pair (`ended_at < started_at`)
  rather than a negative: the two stamps come from different clocks once Module 3 writes them, and a
  plausible-looking wrong number is worse than an admitted gap.
* Indexes `(tenant, location, started_at)`, `(tenant, status)`, `(tenant, contact)`. Ordering `-created_at`.

### `scheduling.Appointment.booked_by_session` — added by 5.1

FK to `CallSession`, `SET_NULL`, `related_name='booked_appointments'`, migration `scheduling/0005`. Absent
from 4.3 until 5.1 because Django refuses a relation to an uninstalled app. `SET_NULL` is load-bearing:
purging a call log under its retention window nulls the provenance link, never deletes the booking that call
produced.

## Contracts Module 3 must honour (written here because the schema cannot enforce them)

1. **One WRITER is not one WRITE.** The row is created when the inbound webhook resolves the dialed number,
   appended to as the call proceeds, and finalized in the consumer's `disconnect()`. Buffering a whole call
   in process memory for one closing `UPDATE` loses the entire transcript and cost trail on a mid-call
   worker restart — not just the tail — and strands the row at `in_progress` with no `ended_at` forever.
2. **`usage` is appended per turn as a delta** (`{turn_sequence, cost_breakdown, cost_usd}`), never
   re-aggregated. A call's cost is summed from the list at read time, so a corrected rate card re-prices
   history.
3. **Concurrent JSON appends are the writer's problem.** No version column exists, so two coroutines that
   each read-append-save will silently drop one entry. Guard with a single writer task per call, or
   `select_for_update()` in a `transaction.atomic()` inside `database_sync_to_async`.
4. **A non-empty `recording_blob` REQUIRES a consent basis in `metadata`.** Validate in the write path
   before persisting — a `CheckConstraint` cannot do it, because MySQL cannot portably assert anything
   about a JSON sub-key. A recorded call with no consent record is the failure that matters, and a
   malformed or replayed webhook is how one gets created.
5. **`transfer` carries an optional `attempts` list** — `[{destination, result}]` — alongside the final
   `result`/`destination`. `AgentSetting` has a `transfer_secondary_number`, so "primary rang out, secondary
   answered" is a designed path; without the list it could only be narrated in free-text `reason`, where
   nothing can query it.

## Routes

`app_name = 'calls'`, mounted at `/calls/`. **Two routes, and that is the whole surface:**

* `calls:callsession_list` — `/calls/`
* `calls:callsession_detail` — `/calls/<int:pk>/`

* `calls:callsession_transcript_print` — `/calls/<int:pk>/print/` (5.2)

There is deliberately **no `callsession_create` / `_edit` / `_delete`** — no route, no view, no `ModelForm`.
`apps/calls/tests/test_security.py` asserts `NoReverseMatch` on all three, so the absence is enforced by
test rather than by convention. Every view is `@login_required` **and** `@require_http_methods(['GET'])`: a
POST gets 405, not a silent 200. The CRUD apps do not need that guard because their list views sit beside a
create view that legitimately answers POST; this app has nothing that does.

**The two transcript-bearing pages — detail and print — also carry `@never_cache`.** A full conversation
restored from the browser's back-forward cache after a receptionist logs out on a shared workstation is a
real exposure, and a transcript is the most sensitive PII in the product. `no-store` forces a re-fetch and
re-authorisation rather than a bfcache restore. The list and the rest of the product carry the same latent
gap and want a shared fix (a middleware or base decorator), not a per-view half-sweep — see 5.2's review
notes.

## Templates

* `templates/calls/calllog/callsession/` — `list.html`, `detail.html`, `_filters.html`. 5.2 wired the
  transcript and analysis panels into `detail.html`'s marked slot.
* `templates/calls/transcript/transcript_print.html` — 5.2's standalone printable page. A STANDALONE page
  (not an entity list/detail/form), so it sits here rather than in `calllog/callsession/` — Template Folder
  Structure rule 6, which names this exact path as its example. It extends `base.html` so the `@media print`
  block already in `theme.css` applies with zero CSS work.

**Shared partials this module owns the contract for** (all pre-existing):

* `partials/_call_status_badge.html` — **the single source of truth for the status map.** Always
  `{% include "partials/_call_status_badge.html" with obj=<session> %}`; never inline the branches.
  `in_progress`→`badge-info`, `completed`→`badge-green`, `abandoned`→`badge-muted`,
  `transferred`→`badge-info`, `failed`→`badge-red`. Five statuses, four classes — `badge-info` twice on
  purpose. There is no `badge-purple`. Always keep the `{% else %}` fallback.
* `partials/_transcript.html` — **wired by 5.2** into both the detail page and the print page. **Its context
  contract is `session`, not `obj`** — the include line MUST read
  `{% include "partials/_transcript.html" with session=obj %}`, passing the page's `obj` under the name the
  partial expects. Get it wrong and it reads `session.transcript` against an undefined variable, which Django
  resolves to falsy: the empty state renders on every call, silently, never erroring.
* `partials/_transfer_outcome.html`, `_audio_player.html` — **exist but wired by 5.4, not yet.**
  `detail.html` carries comments marking where each lands. Including one early claims work no reviewer has
  seen.

**The analysis panel (5.2, in `detail.html`) renders defensively.** An abandoned/failed/in-progress call has
`analysis == {}` — five seeded rows are exactly that. Read keys via the `dict_get` filter (a plain
`dict.get`, purpose-built for this), print each value as-is rather than destructuring a shape Module 3 has
not fixed, guard the `extracted_data` table on `.items` (so a non-dict shape falls through to a fallback
rather than rendering a header over an empty tbody), show an explicit "No analysis" empty state for the empty
dict, and **never print a raw `None`**.

**The event log + cost cards (5.3, in `detail.html`) are the PII-heaviest surface in the product.** The event
log timelines `obj.logs` (level badge via `level_badge`, category, title, `occurred_at` via `iso_time`,
`raw_json` in a `<details>` disclosure OFF by default), and a `category == 'tool'` entry adds the tool name,
ok/failed, `duration_ms`, the `error.code`+`message`, and its `arguments`. **Redaction is the load-bearing
rule here** — a tool-call args payload is a full name and a date of birth:

* **`redact_args`** (`ui.py`) is the DISPLAY-time backstop to Module 3's (unbuilt) write-path redaction — even
  a value the write path forgets is hidden at render. It walks dicts AND lists to depth 6, replacing the value
  of any key whose name contains a sensitive substring with `[redacted]`. **Both call sites must redact to the
  same depth**: the trace passes `arguments`, the disclosure passes the whole `raw_json` one level shallower —
  a one-level filter leaked a doubly-nested value in the disclosure (the bug that was fixed). What it CANNOT
  catch, by construction: a bare string in a list (only protected if the list's KEY is a denylist stem like
  `attendee`/`participant`), and PII used as a dict key. Those are Module-3 tool-schema rules, not display fixes.
* **`pretty_json`** returns a **plain str, never `SafeString`**, so autoescape still escapes the raw payload —
  the stock `pprint` marks its output safe and would not. The `<details>` dumps `raw_json|redact_args|pretty_json`,
  redacted BEFORE the dump so it cannot become a hole around the trace.
* **Nothing in these cards is `|safe`.** `error.message` is the one value rendered raw, documented in-template
  as system-authored per the tool-result envelope contract (`redact_args` works on dict values by key, and a
  free string has no key) — the redaction for it belongs on the write side.
* **`total_cost_usd`** (a `CallSession` @property) sums `usage[].cost_usd` at read time — never a stored column
  (ERD rule). Guarded: a non-list `usage` coerces to `[]` (so it cannot 500 the page), a non-numeric or
  non-finite `cost_usd` is skipped (so a corrupted row cannot render `$nan` on a billing figure).
* The cost table is the four-way `stt/llm/tts/telephony` split per turn + a grand total; empty `usage` shows a
  "No cost recorded" state rather than `$0.0000`.

The list Actions column is **View only**. Caller numbers always render through the `phone_e164` filter
(`{% load ui %}` required) — never raw, so the same number never appears in two shapes. Nothing
caller-controlled is ever `|safe`. **The list renders none of the JSON columns**; the transcript is 5.2's
surface.

## The list's five filters

Search `q` (from/to number, contact name + phone), date range `from`/`to`, `status`, `mode`, `outcome`.

* **Date filters never use `started_at__date`.** That lookup converts in the ACTIVE timezone and compiles to
  `CONVERT_TZ()` on MySQL, which returns NULL unless the server's timezone tables are loaded — so it passes
  under SQLite in tests and silently returns zero rows in production. Convert a local day to a half-open UTC
  range via `apps.scheduling.availability.local_day_bounds_utc`.
* **`outcome` reads inside the `transfer` JSON column.** `no_transfer` uses `transfer__result__isnull=True`,
  not `transfer={}` — the key is genuinely missing both when nothing was attempted (the common case) and
  when the runtime died before writing a result. Exact-dict equality would catch only the first and would
  compile differently across MySQL and SQLite, which is the divergence that passes CI and returns wrong rows
  in production.
* **Known accepted scan:** a JSON key transform cannot use an index. The outcome filter is bounded by
  location (it rides `idx_call_tenant_loc_started`) but NOT by time unless the user also set a date range.
  This table grows per call. If it ever turns hot, the answer is a generated column on `transfer.result`.
* Junk in any parameter degrades to "no filter" and never raises.

## Query discipline

* **`location_sessions()` lives in `apps/calls/views/_helpers.py`** — the ONE tenant+location-scoped call
  queryset, imported by 5.1's list/detail and 5.2's print view. It was entity-local in `CallLogList` while
  5.1 was its only reader and moved here when 5.2 became the second (Backend Package Structure rule 5). A
  second filter over `CallSession` is a second place a cross-location leak could hide, and that leak is a
  transcript — so there is exactly one. It carries `.select_related('contact', 'location')` **and**
  `.prefetch_related('booked_appointments__service')`. `booked_appointments` is a REVERSE FK that
  `select_related` cannot follow, and `service` is a forward FK on the far side of it — miss either and the
  page pays a query per row. The print page never renders bookings, so it carries that prefetch as one cheap,
  bounded, unused query — a deliberate trade for one audited scoping surface over two.
* **The LIST defers the JSON columns** (`transcript, logs, analysis, usage, waveform_peaks, metadata`) — it
  renders none of them, and Module 3 will make them large. **Deferred at the list call site, NOT on the
  shared helper**: the detail page and 5.2–5.4 read the whole row on purpose (that is Invariant 2's design),
  and deferring on the helper would turn each of those reads into its own extra query — the same N+1 in a
  new coat.
* `CallSessionAdmin.get_queryset()` defers the same columns. `readonly_fields` governs the change form, not
  the changelist, which otherwise does `SELECT *`.

## Realtime surfaces

**This module has no realtime surface** — no `consumers/`, no `routing.py`, no `async def`, no websocket
route, no provider adapter, and it does not touch `config/asgi.py`. It ships the TABLE the realtime layer
writes to; Module 3 ships the writer. See the contracts section above before implementing that writer.

## Tools & prompt surface

**This module registers no LLM tool and injects no prompt variable.** `CallSession` is Module 3's write
target, and `session_id` — like `tenant_id`, `location_id` and `contact_id` — comes from server-side session
state and is **never a tool parameter** (Invariant 3).

## Seeder

`manage.py seed_calls` (`--flush` to rebuild). Idempotent, dedupe keyed on the unique `provider_call_sid`.

Seeds **11 sessions across all four demo locations** and both demo tenants, covering all five statuses,
mixed modes, identified and unidentified callers, and every `transfer.result` branch. One Downtown call is
credited with creating a real `Appointment` via `booked_by_session`, so the contact-and-booking link is
demonstrable end to end. Abandoned, failed and in-progress rows carry an **empty `analysis` on purpose** —
nothing happened to analyse, and that is 5.2's defensive-rendering path.

**Touches no provider under any `PROVIDER_MODE`** — this app has no adapter at all. Every transcript, log
and cost figure is hand-authored fiction.

**Seeder order matters, and getting it backwards fails SILENTLY:**

```
seed_tenants → seed_accounts → seed_agents → seed_scheduling → seed_calls
```

`seed_scheduling --flush` deletes and recreates the `Contact` rows, and `CallSession.contact` is `SET_NULL`
— so flushing scheduling AFTER calls nulls the contact on every session just seeded. Nothing errors, the
pages still render, and the demo simply shows every caller as unidentified, which reads as a scoping bug
rather than a stale seed. If you flush scheduling, re-run `seed_calls --flush` afterwards.

## Conventions & gotchas

* **Tenant AND location on every queryset.** `location_sessions(request)` (in `views/_helpers.py`) returns
  `.none()` when no location is active. A cross-location IDOR here leaks a full transcript, not a timestamp.
* **This module has no logger, deliberately.** Every other view module keeps one, so its absence reads as an
  oversight unless stated: these views only read, and the only things worth naming in a log line — the
  caller's number, who they were matched to, what was said — are exactly the PII that must never reach INFO.
* The appointment detail page's "how this was booked" panel **withholds the whole description** — number,
  status, timing — when the session's location differs from the appointment's, not merely the link. The
  number and outcome are the call's substance; rendering them under a withheld link would hand one site a
  readable summary of another's call.

## Common tasks

* **Add a field** → `models/CallLogList/CallSessions.py`, `makemigrations calls`, commit the migration
  separately. Note that a `help_text` change alone generates a migration — Django tracks it.
* **Add a view sub-module (5.4)** → templates + (only if genuinely a new page) a `views/<SubModule>/` +
  `urls/<SubModule>/` folder with the re-export blocks, a `LIVE_LINKS["5.M"]` entry (empty `{}` if the surface
  is reached through the existing detail page) — and **no model, no migration**. Import `location_sessions`
  from `views/_helpers` for scoping; do not redefine it. Extend `seed_calls` idempotently only if the pages
  need richer JSON. Two worked examples now: **5.2** added a print ROUTE (so a new view/url folder) plus two
  `detail.html` panels; **5.3** added NO backend layer at all — two more `detail.html` cards, three `ui.py`
  filters and one model `@property`, because its surfaces render on the page that already has a view. Reach for
  a new view/url folder only when there is a genuinely new route; otherwise it is template + filter + property.
* **Add a filter** → parse in the view BEFORE pagination, validate against a fixed choice set, pass the
  choices in context, and make junk degrade to "no filter".
* **Extend the seeder** → add a spec with a fresh `provider_call_sid`; the dedupe key is that SID.

## Sidebar wiring

`apps/accounts/navigation.py` → `LIVE_LINKS`:

```python
'5.1': {'Call Logs': 'calls:callsession_list'},
'5.2': {},   # built; surfaces reached through the 5.1 detail page, so no link of its own
'5.3': {},   # built; event log + cost cards on the detail page, same as 5.2
```

## Tests

`apps/calls/tests/` — `conftest.py` (its own `make_call_session` factory; pytest conftest fixtures do not
cross sibling app-test packages), `test_models.py`, `test_views.py`, `test_security.py`,
`test_seed_calls.py`, `test_transcript_views.py` (5.2), `test_ui_filters.py` + `test_event_log_cost_views.py`
(5.3 — the redaction/pretty_json/total_cost_usd filters and the event-log/cost cards). **143 passing**, 679
across `apps/scheduling apps/calls` together. The `ui.py` filters are tested under `apps/calls/tests/` because
`apps/accounts` has no test package — note that if you add `accounts` tests later.

**Query-count tests measure the VIEW, not the request.** A `Client` request carries a constant overhead of
session + auth + tenant/location middleware + the navigation context processor, so a literal
`assert_max_num_queries(2)` through the full stack can never pass. Assert on the view's own queryset plus
`paginate()` directly, and keep a separate "count does not grow with row count" test for N+1 protection.
