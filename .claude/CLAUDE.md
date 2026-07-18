# NavAIReceptionist — Project Instructions

NavAIReceptionist is a multi-tenant SaaS **AI voice agent** for inbound and outbound phone calls, running 24/7: it answers calls instantly, follows up with new leads, qualifies prospects, sends SMS, and books appointments automatically so no opportunity is missed. The stack is **all-Django, one codebase, no separate microservice** — Django 5.1 + **Django Channels/ASGI** (realtime telephony media-stream websockets and live-call UI), Tailwind CSS + HTMX + Lucide on the front end, MySQL database `navai_receptionist`. It is multi-tenant end to end: a `tenant` FK on every model and `tenant=request.tenant` on every queryset. Telephony, STT, TTS and LLM providers all sit behind adapters in `apps/core/providers/`.

---

### Stack & Commands

* Python: `venv\Scripts\python.exe` (Django is not on system Python)
* Dev server (ASGI — **required** for websockets): `venv\Scripts\python.exe -m daphne -b 127.0.0.1 -p 8000 config.asgi:application`
* **Never** use `manage.py runserver` for anything touching websockets, media streams or live-call surfaces
* Checks: `venv\Scripts\python.exe manage.py check` · migrations: `makemigrations` / `migrate`
* Tests: `venv\Scripts\python.exe -m pytest -q apps/<app>` (settings `config.settings_test`, SQLite in-memory)
* DB: MySQL/MariaDB (XAMPP) via PyMySQL, `navai_receptionist`; `.env` via python-dotenv (see `.env.example`)
* Tunnel for provider webhooks in dev: ngrok → `TWILIO_WEBHOOK_BASE_URL`
* Provider mode: `PROVIDER_MODE=fake` is the default for dev, tests and seeders — a non-`live` mode must never place a real call or send a real SMS

---

### **Workflow Orchestration**

**1. Plan Mode Default**

* Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
* If something goes sideways, STOP and re-plan immediately – don't keep pushing
* Use plan mode for verification steps, not just building
* Write detailed specs upfront to reduce ambiguity

**2. Subagent Strategy**

* Use subagents liberally to keep main context window clean
* Offload research, exploration, and parallel analysis to subagents
* For complex problems, throw more compute at it via subagents
* One task per subagent for focused execution

**3. Self-Improvement Loop**

* After ANY correction from the user: update `.claude/tasks/lessons.md` with the pattern
* Write rules for yourself that prevent the same mistake
* Ruthlessly iterate on these lessons until mistake rate drops
* Review lessons at session start for relevant project

**4. Verification Before Done**

* Never mark a task complete without proving it works
* Diff behavior between main and your changes when relevant
* Ask yourself: "Would a staff engineer approve this?"
* Run tests, check logs, demonstrate correctness

**5. Demand Elegance (Balanced)**

* For non-trivial changes: pause and ask "is there a more elegant way?"
* If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
* Skip this for simple, obvious fixes – don't over-engineer
* Challenge your own work before presenting it

**6. Autonomous Bug Fixing**

* When given a bug report: just fix it. Don't ask for hand-holding
* Point at logs, errors, failing tests – then resolve them
* Zero context switching required from the user
* Go fix failing CI tests without being told how
* Use the monitor tool 

---

### **Module Creation Sequence (MANDATORY)**

Whenever you create a **new module or sub-module** (especially via `/next-module`), follow this exact sequence. It **starts with research and planning** (`research` → `todo`) so the build is driven by what the best products in the domain actually do, *then* writes the code, *then* runs the review agents. Each step ends with `git add` + `git commit` (one file per commit, PowerShell-safe). **Never run `git push` at any step** — the user pushes manually.

1. **Run the `research` agent** — research the ~6–10 leading commercial AI voice-agent / conversational-telephony products in the ONE target sub-module's (`N.M`) specific domain (not the parent module's generic domain) — the competitor universe is Bland AI, Retell AI, Vapi, Synthflow, PolyAI, Goodcall, Smith.ai, Ruby, Rosie and Dialpad AI — read their feature sets, and write a deduplicated, prioritized feature catalog to `.claude/tasks/research-<slug>-<N.M>.md` (features mapped to that sub-module's NavAIReceptionist.md feature bullets and the core spine in `NavAIReceptionist-ERD.md`, with a recommended 1–4-model build scope). Then `git add` + `git commit` that file. Do NOT `git push`.
2. **Run the `todo` agent** — feed it the `research` output; it turns the specialized features into a checkable build plan in `.claude/tasks/todo.md` (the models + their fields/choices **driven by the researched features**, plus backend/wire-up/templates/verify/close-out items). Then `git add` + `git commit` that file. Do NOT `git push`.
3. **Write the module code** — implement the module per the `todo` plan, then `git add` + `git commit`. Do NOT `git push`.
4. **Run the `code-reviewer` agent** — apply its findings, then `git add` + `git commit`. Do NOT `git push`.
5. **Run the `explorer` agent** — apply its findings, then `git add` + `git commit`. Do NOT `git push`.
6. **Run the `frontend-reviewer` agent** — apply its findings, then `git add` + `git commit`. Do NOT `git push`.
7. **Run the `performance-reviewer` agent** — apply its findings, then `git add` + `git commit`. Do NOT `git push`.
8. **Run the `realtime-reviewer` agent** — apply its findings, then `git add` + `git commit`. Do NOT `git push`.
9. **Run the `qa-smoke-tester` agent** — apply its findings, then `git add` + `git commit`. Do NOT `git push`.
10. **Run the `security-reviewer` agent** — apply its findings, then `git add` + `git commit`. Do NOT `git push`.
11. **Run the `test-writer` agent** — apply its output, then `git add` + `git commit`. Do NOT `git push`.
12. **Create or update the module's Claude Code skill** — on a brand-new-app run, author `.claude/skills/<module-slug>/SKILL.md`; otherwise **UPDATE** the existing skill with this sub-module's models / routes / templates / seeder rows (never overwrite the file — a second sub-module run that re-authors the skill clobbers the previous sub-module's documentation). Then `git add` + `git commit`. Do NOT `git push`. (See **Per-Module Skill (MANDATORY)** below.)

**Rules for this sequence:**

* Run the agents **in this order, one at a time** — do not skip a step and do not reorder. **`research` runs first, then `todo`, then "Write the module code", then the review agents** as listed.
* The `research` step produces `.claude/tasks/research-<slug>-<N.M>.md` (e.g. `research-scheduling-10.3.md`); the `todo` step produces `.claude/tasks/todo.md` from it — commit each as its own file.
* After each agent step, commit the resulting changes before moving to the next agent (still one file per commit).
* `git push` is **never** part of this sequence — stop at `git commit` every time.
* If an agent reports no changes are needed, note that and proceed to the next step (no empty commit required).

---

### **Per-Module Skill (MANDATORY)**

Every time you finish a **new module** (a Django app under `apps/<slug>`), you MUST create a dedicated Claude Code skill for it, and every subsequent sub-module run on that app MUST **update** it rather than re-author it. This makes future work on that module fast and consistent (the skill is the module's living "how to work on me" guide).

**Create or update:** author the file only on a **brand-new-app run**. On every later sub-module run the skill already exists — **UPDATE** it in place, adding this sub-module's models / routes / templates / seeder rows (plus its *Tools & prompt surface* and *Realtime surfaces* subsections). Re-authoring it from scratch clobbers the earlier sub-modules' documentation, which is the exact failure this rule exists to prevent.

1. **Location & name:** create `.claude/skills/<module-slug>/SKILL.md` where `<module-slug>` is the app slug (e.g. `telephony`, `agents`, `calls`, `scheduling`). The skill `name` is the slug (or `<slug>-module`).

2. **Frontmatter** (YAML) is required:
   * `name:` — the slug.
   * `description:` — one line that states **what the skill covers and when to trigger it**, with explicit trigger phrases, e.g. *"Work on the Calls module (inbound/outbound call sessions, transcripts, recordings, dispositions). Use when the user asks to add/change/debug anything under apps/calls or templates/calls, or invokes /calls."*

3. **Body** must document the **as-built** module so it can be worked on without re-reading everything:
   * **Overview** — what the module does (mirror its `NavAIReceptionist.md` section) and its app path.
   * **Models** — each model + key fields, choices, and which **core-spine** entities it reuses (`core.Contact`, `core.ContactChannel`, `core.PhoneNumber`, `core.Agent`/`core.AgentVersion`, `core.Interaction`/`core.InteractionEvent`, `core.UsageEvent`, `core.Appointment`, `core.Recording`, etc.) vs. adds.
   * **URLs / routes** — the `app_name` and url names (list/create/detail/edit/delete) + any custom actions: place-call, transfer, hang-up, retry, play-recording, download-transcript, test-agent, publish-agent-version, send-SMS, book/reschedule/cancel.
   * **Templates** — the `templates/<slug>/` pages and the shared patterns/partials they use.
   * **Tools & prompt surface** — which LLM tools this module registers or enables, their argument schemas, which `AgentVersion.enabled_tools` entries switch them on, and what prompt variables the module injects. State plainly that identity args (`tenant_id`, `contact_id`, `interaction_id`) come from server state, never from the model.
   * **Realtime surfaces** — any Channels consumers, `routing.py` websocket patterns, group-name scheme (`t{tenant_id}:…`), background tasks, provider webhooks and their signature-verification entry points; or the explicit line "this module has no realtime surface".
   * **Seeder** — the `seed_<slug>` command and the demo data it creates: demo tenants, provisioned phone numbers, agent personas with published versions, synthetic interactions carrying transcript events, appointments, SMS threads and usage events. All of it produced through the fake provider adapter.
   * **Conventions & gotchas** — tenant scoping, the context-var contract, any module-specific rules.
   * **Common tasks** — concrete steps for "add a field", "add a new model + CRUD", "add a filter", "extend the seeder".
   * **Sidebar wiring** — the `LIVE_LINKS` entries added in `apps/core/navigation.py` for this module.

4. **Accuracy & upkeep:** the skill must reflect the real code (correct paths, url names, field names). When the module changes later, update its skill in the same change.

5. **Commit it** as its own file (one file per commit, PowerShell-safe). **Never `git push`.**

> Module 0 is the foundation and is covered by the workflow skills (`next-module`, `frontend-design`, `voice-agent-runtime`). Modules **1–13** each get their own skill via this rule.

---

### **Task Management**

1. **Plan First**: Write plan to `.claude/tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `.claude/tasks/todo.md`
6. **Capture Lessons**: Update `.claude/tasks/lessons.md` after corrections

---

### **Core Principles**

* **Simplicity First**: Make every change as simple as possible. Impact minimal code.
* **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
* **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.

---

### GIT Commit Rule

* Whenever you create a new file or update a file or delete a file. You should do a git commits.
* git commit should be in details about new changes, update or add features in detail.
* eg: 
git add 'src/file.js'
git commit -m 'some example changes'.

**STRICT — ONE FILE PER COMMIT (no exceptions):**

* **Never** combine multiple files into a single `git add` / `git commit` pair, **even if they're in the same folder, share a feature, or look like a "set"** (e.g. `persona/list.html` + `persona/form.html` + `persona/detail.html` of the same model).
* **Wrong** (this is what NOT to do):
  ```
  git add 'templates/agents/persona/list.html' 'templates/agents/persona/form.html' 'templates/agents/persona/detail.html'; git commit -m 'feat(agents): persona templates'
  ```
* **Right** — one `git add` + one `git commit` per file, every time:
  ```
  git add 'templates/agents/persona/list.html'; git commit -m 'feat(agents): persona list template'
  git add 'templates/agents/persona/form.html'; git commit -m 'feat(agents): persona form template'
  git add 'templates/agents/persona/detail.html'; git commit -m 'feat(agents): persona detail template with version history'
  ```
* Each commit message should be specific to that one file's content — don't reuse the same message across multiple commits.
* If a change spans 30+ files, the snippet block IS 30+ commits. Length is fine — bundling is not.
* Empty `__init__.py` files still get their own commit.

**Shell Compatibility (CRITICAL — user runs PowerShell on Windows):**

* The user's shell is **Windows PowerShell (5.x)** — `&&` is NOT a valid statement separator and WILL fail with `ParserError`.
* When combining commands on one line, use `;` as the separator, NEVER `&&`.
* When providing "all commits in one copy" / "single copy" / bulk-commit output, ALWAYS output in PowerShell-compatible form:
  * ✅ Correct: `git add 'file.py'; git commit -m 'msg'`
  * ❌ Wrong:  `git add 'file.py' && git commit -m 'msg'`
* Default to PowerShell-safe syntax for ALL shell snippets intended for the user to run directly (not just git).
* Note: `;` runs the next command even if the first fails. If stop-on-failure is required, output commands on separate lines instead of chaining.

---

### Core Spine Invariants (MANDATORY)

`apps/core` (Module 0) owns the **entire** shared spine — identity, the communication log, the metering ledger, the outcome documents and the compliance gate. Modules 1–13 own their own domain tables and the UI/engines over the spine; they **never** own a spine table. The full field-level definitions live in `NavAIReceptionist-ERD.md`; that document is INTENT — the code is truth, so grep before you FK.

The six invariants below are law. They are quoted by number (`Invariant 2`) from every review agent, and the wording must be identical in every file that carries them.

1. **One identity table.** Leads, prospects, customers, callers, attendees and staff are `core.ContactRole` rows on `core.Contact`. **Flag any new standalone person table.** A phone number belongs to `core.ContactChannel` / `core.PhoneNumber` — flag any module storing raw phone strings on its own model.
2. **One communication log.** Every call, SMS and email is a `core.Interaction` + append-only `core.InteractionEvent` rows. Conversation history, transcripts and tool-call audit are **derived by query**, never copied into a module table. **Flag a second transcript/message/activity table.**
3. **One metering ledger.** Every billable unit is a `core.UsageEvent`. **Flag a stored, hand-editable `minutes_used`, `credit_balance`, `calls_placed` or `spend_to_date` field, or code that mutates a usage total directly instead of appending an event.**
4. **Append-only means append-only.** `InteractionEvent` and `UsageEvent` have no update or delete path. Corrections are compensating rows. Redaction is the sole exception and goes through the compliance module's documented redaction service, which writes an `AuditLog` row.
5. **One outbound gate.** Every outbound call, SMS or voicemail drop calls exactly one service function — `apps/core/compliance.check_outbound_allowed(contact, channel, now)` — which consults `ConsentRecord` + `SuppressionEntry` + `QuietHoursPolicy` + `Contact.status`. **There is no second DNC list and no inline `if not contact.do_not_call` check anywhere.** Flag both.
6. **Server owns identity; the model owns wording.** The LLM tool dispatcher signature is `apply_tool_call(state, name, args)` and is **transport-agnostic** (the same dispatcher serves the turn-based path and the realtime websocket path). Identity arguments — `tenant_id`, `contact_id`, `interaction_id` — are injected from server-side session state and are **never tool parameters**. Any ID the model *does* supply (`appointment_id`, `slot_token`) must be authorized server-side against tenant **and** the identified contact.

Two further spine rules are non-negotiable, not suggestions:

* **Opaque signed slot tokens.** The availability tool returns one `slot_token` per slot (a signed, short-TTL blob encoding start/resource/service/tenant), not semantic fields the model must echo verbatim. The model cannot mangle or invent a token, and the backend can verify the slot was actually offered *in this interaction*.
* **One tool-result envelope.** Every tool returns `{"ok": bool, "data": {...}, "error": {"code": ..., "message": ...} | null}`. Never prose, never a bare `{"id": ...}`, never a different success key per tool.

---

### Filter Implementation Rules (Preventing Recurring Issues)

Every list page in this application MUST have working filters. When creating or modifying any list view/template, follow these mandatory steps:

1. **View must pass ALL context needed by template filters:**
   - For status dropdowns: pass `status_choices` (from `Model.STATUS_CHOICES`)
   - For FK dropdowns (agents, phone numbers, campaigns, contacts, dispositions): pass the queryset to the template
   - For type/method dropdowns: pass the model's `CHOICES` constant
   - Never assume the template will get data it wasn't explicitly passed in the view context

2. **Template filter comparison rules:**
   - For string fields: `{% if request.GET.status == value %}selected{% endif %}`
   - For FK/pk fields: use `|stringformat:"d"` — NEVER use `|slugify` for pk comparison
   - Example: `{% if request.GET.agent == a.pk|stringformat:"d" %}selected{% endif %}`

3. **View filter logic:**
   - Always parse GET params and apply to queryset BEFORE pagination
   - Search: `request.GET.get('q', '').strip()` with `Q()` lookups
   - Status: `request.GET.get('status', '')` with `qs.filter(status=value)`
   - Active/Inactive: map `'active'`/`'inactive'` to `is_active=True/False`
   - A junk value (`?agent=abc`) must degrade to "no filter", never raise

4. **Template variable naming must match view context:**
   - If view passes `call_sessions`, template must use `{% for r in call_sessions %}`
   - If model field is `duration_seconds`, template must use `r.duration_seconds` (not `r.duration`)
   - If view passes `stats` dict, template accesses `stats.missed` (not `missed_count`)

5. **Badge values must match model CHOICES:**
   - Template badge conditions must use exact model choice values (e.g., `'no_answer'` not `'noanswer'`, `'voicemail'` not `'vm'`, `'in_progress'` not `'inprogress'`)
   - Always include an `{% else %}` fallback: `{{ obj.get_field_display }}`

Run the `/frontend-design` skill for the full pattern reference.

---

### CRUD Completeness Rules (Preventing Missing Actions)

**Scope — a sub-module is one of exactly three shapes; decide which BEFORE picking models:**

* **CRUD sub-module** — it introduces one or more tenant-scoped models with a list page. These rules apply in full: such a sub-module must never ship with only list/add/view — Edit and Delete are mandatory.
* **Service sub-module** — infrastructure, not CRUD.
* **View sub-module** — pages over spine data it only READS, with **zero new models**.

**Service sub-module exemption:** parts of this product are infrastructure, not CRUD — the realtime runtime (Module 4), the media bridge and webhook ingress in Module 1, the enforcement paths in Modules 6 and 9, and the connectors in Module 13 produce consumers, services, provider adapters and diagnostics rather than list/detail/form pages. A **service sub-module** MAY ship zero CRUD templates. It MUST still ship: tenant scoping on every query, a `LIVE_LINKS["N.M"]` entry pointing at its diagnostics or settings page, migrations if it adds models, tests, an idempotent seeder if it adds data, a fake provider implementation so the whole path runs with `PROVIDER_MODE=fake`, and **at least one observable surface** — a diagnostics page, a settings form or a management command. A sub-module with no observable surface is not done.

**View sub-module exemption:** some sub-modules add **no data of their own** — they are the reading surface over spine tables that already exist. A **view sub-module** ships **ZERO new models and ZERO migrations**: it is pages, filters, search, detail views, exports and a `LIVE_LINKS["N.M"]` entry built over spine tables it only READS. The known instances are **11.1, 11.2, 5.6, 12.4 and 12.5**. *Inventing a model to satisfy the 1–4-model target is the bug this branch exists to prevent. If the data already lives in the spine, the sub-module is a view — ship the pages, not a table.* Concretely, 11.2 (Transcript & Tool-Call Trace) is the transcript view over `core.InteractionEvent`; a `Transcript`/`TranscriptTurn`/`ToolCall` table there is an **Invariant 2** violation. A view sub-module MUST still ship: tenant scoping on every query (`tenant=request.tenant`), the `LIVE_LINKS["N.M"]` entry, its templates under `templates/<slug>/<submodule>/<entity>/`, tests, and **seeded demo data reachable through the pages — seeded into the spine, never into a new table** (extend the existing `seed_<slug>` idempotently). It has no create/edit/delete views, and their absence is correct.

Append-only spine tables (`core.InteractionEvent`, `core.UsageEvent`) and immutable published records (a published `core.AgentVersion`) legitimately have **no** edit or delete view. Their *absence* is correct; their unguarded *presence* is the bug.

1. **Every model that has a list page MUST have these views:**
   - `list_view` — with search + filters
   - `create_view` — add form
   - `detail_view` — read-only detail page (for models with enough fields)
   - `edit_view` — edit form (same template as create, pre-filled)
   - `delete_view` — POST-only with confirmation, redirects to list

2. **Every list template MUST have an Actions column with:**
   - View button (eye icon) — links to detail page
   - Edit button (pencil icon) — links to edit form
   - Delete button (bin icon) — POST form with `onclick="return confirm('...')"` and `{% csrf_token %}`
   - Conditional display: wrap Edit/Delete in `{% if obj.status == 'draft' %}` (unpublished agent version) or `{% if obj.status == 'scheduled' %}` (undialed campaign attempt) when status-dependent

3. **Every detail template MUST have an Actions sidebar with:**
   - Edit button — links to edit form (conditional on status)
   - Delete button — POST form with confirm dialog (conditional on status)
   - Back to List link

4. **Delete view pattern:**
   ```python
   @login_required
   def model_delete_view(request, pk):
       obj = get_object_or_404(Model, pk=pk, tenant=request.tenant)
       if request.method == 'POST':
           obj.delete()
           messages.success(request, 'Deleted successfully.')
           return redirect('app:model_list')
       return redirect('app:model_list')
   ```

5. **Delete URL pattern:**
   - Always add: `path('models/<int:pk>/delete/', views.model_delete_view, name='model_delete')`

---

### Template Folder Structure (MANDATORY)

Templates MUST be organized **one folder per sub-module, then one folder per entity** — never flat. The page
(`list` / `detail` / `form` / a secondary action) is the **bare filename**. A model's CRUD pages live under
`templates/<app>/<submodule>/<entity>/<page>.html`, grouped by the NavAIReceptionist.md sub-module that owns the
model.

1. **Path shape:** `templates/<app>/<submodule>/<entity>/<page>.html` where `<page>` ∈ {`list`, `detail`, `form`,
   … a secondary action like `import`}. e.g. `templates/calls/calllog/callsession/detail.html`,
   `templates/calls/calllog/callsession/list.html`, `templates/contacts/directory/contact/form.html`. The view's
   `render()` / `crud_*` `template=` argument uses that full path: `render(request,
   "calls/calllog/callsession/detail.html", ...)`. **Never** ship a flat `<entity>_<page>.html` file inside a
   sub-module folder (the `callsession_detail.html` shape is banned).

2. **Two folder levels: sub-module → entity.** The sub-module folder uses a short slug taken from the real
   NavAIReceptionist.md catalog sub-modules (Calls, Module 11 — `apps/calls`:
   `calllog/ transcript/ summaries/ scoring/ review/ delivery/`; Contacts, Module 7 — `apps/contacts`:
   `directory/ capture/ qualification/ pipeline/ hygiene/`; Inbound, Module 5 — `apps/inbound`:
   `greeting/ screening/ routing/ transfer/ voicemail/ monitoring/`). **Inside it, each model/entity gets its own
   folder** (`calllog/callsession/`, `directory/contact/`, `transfer/transferrule/`). The page file is
   just `list.html` / `detail.html` / `form.html`.

3. **Single-entity sub-modules: the sub-module folder doubles as the entity folder** — do NOT double-nest. When a
   sub-module owns one main entity whose slug equals the folder (e.g. `persona`, `campaign`, `knowledge`), keep
   `persona/form.html`, `campaign/detail.html` — NOT `persona/persona/list.html`. A child entity added later still
   gets its own folder under the sub-module (e.g. `campaign/step/form.html` alongside the page-only
   `campaign/list.html`). When a single-entity sub-module later grows to multiple entities it graduates to the
   rule-2 two-level form.

4. **Foundation apps (Module 0: core / accounts / tenants / dashboard) are flat — no sub-module level**, so the
   entity folder sits at the app root: `templates/core/contact/list.html`, `templates/accounts/user/form.html`,
   `templates/tenants/subscription/detail.html`.

5. **Secondary entity-action pages go inside the entity folder** (page = the action name):
   `directory/contact/import.html` sits next to `directory/contact/list.html`. Fold a non-CRUD page into
   `<entity>/<action>.html` only when it begins with `<entity>_` for an entity that already has a CRUD triple in
   that directory (longest-entity-stem match — so `call_session_replay.html` is **not** folded into `callsession/`).

6. **Standalone pages stay at the sub-module / app root** (no entity folder): module landing/overview
   (`templates/calls/overview.html`, `templates/agents/overview.html`, `templates/analytics/dashboard.html`),
   reports (`analytics/reports/call_volume.html`, `analytics/reports/answer_rate.html`,
   `calls/scoring/conversion_funnel.html`), print pages (`calls/transcript/transcript_print.html`), wizards
   (`tenants/onboarding_wizard.html`), and other single-purpose pages that aren't an entity's list/detail/form.
   Diagnostics and settings pages for service sub-modules live here too (`runtime/diagnostics.html`).

7. **New modules (via `/next-module`)** MUST follow this from the start — create
   `templates/<app>/<submodule>/<entity>/{list,detail,form}.html`. Never ship flat
   `templates/<app>/<submodule>/<entity>_<page>.html` files.

8. **`{% extends %}` / `{% include %}` are unaffected** by the folders — keep `{% extends "base.html" %}` and
   `{% include "partials/..." %}` (base + partials live at the templates root, not inside a module).

---

### Backend Package Structure (MANDATORY)

The backend mirrors the template rule: `models`, `forms`, `views` and `urls` are **Python packages**, organized
**one folder per sub-module, then one file per entity** — never flat `.py` monoliths. `NavAIReceptionist-ERD.md`
is the reference for what belongs in the spine versus a module; `apps/core` and the first built domain app
(`apps/calls`) **will be** the reference implementations once they exist — do not cite a directory that is not
there yet.

1. **Path shape:** `apps/<app>/<layer>/<SubModule>/<Entity>.py` where `<layer>` ∈ {`models`, `forms`, `views`,
   `urls`}. `<SubModule>` is a short PascalCase form of the real NavAIReceptionist.md sub-module heading
   (`### 11.1 Call Log & Recording` → `CallLogRecording/`; `### 11.2 Transcript & Tool-Call Trace` →
   `TranscriptTrace/`; `### 5.4 Transfer & Escalation` → `TransferEscalation/`); `<Entity>` is the entity in
   **PascalCase** (`Personas.py`, `CallSessions.py`). The four layers **line up one-to-one**:
   `apps/calls/models/CallLogRecording/CallSessions.py` ↔ `forms/…` ↔ `views/…` ↔ `urls/…`.

2. **An entity file owns the primary model plus its children** — `Scorecards.py` = `Scorecard` +
   `ScorecardCriterion`; `Campaigns.py` = `Campaign` + `CampaignStep`. Do not scatter one entity's CRUD across
   files. Note that the child must be a genuine domain table: a module-owned `Transcript`, `TranscriptTurn`,
   `ToolCall`, `Message`, `CallEvent` or `ActivityLog` table is an **Invariant 2** violation — the transcript and
   the tool-call trace are the transcript view over `core.InteractionEvent`.

3. **Every package `__init__.py` re-exports everything it owns**
   (`from .<SubModule>.<Entity> import (A, B)`). This is what keeps `from apps.<app>.models import X`,
   `views.<name>` in the URLconf, and `include('apps.<app>.urls')` working. **Adding a model/form/view WITHOUT
   adding it to the re-export block is a bug** — it will `ImportError` / `AttributeError` at runtime.

4. **Imports inside these packages MUST be ABSOLUTE** — `from apps.<app>.models import X`. A relative
   `from .models import X` resolves to the wrong package one level deeper. Entity modules pull the shared toolkit
   from `<layer>/_base.py` (models) or `<layer>/_common.py` (forms/views) via `import *`.

5. **Shared modules:** `models/_base.py` (django imports + the abstract `Tenant*` base), `forms/_common.py`,
   `views/_common.py`. Private helpers used by **more than one** sub-module go in `views/_helpers.py`; helpers used
   by a single entity stay in that entity's module. **A fifth layer, `consumers/`, follows the same
   `<SubModule>/<Entity>.py` shape** for Channels consumers; `routing.py` stays flat at the app root.

6. **`urls/__init__.py`** sets `app_name` and concatenates each entity module's `urlpatterns`. Django resolves
   **first-match-wins, so order is behaviour** — keep literal routes before `<int:pk>` ones, and check any new
   greedy `<str:token>` route against the whole concatenated list, not just its own module.
   The same is true of `routing.py`: the Channels `URLRouter` also resolves first-match-wins, so a greedy
   `<str:token>` media-stream route must be checked against the whole concatenated websocket list, not just the
   patterns in the file you are editing.

7. **Never create a `*_advanced.py` sidecar** (or any second flat file) for "advanced"/later features — a later
   sub-module's models simply get their own `<SubModule>/<Entity>.py`.

8. **`admin.py`, `apps.py`, `analytics.py`, `services.py`, `consumers.py`, `routing.py`, `tasks.py`,
   `webhooks.py`, `providers.py` and other single-purpose modules stay flat** at the app root — promote one to a
   package (`consumers/`, `providers/`) only when it grows past easy navigation. Migrations are unaffected: models
   sit deeper than the app root, but Django still derives `app_label` from the app config — a correct split needs
   **no new migration** (`makemigrations --check` must say "No changes detected").

9. **Foundation apps (Module 0: `core` / `tenants`) have NO sub-module level** — exactly like their templates
   (rule 4 above). Module 0 has no catalog sub-modules of the kind rule 1 describes, so the entity file sits FLAT
   at the package root: `apps/core/models/Contact.py`, `apps/core/views/Contact.py`,
   `apps/tenants/models/Subscription.py` — never a `<SubModule>/` folder. Shared plumbing still goes in
   `_base.py` / `_common.py` (e.g. `core/forms/_common.py` holds **`TenantModelForm`**, the base class every other
   app's forms inherit, plus `ALLOWED_DOC_EXTENSIONS`/`MAX_UPLOAD_BYTES` and
   `ALLOWED_AUDIO_EXTENSIONS`/`MAX_RECORDING_BYTES`). `accounts` and `dashboard` remain flat modules.

10. **Don't split a file just for symmetry — split it when it's hard to navigate.** `core/urls.py` and
    `tenants/urls.py` stay **flat modules**: a compact `crud(slug, name)` factory that generates the 5 standard
    routes per model beats expanding it into per-entity `urlpatterns` lists with dozens of duplicated `path()`
    lines. The factory IS the better structure.

---

### Realtime & Telephony Rules (MANDATORY)

The realtime layer is where a mistake costs audio, money or a cross-tenant leak — not just a broken page.

1. **No synchronous work on the event loop:**
   - No sync ORM call, sync `requests`/`httpx.Client` call, file I/O or blocking SDK call inside an `async def`
     consumer or task — use `database_sync_to_async`, `sync_to_async(thread_sensitive=False)` or `asyncio.to_thread`
   - A blocking call on the event loop freezes audio for **every** concurrent call on that worker, not just yours

2. **Consumers authorize in `connect()`:**
   - `@login_required` does not apply to consumers — reject with an explicit close code
   - Never accept-then-check; an accepted socket has already leaked the connection

3. **Channels groups are tenant-namespaced:**
   - `t{tenant_id}:call:{interaction_id}` — an un-namespaced group lets tenant A subscribe to tenant B's live audio

4. **Every external provider call is bounded:**
   - Explicit timeout and a bounded retry on every telephony/STT/TTS/LLM call
   - Failures degrade to a spoken fallback, never dead air

5. **The greeting/opener is deterministic** — it never waits on an LLM, so first audio is immediate

6. **Transport-mutating tools are deferred:**
   - Transfer and hangup set a deferred signal on session state; the transport acts **after** the turn's audio completes

7. **Per-turn tool-iteration cap (default 4)** with a spoken fallback, so a looping model never produces dead air

8. **Conversation history is trimmed or summarized on long calls** — resending unbounded history makes input tokens
   grow quadratically in both latency and cost

9. **`disconnect()` releases the interaction and flushes buffered events**; an exception in the receive loop is
   caught so one bad frame does not kill the call

---

### Seed Command Rules (Preventing Data Issues)

1. **Idempotent by default:**
   - Seed commands MUST be safe to run multiple times without `--flush`
   - Use `get_or_create` for models with unique constraints
   - For models with auto-generated numbers (CALL-00001, APPT-00001), check existence before creating:
     ```python
     existing = Model.objects.filter(tenant=tenant, number=number).first()
     if existing:
         results.append(existing)
         continue
     ```
   - Never use bare `.save()` or `.create()` for models with unique_together constraints

2. **Always skip if data exists:**
   - Check `if Model.objects.filter(tenant=tenant).exists()` at the start
   - Print a warning: `"Data already exists. Use --flush to re-seed."`

3. **Print login instructions:**
   - After seeding, always print which tenant admin accounts to use and the seeded password
   - Always warn: `"Superuser 'admin' has no tenant — data won't appear when logged in as admin"`

4. **`__init__.py` files:**
   - When creating `management/commands/` directories, ALWAYS create both:
     - `management/__init__.py`
     - `management/commands/__init__.py`

5. **Seeders never touch a real provider:**
   - Every seeded call, SMS and recording is produced through the fake provider adapter with `PROVIDER_MODE=fake`
   - A seeder that could place a real call or send a real SMS is a defect, not a configuration choice

---

### Multi-Tenancy Rules (Preventing Data Visibility Issues)

1. **Superuser has no tenant:**
   - The `admin` superuser has `tenant=None`
   - All tenant-scoped module views filter by `tenant=request.tenant`
   - When `request.tenant` is `None`, queries return empty results — this is BY DESIGN
   - Always instruct users to log in as a **tenant admin** (e.g., `admin_<slug>`) to see module data

2. **Every view MUST filter by tenant:**
   - `Model.objects.filter(tenant=request.tenant)` — no exceptions
   - Never use `Model.objects.all()` in tenant-scoped views
   - **This rule assumes an HTTP `request`. Channels consumers, background tasks and telephony webhooks have no
     `request.tenant`.** In those paths the tenant MUST be resolved from a verified source — the dialed
     `core.PhoneNumber`, the `core.Interaction` row, or a signature-verified provider payload — never from a
     query-string or body parameter the caller controls. The "never unscoped" guarantee is identical; only the
     resolution mechanism differs. **A consumer that accepts `tenant_id` from the websocket URL is a cross-tenant
     vulnerability.**

3. **Every model MUST have a tenant FK:**
   - Except User, Role (which have it already), pure join/through tables, and the deliberately global masters
     (`core.Currency`, `core.Voice`, `core.TelephonyProvider`, `core.Country`)
   - Always include: `tenant = models.ForeignKey('core.Tenant', on_delete=models.CASCADE, related_name='...')`
   - `core.PhoneNumber.e164` is **globally unique across all tenants** — a deliberate exception, because an inbound
     webhook resolves the tenant from the dialed number

---

### Vulnerability

When you find a security vulnerability, flag it immediately with a WARNING comment and suggest a secure alternative. Never implement insecure patterns even if asked.

This product carries telephony, PII and legal exposure that a normal CRUD app does not. The following are hard rules:

1. **Telephony webhooks must verify the provider signature** (`X-Twilio-Signature`) against the raw body and the exact public URL **before any side effect**. `@csrf_exempt` on a webhook is correct only when paired with signature verification.
2. **Webhook handlers must be idempotent** — providers redeliver. Key on `provider_sid` + `event_type` with a unique constraint; a retry must not double-charge usage, double-book an appointment, or double-send an SMS.
3. **Provider credentials** (Twilio auth token, LLM/STT/TTS API keys, webhook signing secrets, SIP passwords) come from `.env` or a per-tenant encrypted field; they are never in `Meta.fields`, never in `messages.*`, never logged, never rendered.
4. **Call recording**: the consent basis is recorded per recording; announce-before-record where the tenant's jurisdiction requires two-party consent; the retention window is enforced by a scheduled job.
5. **Transcripts and recordings are PII by definition.** Never log transcript bodies, caller numbers or tool-call argument blobs at INFO — a `create_contact` args payload is a full name and date of birth. Redact the tool-call payload before persisting.
6. **Outbound is legally gated**: TCPA/quiet hours evaluated in the *contact's* timezone, DNC/suppression, SMS STOP handling within one message, and A2P 10DLC registration state checked before send — all through the single gate in Invariant 5.
7. **Never place a real call or send a real SMS from a test, seed or development path.** Concretely:
   1. `PROVIDER_MODE` ∈ `fake | sandbox | live`; **`fake` is the default** for dev, tests and seeders.
   2. When the mode is not `live`, adapters resolve to the fake/sandbox implementation and **must never reach a real provider** — no real call placed, no real SMS sent, no billable API call.
   3. The **live** adapter refuses to initialize unless `PROVIDER_MODE == 'live'`, and live mode additionally requires real credentials to be present — missing credentials in live mode is the hard failure.
   4. `on_stop.py` warns loudly if `PROVIDER_MODE=live` is set in a dev environment.
8. **Cost is a security control**: per-tenant spend caps and per-call max-duration / max-turn ceilings prevent a prompt-injected or looping agent from burning unbounded provider spend.
