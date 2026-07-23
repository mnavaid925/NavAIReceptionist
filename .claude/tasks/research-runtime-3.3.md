# Research — Sub-module 3.3: Tools & Dispatcher (Module 3 — Call Runtime, `runtime`)

## Repo state checked first

- **`LIVE_LINKS` in `apps/accounts/navigation.py`**: `'3.1': {'Runtime Diagnostics': 'runtime:diagnostics'}`,
  `'3.2': {}` (built, deliberately no sidebar link). `'3.3'`…`'3.5'` are absent — 3.3 is the next unbuilt
  sub-module in Module 3, confirmed against the real `### 3.3 Tools & Dispatcher` heading in `NavAIReceptionist.md`.
- **`apps/runtime/agent/` exists with three modules already** (`state.py`, `prompt.py`, `turn.py`) — built by 3.2.
  `apps/runtime/agent/tools.py` (the declaration list) and a dispatcher module **do not exist yet** (confirmed by
  `Glob("apps/runtime/**/*.py")` — no `tools.py`, no `dispatcher.py`, nothing under `agent/` beyond the three files
  above). This sub-module builds them.
- **The turn loop already has the exact seam this sub-module fills**, verified by reading `apps/runtime/agent/turn.py`:
  a bounded `while True` loop around `providers.llm.generate(state.history, system_prompt, tools=[])` gated by
  `settings.MAX_TOOL_ITERATIONS` (default 4, already wired), with an explicit comment: *"3.3 seam: apply_tool_call
  for each tool_call, append the results as a tool-role turn, and loop."* On cap-hit it already falls back to
  `FALLBACK_LINE` — 3.3 does not touch the cap or the fallback, only populates what runs inside the loop body.
- **`CallState` (`apps/runtime/agent/state.py`) already carries the two slots this sub-module needs**:
  `contact_id: int = None` (3.3's `create_contact`/`search_contact`/`get_contact_appointments` fill it) and
  `pending_transfer: str = None` (3.3's `transfer_call`/`transfer_call_spanish` set it; 3.4 executes it — this
  sub-module never dials). **There is no `pending_hangup` slot yet** — `end_call` needs one; see build scope.
- **`apps/scheduling/availability.py` already implements the entire booking write-path this sub-module needs to
  call, not reimplement**, verified by reading it in full (built in 4.3, ahead of this sub-module by design — its
  own docstring says *"Module 3.3's LLM tools call these functions directly"*):
  - `find_available_slots(*, tenant, location, service, date_from, date_to, provider, resource, limit, now)` →
    list of `{start, end, provider, resource, service, token}` — `token` is already the opaque signed
    `slot_token` this sub-module's skill mandates. `MAX_OFFERED_SLOTS = 5` is already the server-side cap.
  - `mint_slot_token` / `redeem_slot_token` — `django.core.signing`, salt `'scheduling.slot.v1'`, 300 s TTL,
    payload holds `{t, l, s, sv, p, r}` (tenant/location/start/service/provider/resource surrogate pks), always
    re-validated against the **caller-supplied** `tenant`/`location` on redemption — never trusted from the token
    holder alone.
  - `book_slot(*, tenant, location, token, contact, reason, notes, source, created_by)` — re-authorizes the
    contact's tenant, re-fetches service/resource/provider under tenant+location filters (a token can outlive a
    row's deactivation within its 5-minute TTL), re-checks conflicts under a real `select_for_update()` row lock
    (not a range lock — its own docstring explains why a range lock over an empty set does not serialize), and is
    idempotency-safe (a retry that already committed returns the existing row instead of erroring).
  - `reschedule_appointment(*, tenant, location, appointment, token, reason, actor_contact)` and
    `cancel_appointment(*, appointment, tenant, location, reason, actor_contact)` — both call `_assert_scope()`
    first (tenant+location match) and, when `actor_contact` is passed, refuse an appointment that belongs to a
    **different** contact than the one identified on this call — this is Invariant 3's "any id the model supplies
    is authorized server-side against tenant, location **and** the identified contact" already implemented and
    waiting for 3.3 to pass `actor_contact=state.contact_id`'s resolved `Contact`.
  - **`SlotError`** carries a `code` asserted against a closed `SLOT_ERROR_CODES` set:
    `{'invalid_argument', 'not_permitted', 'slot_expired', 'slot_unavailable'}` — a **subset** of the tool
    envelope's full 8-code set. 3.3's dispatcher catches `SlotError` and drops `.code`/`.message` straight into
    `{"ok": false, "error": {"code": ..., "message": ...}}` with zero translation. The four codes this module's
    tools need that `SlotError` does not cover (`not_found`, `provider_error`, `rate_limited`, `internal_error`)
    are the dispatcher's own responsibility (a missing `appointment_id`, an unexpected exception, etc.).
- **Sibling models verified to exist and their tool-relevant shape** (grepped, not assumed from the ERD):
  - `scheduling.Contact` (`apps/scheduling/models/ContactDirectory/Contacts.py`) — tenant-scoped only (Invariant
    1), `phone_e164` normalized on every `save()` via `normalize_e164` (so `create_contact`'s phone argument does
    not need its own normalization step — the model does it), `SOURCE_AI_PHONE` choice already exists for
    provenance stamping, `display_name` property never returns blank.
  - `scheduling.Appointment` — `contact` FK is `PROTECT`; `booked_by_session` FK to `calls.CallSession` (`SET_NULL`,
    plural `related_name='booked_appointments'`) exists and is exactly what `book_appointment`'s dispatcher branch
    must stamp from `state.session_id` so the call-log's "Booking Provenance" bullet (4.3) has something to show.
  - `scheduling.CallbackRequest` — `contact` FK is `SET_NULL` (nullable, unlike `Appointment`), `caller_name`/
    `caller_phone` are free text specifically because the agent captures them **before** knowing whether the
    caller is already a `Contact` — `create_callback_request`'s dispatcher branch does not need to identify the
    contact first, matching the skill's tool table (`caller_name`, `caller_phone`, `reason`, no `contact_id`
    parameter at all).
  - `agents.AgentSetting` — `transfer_enabled`, `transfer_phone_number`, `transfer_secondary_number` gate whether
    `transfer_call`/`transfer_call_spanish` are even declared to the model this turn (skill §8.3: "Enablement
    follows the location's `AgentSetting`" — the tool list itself is filtered per call, not just per dispatcher
    branch permission-checked after the fact).
  - `tenants.Location` — `full_address` (property), `tzinfo`, `local_now()` all confirmed; `apps/tenants/services.py`
    exposes `get_provider_intervals(user, location, weekday=None)` and `WEEKDAY_BY_INDEX`, already consumed by
    3.2's `prompt.build_open_intervals` — `get_location_hours`'s dispatcher branch reuses the **same** function
    rather than re-deriving hours a second way.
  - `calls.CallSession` — read-only from the dispatcher's point of view (3.3 stamps `contact`/`booked_by_session`
    onto rows it creates elsewhere, but writes its own audit trail through `state.add_log`/`state.add_transcript`,
    which the consumer flushes — 3.3 never touches the ORM row directly, same discipline 3.2 established).
- **`.claude/skills/voice-agent-runtime/SKILL.md` already specifies this sub-module's whole design** (§8, §9.1,
  §10's `agent_name`/tool-blindness note) — authored during 3.1/3.2 planning, ahead of any 3.3 code existing. It
  names the exact 12-tool table, the opaque-slot-token rule, the `{ok, data, error}` envelope and its 8-code closed
  set, and the deferred-transport rule for `transfer_call`/`transfer_call_spanish`. **This research file does not
  re-invent that design; it grounds it against what commercial voice-agent platforms actually ship for function
  calling**, confirms nothing in the skill contradicts researched market practice, and flags the two or three
  places market practice is looser than this project's own (deliberately stricter) contract — most importantly,
  the "verbatim echo" pattern several reference implementations use for slot fields, which this skill already
  rejects in favor of the opaque token `apps/scheduling/availability.py` mints.

---

## Leaders surveyed (with source links)

1. **Retell AI** — voice-agent platform; "Custom Function" node in its conversation-flow builder converts to
   OpenAI-compatible JSON-schema tool declarations, signs the outbound webhook (`X-Retell-Signature`), retries a
   failed call up to 2×, caps the response at 15,000 characters before it re-enters the model's context, and
   auto-injects call context (`call_id`, live transcript so far, dynamic variables) the model never has to ask
   for. — [Custom function in conversation flow](https://docs.retellai.com/build/conversation-flow/custom-function)
2. **Vapi** — telephony-infrastructure voice-agent platform; tools use JSON-schema parameters, match a response
   back to its call via a `toolCallId`, and the ecosystem's own troubleshooting material is explicit about the
   round-trip budget: webhooks time out at 5 s, the function call itself defaults to a 20 s cap, and a slow
   handler should ack immediately and stream the result back later rather than block the turn. —
   [Custom Tools](https://docs.vapi.ai/tools/custom-tools), [Introduction to Tools](https://docs.vapi.ai/tools),
   [Debugging Vapi Calls](https://www.usesherlock.ai/blog/vapi-call-debugging-guide)
3. **Bland AI** — per-call "Custom Tools" attached by id, response fields extracted as `{{variables}}` the
   conversation can reference downstream — the closest published analogue to this project's own
   `{{variable}}` runtime-var merge (§10), confirming the pattern (a tool's result feeding template substitution)
   is market-standard, not a one-off design choice here. — [Custom Tools (Legacy)](https://docs.bland.ai/tutorials/tools)
4. **Synthflow** — four-part custom-action shape (request setup, variables, action details, result handling) and
   explicit **action chaining** guidance (one action's output feeds the next as a documented, prompt-driven
   sequence) — the closest published analogue to this sub-module's own two-step "get_open_slots then
   book_appointment, token carried between them" flow. — [Custom actions overview](https://docs.synthflow.ai/docs/new-custom-actions-overview),
   [Actions overview](https://docs.synthflow.ai/actions-overview)
5. **ElevenLabs Agents** — names three tool classes explicitly: client tools (browser/app-side), server tools
   (webhooks — the class this project's tools are), and **system tools** (call-state actions needing no external
   call at all — end call, transfer, language switch) — directly validating this sub-module's own split between
   "read/write against our DB" tools and "mutate the call transport" tools (`transfer_call`, `end_call`), which
   this project implements as the deferred-signal pattern rather than an immediate system-tool action. —
   [Tools overview](https://elevenlabs.io/docs/eleven-agents/customization/tools),
   [Server tools](https://elevenlabs.io/docs/conversational-ai/customization/tools/server-tools)
6. **Cal.com** (booking-API reference, not a voice-agent competitor) — the clearest published example of the
   availability→hold→confirm shape this sub-module's tool pair (`get_open_slots` → `book_appointment`) implements:
   `POST /v2/slots/reservations` returns a `reservationUid` plus a `reservationUntil` expiry (5-minute default,
   configurable for authenticated callers) that a later booking call is expected to reference rather than
   re-supplying raw start/end times — the same hold-then-confirm shape `mint_slot_token`/`redeem_slot_token`
   already implement locally with a signed token instead of a server-held reservation row. —
   [Reserve a slot](https://cal.com/docs/api-reference/v2/slots/reserve-a-slot)
7. **LiveKit Agents** (referenced in the 3.2 research file, re-surfaced here for its function-tool guidance) —
   publishes explicit function-tool timeout/retry and "tool call must not block the turn indefinitely" guidance
   consistent with Vapi's and Retell's published numbers, reinforcing that a **bounded** tool-call budget is
   universal market practice, not a Vapi-specific quirk. — carried forward from the 3.2 research file's own
   citation, not re-fetched here to avoid duplicating that sub-module's survey.
8. **Bland AI / Vapi / Retell shared reference point** — the "reference implementation" this skill's own §8.1
   explicitly argues against: several public tutorials for these platforms instruct the model to **echo raw slot
   fields verbatim** (`start_at`, `provider_id`, `operatory_id`) between an availability tool and a booking tool.
   This project's own skill names that pattern as "the single most common booking-failure class" and replaces it
   with the opaque `slot_token` — cited here as a **negative example** this sub-module must not reproduce, not as
   a leader to emulate.

---

## Feature catalog (this sub-module only)

### Transport-Agnostic Dispatcher

- **One `apply_tool_call(state, name, args)` function, called identically regardless of transport/voice mode** ·
  seen in: ElevenLabs' three-tool-class split (client/server/system) still routes every server/system tool through
  one internal dispatch surface per its docs; this project's own skill (§8.2) states the requirement explicitly
  ("The same function serves the turn-based path and the realtime speech-to-speech path... divergent argument
  coercion... is the top regression risk") · priority: **REQUIRED** — this is Invariant 3's dispatcher, quoted by
  number from every review agent · model: none — a pure async function in `apps/runtime/agent/dispatcher.py` (new
  file), imported by `turn.py`'s existing bounded loop · realtime: **live-call hot path** — every tool call in the
  turn loop routes through it · tool-surface: this *is* the tool surface's single entry point · buildable now — no
  external dependency; a single function calling into already-built `apps.scheduling.availability` and ORM helpers.
- **A declared-but-undispatched tool is a silent runtime failure** — the skill states this as a hard rule (§8);
  the practical implication is that the 12 entries in `apps/runtime/agent/tools.py`'s declaration list and the 12
  `if name == '...'` branches in the dispatcher must be tested for 1:1 correspondence, not eyeballed · priority:
  table-stakes engineering discipline (every platform surveyed effectively enforces this by construction — a tool
  declared in Retell's/Vapi's dashboard IS its own webhook target, so there is no "declared but unwired" state in
  their model; this project's plain-dict declaration list has no such automatic tie, so it needs an explicit test)
  · tool-surface: a test asserting `{t['name'] for t in TOOL_DECLARATIONS} == set(DISPATCH_TABLE)` · buildable now.
- **Every declared tool call is wrapped so one bad tool never kills the turn** — an unhandled exception inside a
  dispatcher branch must not propagate into the frame loop, mirroring the realtime skill's rule for the receive
  loop itself (CLAUDE.md realtime rule 9: "an exception in the receive loop is caught so one bad frame does not
  kill the call") extended one layer deeper, to the tool-call level · seen in: no platform surveyed publishes this
  as a named feature (it is invisible from outside), but Vapi's own troubleshooting guidance implicitly assumes
  it — a `toolCallResult` with a non-success `result` is how a *handled* tool failure surfaces to their model, not
  a dropped call · priority: **REQUIRED** — a tool bug must degrade to `{"ok": false, "error": {"code":
  "internal_error", ...}}`, never a stack trace into the frame loop, never dead air · model: none · realtime: hot
  path · tool-surface: this is the source of the `internal_error` code in the closed set · buildable now.

### Server-Side Identity Injection

- **`tenant_id`, `location_id`, `contact_id`, `session_id` are read from `state`, never accepted as tool
  parameters** · seen in: every platform surveyed auto-injects *some* call context (Retell's `call` object with
  `call_id`; Vapi's `call.id`/`org.id`; ElevenLabs' dynamic variables) — but none of the surveyed platforms
  publish a documented **rule that an identity field must never be a model-facing parameter at all**; that
  constraint is this project's own, stated as Invariant 3 · priority: **REQUIRED** · model: none — enforced by the
  tool declarations in `tools.py` simply never listing `tenant_id`/`location_id`/`contact_id`/`session_id` as
  `parameters.properties`, and by the dispatcher reading them from `state.tenant_id`/`state.location_id`/
  `state.contact_id`/`state.session_id` exclusively · realtime: hot path · tool-surface: this is the shape of
  every tool's `parameters` schema · buildable now — already fully specified in the skill's own tool table (the
  "Model-supplied arguments" column never lists an identity field).
- **Any id the model DOES supply is re-authorized server-side against tenant, location and the identified
  contact** — this is the deeper half of Invariant 3, and it is where `apps/scheduling/availability.py`'s existing
  `_assert_scope()` and `actor_contact` checks do the actual work · seen in: none of the surveyed platforms
  document an equivalent server-side re-authorization step for a model-supplied id (their docs focus on
  *delivering* the id to a webhook, not on what the webhook must independently verify before acting on it) —
  genuinely this project's own hardening, motivated by CLAUDE.md's own framing ("This is an IDOR with an LLM in
  the middle; treat it as one") · priority: **REQUIRED** · model: reuses `scheduling.Appointment`
  (`reschedule_appointment`/`cancel_appointment` pass `actor_contact=`), `scheduling.Contact` (tenant match on
  `create_contact`/`search_contact`) · realtime: hot path · tool-surface: every tool taking `appointment_id` or
  `slot_token` · buildable now — the re-authorization primitives already exist in `availability.py`; 3.3 only has
  to call them with the right `actor_contact`.
- **A caller who reaches Location A must never read or move an appointment at Location B** — the location half of
  the check above, called out separately because it is this product's own multi-location design and not something
  a single-location competitor's docs would ever need to state · priority: **REQUIRED** · model: reuses
  `Appointment`/`CallSession` tenant+location scoping already in place · realtime: hot path · buildable now.

### Built-In Tool Set

- **`get_contact_appointments(phone?)` — identify the caller, fetch their appointment history** · seen in: every
  AI-receptionist competitor surveyed opens a booking flow with a caller-lookup step (Goodcall's Google Business
  Profile-linked lookup, PolyAI's CRM-integration lookup, Retell's "Book Appointments" feature listing a
  cal.com/CRM contact match as step one) · priority: table-stakes · model: reuses `scheduling.Contact` — query by
  `phone_e164` normalized from `state`'s known `from_number` (the caller's ANI) when `phone` is omitted, else the
  model-supplied digits normalized the same way; `Appointment.objects.filter(contact=..., tenant=state.tenant_id)`
  for history (tenant-scoped only, matching Contact's own scope) · realtime: hot path · tool-surface: new tool
  `get_contact_appointments({"phone": str?})` → `{"ok": true, "data": {"contact_id": int|null, "is_new": bool,
  "appointments": [{...}]}, "error": null}` — sets `state.contact_id` as a side effect when exactly one contact
  matches; identity args from server state (`state.tenant_id`, and `state.from_e164`-equivalent when `phone` is
  omitted) · buildable now.
- **`search_contact(first, last, date_of_birth)` — disambiguate when the phone lookup is ambiguous or absent** ·
  seen in: this is the fallback path implied by every competitor's "identify caller" step when ANI lookup misses
  or returns multiple matches (a shared office line, a household) — none of the surveyed platforms document the
  exact disambiguation fields, but date-of-birth-plus-name is the standard identity-verification pair in
  appointment-booking domains generally (used the same way at a front desk) · priority: common · model: reuses
  `scheduling.Contact`, filtered `tenant=state.tenant_id, first_name__iexact=..., last_name__iexact=...,
  date_of_birth=...` · realtime: hot path · tool-surface: new tool `search_contact({"first": str, "last": str,
  "date_of_birth": str})` → `{"ok": true, "data": {"contact_id": int|null, "matches": [...]}, "error": null}` (an
  empty match list is `ok: true` with `data.matches = []`, not an error — "nobody found" is a normal outcome the
  model narrates, not a failure code) · buildable now.
- **`create_contact(first_name, last_name, date_of_birth, phone)` — create a NEW `scheduling.Contact`** · seen in:
  every competitor surveyed creates a lead/contact record on an unmatched caller (this is the exact place several
  reference stacks would reach for a second `Lead` table — **this project does not**, per Invariant 1) · priority:
  table-stakes · model: reuses `scheduling.Contact` (Invariant 1 — **flag any temptation to add a `Lead`/`Caller`
  table here**; `Contact.save()` already normalizes the phone via `normalize_e164`, so the dispatcher branch does
  no normalization of its own), `source=Contact.SOURCE_AI_PHONE` server-stamped, never model-chosen · realtime: hot
  path · tool-surface: new tool `create_contact({"first_name": str, "last_name": str, "date_of_birth": str?,
  "phone": str?})` → `{"ok": true, "data": {"contact_id": int}, "error": null}`; sets `state.contact_id` · **PII
  note**: the args blob (name + DOB) must be redacted before it reaches `state.add_log` — CLAUDE.md's vulnerability
  rule 5 names this exact tool/payload combination by example · buildable now.
- **`get_open_slots(...)` — return open slots, capped and pre-ranked** · seen in: Cal.com's `GET /v2/slots`, every
  competitor's "check availability" step (Retell's Book Appointments feature, Vapi's documented `get_slots` tool
  pattern, Synthflow's action-chaining example) · priority: table-stakes · model: **reuses
  `apps.scheduling.availability.find_available_slots` directly — no new query logic** · realtime: hot path ·
  tool-surface: new tool `get_open_slots({"date_from": "MM/DD/YYYY"?, "date_to": "MM/DD/YYYY"?, "weekdays":
  [str]?, "time_from": "HH:MM"?, "time_to": "HH:MM"?, "duration_minutes": int?, "service_id": int?,
  "provider_ids": [int]?, "resource_ids": [int]?, "page": int?, "page_size": int?})` → `{"ok": true, "data":
  {"slots": [{"slot_token": str, "display": str, "provider_name": str|null, "resource_label": str|null}]},
  "error": null}` — `slot_token` is `find_available_slots`'s already-minted opaque token, **never** raw
  `start`/`provider`/`resource` fields; `service_id`/`provider_ids`/`resource_ids` are re-validated tenant+location
  scoped before being handed to `find_available_slots` (a model-supplied `service_id` for another tenant's service
  must resolve to "no slots", not leak the row) · buildable now.
- **`book_appointment(slot_token, reason, notes)` — book against the token, never re-check availability after
  confirmation** · seen in: Cal.com's reserve→confirm shape, Vapi's own healthcare-scheduling build guide citing a
  "200–400 ms race window" between availability check and booking write unless the slot is locked (independently
  confirmed by this project's own 4.3 research file and already solved by `availability.book_slot`'s
  `select_for_update()`) · priority: **REQUIRED** — CLAUDE.md's own framing: *"Never announce success before the
  write returns... the worst failure this product can produce"* · model: **reuses `apps.scheduling.availability.
  book_slot`** — no new write logic; the dispatcher's only job is resolving `contact=` from `state.contact_id`
  (refusing the tool if no contact has been identified yet — the tool table implicitly requires
  `get_contact_appointments`/`create_contact` to have run first) and stamping `source=Appointment.SOURCE_AI_PHONE`,
  `booked_by_session_id=state.session_id` · realtime: hot path · tool-surface: `book_appointment({"slot_token":
  str, "reason": str?, "notes": str?})` → `{"ok": true, "data": {"appointment_id": int, "start_at": iso8601,
  "service": str}, "error": null}` or `{"ok": false, "error": {"code": "slot_unavailable"|"slot_expired"|
  "invalid_argument", "message": ...}}` (mapped 1:1 from `SlotError`) · buildable now.
- **`reschedule_appointment(appointment_id, slot_token)` / `cancel_appointment(appointment_id,
  cancellation_reason)`** · seen in: every calendar competitor surveyed in the 4.3 research pass (Calendly, Acuity,
  Cal.com) ships both as first-class actions; the voice-specific risk both platforms document informally is a
  caller moving or cancelling **someone else's** booking by guessing an id, which is exactly what
  `reschedule_appointment`/`cancel_appointment`'s `actor_contact=` parameter exists to prevent · priority:
  table-stakes · model: **reuses `apps.scheduling.availability.reschedule_appointment` /
  `.cancel_appointment`** — the dispatcher resolves `appointment` via `Appointment.objects.filter(pk=appointment_id,
  tenant=state.tenant_id, location=state.location_id).first()`, returning `not_found` (not `not_permitted`) when
  the row does not exist at all, and passes `actor_contact=` the resolved `state.contact_id`'s `Contact` so a
  cross-contact id is refused by `availability.py`'s own check · realtime: hot path · tool-surface: two tools,
  envelopes mapped from `SlotError` the same way as `book_appointment`, plus a dispatcher-level `not_found` for a
  missing/foreign-scoped id `availability.py` never sees (it only receives an already-scoped `Appointment`
  instance) · buildable now.
- **`create_callback_request(caller_name, caller_phone, reason)` — log a queue item, no identification required
  first** · seen in: this exact "graceful degrade to a message-taking flow" is the core promise of Smith.ai/Ruby's
  human-staffed answering products, and Rosie's AI voicemail tier read-only mode is the AI-native analogue ·
  priority: table-stakes for an inbound-only agent (it is the fallback for every path where booking cannot
  complete) · model: reuses `scheduling.CallbackRequest` — **no contact lookup required first**, matching the
  model's own docstring ("Invariant 1 holds even for a caller nobody identified... `contact` is simply left null");
  if `state.contact_id` is already set the dispatcher additionally sets `contact=` on the row so a known caller's
  callback is linked, but this is an enhancement, never a precondition · realtime: hot path · tool-surface:
  `create_callback_request({"caller_name": str, "caller_phone": str, "reason": str})` → `{"ok": true, "data":
  {"callback_id": int}, "error": null}`, `source=CallbackRequest.SOURCE_AI_PHONE` server-stamped · buildable now.
- **`get_location_hours()` — read out this location's hours + address, no arguments** · seen in: Bland's/Vapi's
  static "business info" tool pattern (a zero-argument lookup tool is a documented category on both platforms) ·
  priority: table-stakes · model: **reuses `apps.tenants.services.get_provider_intervals` +
  `tenants.Location.full_address`** — the exact same function 3.2's `prompt.build_open_intervals` already calls,
  so hours are computed **one way** in this product, never two divergent interpretations (the prompt module's own
  docstring states this explicitly: "computed through the audited `tenants.services` hours logic rather than a
  second, divergent hours interpretation") · realtime: hot path · tool-surface: `get_location_hours()` (no
  parameters) → `{"ok": true, "data": {"address": str, "hours": [{"weekday": str, "windows": [...]}]}, "error":
  null}` · buildable now.
- **`transfer_call()` / `transfer_call_spanish()` — set the deferred signal, never dial from inside the
  dispatcher** · seen in: ElevenLabs' own "system tool" category names transfer as a call-state action distinct
  from a server webhook — validating the deferred/no-external-call shape at the dispatcher layer, even though this
  project's own transfer eventually DOES make an external (Twilio REST) call, just not from here · priority:
  **REQUIRED** (CLAUDE.md realtime rule 6: "Transport-mutating tools are deferred... the transport acts after the
  turn's audio completes") · model: none written here — sets `state.pending_transfer = "human"` or `"spanish"` and
  returns an immediate ack; **gating (working hours, `transfer_enabled`, destination presence), the single-fire
  guard, and the actual Twilio REST redirect are 3.4's**, not this sub-module's · realtime: hot path (the flag-set
  is instant; the dial happens after this turn's TTS finishes, in the transport 3.4 builds) · tool-surface: two
  zero-argument tools, both declared **only when `AgentSetting.transfer_enabled` and the relevant destination
  number are present** (skill §8.3: "Enablement follows the location's `AgentSetting`") — an undeclared tool is
  simply absent from `tools=[...]` that turn, not a runtime error · buildable now for the flag-set half; the
  execution half is explicitly out of this sub-module's scope (see Belongs to sibling sub-modules).
- **`end_call()` — end the call deterministically, no silence-timeout wait** · seen in: ElevenLabs' system-tool
  category again (end-call is the other named system tool alongside transfer/language-switch); the skill's own
  §9.3 closing note: *"An explicit `end_call` tool ends the call deterministically for wrong-number and
  caller-done outcomes — waiting on a silence timeout burns minutes and looks broken"* · priority: table-stakes ·
  model: writes nothing directly — sets `state.ended_reason` and a **new** deferred-hangup flag (see build scope
  below; `CallState` has `pending_transfer` today but no equivalent for a plain hangup) · realtime: hot path (the
  flag-set), the actual socket close/teardown happens after this turn's goodbye line finishes, mirroring the
  transfer pattern but with no external redirect to place · tool-surface: `end_call()` (no parameters) →
  `{"ok": true, "data": {}, "error": null}` · buildable now — the mechanics are a smaller version of the transfer
  seam 3.2 already wired, so this sub-module both declares the tool AND wires its own tiny consumer-side check
  (distinct from 3.4's Twilio REST work, which `end_call` never needs).

### Opaque Signed Slot Tokens

- **One signed short-TTL token per offered slot, minted server-side, never model-echoed raw fields** · seen in:
  Cal.com's `reservationUid` + `reservationUntil` is the clearest published commercial analogue (hold a slot,
  return an opaque handle, expect the handle back on confirm) — **already fully implemented** in
  `apps/scheduling/availability.py` (`mint_slot_token`/`redeem_slot_token`, salt `'scheduling.slot.v1'`, 300 s TTL)
  · priority: **REQUIRED** — this sub-module's own named bullet, and the skill states plainly that the
  verbatim-echo alternative several reference tutorials use "is the single most common booking-failure class" ·
  model: none new — 3.3 only **calls** the existing token functions through `get_open_slots`/`book_appointment`/
  `reschedule_appointment`'s dispatcher branches · realtime: hot path · tool-surface: the `slot_token` field on
  three tools · **already buildable, already built** at the scheduling layer — 3.3's job is wiring, not inventing.
- **Re-validated on redemption against the CALLER's tenant/location, not merely a valid signature** — a
  perfectly-signed token minted for tenant A location 1 must be refused if redeemed under tenant A location 2 ·
  seen in: no surveyed competitor publishes an equivalent multi-tenant replay concern (single-location
  competitors have no such axis) — this is this product's own hardening, and `redeem_slot_token` already
  implements it (`payload.get('t') != tenant.pk or payload.get('l') != location.pk` → `not_permitted`) · priority:
  **REQUIRED** · model: none new · realtime: hot path · buildable now (already built).
- **Every row a token references is RE-FETCHED at redemption time, not trusted from the token's own payload
  values** — a service deactivated, a resource retired or a provider's assignment revoked inside the token's
  5-minute life must not silently book against a stale row · seen in: not documented by any surveyed competitor
  (their booking APIs generally re-fetch by nature of hitting a live calendar backend each time) — but it is
  exactly what `book_slot`/`reschedule_appointment` already do (`Service.objects.filter(pk=payload.get('sv'),
  tenant=tenant, is_active=True)`, etc.) · priority: table-stakes engineering discipline · model: none new ·
  realtime: hot path · buildable now (already built).

### Standard Result Envelope

- **`{"ok": bool, "data": {...}, "error": {"code": "...", "message": "..."} | null}`, one shape, every tool** ·
  seen in: Vapi's own envelope (`{"results": [{"toolCallId", "result"}]}`) and Retell's (raw string capped at
  15,000 chars) are both **weaker** than this project's contract — neither enforces a closed, machine-branchable
  error-code vocabulary; both leave "did it actually succeed" to be inferred from the `result` string's content,
  which is exactly the ambiguity CLAUDE.md's own framing calls out ("`ok` is what the log recorder, the
  diagnostics page and the 'did it actually succeed' rules key off") · priority: **REQUIRED** — Invariant-adjacent
  (quoted in the "Two supporting rules" section of CLAUDE.md) · model: none — a small `apps/runtime/agent/
  envelope.py` (or inline in `dispatcher.py`) pair of helpers, `ok_result(data)` / `err_result(code, message)`,
  asserting `code` is in the closed set the same defensive way `availability.SlotError.__init__` already asserts
  against `SLOT_ERROR_CODES` · realtime: hot path · tool-surface: wraps every dispatcher branch's return ·
  buildable now.
- **The closed 8-code set is a strict superset of what `SlotError` already emits** — `not_found` (a missing
  `appointment_id`/`callback_id`), `provider_error` (reserved — no external provider sits behind any of these 12
  tools today; a future calendar-sync integration would use it), `rate_limited` (reserved — no per-tool rate limit
  exists yet; see Deferred), `internal_error` (an unhandled exception caught at the dispatcher boundary) · seen in:
  no competitor publishes a closed code vocabulary this explicit — Retell's/Vapi's envelopes are both
  free-text/string-shaped · priority: **REQUIRED** for the 4 codes actively used this pass (`not_found`,
  `internal_error`, plus the 4 `SlotError` already covers); `provider_error`/`rate_limited` are declared in the
  set but genuinely unreachable until a later integration exists — noted, not built around, this pass · model:
  none · tool-surface: the full set lives in one place (`apps/runtime/agent/envelope.py` or similar), imported by
  the dispatcher · buildable now.
- **`code` is always `lower_snake_case`, drawn from the closed set, never invented per-tool** · seen in: this is
  where this project's contract is strictly tighter than every platform surveyed — none of Retell/Vapi/Bland/
  Synthflow document a shared error taxonomy across their tool systems; each webhook integrator invents its own ·
  priority: **REQUIRED** · tool-surface: a test enumerating every dispatcher branch's possible `error.code` values
  against the closed set, the same discipline `SlotError.__init__`'s `assert` already gives the scheduling layer ·
  buildable now.

### Per-Turn Iteration Cap

- **`MAX_TOOL_ITERATIONS` (default 4), already wired in `turn.py`, with a spoken fallback on cap-hit** · seen in:
  Retell's documented 2-retry cap on a *failed* function call is a narrower, adjacent concept (retry-on-failure,
  not iterations-per-turn); the more directly comparable industry number is the general "bounded agentic loop"
  practice LiveKit and the 3.2 research file both cite — this project's own number (4) is a considered choice
  already made and shipped, not something 3.3 re-derives · priority: **REQUIRED** — CLAUDE.md realtime rule 7 ·
  model: none — `settings.MAX_TOOL_ITERATIONS`, unmodified by this sub-module · realtime: hot path · tool-surface:
  the loop that calls `apply_tool_call` in `turn.py` — **3.3's actual work here is filling in the loop body that
  currently has a comment where the dispatcher call goes**, not touching the cap itself · buildable now.
- **Multiple tool calls in one turn are normal and must all be applied before the next model call** · seen in:
  every platform surveyed supports multi-tool-call turns as a baseline LLM function-calling capability (this is
  an OpenAI/Anthropic tool-calling-API property, not a platform-specific feature) · priority: table-stakes · model:
  none · realtime: hot path — `turn.py`'s loop body iterates `tool_calls` (plural) from one `llm.generate()` call,
  applying each through `apply_tool_call` and appending each result as its own tool-role history turn before the
  next `llm.generate()` · buildable now.
- **A capped-out turn still logs why, for the diagnostics/event-log surface** — `turn.py` already does this
  (`state.add_log('warning', 'llm', 'Tool-iteration cap hit', {'cap': settings.MAX_TOOL_ITERATIONS})`) · priority:
  table-stakes · tool-surface: none — 3.3 adds nothing here, just confirms the existing log entry's `category`
  (`'llm'`) is where a future 3.5 diagnostics page would also want to see individual tool-call entries (`category`
  `'tool'`), so the two categories don't collide when read back.

### Beyond the bullets

- **A tool's error message is written to be SPOKEN, not logged** — `SlotError`'s own docstring states this
  ("these strings reach a caller through a voice agent, so they say what happens next rather than naming an
  internal failure") and the dispatcher must carry that discipline to the 4 codes it adds beyond `SlotError`'s
  four (`not_found`'s message reads as "I couldn't find that appointment," never "Appointment.DoesNotExist") ·
  seen in: Bland's/Retell's variable-extraction patterns implicitly assume a tool's textual output is
  conversation-ready, not a raw exception string · priority: table-stakes · model: none · realtime: hot path ·
  tool-surface: every `err_result(code, message)` call site · buildable now.
- **The prompt must never name a tool or a tool parameter** — skill §8.3's closing line, worth repeating here
  because it is the boundary between "a tool exists" (3.3's job) and "the agent is instructed to call it well"
  (2.1's prompt-authoring job) · priority: table-stakes · tool-surface: none — a review-time check on
  `AgentSetting.prompt_text` content, not a runtime behavior 3.3 enforces in code.
- **Tool enablement is per-call, not just per-branch** — `transfer_call`/`transfer_call_spanish` are not merely
  *dispatched* conditionally; they must not even appear in the `tools=[...]` list handed to the LLM when
  `AgentSetting.transfer_enabled` is false or the relevant destination number is blank, matching skill §8.3 · seen
  in: no surveyed competitor documents this distinction explicitly (most either always expose their transfer tool
  or gate it in the dashboard, not per-call), but it directly prevents the model narrating a capability ("let me
  transfer you") that then silently fails when dispatched anyway · priority: differentiator · model: reuses
  `agents.AgentSetting` fields, read once per call (already cached on `CallState` would be a reasonable follow-up,
  but `agent_setting_id` alone is on `CallState` today — see build scope for whether tools.py re-reads
  `AgentSetting` per turn or the consumer passes a resolved instance in) · realtime: hot path · buildable now.

---

## Compliance & provider constraints

- **PII discipline is REQUIRED and this sub-module is the single largest source of raw PII touching the tool
  layer.** `create_contact`'s args are a full name and a date of birth; `search_contact`'s args are the same;
  `get_contact_appointments`'s optional `phone` argument and its `state`-derived caller ANI are both PII.
  CLAUDE.md's vulnerability rule 5 names `create_contact`'s payload by example. Every `state.add_log(...,
  raw_json=...)` call from a dispatcher branch must pass an already-redacted blob (drop `date_of_birth`, mask
  `phone`/`caller_phone` to a partial, never persist a free-text `notes`/`reason` value verbatim into `logs` even
  though it is fine in `transcript`) — `state.add_log`'s own docstring already states the redaction contract is
  the caller's job, inherited from 3.2, now actually exercised for the first time by real PII-bearing tool args.
- **Prompt injection is a live threat at exactly this layer.** A caller's speech reaches the model, and the model
  chooses tool arguments from what the caller said. Every tool that accepts a "which record" argument
  (`appointment_id`) is re-authorized server-side against tenant, location and `state.contact_id` — never trusted
  because the model supplied a plausible-looking id. This is Invariant 3's whole point and it is this sub-module's
  primary security surface, not an incidental concern (CLAUDE.md vulnerability rule 6, verbatim).
- **`transfer_call`/`transfer_call_spanish` never derive their destination from caller speech or a tool argument**
  — the tool takes **no parameters at all** specifically so there is nothing for the model to supply that could be
  misread as a phone number. The destination is always `AgentSetting.transfer_phone_number` /
  `.transfer_secondary_number`, resolved by 3.4 at execution time. This sub-module's contribution to that
  guarantee is simply declaring both tools as zero-argument — a tool that grew a `destination` parameter later
  would be a toll-fraud regression, not a feature request to accept.
- **No new recording-consent, two-party-consent-announcement or HIPAA/GDPR retention obligation is introduced by
  this sub-module** — those remain 3.5's (Consent-Gated Recording) and 4.1's (`Contact.anonymize()`, already
  built) territory. `create_contact`'s date-of-birth argument makes this sub-module a **consumer** of the erasure
  contract 4.1 already ships (an AI-created contact is erasable the same way a manually-created one is;
  `Contact.anonymize()`'s cascade to `CallbackRequest` already covers a callback this sub-module's
  `create_callback_request` tool creates), not a new obligation to design.
- **Cost implication — this sub-module appends nothing new to `calls.CallSession.usage`.** Every one of the 12
  tools is a local DB read/write with no external provider call behind it (no STT/TTS/LLM cost line originates in
  a dispatcher branch) — the LLM cost of the turn that *chose* to call a tool is already accounted for by
  `turn.py`'s existing per-turn `usage` append, which already counts the tool-bearing turn's input/output tokens
  like any other. If a future tool calls an external provider (e.g., a calendar-sync integration using
  `provider_error`), that tool's dispatcher branch would need its own bounded-call wrapper and its own cost line —
  noted for that hypothetical, not built now.
- **Rate limiting is a security control here too, not just a UX one** — `MAX_TOOL_ITERATIONS` already bounds
  tool-calls-per-turn; there is currently no cap on **how many `create_contact`/`create_callback_request` calls a
  single call session can make across its whole duration** (a looping or prompt-injected agent could still spam
  callback rows within the 4-per-turn cap, once per turn, for the whole call). This is bounded indirectly by
  `MAX_CALL_SECONDS`/`IDLE_TIMEOUT_SECONDS` (3.2) but not by a tool-specific ceiling — flagged under Deferred, not
  built this pass, since no researched competitor documents a per-tool call-session ceiling either and the
  existing call-level bounds are the researched, shipped mitigation.

---

## Recommended build scope (this pass)

**This is a SERVICE sub-module — zero models, zero migrations attributable to 3.3.** It reuses five already-built
models (`scheduling.Contact`, `scheduling.Appointment`, `scheduling.CallbackRequest`, `agents.AgentSetting` read,
`calls.CallSession` read via `state`) and one already-built service layer (`apps.scheduling.availability`) with no
new table. The build scope is the tool declaration list, the dispatcher and its twelve branches, the envelope
helper, the closed error-code set, the per-tool authorization rules, and the tests:

- **`apps/runtime/agent/tools.py`** (new) — the 12 tool declarations as plain, provider-agnostic dicts (`name`,
  `description`, `parameters` JSON-schema), matching the skill's §8.1 table exactly. `transfer_call`/
  `transfer_call_spanish` are filtered out of the list returned to a given call when
  `AgentSetting.transfer_enabled` is false or the relevant destination number is blank — a function
  `active_tools(agent_setting)` returning the filtered list, not a static constant, since enablement is per-call.
- **`apps/runtime/agent/envelope.py`** (new) — `ok_result(data=None)` / `err_result(code, message)`, `code`
  asserted against the closed set `{'not_found', 'invalid_argument', 'slot_unavailable', 'slot_expired',
  'not_permitted', 'provider_error', 'rate_limited', 'internal_error'}`, mirroring `SlotError`'s own defensive
  `assert` pattern in `availability.py`.
- **`apps/runtime/agent/dispatcher.py`** (new) — `async def apply_tool_call(state, name, args) -> dict`, one
  branch per tool:
  - `get_contact_appointments`, `search_contact`, `create_contact` — ORM reads/writes against `scheduling.Contact`
    (tenant-scoped only), each wrapped in `database_sync_to_async` (this dispatcher is called from the async turn
    loop, so every ORM touch needs the same off-loop discipline 3.2 already established); sets `state.contact_id`
    on a successful identify/create.
  - `get_open_slots`, `book_appointment`, `reschedule_appointment`, `cancel_appointment` — thin wrappers around
    `apps.scheduling.availability.{find_available_slots, book_slot, reschedule_appointment, cancel_appointment}`,
    each call wrapped in `database_sync_to_async`, `SlotError` caught and mapped 1:1 into `err_result(exc.code,
    exc.message)`; `book_appointment`/`reschedule_appointment`/`cancel_appointment` refuse with `not_permitted`
    (spoken as "I need to know who I'm speaking with first") when `state.contact_id` is still `None`.
  - `create_callback_request` — a plain `scheduling.CallbackRequest.objects.create(...)`, `contact=` set from
    `state.contact_id` when known, else left null; `database_sync_to_async`.
  - `get_location_hours` — reuses `apps.tenants.services.get_provider_intervals` (the same call 3.2's
    `prompt.build_open_intervals` already makes) plus `location.full_address`; `database_sync_to_async`.
  - `transfer_call`, `transfer_call_spanish` — set `state.pending_transfer = 'human'` / `'spanish'`; return an
    immediate `ok_result` ack. **No Twilio call, no working-hours check, no single-fire guard here** — those are
    3.4's, which reads `state.pending_transfer` the same way `turn.py`'s existing "3.4 seam" comment already
    documents.
  - `end_call` — sets `state.ended_reason` and a **new** `state.pending_hangup: bool = False` field this sub-module
    adds to `CallState` (a small, additive change to `apps/runtime/agent/state.py`, the same shape as
    `pending_transfer`); the consumer (already built in 3.2) gets a small, matching addition to check
    `pending_hangup` after a turn's audio completes and close the socket gracefully — this piece is genuinely
    3.3's to build (not 3.4's), because it needs **no** Twilio REST call, unlike a cold transfer.
  - Every branch wrapped so an unhandled exception becomes `err_result('internal_error', ...)`, never propagates.
- **`apps/runtime/agent/turn.py`** (touch, not rewrite) — fill in the existing "3.3 seam" comment: after
  `providers.llm.generate(...)` returns `tool_calls`, call `apply_tool_call(state, call.name, call.args)` for each,
  append the result as a `{'role': 'tool', 'text': json.dumps(result)}` history turn (or the shape the concrete LLM
  adapter's SDK expects — kept provider-agnostic per §8.2), then loop. The `tools=[]` argument becomes
  `tools=active_tools(agent_setting)`.
- **`apps/runtime/providers/llm.py`** (touch) — `FakeLlmBackend` currently always returns `tool_calls=[]`
  (documented: *"wiring one here would be building 3.3 early"*). 3.3 is that pass: extend the fake to accept an
  optional **scripted tool-call sequence** (a list of `[{'name', 'args'}, ...]` per reply, consumed the same way
  `replies` already is) so the dispatcher can be exercised end-to-end through the real turn loop in tests and via
  `simulate_call`, without needing a live LLM.
- **Tests** — declaration/dispatch-table parity (every declared tool has a branch and vice versa); identity
  injection (a tool declaration never lists `tenant_id`/`location_id`/`contact_id`/`session_id` as a parameter);
  cross-tenant and cross-**location** `appointment_id` rejection (`not_permitted`, not `not_found` — the row
  exists, it's just not authorized); cross-**contact** `appointment_id` rejection (a second identified caller on a
  different call cannot move this caller's booking); an unoffered/tampered `slot_token` → `invalid_argument`; an
  expired `slot_token` → `slot_expired`; a double-book race → `slot_unavailable` (exercising
  `availability.book_slot`'s existing lock, not re-testing it — just confirming the dispatcher passes the error
  through unmodified); `transfer_call`/`transfer_call_spanish` absent from `active_tools()` when
  `transfer_enabled=False`; `end_call` sets `pending_hangup` and the consumer closes gracefully after the reply
  plays; the tool-iteration cap still produces the spoken fallback with a populated tool table (not just the
  empty-list case 3.2 tested); every dispatcher branch's possible `error.code` values are members of the closed
  set; PII redaction on `create_contact`'s logged args.
- **Observable surface**: no new page — 3.3 has no navigable surface of its own (a tool table is not a settings
  form), same posture as 3.2. `simulate_call` (3.2's management command) becomes materially more useful once a
  scripted fake LLM can drive it through a real booking, so extending its fixture library to include one
  full-booking script is this sub-module's contribution to the observable-surface obligation, satisfied through
  3.2's existing command rather than a new one. No `LIVE_LINKS["3.3"]` entry is expected (matches 3.2's own
  precedent) — confirm with `todo` whether an empty-dict entry should still be added for ledger completeness.

Deferred to later sub-modules, so nothing here is lost: the transfer working-hours gate, the single-fire guard and
the actual Twilio REST redirect (3.4, though 3.3 sets the signal 3.4 reads); consent-gated recording and the
runtime diagnostics page's tool-call trace rendering (3.5, though 3.3 is what produces the `logs` entries 3.5 will
render); a per-call-session ceiling on repeated `create_contact`/`create_callback_request` calls beyond the
existing turn/duration bounds (no researched competitor documents an equivalent, and the existing bounds are the
shipped mitigation).

---

## Belongs to sibling sub-modules (parked, not scoped here)

- Transfer working-hours gating (`AgentSetting.transfer_working_hours` evaluated in `transfer_timezone`), the
  single-fire guard, the drain interval, E.164/SID validation before interpolation, the actual Twilio REST
  `<Dial>` redirect, and `CallSession.transfer` outcome capture → **3.4** (3.3 only sets
  `state.pending_transfer`).
- Consent-gated recording, the two-party-consent announcement, `waveform_peaks`, `recording_blob` persistence, the
  full runtime diagnostics page (per-stage latency, a tool-call trace rendering of the `logs` entries 3.3
  produces) → **3.5**.
- The call-detail transcript/event-log/cost-breakdown UI that will eventually render this sub-module's `logs`
  entries and tool-call trace → **Module 5** (5.2/5.3, both already built as view sub-modules reading
  `CallSession`'s JSON columns — no new work triggered here, just noting where 3.3's `logs` entries surface).
- A configurable per-tenant/per-location tool-call rate ceiling beyond `MAX_TOOL_ITERATIONS` → not currently
  scoped to any sub-module; would need a new `AgentSetting` field (a 2.1 decision) if ever built.

## Out of scope for this product (outside the seven capabilities)

- **A vertical-specific tool** (insurance verification, clinical notes, order lookup, CRM sync beyond
  `scheduling.Contact`) — the skill states this explicitly: "If a tool is not in the table above, it does not
  exist — no insurance tool, no clinical note, nothing vertical-specific." This product's seven capabilities do
  not include any of these.
- **A client-side/browser tool** (ElevenLabs' "client tools" category — UI-triggered actions in a web widget) —
  this product's only caller-facing surface is a phone call; there is no browser widget for a tool to reach into.
- **Outbound-initiated tool actions** (e.g., a tool that places a follow-up call) — the telephony adapter has no
  dial-out method by design (carried forward from 3.1/3.2's own scope boundary); none of the 12 tools originates a
  call, only the transfer tools redirect an already-live one.
- **A tool marketplace / third-party tool plugin system** (several enterprise platforms like PolyAI support
  arbitrary customer-authored integrations) — this product's tool set is closed at 12, by design, matching the
  skill's own "no more" framing.

## Deferred (later passes / integrations)

- **`provider_error` and `rate_limited` are declared in the closed code set but unreachable this pass** — no tool
  in the 12-tool table calls an external provider today, so nothing can legitimately return `provider_error`; no
  per-tool rate limit exists yet, so nothing returns `rate_limited`. Both stay in the set (future tools/limits
  will need them and the set must not grow ad hoc later) but no dispatcher branch emits either this pass.
- **A per-call-session ceiling on repeated identity/callback tool calls** (beyond the existing per-turn iteration
  cap and call-duration/idle bounds) — no researched competitor publishes an equivalent, and the existing 3.2
  bounds are the shipped, sufficient mitigation for this pass; revisit only if real traffic shows a gap.
- **Native-audio (`voice_provider='live'`) tool-calling semantics** — the skill's §8.2 note that "the same function
  serves the turn-based path and the realtime speech-to-speech path" is written for when `LiveLlmBackend` actually
  exists; today it raises `NotImplementedError` by design (3.2), so this pass's tests exercise the dispatcher only
  through the cascaded (`FakeLlmBackend`) path. Proving the dispatcher is genuinely transport-agnostic against a
  real native-audio adapter is deferred until that adapter is built, matching 3.2's own deferred-live-adapter note.
- **A tool-call-specific rate/latency budget distinct from the general provider-call budget** — every dispatcher
  branch here is a local DB call with no external round-trip, so the existing `PROVIDER_TIMEOUT_SECONDS` (which
  bounds STT/TTS/LLM calls) does not apply to tool dispatch itself; a future provider-backed tool would need its
  own bounded-call wrapper, following the same pattern `providers/{stt,tts,llm}.py` already establish — noted for
  that hypothetical, not built now.
