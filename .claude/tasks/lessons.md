# Lessons

This file is the project's running list of failure classes — the mistakes that cost time, written as rules a
reviewer can check. **A lesson is appended after a user correction**: whenever the user corrects a behaviour, add
(or sharpen) the lesson that would have prevented it, keeping existing numbering stable and appending the new one
at the end of its group. A lesson number is **stable once assigned** — never renumber an existing lesson and never
reuse a retired number — so that any future reference of the form `(L7)`, from `.claude/CLAUDE.md`, a review agent
or a `todo.md` plan, keeps pointing at the same rule. **No file cites these numbers yet**; the stability rule
exists so that citations remain safe to add. Review this file at session start before touching code; if a lesson
here contradicts what you were about to do, the lesson wins. The numbers below are the seed set — they describe
traps known to this domain and this stack, not history in this repo.

---

## Django/template traps

## L1 — Multi-line `{# #}` comment renders as visible page text

**Symptom:** raw comment text appears on the rendered page as body copy. No exception, no warning, 200 OK — it is
only ever caught by looking at the page.
**Cause:** Django's `{# … #}` comment syntax is **single-line only**. As soon as the comment spans a newline the
engine stops treating it as a comment and emits the remainder as literal text.
**Rule:** Never write a `{# … #}` comment that spans more than one line — use `{% comment %} … {% endcomment %}`
for anything multi-line. A reviewer greps the diff's templates for `{#` and confirms the matching `#}` is on the
same line; a smoke run asserts no rendered page contains the literal strings `{#` or `{% comment`.

## L2 — Unguarded `page_obj.previous_page_number` 500s on page 2

**Symptom:** the list page works perfectly; clicking through to page 2 (or the last page) returns a 500 —
`EmptyPage` / `InvalidPage` from the paginator.
**Cause:** `previous_page_number` / `next_page_number` raise when there is no such page. The pagination partial
calls them unconditionally, and page 1 never exercises the failing branch, so the bug ships.
**Rule:** Every use of `previous_page_number` sits inside `{% if page_obj.has_previous %}` and every use of
`next_page_number` inside `{% if page_obj.has_next %}`. Smoke tests must hit **page 2 and the last page**, not
just page 1.

## L3 — Context-key / template-variable mismatch renders a silently blank region

**Symptom:** a table, card grid or sidebar block is simply empty. Status 200, nothing in the log, no template
exception — the page looks "built, with no data".
**Cause:** Django resolves an unknown template variable to the empty string instead of raising. A view passing
`call_sessions` with a template looping `{% for c in calls %}`, a field named `duration_seconds` read as
`duration_secs`, or a `stats` dict accessed as `missed_count` instead of `stats.missed`, all fail silently.
**Rule:** Name the context key and the template variable identically and check them against each other in the
same edit; pin **both** the list variable and the detail/edit object variable. Read the view's context dict and
the template side by side — never assume a template "gets" data it was not explicitly passed. Any empty region in
a smoke run is a defect until proven to be genuinely empty data.

## L4 — A junk GET filter parameter 500s the list view

**Symptom:** `?agent=abc` (or `?status=`, `?page=999`, `?date_from=notadate`) returns a 500 instead of an empty
or unfiltered list.
**Cause:** the view feeds a raw GET string straight into `filter(agent_id=...)`, `int()` or a date parser, and
the resulting `ValueError` / `ValidationError` is uncaught.
**Rule:** Parse every GET filter defensively — `.strip()`, validate, skip the filter when the value is unusable —
so an unknown or malformed parameter yields a normal page, never a 500. Every list view is smoke tested with a
junk value for each of its filter params. Apply filters to the queryset **before** pagination.

## L5 — theme.css modifier classes are colour-named; semantic names render unstyled

**Symptom:** a badge or stat icon renders as plain, unstyled grey text. No error — the class simply matches no
rule in the stylesheet.
**Cause:** the design system's modifier classes are **colour-named and fixed** (the `badge-*` / `stat-icon-*` /
`text-*` inventory in `static/css/theme.css`). Inventing semantic modifiers such as `badge-success`,
`badge-danger` or `badge-warning` produces valid HTML that matches nothing.
**Rule:** Never invent a modifier class. Enumerate the real inventory first with
`grep -oE '\.(badge-[a-z]+|stat-icon(\.[a-z]+)?|text-[a-z]+)' static/css/theme.css | sort -u` and use only what
that prints. Map call status onto those existing colour classes — `ringing`→`badge-amber`,
`in_progress`→`badge-info`, `transferred`→`badge-info`, `completed`→`badge-green`, `missed`→`badge-red`,
`failed`→`badge-red`, `no_answer`→`badge-muted`, `busy`→`badge-muted`, `voicemail`→`badge-slate`. Nine statuses
share six badge classes; `badge-info`, `badge-red` and `badge-muted` are each intentionally used twice. There is
no `badge-purple`. Always ship an
`{% else %}` fallback rendering `{{ obj.get_status_display }}`. Badge conditions compare against the **exact**
model choice values — `'no_answer'` not `'noanswer'`, `'in_progress'` not `'inprogress'`, `'voicemail'` not
`'vm'`.

---

## Multi-tenant & security traps

## L6 — A secret left in `Meta.fields` ships in plaintext in the edit form

**Symptom:** nothing looks wrong in the UI, but the page source on the edit form shows the provider auth token,
API key or webhook signing secret in the input's `value=` attribute — now in the browser cache, in any
intermediary log, and in page history.
**Cause:** a `ModelForm` renders every field in `Meta.fields`; a credential field listed there is bound to its
current value and echoed into the HTML.
**Rule:** Credential fields (telephony auth tokens, LLM/STT/TTS API keys, webhook signing secrets, SIP passwords)
are **never** in `Meta.fields`. They are written through a dedicated write-only flow — a blank input that only
writes when non-empty, display limited to a prefix plus a hash, reveal-once at generation time. A reviewer greps
the diff's forms for any field whose name contains `token`, `secret`, `key`, `password` or `credential` and
confirms it is excluded.

## L7 — A secret flashed via `messages.success` persists in the session store

**Symptom:** the one-time reveal looks careful and works, but the plaintext value now sits in the message
storage — session backend or signed cookie — long after the page was dismissed.
**Cause:** `messages.*` serializes the message body into storage, where it survives until consumed and, under
cookie storage, is readable client-side.
**Rule:** Never pass a secret through `messages.*`. Render a reveal-once value directly into the response context
for that single render; never log it, never put it in a redirect query string, never include it in an error
message. A reviewer greps the diff for `messages.` calls interpolating a credential field.

## L8 — Tenant resolved from a caller-controlled parameter outside the HTTP request

**Symptom:** nothing, until a cross-tenant read or write happens. Everything passes in single-tenant dev and in
tests that only exercise one tenant.
**Cause:** the "filter by `request.tenant`" rule assumes an HTTP request. Telephony webhooks, Channels consumers
and background tasks have **no** `request.tenant`, so the tenant is taken from whatever is at hand — a query
string, a websocket URL segment, a JSON body field — all of which the caller controls.
**Rule:** Outside the HTTP request cycle the tenant MUST be resolved from a **verified** source: the dialed
`core.PhoneNumber`, the `core.Interaction` row, or a signature-verified provider payload. Never from a query
string, path segment or body parameter the caller supplies. The "never unscoped" guarantee is identical; only the
resolution mechanism differs. A reviewer flags any `tenant_id` read from a websocket URL or webhook query string,
and any queryset inside a consumer, task or webhook that is not scoped to a verified tenant.

## L9 — An unverified or non-idempotent provider webhook

**Symptom:** two kinds, both quiet. Forgery: a hand-crafted POST creates interactions, books appointments or
drains a tenant's balance, and the rows look exactly like real ones. Replay: the provider redelivers on its
normal retry schedule and the tenant is charged twice, texted twice, or double-booked.
**Cause:** `@csrf_exempt` on the handler without signature verification; and no uniqueness anywhere on the
provider's event identity, because retries never happen in manual testing.
**Rule:** Verify the provider signature (`X-Twilio-Signature`) over the **raw body** and the **exact** public URL,
with a constant-time compare, **before any side effect**; reject missing/invalid with 403 and zero writes.
`@csrf_exempt` is acceptable only when paired with verification. Make the handler idempotent with a unique
constraint on `(provider, provider_sid, event_type)` — a redelivery must produce exactly one `core.Interaction`,
one `core.UsageEvent`, one SMS, one booking. Handlers return the provider's expected body (TwiML/JSON) or a bare
200/204 — **never a redirect**.

---

## Realtime/async traps

## L10 — A sync ORM or SDK call inside an async consumer freezes audio for every concurrent call

**Symptom:** audio stutters and callers hear multi-second dead air — typically only under concurrency, so it
passes every single-call manual test. Sometimes it surfaces instead as `SynchronousOnlyOperation`.
**Cause:** an `async def` consumer or task runs on the event loop. Any blocking call inside it — `.objects.get()`,
a sync `requests`/`httpx.Client` request, file I/O, `time.sleep`, a blocking provider SDK method — stops the loop,
and one stalled coroutine stalls **every** call served by that worker.
**Rule:** No synchronous ORM, HTTP, file or SDK call inside an `async def`. Use `database_sync_to_async` for ORM
access, `sync_to_async(thread_sensitive=False)` or `asyncio.to_thread` for blocking libraries, or a genuinely
async client. Every external provider call carries an explicit timeout and a bounded retry, and a failure degrades
to a spoken fallback rather than silence. A reviewer greps each `async def` body in the diff for `.objects.`,
`requests.`, `httpx.Client`, `open(` and `time.sleep`. Exceptions in the receive loop are caught so one bad frame
does not kill the call.

## L11 — An un-namespaced Channels group leaks another tenant's live call

**Symptom:** nothing in normal use — a single tenant sees exactly what it should. It appears only when two
tenants have concurrent calls whose ids collide, at which point tenant A receives tenant B's live transcript and
audio events.
**Cause:** group names built from a bare identifier (`call_{interaction_id}`, `live_calls`) share one namespace
across the whole channel layer, and `group_add` authorizes nothing by itself. Compounded when the consumer
accepts the connection first and checks ownership afterwards.
**Rule:** Channels group names are always tenant-namespaced (`t{tenant_id}:call:{interaction_id}`). Consumers
authorize **in `connect()`** — session/permission checked, interaction ownership verified against the resolved
tenant — and reject with a close code; never accept-then-check, and never rely on `@login_required`, which does
not apply to consumers. `disconnect()` releases the interaction and flushes buffered events. A reviewer checks
every `group_add`/`group_send` name for a tenant prefix and every `connect()` for an authorization branch.

---

## LLM & tool-dispatch traps

## L12 — One field, three names (`dob` / `birthdate` / `date_of_birth`)

**Symptom:** a value the caller clearly gave goes missing at the point it is needed — the booking is created with
a blank field, or a tool reports a required argument absent although the model supplied it. No exception; the key
just never matches.
**Cause:** the same logical field is spelled differently in the tool declaration's `parameters`, in the session
state dict, and in the model or serializer, so each hop silently drops it.
**Rule:** A field has exactly **one** name across the declaration, the dispatcher, the session state and the
database column. When adding or renaming a tool parameter, grep the whole path for both the old and the new name
in the same edit. A reviewer diffs the declaration's parameter names against the keys the dispatcher reads and
the model fields it writes.

## L13 — Inconsistent tool result envelopes across tools

**Symptom:** the "did it actually succeed" check, the usage recorder and the spoken confirmation work for some
tools and silently misread others. A failure gets narrated to the caller as a success.
**Cause:** each tool grew its own return shape — one returns prose, one a bare `{"id": …}`, one
`{"status": "ok"}`, one raises — so nothing can key off a common flag.
**Rule:** **Every** tool returns exactly
`{"ok": bool, "data": {...}, "error": {"code": ..., "message": ...} | null}` — never prose, never a bare id,
never a per-tool success key. The `ok` flag is what the recorder and the confirmation logic read. A reviewer
checks every return path of every new or changed tool against this shape, error paths included.

## L14 — Two runtime paths, one dispatcher: silent drift between them

**Symptom:** a tool behaves correctly in the turn-based path and subtly differently on live calls (or the
reverse) — an argument coerced in one path and not the other, `ok` computed differently, usage recorded twice or
not at all. Tests pass because they exercise only one path.
**Cause:** both the realtime websocket path and the turn-based path invoke the tool layer; whenever logic lives
at the call site instead of inside the shared dispatcher, the two copies drift.
**Rule:** The dispatcher signature `apply_tool_call(state, name, args)` is **transport-agnostic** — argument
coercion, authorization, envelope construction and usage emission live inside it, never at the call site. Every
new or changed tool is traced and tested through **both** runtime paths in the same change. This is the top
regression risk in the product; treat an untested second path as an unfinished change.

## L15 — The prompt promises a capability whose tool does not exist or is disabled for that tenant

**Symptom:** the agent confidently tells the caller it will transfer them, text them a link or look something up,
and then nothing happens. The call ends with the caller believing an action was taken.
**Cause:** prompt text and tool enablement are edited independently, so a published prompt describes a capability
that was never implemented or is absent from that tenant's `AgentVersion.enabled_tools`.
**Rule:** Prompt and tool surface change together: any capability a prompt promises must have an implemented tool
that is enabled for that agent version — and the prompt must **never name a tool function or a tool parameter**,
it describes what the agent can do, not how it is wired. A reviewer cross-checks the capability sentences in a
changed prompt against `enabled_tools` and the declaration list.

## L16 — Stale `current_time` on long calls

**Symptom:** on a call that runs past a boundary the agent asserts the wrong day, offers "today" slots that have
already passed, or reports the business as open after closing. Short test calls never reveal it.
**Cause:** runtime prompt variables (`current_date`, `current_time`, `is_open_now`) are computed **once** at call
start and reused for the whole conversation.
**Rule:** Time-dependent runtime variables are recomputed per turn, not captured at call start, and runtime
variables always override tenant-configured ones. `is_open_now` in particular is computed **server-side** from
`core.BusinessHours` and injected as the literal string `"yes"`/`"no"` — the model must never derive open/closed
from raw hours plus a clock. A reviewer checks where each time-derived variable is evaluated in the turn loop.

## L17 — The default prompt duplicated in several places, drifting apart

**Symptom:** changing the default greeting or system prompt fixes one surface while a seeder, a test fixture or a
fallback constant keeps serving the old wording. Nobody can say which text a given call actually used.
**Cause:** the same default text was pasted into a model default, a form initial, a seeder and a fallback branch.
**Rule:** A default prompt has **one** source of truth — a prompt-template row, with `null` on the agent version
meaning "inherit the current default" — and every other surface reads it rather than restating it. Because
published `core.AgentVersion` rows are immutable and every `core.Interaction` records the exact version it ran,
"which prompt said that?" must always be answerable. A reviewer greps the diff for duplicated prompt literals.

---

## Booking-flow traps

## L18 — The re-offer loop: re-checking availability after the caller has confirmed

**Symptom:** the caller says "yes, 3pm works", the agent offers slots again, the caller confirms again, and the
call never converges. Callers hang up mid-loop. Nothing errors and no row is written.
**Cause:** the confirmation turn re-invokes the availability tool instead of proceeding to the booking tool, so
every confirmation restarts the offer step.
**Rule:** Availability search and booking are distinct steps with a one-way transition: once a slot is confirmed,
the next tool call is the booking call, never another availability search. Track the confirmed slot in
server-side session state and treat a second availability call after confirmation as a defect. A reviewer walks
offer → confirm → book for any change to the booking flow.

## L19 — Announcing success before verifying the write

**Symptom:** the agent says "you're all booked for Tuesday at 3" and there is no `core.Appointment` row. Nothing
errors — the tenant finds out from an empty slot and a no-show.
**Cause:** the spoken confirmation is generated from the model's intent rather than from the tool result, or the
tool returns before the write commits and its `ok` flag is never checked.
**Rule:** The agent confirms an outcome only after the tool returns `ok: true` **and** the row exists, and the
confirmation wording is derived from the returned `data` (the appointment number, the stored start time), never
from what the model believed it requested. Failures produce an explicit spoken fallback, never an optimistic
confirmation. A reviewer checks that every user-facing success statement is gated on the envelope's `ok`.

## L20 — Verbatim-echo drift on slot fields

**Symptom:** a booking lands at the wrong time, against the wrong resource, or fails validation, because the
model echoed back a slightly different start time, timezone or resource id than the one it was offered.
**Cause:** the availability tool returned semantic fields (start, resource, service) that the model had to repeat
verbatim into the booking call. Models paraphrase, reformat and occasionally invent such values.
**Rule:** Availability returns **one opaque signed `slot_token` per slot** — a short-TTL blob encoding
start/resource/service/tenant — and the booking tool accepts only that token. The token cannot be mangled or
invented, and the backend verifies the slot was actually offered **in this interaction**. Never make the model
re-emit semantic slot fields. Flag any booking tool that accepts a raw start time plus resource id from the model.

## L21 — Caller identity is not the booking-subject identity

**Symptom:** a parent books for a child, an assistant for an executive, a neighbour for a relative — and the
appointment is attached to the caller. The wrong person gets reminded and the record is wrong.
**Cause:** the code treats the resolved caller as the person the booking is for, because in the common case they
are the same person.
**Rule:** `core.Interaction` carries `contact` (the caller) and `subject_contact` (who the booking is for) as
**distinct** fields, and the booking path resolves the subject explicitly rather than defaulting to the caller.
Identity arguments (`tenant_id`, `contact_id`, `interaction_id`) still come from server-side session state and are
never tool parameters; any model-supplied id (`appointment_id`, `slot_token`) is authorized against the tenant
**and** the identified contact — this is an IDOR with an LLM in the middle.

---

## Windows/environment traps

## L22 — `%-d` / `%-I` strftime directives are unsupported on Windows

**Symptom:** a `ValueError` from `strftime`, or a test that passes on one host and fails on the other, for
date/time text destined for a prompt variable, an SMS body or a spoken confirmation.
**Cause:** the `%-d` / `%-I` / `%-m` no-padding directives are a glibc extension; the Windows C runtime rejects
them outright.
**Rule:** Never use `%-`-prefixed strftime directives. Use the portable padded form and strip leading zeros in
Python, or go through a shared formatting helper, and assert on the **portable** output in tests. Freeze time for
anything touching quiet hours, business hours, `current_date`/`current_time` prompt variables or retention
windows, and test both sides of every boundary.

## L23 — `&&` is not a statement separator in PowerShell

**Symptom:** a chained command the user pastes fails immediately with `ParserError` — nothing runs at all,
including the first half, so it looks like the command itself was wrong.
**Cause:** the development host runs Windows PowerShell 5.x, which has no `&&` / `||` pipeline chain operators.
**Rule:** Every shell snippet intended for the user is PowerShell-safe: use `;` as the separator, never `&&`
(`git add 'path'; git commit -m 'msg'`). When stop-on-failure matters, emit the commands on separate lines
instead of chaining. This applies to all snippets, not only git.

## L24 — `manage.py runserver` cannot serve the websocket routes at all

**Symptom:** the site loads normally but every live-call surface silently fails to connect; the websocket
handshake 404s or is refused, with no traceback pointing at the cause. The sibling symptom: under Daphne, a fix
"does nothing" because the process was never restarted.
**Cause:** `runserver` serves the WSGI path, which has no protocol router — websocket routes do not exist under
it. And Daphne has no autoreload, so source edits are not picked up until it is restarted.
**Rule:** Anything touching websockets runs under ASGI —
`venv\Scripts\python.exe -m daphne -b 127.0.0.1 -p 8000 config.asgi:application` — never `runserver`. Restart
Daphne after editing consumer or routing code. In-process checks
(`channels.testing.WebsocketCommunicator` against `config.asgi.application`) remain the authoritative
verification. Provider webhooks in dev additionally need a tunnel whose public URL matches
`TWILIO_WEBHOOK_BASE_URL` **exactly**, or signature verification fails with a confusing 403.

## L25 — A test, seeder or dev path reaching a live provider

**Symptom:** a real phone rings, a real SMS is delivered, or a paid LLM endpoint is billed — from a test run, a
seeder, or a smoke sweep. There is no error; the run looks successful.
**Cause:** the provider adapter defaults to the live implementation, or a test mocks at the SDK level and one
un-mocked path slips through to the real client.
**Rule:** `PROVIDER_MODE` ∈ `fake | sandbox | live`, and **`fake` is the default** for dev, tests and seeders —
assert it is `fake` before any test or smoke run. When the mode is not `live`, adapters resolve to the
fake/sandbox implementation and **must never reach a real provider** — no real call placed, no real SMS sent, no
billable API call. The **live** adapter refuses to initialize unless `PROVIDER_MODE == "live"`, and live mode
additionally requires real credentials to be present — missing credentials in live mode is the hard failure.
Tests exercise the **fake adapters**, never SDK-level mocks, so the adapter contract
itself is covered. A path that can place a real call or send a real SMS from a test, seed, fixture, management
command or `DEBUG=True` context is a Critical finding, not a nit.
