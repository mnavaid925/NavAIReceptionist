# NavAIReceptionist — Module Catalog

NavAIReceptionist is a multi-tenant SaaS AI voice agent that answers every inbound call within seconds, 24/7/365, follows up with new leads by voice and SMS, qualifies prospects against tenant-defined criteria, and books appointments directly into live calendars. Every tenant configures its own agents, numbers, knowledge, hours, transfer targets and compliance policy; the platform meters, audits and isolates all of it.

**Stack.** All-Django: Django 5.1 + Channels/ASGI for the realtime telephony media-stream websocket, Tailwind + HTMX + Lucide for the UI, MySQL for storage, strict tenant-FK scoping on every model and every queryset. There is no separate microservice. Each module is a Django app under `apps/<slug>`, and anything touching websockets is served over ASGI (`daphne … config.asgi:application`), never `manage.py runserver`.

**How to use this catalog.** It is the master build sequence and the scope authority for the whole build. Modules are numbered `N`, sub-modules `N.M`; the build runs **one sub-module at a time** through the mandated `research → todo → code → review-agents → skill` sequence, each step ending in its own commit. Module 0 is the cross-cutting foundation and is built first: it owns the **entire core spine** — the shared masters, the append-only interaction and usage ledgers, the compliance gate and the provider adapters that every other module builds on. The spine's intended shape is written out in `NavAIReceptionist-ERD.md`; read it before adding any model or foreign key. Modules 1–13 are ordered so each depends only on what precedes it: telephony before agents, agents before inbound, contacts before campaigns, calls before analytics, compliance early enough that outbound and messaging can lean on it.

**Two rules that shape everything below.** (1) An agent configuration is a *versioned, publishable artifact* — draft → version → publish → compare → rollback — decided in 2.1 and never retrofitted. (2) Compliance (Module 6) ships **before** outbound (Module 8) and messaging (Module 9), because A2P 10DLC registration, TCPA consent and recording consent are hard gates those modules cannot legally or technically clear without.

## Module Index

**Module 0 owns the entire spine; modules 1–13 own domain tables and the UI/engines over them, and never own a spine table.** This table agrees row for row with `NavAIReceptionist-ERD.md` §8 — if the two ever disagree, the ERD's shape is the one to reconcile to.

| # | Module | App slug | Owns (domain tables) | Reads (spine) |
|---|---|---|---|---|
| 0 | System Admin & Security | `core` + `accounts` + `tenants` + `dashboard` | The whole spine (Tiers 0–4), plus `accounts.User`/`Role` and the `tenants` billing models — `Plan`, `Subscription`, `RateCard`, `BillingPeriod`, `Invoice`, `Payment`, `PaymentMethod`, `TaxCode`, `SpendCap` — and the dashboard views; **plus the provider-adapter layer in `apps/core/providers/`** — the telephony/STT/TTS/LLM adapter interfaces, the fakes and `PROVIDER_MODE` resolution. | — (it defines the spine) |
| 1 | Telephony & Number Management | `telephony` | Port-in requests, carrier and SIP credentials, routing maps, per-number overrides, caller-ID reputation records, concurrency policy. | `PhoneNumber`, `TelephonyProvider`, `Tenant`, `Location`, `AgentVersion`, `Interaction` |
| 2 | Voice Agent Studio | `agents` | Prompt sections, escalation and counter rules, guardrail policies, templates and vertical packs, A/B traffic splits. | `Agent`, `AgentVersion`, `Voice`, `Service`, `Location` |
| 3 | Knowledge Base & Business Facts | `knowledge` | Knowledge sources, crawled pages, curated Q&A, ingestion and refresh jobs, retrieval config. | `Location`, `BusinessHours`, `HoursException`, `Service`, `Resource`, `Document`, `Contact` |
| 4 | Realtime Conversation Runtime | `runtime` | The realtime **orchestration** that calls the Module 0 adapters (media-stream consumer, turn loop, VAD/barge-in, audio chain); session state, latency and ended-reason diagnostics, rate-limit and fraud records, `DestinationPolicy`. Writes (never owns) `Interaction`, `InteractionEvent`, `UsageEvent`, `Recording`. **Does not own the provider adapters — those are Module 0, `apps/core/providers/`.** | `AgentVersion`, `PhoneNumber`, `Contact`, `Location` |
| 5 | Inbound Call Handling & Routing | `inbound` | Routing rules, spam allow/block lists, transfer destinations and ring groups, voicemail-box configuration, IVR and DTMF maps, live-monitor views. | `Interaction`, `InteractionEvent`, `Contact`, `PhoneNumber`, `BusinessHours`, `CallbackRequest` |
| 6 | Compliance, Consent & Trust | `compliance` | Disclosure templates, jurisdiction policies, A2P 10DLC brand and campaign registrations, retention policies, the redaction service, subject-rights requests. | `ConsentRecord`, `SuppressionEntry`, `QuietHoursPolicy`, `Recording`, `InteractionEvent`, `AuditLog` |
| 7 | Contacts, Leads & Qualification | `contacts` | Qualification scripts and answers, scoring rules, `PipelineStage` and `ContactPipelineEntry`, saved views, import mappings, segments. | `Contact`, `ContactRole`, `ContactChannel`, `ContactRelationship`, `Interaction`, `Appointment` |
| 8 | Outbound Calling & Campaigns | `campaigns` | Campaigns, cadences, attempt-queue rows, dialer and throughput policy, speed-to-lead triggers, reactivation rules. | `Contact`, `ContactChannel`, `PhoneNumber`, `AgentVersion`, `Interaction`, `check_outbound_allowed()` |
| 9 | Messaging & Missed-Opportunity Recovery | `messaging` | SMS templates, thread and inbox state, opt-in and A2P 10DLC registration records, notification routing rules, follow-up sequences. **Delivery status is not a Module 9 table** — it is `core.Interaction.status` (`queued`, `sent`, `delivered`, `undelivered`, `failed`) plus `provider_webhook` `core.InteractionEvent` rows. | `Interaction`, `InteractionEvent`, `ContactChannel`, `SuppressionEntry`, `check_outbound_allowed()` |
| 10 | Appointments & Scheduling | `scheduling` | Availability rules and blackouts, calendar connections and tokens, slot-token issuance, reminder schedules, waitlist entries. | `Appointment`, `Service`, `Resource`, `Location`, `BusinessHours`, `Contact`, `Interaction` |
| 11 | Call Records, Transcripts & Post-Call Intelligence | `calls` | Dispositions and outcome taxonomy, tags, extraction schemas and extracted values, sentiment and rubric scores, review queue, artifact-delivery log. | `Interaction`, `InteractionEvent`, `Recording`, `UsageEvent`, `AgentVersion` |
| 12 | Testing, QA & Analytics | `analytics` | Test-call sessions, simulated-caller scenarios and runs, QA cohorts and scorecards, saved reports, alert rules and incidents. | `Interaction`, `InteractionEvent`, `UsageEvent`, `Appointment`, `AgentVersion`, `Contact` |
| 13 | Integrations, API & Onboarding | `integrations` | Webhook endpoints and delivery log, CRM and calendar connectors and field maps, API keys and quotas, widget config, onboarding wizard state, vertical packs. | Effectively all spine tables, read-only and permission-scoped |

---

## 0. System Admin & Security

### 0.1 Tenant & Workspace Management
- **Tenant Provisioning** — Creates an isolated tenant with slug, timezone, locale and default admin, seeding baseline config so the workspace is usable immediately.
- **Business & Location Records** — Stores legal/trading name, industry, address, service area and timezone, with per-location overrides for multi-site and franchise tenants.
- **Agency & Sub-Account Hierarchy** — Lets an agency workspace own many client tenants with strict data isolation and cross-tenant roll-up reporting.
- **White-Label Branding** — Applies per-tenant logo, colours, sender names and custom domain so the dashboard and notifications carry the agency's brand.
- **Tenant Lifecycle States** — Moves a tenant through trial, active, past-due, suspended and closed, with defined behaviour for live calls in each state.
- **Data Residency & Isolation Policy** — Records the tenant's storage region and enforces tenant-FK scoping as a queryset-level default across every app.

### 0.2 Subscription, Plans & Billing
- **Plan Catalog** — Defines plans with included voice minutes, SMS volume, concurrency ceiling, agent count and feature flags.
- **Subscription Management** — Handles signup, upgrade, downgrade, proration, pause and cancellation with an effective-dated change history.
- **Payment Method & Invoicing** — Stores tokenized payment methods via the payment processor and issues invoices with per-tenant billing statements.
- **Overage & Top-Up Handling** — Prices usage beyond plan allowances and supports prepaid minute top-ups with a configurable auto-recharge threshold.
- **Dunning & Grace Periods** — Retries failed payments on a schedule and degrades service gracefully rather than dropping live calls without warning.
- **Agency Pool Allocation** — Lets an agency distribute pooled minutes and SMS across its sub-accounts with per-account visibility and caps.

### 0.3 Usage Metering & Cost Control
- **Per-Call Cost Ledger** — Records STT seconds, LLM input/output tokens, TTS characters and telephony minutes per call as the call proceeds.
- **Usage Aggregation** — Rolls per-call cost lines into daily and monthly per-tenant totals for billing, margin analysis and plan-fit reporting.
- **Spend Ceilings & Auto-Suspend** — Enforces a per-tenant hard spend cap that suspends outbound and optionally inbound before a runaway bill accrues.
- **Concurrency Quota Enforcement** — Caps simultaneous calls per tenant with reserved headroom so one tenant's spike cannot starve another.
- **Margin & Unit-Economics View** — Surfaces cost per call, cost per booked appointment and cost per qualified lead for the platform operator.

### 0.4 Identity, Access & RBAC
- **User Accounts & Invitations** — Manages tenant-scoped users with email invitation, activation and deactivation flows.
- **Role Definitions** — Ships owner, manager, agent and read-only roles governing who can edit agents, hear recordings and see caller PII.
- **Permission Enforcement** — Applies object-level permission checks in views and templates so restricted users never see or reach forbidden actions.
- **Multi-Factor Authentication** — Offers TOTP and enforced MFA for owner and manager roles on a per-tenant policy.
- **Session & Device Management** — Lists active sessions with last-seen device and IP, and allows remote revocation.
- **SSO / SAML Connection** — Connects an enterprise identity provider with just-in-time user provisioning and role mapping.

### 0.5 Audit, Security & Access Logging
- **Immutable Audit Trail** — Records who changed which record, from which IP, with a before/after diff on every configuration object.
- **PII & Recording Access Log** — Logs every view, playback or download of a recording, transcript or contact PII field, with the actor and timestamp.
- **Agent Configuration History** — Tracks prompt, greeting, voice and routing changes so any call can be traced to the exact config that handled it.
- **Security Event Monitoring** — Flags failed logins, permission-denied bursts, API-key abuse and anomalous export volume.
- **Encrypted Credential Vault** — Stores carrier, CRM and calendar credentials encrypted at rest with rotation and last-used tracking.

### 0.6 Platform Health & Admin Dashboard
- **Tenant Health Scoring** — Combines call volume trend, containment rate, error rate and login recency into a churn-risk signal per tenant.
- **Operator Console** — Gives platform staff a cross-tenant view of live calls, queue depth, provider status and recent failures.
- **Impersonation with Consent** — Allows scoped support impersonation of a tenant user, fully audited and time-limited.
- **Provider Status Board** — Monitors carrier, ASR, LLM and TTS provider availability and latency, with automatic incident banners.
- **Background Job Monitor** — Shows queue depth, retries and dead-lettered tasks for analysis, notification and sync workers.
- **Tenant Dashboard Home** — Presents each tenant's own today-view: calls answered, leads captured, bookings made and items needing attention.

---

## 1. Telephony & Number Management

### 1.1 Phone Number Inventory & Provisioning
- **Number Search & Purchase** — Searches available local and toll-free numbers by area code and provisions them to the tenant in one step.
- **Existing Number Import** — Imports a tenant's own Twilio or Telnyx number by SID and credentials without repurchasing it.
- **Port-In Workflow** — Tracks a number port with LOA upload, carrier status timeline and scheduled cutover date.
- **Number Release & Reassignment** — Releases, parks or reassigns a number, blocking release while it still carries live routing.
- **Number Tagging & Purpose** — Labels each number as main line, tracking/marketing source, department or location for attribution and reporting.

### 1.2 Carrier & SIP Connectivity
- **Carrier Account Registration** — Stores per-tenant carrier credentials encrypted, or uses the platform-managed carrier account.
- **BYO SIP Trunk** — Connects a tenant's existing SIP trunk with credentials, allowed IP ranges and codec preferences.
- **SIP Header Passthrough** — Reads and writes custom SIP headers so upstream phone systems can hand context to the agent.
- **Trunk Health & Failover** — Health-checks trunks and fails over to a secondary carrier on registration or media failure.
- **Contact-Centre Connectors** — Provides connector profiles for Genesys, Five9 and Amazon Connect for queue-overflow deployments.

### 1.3 Inbound Webhook & Media Bridge Entry
- **TwiML Voice Webhook** — Answers the carrier's inbound webhook and returns the media-stream connect instruction with per-call parameters.
- **Signature Verification** — Validates the carrier request signature against the resolving tenant's auth token before accepting the call.
- **DID Resolution** — Resolves the dialed number to tenant, location and enabled agent version before any media flows, hanging up cleanly on an unmapped number.
- **Public URL Derivation** — Derives the exact signed callback and websocket URLs behind proxies and tunnels so signature checks never falsely fail.
- **Unserviceable-Number Handling** — Plays a defined out-of-service message and terminates rather than dropping the caller into silence.

### 1.4 Number-to-Agent Routing Map
- **Agent Binding** — Binds each inbound number to a published agent version, an hours schedule and a guaranteed fallback destination.
- **Per-Number Overrides** — Overrides greeting, language and transfer targets on a single number without cloning the agent.
- **Location Routing** — Routes multi-location tenants so each site's number reaches its own staff, calendar and knowledge.
- **Pre-Answer Hook** — Fires a number-level webhook before the agent answers, enabling spam rejection or CRM context lookup.
- **Routing Change Audit** — Shows a full history of routing changes with actor, timestamp and previous destination.

### 1.5 Caller ID Reputation & Branded Calling
- **Business Profile Registration** — Registers legal name, EIN, address and use case with carriers for verification.
- **Branded Caller ID** — Displays the business name instead of a bare number on outbound calls where carriers support it.
- **Spam-Rejection Detection** — Detects SIP 608 and equivalent carrier rejections and flags the affected number as reputation-damaged.
- **Reputation Monitoring** — Polls third-party reputation services and surfaces a health score per number over time.
- **Remediation Workflow** — Drives re-registration, delisting requests or number rotation when a number is flagged.

### 1.6 Concurrency, Capacity & Overflow
- **Concurrency Ceiling** — Enforces the tenant's plan concurrency limit at call-accept time.
- **Overflow Behaviour** — Defines what happens at the ceiling: queue, forward to a human line, or take a message.
- **Live Capacity View** — Shows current concurrent calls and a historical peak-usage chart per tenant and per number.
- **Capacity Alerting** — Warns the tenant and the operator when sustained usage exceeds a configurable share of the ceiling.
- **Burst Reservation** — Reserves headroom per tenant so cross-tenant contention cannot cause a rejected inbound call.

---

## 2. Voice Agent Studio

### 2.1 Agent Definition & Versioning
- **Agent Record** — Creates a named agent with persona, business context, agent name and closing behaviour, scoped to a tenant and location.
- **Draft / Published Versions** — Keeps an editable draft and immutable published versions so a prompt edit can never silently change live call behaviour.
- **Version Comparison & Rollback** — Diffs any two versions field by field and restores a previous version in one action.
- **Publish Gating** — Blocks publishing until the version has passed a successful test call and a compliance check.
- **Agent Cloning** — Clones an agent from another agent or a vertical pack as a starting point.
- **Live Assignment History** — Records which version was live on which number at any point in time, so every call is traceable to its config.

### 2.2 Prompt Authoring & Variables
- **Structured Prompt Editor** — Edits the system prompt in sections for role, rules, escalation policy and refusal behaviour, with a length and readability guide.
- **Prompt Variable Rendering** — Resolves whitespace-tolerant `{{variable}}` placeholders against a merged variable dictionary at call setup.
- **Reserved Runtime Variables** — Injects caller number, dialed number, location name and address, business-local date and time, and a server-computed open/closed literal that tenant variables can never shadow.
- **Save-Time Placeholder Validation** — Rejects unknown placeholders on save and previews the fully rendered prompt, so a typo can never blank out a sentence at runtime.
- **Capability-Aware Prompt Assembly** — Composes the prompt's capability statements from the enabled tool set, so the agent never offers SMS or booking a tenant has disabled.
- **Default Prompt Inheritance** — Leaves the prompt null to inherit the maintained platform default, giving tenants improvements without re-editing.

### 2.3 Deterministic Greeting & Opening
- **Zero-Latency Greeting** — Speaks a rendered, pre-authored greeting without an LLM round trip so first audio lands immediately.
- **Greeting Fallback** — Falls back to a safe generated line when the configured greeting renders empty.
- **Non-Interruptible Opening** — Marks the greeting as uninterruptible so the disclosure and business name always reach the caller in full.
- **Time-of-Day Variants** — Selects distinct greetings for open hours, after hours, weekends and holidays.
- **Known-Caller Personalisation** — Uses a recognised contact's name in the opening when caller memory returns an unambiguous match.

### 2.4 Voice, Speech & Language Settings
- **Voice Selection & Preview** — Picks a platform voice per language with in-browser preview before publishing.
- **Brand Voice Cloning** — Uses a cloned owner or brand voice where the provider and tenant plan allow it.
- **Automatic Language Detection** — Detects the caller's language mid-call and switches to a localised voice without a menu prompt.
- **Pronunciation Dictionary** — Forces correct pronunciation of business names, staff names, streets and domain terms.
- **Speech Style Controls** — Tunes pacing, filler pauses, backchannel acknowledgements and expressiveness per agent.
- **Provider Fallback Chain** — Fails over to a secondary TTS or ASR provider on error or timeout so a call never dies mid-sentence.

### 2.5 Tools, Functions & Dispatcher
- **Provider-Agnostic Tool Declarations** — Defines the callable surface as plain JSON-schema dictionaries so the LLM provider can be swapped without touching domain code.
- **Built-In Tool Set** — Ships identify contact, search contact, create contact, get availability, book, reschedule, cancel, callback request, send SMS, get business info, transfer and end call.
- **Transport-Agnostic Dispatcher** — Applies every tool through a single `(state, name, args)` dispatcher shared by the turn-based and realtime paths, so invariants can never drift between them.
- **Server-Side Identity Injection** — Injects tenant, contact and location ids from server-held session state rather than accepting them as model arguments.
- **Standard Result Envelope** — Returns every tool result in one `{"ok": bool, "data": {...}, "error": {"code": "...", "message": "..."} | null}` shape, with `code` always lower_snake_case from a closed set, so success detection and logging are uniform.
- **Custom HTTP Tools & MCP** — Lets a tenant register its own HTTP endpoints or an MCP server as additional tools with auth, timeout and retry policy.

### 2.6 Guardrails & Behaviour Policy
- **Grounded-Answer Restriction** — Restricts answers to approved knowledge with a configurable refusal-and-escalate line when the answer is unknown.
- **Honest-AI Guardrail** — Forces a truthful answer whenever the caller asks whether they are speaking to a bot, non-overridable by tenant prompt text.
- **No-Invented-Availability Rule** — Blocks the agent from stating any time, staff member or resource that did not come back from a lookup in this call.
- **Confirmed-Before-Claimed Rule** — Prevents the agent from saying booked, cancelled or changed until the tool returned a confirmed record.
- **Topic Blocklist & Handoff** — Routes legal, medical and financial advice requests to a human instead of answering.
- **Call Limits & Abuse Handling** — Enforces max call duration, silence timeout, profanity handling and automatic termination for looping abusive callers.

### 2.7 Escalation & Deterministic Counters
- **Failure & Repeat Counters** — Counts failed lookups, repeated caller intents and tool errors in session state rather than relying on the model to notice.
- **Deterministic Escalation Triggers** — Forces a callback or transfer once a counter crosses its threshold, independent of model judgement.
- **Urgent-Intent Rules** — Matches tenant-defined urgent keywords with distinct open-hours and closed-hours actions, replacing hardcoded vertical logic.
- **Sentiment Escalation** — Escalates on detected frustration or sustained negative sentiment mid-call.
- **Escalation Rule Testing** — Simulates a transcript against the rule set and shows exactly which rule would fire and why.

### 2.8 Agent Templates & A/B Testing
- **Vertical Starter Packs** — Provides prebuilt agents for clinics, salons, law firms, home services, property management and real estate.
- **Tenant Template Library** — Saves a tuned agent back to the tenant's private template library for reuse across locations.
- **Traffic Splitting** — Splits inbound traffic across two published versions by percentage.
- **Version Outcome Comparison** — Compares containment, transfer, booking and sentiment metrics between the split versions.
- **Winner Promotion** — Promotes the winning version to full traffic in one action with an audit entry.

---

## 3. Knowledge Base & Business Facts

### 3.1 Business Profile, Hours & Staff
- **Hours & Holiday Calendar** — Defines weekly opening hours, holidays and blackout dates per location in the location's timezone.
- **Server-Computed Open State** — Computes an authoritative open/closed value server-side and injects it as a literal, never letting the model derive it from the clock.
- **Staff & Department Directory** — Lists staff and departments with roles, extensions and transfer numbers for routing and booking.
- **Location Overrides** — Applies per-location hours, numbers, staff and knowledge under one brand.
- **Business Info Tool Surface** — Exposes hours, address, directions and parking to the agent as a single structured lookup.

### 3.2 Knowledge Sources & Ingestion
- **Website Crawl Seeding** — Builds a working knowledge base from a single URL by crawling pages, services, FAQs and prices.
- **Business Listing Import** — Ingests the Google Business Profile for hours, address, services and review context.
- **Document Upload** — Accepts PDF, Word, spreadsheet and image files with enforced per-file size and per-base count limits.
- **Manual Text Snippets** — Captures facts that appear nowhere on the website as short curated snippets.
- **Ingestion Status View** — Shows page counts, errors and last-fetched timestamps per source so a tenant can see what the agent actually knows.

### 3.3 Refresh, Crawl & Sync
- **Scheduled Auto-Refresh** — Re-fetches all URL sources on a fixed cycle so pricing and hours answers never go stale.
- **Auto-Crawl Discovery** — Periodically discovers new pages under configured paths while honouring an exclusion list.
- **Manual Re-Sync** — Re-fetches a single source on demand after a website change.
- **Change Diff View** — Shows what changed on the last refresh and which stored answers it affects.
- **Refresh Pause** — Suspends auto-refresh per source while a tenant rebuilds its website.

### 3.4 FAQ & Answer Curation
- **Curated Q&A Pairs** — Stores tenant-authored answers that take precedence over crawled content.
- **Unanswered-Question Harvesting** — Surfaces questions from real calls the agent could not answer as suggested FAQ entries.
- **Review Queue** — Lets a tenant approve, edit or reject suggested entries before they go live.
- **Effective-Dated Answers** — Applies seasonal answers such as holiday hours only within their date window.
- **Bulk Import & Export** — Imports and exports FAQ pairs as CSV for offline editing.

### 3.5 Services, Pricing & Retrieval
- **Service Catalogue** — Defines bookable services with duration, buffer, price or range, and eligible resources.
- **Default New-Contact Service** — Sets the service assumed for a first-time caller so the agent need not ask an unnecessary question.
- **Scoped Retrieval** — Attaches knowledge bases at agent level and at individual topic or flow-node level for focused grounding.
- **Retrieval Preview** — Types a question and shows the exact passages the agent would ground its answer on.
- **Quote-Only Marking** — Marks price and policy answers as non-binding so the agent never commits the business to a figure.

---

## 4. Realtime Conversation Runtime

### 4.1 Media Session & Channels Bridge
- **ASGI Media Consumer** — Terminates the carrier's bidirectional media websocket in a Channels consumer holding all per-call state.
- **Non-Blocking Turn Dispatch** — Dispatches each turn as a background task so long LLM or tool work never stalls subsequent audio frames.
- **Session Lifecycle States** — Persists ring, answer, active, hold, transfer and end transitions with timestamps.
- **Reconnection & Buffer Recovery** — Recovers gracefully from transient websocket drops without losing captured audio.
- **Guaranteed Teardown** — Finalises recording, flushes the transcript and enqueues analysis even on abnormal termination.

### 4.2 Audio Codec & Framing
- **μ-law Transcoding** — Converts carrier μ-law 8 kHz to PCM for the speech pipeline and back for playback.
- **Persistent Resampler State** — Threads resampler state across frames so no audible artefact appears at frame boundaries.
- **Paced Outbound Framing** — Emits outbound audio in real-time-paced frames so playback can be cancelled instantly on interruption.
- **Played-Audio Accounting** — Records only the audio actually played into the call recording so the two channels stay time-aligned after an interruption.
- **Stereo Call Recorder** — Writes caller and agent audio on separate channels for clean QA playback and diarisation.

### 4.3 Speech Pipeline Orchestration
- **Pluggable Provider Modes** — Selects per agent between turn-based STT→LLM→TTS and end-to-end realtime speech-to-speech.
- **Off-Loop Model Calls** — Runs blocking SDK and ORM work off the event loop so one call can never freeze another on the same worker.
- **Streaming Partial Transcripts** — Feeds partial recognition into the model to cut perceived response latency.
- **Keyword & Vocabulary Boosting** — Boosts staff names, service names and domain terms for transcription accuracy.
- **Per-Turn Cost Capture** — Records STT seconds, token counts, TTS characters and model name for every turn.

### 4.4 Turn-Taking, VAD & Barge-In
- **Energy Voice Activity Detection** — Detects utterance start and end using tuned energy, minimum-speech and end-silence thresholds.
- **Pre-Roll Buffering** — Retains a bounded window of pre-speech audio so the first syllable is never clipped, while capping memory on a silent line.
- **Sustained-Speech Barge-In** — Interrupts agent playback only after sustained caller speech past a grace window, so a cough or click cannot cut the agent off.
- **Echo Suppression** — Suppresses listening during and briefly after agent playback so the agent's own audio never registers as caller speech.
- **Pending-Utterance Queue** — Queues an utterance captured during a busy turn and processes it after, rather than dropping it.
- **Idle & No-Response Behaviour** — Speaks a configured idle prompt after silence and ends the call after a bounded no-response period.

### 4.5 Turn Loop & Tool Iteration
- **Bounded Tool Iteration** — Caps tool calls per turn and always emits a spoken fallback rather than leaving the caller in silence.
- **Multi-Tool Turn Handling** — Applies multiple tool calls in one turn with precondition guards on every state-dependent tool.
- **Filler Speech Policy** — Speaks a short holding line only when a genuinely slow lookup is starting, never as a standalone stall.
- **Conversation History Management** — Trims or summarises history on long calls so token cost and latency do not grow superlinearly.
- **Per-Turn Variable Refresh** — Recomputes time-sensitive variables each turn so a long call or a midnight crossing never leaves a stale date.

### 4.6 Deferred Transport Actions
- **Deferred Transfer Signal** — Sets a pending-transfer flag that the transport executes only after the acknowledgement audio has fully played.
- **Playback Drain Delay** — Waits a short interval after speaking a handoff line so the carrier buffer drains before the redirect.
- **Playback Cancellation** — Drops queued agent audio before speaking a transfer or handoff line.
- **Explicit End-Call Tool** — Ends the call deterministically for voicemail, do-not-call and wrong-number outcomes instead of waiting on a silence timeout.
- **Single-Fire Transfer Guard** — Marks a transfer as initiated before any await so concurrent turns cannot double-execute it.

### 4.7 Reliability & Diagnostics
- **Per-Call Latency Breakdown** — Attributes latency to ASR, LLM, tool and TTS stages with estimated-versus-actual comparison.
- **Ended-Reason Codes** — Standardises hangup and failure causes across carrier, provider and application terminations.
- **Runtime Error Surface** — Shows per-call runtime errors on the call detail page rather than only in server logs.
- **Transfer-Drop Diagnostics** — Identifies precisely where a failed bridge broke on a transfer leg.
- **Packet Capture Retention** — Retains packet-level capture for escalated call-quality investigations under an operator-only policy.

### 4.8 Fraud & Abuse Protection
- **Per-Caller Rate Limiting** — Limits repeat calls from one number to stop an attacker looping the agent to burn minutes.
- **Destination Policy** — Allows or denies transfer and dial-out destinations by country code or dial prefix through `runtime.DestinationPolicy`, purely as toll-fraud and traffic-pumping protection; it is not a consent or DNC list and must never be consulted for consent.
- **Cost Anomaly Detection** — Detects sudden spikes in volume, duration or spend and alerts before the bill lands.
- **Automatic Caller Suppression** — Suppresses abusive callers by writing a `core.SuppressionEntry` row, with a manual review and release queue, rather than keeping a second blocklist in the runtime.
- **Session Duration Caps** — Enforces a maximum call length and a short no-audio timeout so hung sessions cannot burn channels.

---

## 5. Inbound Call Handling & Routing

### 5.1 Greeting, Intent & Caller Identification
- **Caller Lookup by Number** — Identifies the caller from the inbound number and loads prior context before the first question.
- **Intent Classification** — Classifies the call into tenant-defined categories such as new booking, existing customer, sales, vendor or emergency.
- **Caller vs Subject Separation** — Tracks the person calling and the person being booked as distinct contacts for third-party bookings.
- **Ambiguity Resolution** — Searches by name plus a tenant-configured secondary identifier and binds identity only on an unambiguous single match.
- **Required Detail Capture** — Captures and reads back caller name and callback number on every call for the record.

### 5.2 Spam & Robocall Screening
- **Behavioural Screening** — Ends or diverts suspected robocalls before any staff member or notification is involved.
- **Allow & Block Lists** — Maintains per-tenant number, prefix and caller-name lists with precedence over behavioural rules.
- **Pre-Answer Rejection Hook** — Calls an external reputation service before media connects and rejects the call if it scores as spam.
- **Silent-Caller Detection** — Terminates calls with no speech after a configurable timeout, recording the reason.
- **Blocked-Call Audit** — Logs every screened call with its reason so tenants can review and correct false positives.

### 5.3 Routing Rules & Schedules
- **Rule Builder** — Routes by intent, caller type, time of day, weekday, language or location with drag-to-reorder priority.
- **First-Match Evaluation** — Evaluates rules first-match-wins with a live simulator showing where a given caller would land.
- **After-Hours Behaviour** — Selects the closed-hours mode per tenant: book-only, message, callback request or forward.
- **Emergency Bypass Path** — Routes tenant-defined urgent situations straight to an on-call destination regardless of hours.
- **Guaranteed Fallback** — Enforces a default destination on every rule set so no call can fall through unhandled.

### 5.4 Transfer & Escalation
- **Warm Transfer with Whisper** — Holds the caller, dials the target, plays a private context briefing, then bridges the two legs.
- **Human-Answer Detection** — Confirms a live person answered before whispering or bridging, branching if voicemail picked up.
- **Hours-Gated Human Transfer** — Permits human transfer only inside configured transfer hours, with a defined message when outside.
- **Language & Department Routing Table** — Maps detected language and classified department to specific destinations, with language handoff available regardless of hours.
- **Ring Groups & Sequential Hunt** — Tries multiple targets in order or in parallel with per-target timeout and a no-answer fallback.
- **Transfer Outcome Recording** — Records every transfer attempt with reason, destination and outcome including unavailable, off-hours, connected and failed.

### 5.5 Voicemail, Messages & Callbacks
- **Structured Message Taking** — Collects required fields such as name, number, reason and urgency instead of an unstructured voicemail.
- **Voicemail Recording & Transcription** — Records and transcribes audio messages when the caller prefers to speak freely.
- **Callback Request Queue** — Creates prioritised callback records with due-by times calculated against business hours.
- **Assignment & Resolution** — Assigns callbacks to staff with status, notes and a resolved timestamp.
- **Delivery & Unread Escalation** — Tracks whether a message was seen and escalates unread urgent items.

### 5.6 In-Call Controls & Live Monitoring
- **DTMF Capture** — Accepts touch-tone digits for account numbers, extensions and confirmations.
- **Outbound IVR Navigation** — Presses digits when the agent must navigate an external phone menu on a transfer or callback leg.
- **Hold & Wait Behaviour** — Manages hold state and hold audio while a slow tool call completes.
- **Live Call Board** — Displays active calls with running transcript for supervisors.
- **Listen-In & Takeover** — Lets an authorised human monitor and then seize an in-progress call.

---

## 6. Compliance, Consent & Trust

### 6.1 AI Disclosure
- **Mandatory Disclosure Line** — Plays a clear notice that the caller is speaking with an AI as part of the greeting.
- **Jurisdiction Templates** — Selects disclosure wording by tenant and caller jurisdiction, defaulting to the strictest applicable rule.
- **Non-Removable Enforcement** — Blocks publishing any agent version whose greeting lacks a valid disclosure.
- **Disclosure Playback Logging** — Records on every call that the disclosure was played, as the evidentiary record.
- **Bot-Question Guardrail Binding** — Ties the honest-AI guardrail to this policy so it cannot be disabled per agent.

### 6.2 Recording Consent
- **Pre-Agent Consent Step** — Runs the consent exchange before the main agent and starts the recorder only after consent is granted.
- **Consent Modes** — Supports stay-on-line implied consent and explicit verbal consent that is re-asked until answered.
- **Decline Behaviour** — Configures what happens on refusal: continue unrecorded, transfer to a human, or end the call.
- **Jurisdiction Selection** — Selects the consent policy from the caller's area code, defaulting to all-party consent when uncertain.
- **Immutable Consent Record** — Stores consent type, wording played and grant timestamp per call as an audit artefact.

### 6.3 A2P 10DLC & Messaging Registration
- **Brand Registration** — Registers the tenant's brand with the messaging registry, tracking status and rejection reasons.
- **Campaign Registration** — Registers use case, sample messages and throughput tier per messaging campaign.
- **Send Hard-Block** — Blocks all SMS from any number without an approved campaign, with a clear tenant-facing explanation.
- **Opt-Out Handling** — Processes STOP and equivalent keywords into a `core.SuppressionEntry` row and an opt-out timestamp on the sending `core.ContactChannel`, never into a messaging-owned list.
- **Required Message Elements** — Appends business identification and opt-out language to outbound templates automatically.

### 6.4 TCPA Consent, DNC & Calling Windows
- **Consent Record per Channel** — Writes consent source, exact wording, timestamp and capture channel to `core.ConsentRecord` against the specific `core.ContactChannel` it was given for, since consent is never a single contact-level flag.
- **Marketing vs Transactional Classification** — Classifies each outbound template and campaign so the correct consent bar is applied.
- **DNC Scrubbing** — Loads federal, state and tenant do-not-contact data into `core.SuppressionEntry` so `check_outbound_allowed` scrubs every outbound attempt before dialling, rather than standing up a parallel list.
- **Calling Window Enforcement** — Enforces permitted call and text hours in the recipient's timezone, not the business's.
- **Immediate Revocation** — Honours an opt-out across voice and SMS instantly and halts all queued campaign attempts for that contact.

### 6.5 HIPAA & Sensitive Data
- **Tenant HIPAA Mode** — Enables compliant handling of recordings, transcripts and analysis at the tenant level.
- **BAA Tracking** — Blocks HIPAA mode until a signed business associate agreement is recorded.
- **Approved Subprocessor Enforcement** — Restricts HIPAA tenants to an allow-listed set of ASR, LLM and TTS providers.
- **PHI & PII Redaction** — Redacts sensitive values from transcripts, tool-call argument logs, notifications and webhook payloads.
- **Mode Exclusivity** — Enforces at the model level that HIPAA mode and zero-retention mode cannot both be active.

### 6.6 Data Retention, Access & Subject Rights
- **Per-Tenant Retention Windows** — Purges audio, transcripts and analysis automatically after the configured window.
- **Zero-Retention Option** — Discards call artefacts once the call ends for tenants who require it.
- **Signed Expiring Media URLs** — Serves every recording and transcript through short-lived signed URLs, never a public or guessable path.
- **Subject Access & Erasure** — Exports or deletes everything held about a specific caller on request, across calls, messages and bookings.
- **Compliance Readiness Report** — Summarises disclosure, consent, registration and retention posture per tenant in one reviewable view.

---

## 7. Contacts, Leads & Qualification

### 7.1 Contact Directory & Call Memory
- **Phone-Keyed Contact Records** — Creates a contact on first contact, keyed on a normalised E.164 number and deduplicated across channels.
- **Unified Interaction Timeline** — Shows every call, message, booking and note for a contact on one chronological view.
- **Cross-Call Memory** — Persists extracted fields so the agent recalls prior context on the next call.
- **Duplicate Merge** — Merges duplicate contacts with a controlled field-survivorship rule and full audit.
- **Per-Channel SMS Consent** — Records opt-in state, source, opt-in timestamp and opt-out timestamp on each `core.ContactChannel`, because a contact can be voice-reachable and SMS-suppressed at the same time.
- **Do-Not-Call as a Suppression Row** — Expresses do-not-call as a `core.SuppressionEntry` row rather than a contact flag, so there is exactly one DNC list on the platform.
- **Single Outbound Gate** — Clears every outbound voice or SMS attempt through `apps/core/compliance.py::check_outbound_allowed(contact, channel, now)`, the only consent gate; `core.Contact.status` may show the coarse value `dnc` as a denormalised display convenience, never as the authority and never as the thing a gate reads.
- **Contact Preferences** — Stores preferred language and timezone on the contact, which are routing and rendering preferences rather than consent state.

### 7.2 Lead Capture & Scoring
- **Conversational Field Capture** — Captures names, numbers and emails with read-back confirmation for accuracy.
- **Custom Field Schema** — Defines tenant-specific fields with types and choices, replacing hardcoded vertical fields.
- **Lead Scoring** — Computes a score and grade from qualification answers to drive notification priority.
- **Source Attribution** — Attributes each lead to its tracking number, campaign and channel for marketing measurement.
- **Duplicate Lead Detection** — Detects a returning enquirer and updates the existing lead rather than creating a second one.

### 7.3 Qualification Scripts
- **Script Builder** — Defines ordered questions with type, choices, required flag and disqualifying answers.
- **Backend-Owned Question Order** — Returns the next question from the server so script order cannot drift with model improvisation.
- **Answer Persistence** — Stores each answer against the contact and the call for later reporting and re-scoring.
- **Disqualification Handling** — Ends or reroutes politely when a disqualifying answer is given, recording the reason.
- **Script Versioning** — Versions scripts so historical answers remain interpretable after a script change.

### 7.4 Pipeline & Ownership
- **Tenant-Configurable Pipeline Stages** — Defines an ordered set of stages as Module 7's own `PipelineStage` table, so each tenant names and sequences its own pipeline.
- **Stage Membership & Timestamps** — Tracks a contact's position through those stages as `ContactPipelineEntry` rows carrying the stage and its entered-at timestamp, giving stage-duration reporting without mutating history.
- **Never a Redefinition of Contact Status** — Keeps these stages strictly separate from `core.Contact.status`, which stays the coarse spine status with exactly the values new, contacted, qualified, disqualified, customer and dnc.
- **Owner Assignment** — Assigns leads to users by round-robin, territory or manual selection.
- **Follow-Up Scheduling** — Sets a next-follow-up date that feeds outbound campaign targeting.
- **Saved Views & Filters** — Saves filtered lead views such as today's new leads or unworked after-hours enquiries.
- **Bulk Operations** — Applies tag, owner, status or export actions across a filtered set.

### 7.5 Import, Export & List Hygiene
- **CSV Import with Mapping** — Imports contact lists with column mapping, validation preview and error reporting.
- **Phone Normalisation** — Normalises every imported number to E.164 and flags unreachable or invalid entries.
- **Suppression Application** — Checks imported numbers against `core.SuppressionEntry` and per-channel opt-in state at import time so unlawful numbers never enter a campaign.
- **Segmentation** — Builds dynamic segments from field, tag, score and activity criteria for campaign targeting.
- **Export with Access Control** — Exports contact data under permission checks with every export written to the audit log.

---

## 8. Outbound Calling & Campaigns

### 8.1 Outbound Call Engine
- **Programmatic Dial-Out** — Places an outbound call from a designated caller-ID number and bridges it into the agent runtime.
- **Outbound Agent Configuration** — Uses an outbound-specific prompt, variable set and opener distinct from the inbound agent.
- **Deterministic Outbound Opener** — Speaks a scripted identity, business name and purpose line with no LLM latency at connect.
- **Answering-Machine Detection** — Detects voicemail and branches to leave a message, retry later, or hang up cleanly.
- **Pre-Dial Compliance Gate** — Calls `check_outbound_allowed(contact, channel, now)` before every dial and refuses when the contact is suppressed, unconsented, or outside the permitted window.
- **Outbound Disposition Set** — Records outcomes including answered, voicemail, no-answer, busy, wrong number, not interested and do-not-call.

### 8.2 Campaign Management
- **Campaign Definition** — Creates a campaign with type, target segment, agent version, script and calling window.
- **Attempt Cadence** — Defines attempt count, spacing and per-attempt channel across days.
- **Campaign Scheduling** — Starts, pauses, resumes and ends campaigns with clear handling of already-queued attempts.
- **Throughput Controls** — Caps concurrent outbound calls and calls-per-hour per campaign to protect capacity and reputation.
- **Campaign Cost Ceiling** — Halts a campaign automatically when its spend cap is reached.

### 8.3 Dialer & Attempt Queue
- **Attempt Queue** — Materialises scheduled attempts per contact with a due time and a stable ordering.
- **Timezone-Aware Scheduling** — Schedules each attempt in the contact's local time, never the tenant's.
- **Retry Policy** — Applies distinct retry rules for busy, no-answer and failed outcomes with escalating spacing.
- **Attempt Exhaustion** — Stops after the configured maximum attempts and marks the contact with a terminal reason.
- **Live Queue Monitor** — Shows queued, in-flight and completed attempts with real-time throughput.

### 8.4 Speed-to-Lead
- **Inbound-Trigger Dial** — Places a callback within seconds of a web form, missed call or inbound enquiry event.
- **Trigger Source Configuration** — Defines which events trigger immediate outreach and which agent handles each source.
- **Business-Hours Deferral** — Queues an out-of-hours trigger to fire at the start of the next permitted window.
- **Rep Notification Race** — Optionally alerts a human rep in parallel and cancels the AI call if the rep connects first.
- **Response-Time Reporting** — Measures time from enquiry to first contact attempt as the headline speed-to-lead metric.

### 8.5 Reactivation & Recall Campaigns
- **Dormant Contact Targeting** — Builds campaigns from contacts with no activity in a defined period.
- **Recall & Recurring Service Prompts** — Contacts customers due for a recurring service or check-up.
- **Post-Appointment Follow-Up** — Follows up after a completed appointment for feedback or a rebooking offer.
- **Review Request Outreach** — Requests a review from satisfied customers via voice or SMS with a link.
- **Suppression Respect** — Excludes recently contacted, opted-out and in-progress contacts from every reactivation run.

---

## 9. Messaging & Missed-Opportunity Recovery

### 9.1 SMS Infrastructure
- **Send & Receive Pipeline** — Sends and receives SMS through the carrier with delivery status callbacks persisted per message.
- **Consent-Gated Sending** — Blocks any send that `check_outbound_allowed` rejects, covering per-channel opt-in, suppression and an approved campaign in one gate.
- **Message Threading** — Groups messages into a per-contact thread linked to the originating call.
- **Delivery Status Tracking** — Records queued, sent, delivered, failed and undelivered states with carrier error codes.
- **Quiet Hours Enforcement** — Holds outbound messages until the recipient's permitted local window.

### 9.2 Missed-Call Text-Back
- **Missed-Event Detection** — Detects abandoned, unanswered, overflow and after-hours calls as recovery triggers.
- **Immediate Recovery Message** — Opens an SMS thread within seconds of the missed event with a scenario-appropriate template.
- **Duplicate & Spam Suppression** — Skips the text-back for screened numbers and contacts already in an active thread.
- **Reply-to-Action Conversion** — Turns the SMS reply into a booking or callback request without human involvement.
- **Recovery Reporting** — Reports missed calls texted, replied and converted, with recovered value.

### 9.3 Two-Way AI SMS Agent
- **Shared Knowledge & Tools** — Runs the SMS agent on the same knowledge base, tool set and guardrails as the voice agent.
- **Conversational Booking over Text** — Answers questions, qualifies and books appointments entirely by message.
- **Human Handover** — Escalates a thread to a staff inbox with full context and internal notes.
- **Voice Callback Offer** — Offers to switch the conversation to a call when text is the wrong channel for the request.
- **Thread Inbox** — Provides a staff inbox with unread state, assignment and search across threads.

### 9.4 Templates & Notification Routing
- **Template Library** — Manages SMS and email templates with merge variables and per-tenant branding.
- **Event Routing Rules** — Routes each event type such as new qualified lead, booking confirmed or negative sentiment to the right recipients.
- **Language Variants** — Selects the template variant matching the contact's detected language.
- **Preview & Test Send** — Renders and test-sends a template before it is activated.
- **Delivery & Opt-Out Analytics** — Tracks delivery, failure and opt-out rates per template.

### 9.5 Follow-Up Sequences
- **Multi-Step Cadences** — Runs sequenced SMS and email steps triggered by a call outcome or a lead status change.
- **Automatic Stop Conditions** — Stops the sequence immediately on reply, booking, opt-out or do-not-call.
- **Per-Step Channel & Delay** — Configures channel, delay and quiet-hours behaviour independently per step.
- **Voice Callback Step** — Inserts an AI voice call as a sequence step for high-value unconverted leads.
- **Sequence Performance Reporting** — Reports reply, booking and opt-out rates by step and by trigger.

---

## 10. Appointments & Scheduling

### 10.1 Resources, Services & Availability Rules
- **Polymorphic Resource Model** — Models staff, rooms, chairs, bays and equipment as bookable resources rather than hardcoded roles.
- **Service-to-Resource Mapping** — Defines which resources can deliver which services and for how long.
- **Working Patterns & Blackouts** — Sets per-resource working hours, breaks, holidays and one-off blackout dates.
- **Buffers & Lead Times** — Applies setup, travel and clean-down buffers plus minimum booking notice to offered slots.
- **Capacity Rules** — Supports resources that serve more than one appointment concurrently where the business allows it.

### 10.2 Calendar Integration
- **OAuth Calendar Connection** — Connects Google Calendar and Microsoft Outlook per resource with token refresh monitoring.
- **Free/Busy Read** — Reads real availability with a configurable lookahead window and slot granularity.
- **Event Write-Back** — Creates calendar events with the tenant's own title, description, location and attendee template.
- **Two-Way Sync** — Reflects calendar-side reschedules and cancellations back into the booking record.
- **Expiry Alerting** — Warns the tenant before a calendar connection's authorisation lapses.

### 10.3 Availability Search & Slot Offering
- **Multi-Filter Slot Query** — Finds open slots filtered by date range, weekdays, time window, duration and resource.
- **Caller-Time Honouring** — Converts a spoken time preference into a precise search window so a requested time is genuinely honoured.
- **Server-Capped Result Set** — Returns a small pre-ranked set of slots so the agent offers a manageable choice, enforced server-side.
- **Signed Slot Tokens** — Issues opaque signed slot tokens the agent echoes back, so a slot cannot be mangled, invented or replayed from another session.
- **Empty-Result Handling** — Offers a widened search, a later date or a callback rather than telling the caller there is nothing.

### 10.4 Booking, Reschedule & Cancellation
- **Idempotent Booking** — Books against a slot token with an idempotency key so a retried tool call cannot create a duplicate appointment.
- **Slot Locking** — Locks the slot between offer and write so two concurrent calls cannot double-book it.
- **Ownership-Verified Changes** — Authorises reschedule and cancel against the tenant and the identified contact, never on a model-supplied id alone.
- **Confirmation Delivery** — Sends an SMS and email confirmation with an add-to-calendar link immediately after booking.
- **Waitlist Capture** — Records a waitlist entry when no suitable slot exists and notifies on a cancellation.

### 10.5 Reminders, No-Shows & Recovery
- **Reminder Cadence** — Sends configurable reminders ahead of the appointment prompting confirm or reschedule.
- **Conversational Reschedule** — Handles the reminder reply by voice or SMS and updates the calendar automatically.
- **No-Show Detection** — Marks unattended appointments and records the reason.
- **Rebooking Sequence** — Triggers an automatic re-engagement sequence to rebook after a no-show or cancellation.
- **Recovery Reporting** — Reports appointments saved, no-shows recovered and estimated value retained.

---

## 11. Call Records, Transcripts & Post-Call Intelligence

### 11.1 Call Log & Recording
- **Unified Call Record** — Presents direction, numbers, contact, agent version, campaign, duration and disposition from `core.Interaction` as one hub view, with cost aggregated from `core.UsageEvent` — never stored on the record.
- **Recording Storage** — Stores call audio under the tenant's retention policy with signed expiring access only.
- **Synced Playback** — Plays the recording with a waveform synced to the transcript position.
- **Filterable Call List** — Filters calls by date, direction, number, agent, outcome, tag and campaign.
- **Call Bundle Export** — Exports audio, transcript and analysis together for legal, clinical or dispute purposes.

### 11.2 Transcript & Tool-Call Trace
- **Speaker-Attributed Transcript** — Renders the transcript view over `core.InteractionEvent` as timestamped, speaker-labelled turns, without a separate transcript table.
- **Inline Tool-Call Cards** — Interleaves the tool-call events from that same `core.InteractionEvent` stream into the transcript with arguments, result, success flag and duration.
- **Full-Text Search** — Searches across all transcripts with tenant scoping and permission checks.
- **Redacted Views** — Shows a redacted transcript to roles not permitted to see caller PII or PHI.
- **Turn-Level Cost Detail** — Displays per-turn token, STT, TTS and telephony cost for latency and margin investigation.

### 11.3 Summaries & Structured Extraction
- **Automatic Call Summary** — Generates a short summary plus action items on every completed call, off the realtime path.
- **Typed Extraction Schema** — Extracts tenant-defined fields as boolean, text, number or single-select values.
- **Vertical Default Schemas** — Ships sensible extraction defaults per industry that a tenant can edit rather than build from scratch.
- **Null-Safe Rendering** — Renders every analysis field defensively, since disconnected calls produce no analysis at all.
- **Retroactive Re-Analysis** — Re-runs analysis over historical calls after a schema change without re-running the calls.

### 11.4 Sentiment, Outcome & Resolution Scoring
- **Sentiment Scoring** — Scores caller sentiment and links the moment sentiment turned negative in the transcript.
- **Outcome Taxonomy** — Classifies each call into a tenant-configurable outcome set such as booked, qualified, message, transferred, spam or abandoned.
- **Rubric Success Evaluation** — Grades whether the call achieved its objective using pass/fail, checklist, numeric or percentage rubrics.
- **Resolution Criteria per Intent** — Defines what handled means for each intent so containment is measured honestly.
- **Automatic Review Flagging** — Flags calls for human review on negative sentiment, failed resolution or low confidence.

### 11.5 Tagging, Review & Follow-Up Queue
- **Tag Taxonomy** — Applies manual and automatic tags from a per-tenant controlled vocabulary.
- **Review Workflow** — Assigns flagged calls to reviewers with comments and a resolved state.
- **Follow-Up Linking** — Links a call to the SMS thread, booking or CRM record that resulted from it.
- **Saved Call Views** — Saves filtered views such as unhandled after-hours calls or negative sentiment this week.
- **Bulk Call Actions** — Tags, assigns or exports across a filtered call set in one operation.

### 11.6 Artifact Notification & Delivery
- **Instant Summary Push** — Delivers the summary, transcript link and extracted fields by SMS and email within seconds of hangup.
- **Recipient Routing Rules** — Routes new leads, complaints and emergencies to different recipients.
- **Per-Call Webhook Delivery** — Posts the full call artefact to tenant endpoints for downstream automation.
- **Digest Mode** — Sends hourly or end-of-day roll-ups instead of per-call alerts for high-volume tenants.
- **Delivery Log & Retry** — Logs every notification with status and retries transient failures visibly.

---

## 12. Testing, QA & Analytics

### 12.1 Test Calls & Sandbox
- **Browser Playground** — Converses with a draft agent in the browser without placing a real call.
- **Verified Test Call** — Places a real call from the draft version to a verified number.
- **Turn Debug View** — Shows retrieved knowledge, tool calls, arguments and timings behind every response.
- **Production Call Replay** — Replays a real call's transcript against a new draft to see how it would have behaved.
- **Publish Gate Integration** — Records a successful test as the precondition that unlocks publishing.

### 12.2 Simulated Caller Testing
- **Scenario Definition** — Defines synthetic callers as a persona plus a goal, such as impatient caller, wrong number or emergency.
- **Batch Scenario Runs** — Runs the scenario suite against an agent version and returns pass/fail per scenario.
- **Outcome Assertions** — Asserts that the agent booked, transferred, captured required fields or stayed in scope.
- **Regression Suite on Publish** — Runs the suite automatically at publish and blocks release on failures.
- **Vertical Scenario Library** — Seeds scenarios per vertical and lets tenants extend them.

### 12.3 QA Scorecards & Call Review
- **Cohort Definition** — Defines a filtered slice of calls to grade as a QA cohort.
- **Rubric Scoring** — Scores cohorts against pass/fail, checklist, numeric or descriptive rubrics.
- **AI Scoring with Human Override** — Applies automatic scoring that a reviewer can correct, with the correction retained.
- **Failure Drill-Down** — Jumps from a failing metric to the exact transcript moment that caused it.
- **Quality Trend by Version** — Trends quality scores across agent versions to prove a prompt change helped.

### 12.4 Operational Analytics
- **Volume & Answer Metrics** — Reports call volume, answer rate, average duration and a peak-hour heatmap by number and agent.
- **Containment & Transfer Rates** — Reports automation rate and transfer rate with a reason breakdown for every transfer.
- **Outcome Mix Trends** — Trends the outcome distribution over time to expose behaviour drift.
- **Missed-Opportunity Report** — Reports after-hours calls, calls over concurrency and unanswered follow-ups.
- **Segment Breakdowns** — Breaks every metric down by location, department, campaign and agent version.

### 12.5 Business Outcome Reporting
- **Conversion Reporting** — Reports bookings created, leads qualified and estimated revenue influenced by the agent.
- **Attribution by Source** — Attributes outcomes to tracking numbers, campaigns and channels.
- **Unit Cost Metrics** — Reports cost per call, cost per booked appointment and cost per qualified lead.
- **Baseline Comparison** — Compares current performance against the tenant's pre-deployment missed-call baseline.
- **Scheduled Value Report** — Emails a weekly or monthly report as the tenant-facing proof of value.

### 12.6 Alerting & Monitoring
- **Threshold Alert Rules** — Alerts on volume, success rate, sentiment, latency, cost and error count.
- **Absolute & Relative Thresholds** — Supports both fixed thresholds and percentage-change thresholds to catch spikes and collapses.
- **Email & Signed Webhook Channels** — Delivers alerts by email and HMAC-signed webhook with a delivery log.
- **Incident Semantics** — Fires once per incident with an explicit resolution state, avoiding alert storms.
- **Operator vs Tenant Alerts** — Separates platform-level alerts such as provider outage from tenant-level business alerts.

---

## 13. Integrations, API & Onboarding

### 13.1 Webhooks & Event Bus
- **Published Event Catalogue** — Publishes a documented event set covering call, analysis, booking, lead and message lifecycle.
- **Signed Delivery** — Signs every payload with HMAC and a timestamp so receivers can verify authenticity.
- **Retry & Dead Letter** — Retries with exponential backoff under a bounded timeout and dead-letters persistent failures.
- **Delivery Log** — Stores request and response bodies per attempt for tenant self-service debugging.
- **Manual Replay** — Replays a failed delivery from the dashboard without re-running the underlying event.

### 13.2 CRM & Vertical System Connectors
- **Native CRM Connectors** — Connects HubSpot and Salesforce via OAuth with a visual field-mapping interface.
- **Generic Connector Framework** — Provides a configurable connector for practice-management, case-management and field-service systems.
- **Bidirectional Sync** — Writes call outcomes outward and reads customer context inward for personalised greetings.
- **Conflict & Duplicate Rules** — Defines behaviour when a matching contact already exists in the external system.
- **Sync Status & Retry** — Shows per-record sync state with error detail and targeted retry.

### 13.3 Automation Platforms & Public API
- **Automation Connector** — Exposes triggers and actions to Zapier and Make for the long tail of tenant tools.
- **Public REST API** — Covers agents, calls, contacts, leads, bookings, messages and knowledge bases.
- **Scoped API Keys** — Issues per-tenant keys with scoped permissions, rotation and last-used tracking.
- **Rate Limits & Quotas** — Enforces per-key rate limits and quotas with usage visible to the tenant.
- **Versioning & Deprecation** — Versions the API with a documented deprecation window and change log.

### 13.4 Web Voice & Chat Widget
- **Embeddable Chat Widget** — Serves a website chat widget backed by the same agent, knowledge and guardrails.
- **Click-to-Talk Voice Widget** — Enables a browser voice conversation without a phone number.
- **Widget Theming** — Configures colours, position, greeting and availability per tenant.
- **Unified Conversation Logging** — Records widget conversations into the same call and conversation log as phone calls.
- **Widget Escalation** — Escalates from the widget to a phone callback or a human inbox.

### 13.5 Guided Onboarding & Go-Live
- **Setup Wizard** — Walks a new tenant from website URL through knowledge build, vertical pack, voice, hours, transfer targets, calendar, test call and number assignment.
- **Progress Persistence** — Saves partial setup so a tenant can resume where they left off.
- **Inline Readiness Validation** — Validates at each step that the calendar is connected, a transfer target exists and the disclosure is present.
- **Pre-Launch Health Scan** — Flags an empty knowledge base, unreachable transfer numbers, missing fallbacks or an unapproved messaging campaign.
- **Activation Metrics** — Tracks time-to-first-call and setup completion as internal activation signals.

### 13.6 Vertical Packs & Rollback Safety
- **Industry Packs** — Bundles prompt, intents, routing rules, extraction schema, qualification script and templates per industry.
- **Compliance Defaults per Vertical** — Pre-enables the appropriate compliance posture, such as HIPAA prompts and PHI redaction for clinics.
- **Packaged Test Scenarios** — Ships vertical-specific simulation scenarios with each pack for the regression suite.
- **Pack Forking & Versioning** — Forks a pack into a tenant-private template that versions independently.
- **One-Click Safe Rollback** — Reverts to the previous agent version or plain call forwarding instantly if a go-live goes wrong.
