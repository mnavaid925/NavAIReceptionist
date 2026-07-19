# Research — Sub-module 1.1: Business Settings (Module 1 — Business & Locations, tenants)

## Repo state checked first

- **LIVE_LINKS built so far:** `0.1` (no sidebar link — pre-auth surfaces), `0.2` (Change Password, Change Email),
  `0.3` (My Profile, Users), `0.4` (My Locations). **Nothing in module 1 is built yet** — 1.1 is the first
  sub-module of Module 1, so there is no sibling research file to defer to and no in-module sidebar precedent.
- **Sibling models available to FK:** `accounts.User` (`tier` field: `owner`/`manager`/`staff`, via
  `apps/accounts/models/User.py`), `accounts.UserLocation`. `tenants.Location` is a sibling model within this app
  but is **1.2's** table, not touched here.
- **Models verified to exist (grep evidence):**
  - `apps/tenants/models/Tenant.py` — `class Tenant(TimeStamped)` with **exactly** `name` (Char), `slug`
    (SlugField, unique), `customer_id` (Char(32), unique — "the Customer ID a user enters at login to resolve this
    business"), `timezone` (Char(64), IANA, default `UTC`), `is_active` (Bool, default `True`), plus
    `created_at`/`updated_at` from `TimeStamped`. This matches `NavAIReceptionist-ERD.md` §3.1 `tenants.Tenant`
    exactly — **no drift, no extra fields**.
  - `apps/tenants/models/Location.py` — `class Location(TenantOwned)` exists (1.2's model, confirmed only to know
    the boundary, not scoped here).
  - `apps/tenants/admin.py` — `TenantAdmin` already exposes `name, customer_id, slug, timezone, is_active,
    created_at` as list_display/list_filter/search_fields, with `prepopulated_fields = {'slug': ('name',)}`. This
    is the **existing superuser-only surface**; 1.1 builds the **owner-facing** equivalent, scoped to their own
    single row.
  - `apps/accounts/backends.py:81` and `apps/accounts/views/Auth.py:180` — **`tenant__is_active=True` is already
    enforced at login.** The "inactive tenants blocked at login" half of the Tenant Activation State bullet is
    **already built in Module 0.1**. 1.1's job for that bullet is narrower than it first reads: **display** the
    status on the business settings page; do not build a second login gate.
  - `grep "^class AgentSetting"` across `apps/` — **no match.** `agents.AgentSetting` is not built yet (Module 2).
    Any feature that would read from it (agent prompt preview, per-location Twilio number) is out of scope here
    and parked to Module 2.
  - No `slug` reference anywhere outside `apps/tenants/models/Tenant.py` and `admin.py` — it is not yet used to
    route or resolve anything. Treat it as a stored identifier only, not a routing key, when scoping the form.
- **Reused, not re-planned:** `TenantModelForm` (`apps/accounts/forms/_common.py`) — note it pops `tenant` as a
  field and stamps it in `save()`, which is irrelevant here since `Tenant` has no `tenant` FK (it IS the tenant);
  this sub-module's form is a **plain `ModelForm`** bound to `request.tenant`'s own instance, not a
  `TenantModelForm` subclass. `tier_required('owner')` (`apps/accounts/views/_helpers.py`) gates the edit view.

## Leaders surveyed (with source links)

1. **Ruby Receptionists** — human-backed virtual receptionist with an online portal; the closest analog to a
   "company profile" screen an inbound-answering product ships — [Updating Your Company Profile](https://rubyhelpcenter.helpjuice.com/updating-your-company-profile), [Receptionist Service Quick Start Guide](https://rubyhelpcenter.helpjuice.com/en_US/getting-started/receptionist-service-quick-start-guide)
2. **Smith.ai** — AI + human hybrid receptionist; onboarding captures business info once, dashboard exposes
   call-handling preferences — [Smith.ai AI Receptionist](https://smith.ai/ai-receptionist), [Get Started guide](https://smithaivoiceassistant.freshdesk.com/support/solutions/151000219531)
3. **Goodcall** — pure AI phone agent; setup ingests a website/Google-listing URL to auto-populate business facts
   used by the agent — [Goodcall AI Receptionist](https://www.goodcall.com/voice-ai/ai-receptionist), [Getting Started](https://help.goodcall.com/en/collections/4196146-getting-started)
4. **Rosie** — mobile-first AI answering app; onboarding auto-learns hours/services from Google Business profile,
   owner confirms/edits before going live — [Rosie AI Receptionist](https://heyrosie.com/solutions/ai-receptionist), [App Store listing](https://apps.apple.com/us/app/rosie-ai-business-receptionist/id6757593086)
5. **Dialpad AI (Ai Receptionist / Auto Attendant)** — enterprise phone system; company name + hours + services
   feed the AI's knowledge, separate from per-line business-hours routing — [Dialpad AI Virtual Receptionist](https://www.dialpad.com/features/virtual-receptionist/), [Set Business Hours](https://help.dialpad.com/docs/set-business-hours)
6. **Numa** — SMS/voice AI receptionist for dealerships/SMBs; "learns your business" so hours/policies stay
   consistent across text and voice — [Numa](https://www.numa.com/blog/virtual-receptionist-software)
7. **Retell AI** — developer-facing voice-agent platform; workspace-level settings (name, workspace ID) are
   thin, business facts live in per-agent prompt variables instead of an org profile — [Retell Workspace docs](https://docs.retellai.com/accounts/workspace)
8. **Synthflow** — voice-agent platform; injects business facts via `custom_variables` merged into the prompt at
   call time rather than a persistent org-profile record — [Synthflow Variables](https://docs.synthflow.ai/variables)
9. **Calendly** (booking-product comparator, not a receptionist) — org-level Admin Center carries organization
   name, logo/branding and default timezone/locale, editable by owners/admins only — [Admin Center](https://help.calendly.com/hc/en-us/articles/16945127422487-Calendly-Admin-Center), [Account settings overview](https://calendly.com/help/account-settings-overview)
10. **Multi-tenant SaaS lifecycle practice** (AWS/Microsoft Entra patterns, not a receptionist product but the
    right precedent for the activation-state bullet) — tenant suspension is a **platform/admin-side** status flip,
    reversible, and gates login/API access without deleting tenant data — [Handling Tenant Suspension and Reactivation Gracefully](https://sollybombe.medium.com/handling-tenant-suspension-and-reactivation-gracefully-in-multi-tenant-saas-0af58945545a), [Tenant Blocked Due to Inactivity](https://learn.microsoft.com/en-us/answers/questions/5793182/how-to-fix-this-tenant-has-been-blocked-due-to-ina)

## Feature catalog (this sub-module only)

### Business Record
- **Business name as the spoken identity** — the business's display name is what every leader's agent says in its
  greeting/opener ("Thanks for calling Acme Dental") and in confirmations · seen in: Ruby, Smith.ai, Goodcall,
  Rosie, Dialpad AI · priority: table-stakes · model: reuses `tenants.Tenant.name` (**tenant-scoped**, not
  location-scoped — the single business record) · realtime: post-call (this sub-module only stores/edits it; the
  greeting render that *consumes* it at call time is Module 2/3's job) · tool-surface: pure UI (no tool; the value
  becomes a prompt/greeting variable a later module reads, never a tool argument) · buildable now.
- **Stable login-resolution identifier separate from the display name** — every product that fronts multiple
  client businesses (Ruby's account number, Retell's workspace ID, this product's `customer_id`) keeps a
  non-cosmetic id distinct from the editable display name, because the display name changes (rebrand) but the
  resolution key must not silently break sign-in · seen in: Retell (workspace ID), and structurally the same
  problem this product already solved with `customer_id` · priority: REQUIRED (breaking it locks out every user of
  the business) · model: reuses `tenants.Tenant.customer_id` · realtime: post-call · tool-surface: pure UI, and
  specifically **read-only display, not an editable field**, in the owner-facing form (see Compliance section) ·
  buildable now.
- **Default timezone as the business-wide fallback** — every product with any scheduling surface carries an
  org-level default timezone, distinct from a location's or a scheduling page's own override · seen in: Calendly
  (org-level time zone under Admin Center), Ruby (explicit "which timezone should the receptionist use" setup
  question), Dialpad (workspace vs. per-user timezone) · priority: table-stakes · model: reuses
  `tenants.Tenant.timezone` (**tenant-scoped** — `tenants.Location.timezone` already overrides it per-site, which
  is 1.2's field, not this one's) · realtime: post-call (consumed at call/booking time by 1.4/Module 4, not
  computed here) · tool-surface: pure UI · buildable now.

### Business Profile Editing
- **Owner-only edit of the fields that reach a caller's ear** — every human-backed leader (Ruby, Smith.ai) draws a
  hard line between what receptionists can say (business name, description, hours) and account/billing fields,
  and restricts who can change the former · seen in: Ruby ("company profile" is read-only in-app, changes go
  through support — i.e., even *more* locked down than a self-service form), Calendly (org settings restricted to
  owners/admins) · priority: table-stakes · model: uses `tenants.Tenant` (the two fields that actually feed spoken
  content given the current schema are **`name`** and **`timezone`** — see below) · realtime: post-call · tool
  surface: pure UI, gated by `tier_required('owner')` · buildable now.
- **Fields Ruby/Smith.ai/Rosie/Goodcall capture that THIS schema does not have** — company description ("what we
  do", used by the agent to answer "what does your company do?"), published phone number/fax, website URL,
  industry/vertical (used to select a starter prompt template), default language/locale. Every one of these is a
  real, researched, spoken-to-caller field · seen in: Ruby (description, published number, fax, website), Rosie
  and Goodcall (industry, services blurb pulled from Google Business/website) · priority: common (not
  REQUIRED — the product functions without them, but a caller asking "what do you do?" or "what's your website"
  has nowhere for the agent to get an answer) · model: **none exist on `tenants.Tenant`** — flagged explicitly per
  the hard constraint: this is a **small additive field change** (e.g. `description` Text blank, `website` URLField
  blank), NOT buildable in this pass because the model is frozen at 11 and this pass ships zero migrations ·
  realtime: n/a until added · tool-surface: n/a · **deferred** (see Deferred section — do not add in this pass).
- **Locked/support-only identifiers vs. self-service identifiers** — Ruby explicitly will not let a customer
  self-edit certain identity fields in-app ("It's not currently possible to update your company information from
  the app... contact support"), precisely because those fields are load-bearing for how the business is resolved
  · seen in: Ruby · priority: table-stakes (informs a design decision, not a new field) · model: applies to
  `tenants.Tenant.customer_id` and `slug` — **recommend both read-only in the owner form** (see Recommended build
  scope) · realtime: post-call · tool-surface: pure UI · buildable now (it's a form-field-inclusion decision, no
  schema change).

### Tenant Activation State
- **Suspension is a platform action, not tenant self-service** — every multi-tenant SaaS precedent surveyed
  (Entra tenant blocks, AWS account-lifecycle tagging) treats "this tenant is disabled" as something the
  **platform operator** flips, never something the tenant's own owner can toggle on themselves, because a
  self-service off-switch is an accidental-lockout footgun with no support path back in for that same owner ·
  seen in: AWS/Microsoft multi-tenant lifecycle guidance (pattern, not a receptionist product feature per se) ·
  priority: table-stakes (this is the correct authorization posture, not optional) · model: reuses
  `tenants.Tenant.is_active` · realtime: post-call · tool-surface: pure UI — **read-only status badge** in the
  owner-facing settings page; the field stays editable only through the existing Django admin (`TenantAdmin`,
  already built, superuser-only) · buildable now.
- **"Blocked at login, not mid-call" is already enforced** — confirmed built in Module 0.1
  (`backends.py:81`, `Auth.py:180` both filter `tenant__is_active=True` before authentication succeeds). 1.1 adds
  no new gate; it only **surfaces** the current value so an owner can see why, e.g., a teammate reports being
  unable to log in · seen in: n/a (internal repo finding, cross-checked against the AWS/Microsoft precedent that
  status should be visible to the tenant, not just enforced silently) · priority: table-stakes · model: reuses
  `tenants.Tenant.is_active` (read) · realtime: post-call · tool-surface: pure UI · buildable now.

### Beyond the bullets
- **Read-only account snapshot on the settings page** — location count, active-agent count (once Module 2 ships)
  give an owner an at-a-glance summary alongside the editable fields, a pattern every dashboard-style leader
  (Smith.ai, Goodcall) uses on its account/overview screen · seen in: Smith.ai dashboard, Goodcall dashboard ·
  priority: common · model: **pure aggregate query** over `tenants.Location.objects.filter(tenant=...)` — no new
  field, no new model · realtime: post-call · tool-surface: pure UI · buildable now (location count only; agent
  count is Module 2's table and isn't queryable yet — omit that stat until 2.1 ships, don't stub it).
- **Slug shown as a read-only technical identifier** — not yet consumed anywhere in the routing layer (verified:
  zero references outside `models/Tenant.py` and `admin.py`), so exposing it as editable now would let an owner
  change a value nothing currently reads, while risking collision with whatever later feature (a public booking
  slug, e.g.) eventually does read it · seen in: n/a (repo-grounded, not a competitor pattern) · priority: common
  · model: reuses `tenants.Tenant.slug`, **read-only** in this form · realtime: post-call · tool-surface: pure UI
  · buildable now.

## Compliance & provider constraints

- **No recording/telephony consent surface here.** 1.1 has no call-audio, no LLM token spend and no PROVIDER_MODE
  concern of its own — it is a plain settings form over an existing row. The REQUIRED compliance items in this
  product (recording consent basis, two-party-consent announcement, HIPAA/GDPR retention) attach to
  `calls.CallSession` and `agents.AgentSetting` (Modules 2, 3, 5), not to `tenants.Tenant`.
- **The one compliance-adjacent finding that DOES apply here:** `customer_id` is the tenant-resolution key used at
  authentication (`accounts.backends`). Treating it as freely editable by the tenant owner is a **self-lockout and
  support-burden risk** analogous to why Ruby locks its own equivalent fields — recommend **read-only** in this
  sub-module's form, changeable only via Django admin (already built, superuser-gated) until/unless a future
  sub-module adds a guarded "regenerate customer ID" flow with re-confirmation. This is a design recommendation,
  not a legal requirement, so it is `table-stakes` priority above, not `REQUIRED`.
- **No Twilio/STT/TTS/LLM cost lines originate in this sub-module.** `calls.CallSession.usage` is untouched by
  1.1 — this page has no realtime hot path and appends nothing to any per-call cost ledger.

## Recommended build scope (this pass)

**CRUD sub-module — but the "CRUD" here is a single always-existing row, not a list.** Per the authorization note
in the task: there is exactly one `Tenant` row per business and `request.tenant` IS it, so this sub-module ships
**no list page, no create view, no delete view, and no pk in the URL** — the CRUD-completeness rule's "every list
model needs list/create/detail/edit/delete" does not apply here because there is no list. What it ships instead:

- **`tenants.Tenant` (existing model, zero migrations)** — **tenant-scoped by definition (it IS the tenant, no
  `tenant` FK)**. One view pair only:
  - `business_settings_view` (GET) — read-only detail/overview: `name`, `customer_id` (read-only), `slug`
    (read-only), `timezone`, `is_active` status badge (read-only), `created_at`, plus the location-count
    aggregate. Route: `tenants:business_settings` (no pk).
  - `business_settings_edit_view` (GET renders form / POST saves) — a plain `django.forms.ModelForm` (not
    `TenantModelForm`, since `Tenant` has no `tenant` FK to stamp) bound to `Meta.fields = ['name', 'timezone']`
    only. `slug`, `customer_id` and `is_active` are **excluded from `Meta.fields` entirely** — never rendered,
    never accepted from POST, consistent with the "server owns what the client may write" posture applied
    elsewhere in this app to secrets. Route: `tenants:business_settings_edit`. Gated by `tier_required('owner')`.
  - No `business_settings_delete_view` — deleting the single business record is out of scope for a tenant owner
    in any SaaS surveyed; that action (if it ever exists) is a platform-operator/billing action, not this
    sub-module's job.
- Fields justified by research: `name` → Business Record + Business Profile Editing (spoken identity); `timezone`
  → Business Record (scheduling default, Calendly/Ruby precedent); `customer_id`, `slug`, `is_active` → displayed
  per Business Record / Tenant Activation State but **read-only**, justified by the Ruby "locked support-only
  identifier" pattern and the AWS/Microsoft "suspension is platform-side" pattern.
- **FKs:** none added — `Tenant` carries no FK (it is the isolation root). The location-count stat queries
  `tenants.Location` (verified-existing, 1.2's model) read-only, with no write path from this sub-module.

## Belongs to sibling sub-modules (parked, not scoped here)

- Location name/slug/address/timezone/phone CRUD, list + search + active filter → **1.2** (Location Directory)
- Assigning users to locations, provider marking → **1.3** (Staff & Location Assignment)
- Per-provider weekly working-hour intervals → **1.4** (Provider Working Hours)
- Agent greeting, system prompt, `{{variable}}` map, per-location Twilio credentials and inbound number →
  **2.1/2.2** (Agent Setup & Telephony) — this is where "business facts reach the live call" actually gets wired,
  not here. 1.1 only stores the facts; Module 2 renders them into the prompt/greeting.
- Transfer settings (hours, keywords, secondary number) → **2.3**
- Call-recording consent basis/disclosure, HIPAA/GDPR retention → **Module 3 (runtime)** and **Module 5 (calls)**,
  since consent is recorded per-recording on `calls.CallSession`, not per-tenant.

## Out of scope for this product (outside the seven capabilities)

- **Company logo / visual branding upload** (Calendly org branding) — this product has no caller-facing web page
  or booking widget to brand; branding a phone call is the greeting text (Module 2), not an image asset.
- **CRM/PMS integration hub, 7,000+ tool integrations** (Smith.ai) — outside the seven capabilities; this product
  is not an integration platform.
- **Billing/subscription/plan tier management** (Goodcall's per-plan caller limits, Rosie's subscription tiers) —
  no billing capability exists in this product's seven capabilities; `is_active` here is a binary access gate, not
  a plan/usage-limit system.
- **Multi-workspace / multi-organization switcher** (Retell's "switch between workspaces") — this product's
  isolation unit is the location switcher (built in 0.4), not a workspace switcher; a user belongs to one tenant.
- **FAQ knowledge-base authoring** (Rosie, Goodcall) — this is prompt-content authoring, which belongs to Module
  2's prompt/variables surface, not a tenant-level "FAQ" field.

## Deferred (later passes / integrations)

- **`Tenant.description` (Text, blank) and `Tenant.website` (URLField, blank)** — researched, real, spoken-to-caller
  fields (Ruby's "company description", Goodcall/Rosie's business summary) that a caller-facing agent would
  eventually reference ("what do you do", "what's your website"). Deferred because they require an **additive
  migration**, which this pass explicitly must not ship (zero-migration hard constraint). Flagged here so a later
  pass doesn't have to re-research it — if added, they belong on `Tenant` (tenant-wide) and become new
  prompt-variable inputs for Module 2, not new tool-surface.
- **`Tenant.default_language` / locale** — same additive-migration reasoning; deferred until there is a
  multi-language prompt/voice feature to justify it (Module 2 territory).
- **Self-service "regenerate customer ID" flow with re-confirmation** — deferred; today `customer_id` is
  Django-admin-only, which is sufficient for a first pass and avoids building a lockout-recovery flow this pass
  has no budget for.
- **Tenant-level "danger zone" (deactivate own account, export data, delete business)** — deferred indefinitely;
  every SaaS precedent treats this as a platform-operator action gated behind support/billing, not a self-service
  control, and this product has no such workflow to hang it off yet.
