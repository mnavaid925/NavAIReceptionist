# Research — Sub-module 2.2: Twilio Connection (Module 2 — Agent Setup & Telephony, `agents`)

## Repo state checked first

- **LIVE_LINKS built so far in module 2:** none. `apps/accounts/navigation.py` only has `0.1`–`0.4` and
  `1.1`–`1.4`. Module 2 (`agents`) has not shipped any sub-module yet — this research targets `2.2` directly per
  the invoking prompt, ahead of `2.1` in build order. `2.2`'s form/view code will therefore be the first code in
  `apps/agents/`; it must not assume `2.1`'s greeting/prompt fields already have a form, only that they exist as
  columns on the same `AgentSetting` row.
- **`apps/agents/` does not exist** (`Glob apps/agents/**` → no files). Confirmed greenfield for this module.
- **`grep -rn "^class AgentSetting"` → no matches anywhere in the repo.** The model is not built. Every mapping
  below targets the *documented* `agents.AgentSetting` shape in `NavAIReceptionist-ERD.md` §3.2, not code.
- **Sibling models verified to exist** (grep hits): `tenants.Tenant` (`apps/tenants/models/Tenant.py`),
  `tenants.Location` (`apps/tenants/models/Location.py`), `accounts.User` (`apps/accounts/models/User.py`),
  `accounts.UserLocation` (`apps/accounts/models/UserLocation.py`). These are the only FK targets `AgentSetting`
  needs for this sub-module (`tenant`, `location`).
- **`config/settings.py` verified**: `ENCRYPTION_KEY` (line 353, comment already says *"Fernet key used to encrypt
  per-location Twilio credentials at rest (Module 2)"*), `PROVIDER_MODE` (320-322, default `fake`),
  `TWILIO_WEBHOOK_BASE_URL` / `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` (324-326, these are **platform-level**
  fallback/dev values only — per-location credentials live encrypted on `AgentSetting`, not here, per the comment
  block at line 312-317).
- **`requirements.txt` does NOT yet list `cryptography`** despite the brief stating it is installed — the `todo`
  step should add `cryptography>=42,<50` (or pin to the resolved installed version) as its own commit.
- **No sibling `research-agents-2.1.md` exists yet.** Nothing to defer from or fold in; 2.1's greeting/prompt/voice
  fields on the same row are read-only context here, not scoped by this file.

## Leaders surveyed (with source links)

The receptionist-brand tier (Smith.ai, Ruby, Rosie, Goodcall, Dialpad AI) manages its own telephony internally and
does not expose BYO-Twilio credential entry to the customer, so it is **not** a source for this specific
sub-module. The comparable competitor set for "customer pastes their own Twilio Account SID + Auth Token to bind a
number" is the developer-facing voice-agent platform tier, plus Twilio's own subaccount/credential model as the
provider being connected to:

1. **Vapi** — voice-agent platform with an explicit "Import number from Twilio" flow — [docs.vapi.ai/phone-numbers/import-twilio](https://docs.vapi.ai/phone-numbers/import-twilio)
2. **Retell AI** — BYO-Twilio via REST webhook or Elastic SIP Trunk import — [docs.retellai.com/deploy/twilio](https://docs.retellai.com/deploy/twilio)
3. **Synthflow** — "bring your own Twilio account", explicitly recommends a **Twilio subaccount per connected
   number** to avoid interfering with existing trunking — [docs.synthflow.ai/integrate-twilio](https://docs.synthflow.ai/integrate-twilio)
4. **Bland AI** — "BYOT" (Bring Your Own Twilio): POST SID+token, receive an opaque `encrypted_key` back, never the
   raw credential again — [docs.bland.ai/tutorials/custom-twilio](https://docs.bland.ai/tutorials/custom-twilio)
5. **ElevenLabs Agents** — native Twilio integration; import modal takes phone number + Account SID + Auth Token,
   then auto-configures the number's webhook — [elevenlabs.io/docs/eleven-agents/phone-numbers/twilio-integration/native-integration](https://elevenlabs.io/docs/eleven-agents/phone-numbers/twilio-integration/native-integration)
6. **PolyAI** — enterprise tier; numbers page grouped by environment (sandbox/pre-release/live) with SIP addresses
   to paste into the carrier/Twilio config, sales-scoped rather than self-serve — [docs.poly.ai/telephony/route-management](https://docs.poly.ai/telephony/route-management)
7. **Twilio itself** — Subaccounts (each has its own independent Account SID + Auth Token, cannot access another
   subaccount's resources, still billed to the parent) — [twilio.com/docs/iam/api/subaccounts](https://www.twilio.com/docs/iam/api/subaccounts); Test Credentials / credential validation via a
   non-billable `GET /Accounts/{Sid}.json` call, `401`/Error 20003 on bad credentials — [twilio.com/docs/iam/test-credentials](https://www.twilio.com/docs/iam/test-credentials), [twilio.com/docs/iam/credentials/api](https://www.twilio.com/docs/iam/credentials/api)
8. **Stripe** (secret-key handling reference, not a telephony competitor) — never redisplays a full secret key
   after creation, shows a masked/truncated value, offers "roll key" instead of edit-in-place — [docs.stripe.com/keys-best-practices](https://docs.stripe.com/keys-best-practices)

## Feature catalog (this sub-module only)

### Per-Location Credentials
- **Independent SID + token per (tenant, location)** — every leader that supports BYO-Twilio stores a distinct
  credential pair per connected number/location, never one platform-wide credential shared across customers ·
  seen in: Vapi, Retell AI, Synthflow, Bland AI, ElevenLabs Agents · priority: table-stakes · model: reuses
  `agents.AgentSetting` (tenant + location scoped, unique on `(tenant, location)` — already the model's shape) ·
  realtime: post-call (a config-time concern; Module 3 reads the row at webhook time, but connecting/saving the
  credential is not itself a live-call path) · tool-surface: pure UI (form) · buildable now.
- **Twilio-subaccount-per-location as the recommended topology** — Synthflow explicitly tells customers to create
  a fresh Twilio subaccount per connected number so trunking/webhooks from one customer's number never collide
  with another's; Twilio's own subaccount docs confirm a subaccount's SID/token cannot reach another subaccount's
  resources · seen in: Synthflow, Twilio (subaccounts) · priority: common (a documented best practice, not
  enforced by the product — a tenant can also point two locations' `AgentSetting` rows at the same Twilio main
  account with different numbers, that's their choice) · model: no new field — this is operator guidance to
  surface as help text next to the SID/token inputs, not a schema decision · realtime: post-call · tool-surface:
  pure UI (help text) · buildable now.

### Write-Only Auth Token
- **Encrypted-at-rest storage, decrypted only server-side when actually dialing/verifying** — every BYO-Twilio
  platform treats the auth token as a secret that is stored encrypted and never redisplayed; Bland AI's pattern is
  the most concrete precedent: POST the raw SID+token once, get back an **opaque `encrypted_key` reference**, and
  every subsequent API call uses that reference — the raw token is never returned again · seen in: Bland AI
  (encrypted_key), Stripe (masked secret, never redisplayed) · priority: **REQUIRED** (`CLAUDE.md` §"Vulnerability"
  rule 3 — provider credentials are write-only in forms) · model: reuses `agents.AgentSetting.twilio_auth_token`
  (tenant + location scoped) · realtime: post-call · tool-surface: pure UI (form field + model method, no LLM
  tool — this field is never read by the model or exposed through `apply_tool_call`) · buildable now, needs the
  `cryptography` package (already targeted at `settings.ENCRYPTION_KEY`).
- **Blank-submit-means-unchanged semantics** — every masked-secret settings UI (Stripe's key rotation UI, AWS
  console's masked-secret inputs) treats an empty submission on a write-only field as "leave it alone", and a
  non-empty submission as "replace it" — never as "erase it". Concretely for this build: the form field is
  `forms.CharField(required=False, widget=forms.PasswordInput(render_value=False))`; the form's `save()` (or a
  `clean_twilio_auth_token()` combined with an explicit branch in `save()`) reads `cleaned_data['twilio_auth_token']`
  and **only** calls `instance.set_twilio_auth_token(value)` when `value` is truthy — an empty string never
  triggers `set_twilio_auth_token('')`, so a token that was already saved survives every subsequent edit of the
  other fields on the same form · seen in: Stripe (never round-trips a full key), Bland AI (write-once,
  reference-only), AWS/Google Cloud console API-key forms · priority: **REQUIRED** · model: reuses
  `agents.AgentSetting` + a model-level `set_twilio_auth_token(plaintext)` method that owns the encrypt call ·
  realtime: post-call · tool-surface: pure UI · buildable now.
- **Set / not-set indicator, never the value** — Stripe and every reviewed platform show a masked state
  ("•••• configured" / "Not connected") rather than any character of the secret, sourced from `bool(value)`
  on the ciphertext column, never a decrypt · seen in: Stripe, Bland AI, Vapi (dashboard shows "Connected" state
  after import, not the token) · priority: **REQUIRED** · model: reuses `agents.AgentSetting` via an
  `is_twilio_configured` (or `has_twilio_auth_token`) property that only checks truthiness of the stored
  ciphertext — never calls the decrypt path · realtime: post-call · tool-surface: pure UI, `badge-green`
  "Connected" / `badge-muted` "Not connected" · buildable now.

### Inbound Number Binding
- **Global uniqueness across all tenants** — the number is the routing key an inbound webhook resolves tenant AND
  location from (`AgentSetting.objects.get(inbound_phone_number=to_number)`, per `NavAIReceptionist-ERD.md` §1);
  every BYO-telephony platform surveyed treats "this number is already imported/assigned" as a hard conflict, not
  a per-customer scoped check, because the underlying carrier number can only route to one destination · seen in:
  Vapi (import fails if the number is already imported to another workspace), Retell AI, ElevenLabs Agents ·
  priority: **REQUIRED** (this is also Invariant-adjacent — it's the mechanism Module 3's dialed-number resolution
  depends on) · model: reuses `agents.AgentSetting.inbound_phone_number`, DB-level
  `UniqueConstraint(fields=['inbound_phone_number'])` with **no** tenant/location in that constraint (deliberately
  the one field on this model that is NOT scoped to `(tenant, location)`) · realtime: post-call (the binding
  itself is config-time; Module 3's webhook resolution is the live-call consumer of this uniqueness) ·
  tool-surface: pure UI · buildable now.
- **Tenant-blind collision error** — none of the surveyed platforms' public docs describe their exact collision
  copy (this is a security-by-obscurity area, so it is under-documented by design), but the general secret/resource
  -ownership-check best practice (same family as "don't reveal whether an account exists" in this product's own
  `0.1` login throttling) applies directly: reveal that a number is taken, never who holds it · priority:
  **REQUIRED** — this is a cross-tenant information-disclosure risk specific to a multi-tenant SaaS, not a
  feature a single-tenant telephony platform would even need to think about. Concretely: `clean_inbound_phone_number()`
  runs `AgentSetting.objects.exclude(pk=self.instance.pk).filter(inbound_phone_number=normalized).exists()`
  **across all tenants** (deliberately not narrowed by `tenant=`) and raises one generic
  `ValidationError("This number is already connected to another account. Contact support if this is unexpected.")`
  — identical wording whether the collision is with another location in the *same* tenant or a *different* tenant,
  never the other tenant's name/slug/location, never a different HTTP status or timing profile for "taken by us"
  vs "taken by them" · model: reuses `agents.AgentSetting` · realtime: post-call · tool-surface: pure UI (form
  validation error) · buildable now.
- **E.164 normalization before comparison** — leaders normalize punctuation/whitespace/country-code formatting
  before treating two numbers as equal, so `+1 (512) 555-0100` and `+15125550100` collide correctly · seen in:
  Twilio (E.164 is the platform-wide number format), Vapi, Retell AI · priority: table-stakes · model: reuses
  `agents.AgentSetting.inbound_phone_number`, normalized in `clean()`/`save()` (strip formatting, enforce leading
  `+`, reject if it doesn't parse as E.164) · realtime: post-call · tool-surface: pure UI · buildable now (a
  regex/`phonenumbers`-style check is enough; no external call needed to validate *format*).

### Webhook URL Display
- **Copy-pasteable voice-webhook URL** — shown for the customer to paste into their own Twilio console's "A call
  comes in" field, scoped to this location's number · seen in: Retell AI (REST webhook path documented alongside
  the SID/token fields), Vapi · priority: table-stakes · model: pure computed display —
  `f"{settings.TWILIO_WEBHOOK_BASE_URL}/runtime/voice/{location.id}/"` (or equivalent Module-3-owned path; this
  sub-module only **renders** the URL string, it does not own the endpoint) · realtime: post-call · tool-surface:
  pure UI · buildable now (the URL is a string built from `settings.TWILIO_WEBHOOK_BASE_URL` + a Module-3 route
  name that does not need to resolve yet — display it even before Module 3 exists, clearly labeled "for Module 3
  once built" if the URL name is not yet registered).
- **Copy-pasteable media-stream (WebSocket) URL** — the `wss://…` URL for Twilio's `<Stream>` TwiML verb to
  connect to the ASGI consumer · seen in: Vapi, Retell AI, ElevenLabs Agents (all show a distinct
  stream/websocket endpoint alongside the voice webhook) · priority: table-stakes · model: pure computed display,
  same caveat as above (Module 3 owns the actual consumer route) · realtime: post-call · tool-surface: pure UI ·
  buildable now.
- **Auto-configure the number's webhook via the Twilio API** — ElevenLabs Agents goes further than "display": it
  calls Twilio's `IncomingPhoneNumbers` update API to set the Voice URL automatically once credentials + number
  are verified, so the customer never touches the Twilio console at all · seen in: ElevenLabs Agents · priority:
  differentiator · model: would need a live Twilio API write (`client.incoming_phone_numbers(sid).update(voice_url=...)`)
  · realtime: post-call · tool-surface: none (server-side provider call, not an LLM tool) · **integration/later —
  the documented `2.2` bullet is explicitly "Shows the exact … URLs to paste into the Twilio console", i.e.
  manual paste-in is the specified scope for this pass; auto-configuration is scope creep beyond the bullet and
  belongs in a later hardening pass, not this build.**
- **One-click "copy to clipboard"** — pure UI affordance next to each displayed URL · seen in: Vapi, Retell AI,
  ElevenLabs Agents dashboards (implicit UX convention across all of them) · priority: table-stakes · model: none
  · realtime: post-call · tool-surface: pure UI (a small HTMX/Alpine or vanilla-JS clipboard write, no backend
  call) · buildable now.

### Connection Check
- **Credential validation without a billable/real call** — Twilio's own guidance is the concrete mechanism: a
  `GET https://api.twilio.com/2010-04-01/Accounts/{AccountSid}.json` request authenticated with
  `(account_sid, auth_token)` as HTTP Basic Auth is free and non-billable; bad credentials return HTTP 401 /
  Twilio Error 20003 "Permission Denied" · seen in: Twilio (Test Credentials / REST API docs), and implicitly
  every BYO-Twilio platform's "verify" step (Vapi's import endpoint "uses your Twilio credentials to verify and
  configure the number") · priority: **REQUIRED** (this is the literal "Connection Check" bullet) · model: no new
  field beyond what's already on `AgentSetting`; the check reads `twilio_account_sid` +
  decrypted `twilio_auth_token` transiently, never persists a "last checked" boolean unless a small `metadata`-style
  JSON note is wanted (defer — 11-model ceiling, and `AgentSetting` has no `metadata` JSON field in the ERD, so
  don't invent one just to cache a check result) · realtime: post-call (this is an explicit, user-triggered
  "Check connection" button press, never part of the live-call hot path) · tool-surface: pure UI — **NOT an LLM
  tool**; this is an operator-facing action behind a form button, never something the voice agent calls mid-call
  (there is no `check_twilio_connection` tool in Module 3's built-in tool set per `NavAIReceptionist.md` §3.3) ·
  buildable now BUT it is an external-provider call, so it ships behind the thin telephony-control seam this
  sub-module defines (see "Buildable now vs. integration/later" below) with a **fake** implementation under
  `PROVIDER_MODE != 'live'`.
- **Number-ownership verification against the connected Twilio account** — beyond "are these credentials valid",
  confirm the specific `inbound_phone_number` is actually one of *this* Twilio account's `IncomingPhoneNumbers` —
  concretely `client.incoming_phone_numbers.list(phone_number=<E.164>)` scoped to that account, empty result means
  "not found in this Twilio account" · seen in: Vapi ("verify and configure the number" on import — implies an
  ownership lookup), Twilio (`IncomingPhoneNumbers` resource is exactly this list) · priority: **REQUIRED** (the
  bullet explicitly says "verifies the credentials **and number ownership**") · model: none new · realtime:
  post-call · tool-surface: pure UI · integration/later behind the same seam, fake-mode by default.
- **Explicit "no call is placed" framing in the UI and result copy** — every reviewed platform's verify/import
  step is a metadata-only API call, never a dial; this needs to be stated in the UI copy itself ("Checking your
  Twilio credentials — this does not place a call") so a tenant does not confuse this with `2.4`'s Test Call ·
  priority: table-stakes (a UX/trust concern specific to a product whose whole pitch is "answers real calls") ·
  model: none · realtime: post-call · tool-surface: pure UI · buildable now.
- **Distinct result states surfaced to the user** — not just pass/fail: "credentials invalid" vs "credentials
  valid, number not found on this account" vs "connected" are three different outcomes a tenant needs to act on
  differently (fix the SID/token vs. fix the number vs. done) · seen in: Twilio's own error taxonomy (20003
  permission denied vs. a 404-shaped "not found" for a missing resource) · priority: common · model: none — this
  is a transient result rendered from the check's return value, never persisted · realtime: post-call ·
  tool-surface: pure UI, three-state badge (`badge-red` invalid credentials / `badge-amber` number not found /
  `badge-green` connected) · buildable now.

### Beyond the bullets
- **Credential-change notice (account-takeover tripwire)** — this product already has the pattern for the exact
  same risk shape: `0.2`'s **Credential Change Notice** emails the previous address whenever password or email
  changes. A Twilio auth-token replacement is the same class of event (a compromised admin session could silently
  repoint a location's telephony to an attacker's Twilio account) and the two carrier fields together
  (`twilio_account_sid` + a valid `twilio_auth_token`) are described in the ERD itself as "a live Twilio account"
  · seen in: AWS/Google Cloud (security-center alerts on IAM key rotation), general secret-management best
  practice · priority: differentiator · model: reuses `agents.AgentSetting` (no new field — trigger is
  `set_twilio_auth_token()` being called with a new value) + `0.2`'s existing email-notice plumbing (whatever
  mail-sending helper `accounts` already built) · realtime: post-call · tool-surface: pure UI/backend (an email
  side-effect on save, not a tool) · **deferred** — needs `0.2`'s email infrastructure confirmed reusable; do not
  build a parallel notification mechanism for one field. Flag as a fast follow, not part of this pass's minimum.
- **Audit trail of who changed the credential and when** — general secret-management best practice (see
  GitGuardian/Akeyless sources) is to log every credential-changing action for later review · priority: common ·
  model: would need either a new audit-log table (blocked by the 11-model ceiling — `AgentSetting` is model #5 of
  11 and this sub-module recommends **zero** new models) or reuse of Django's built-in `LogEntry`
  (`django.contrib.admin.models`) if the admin is used for this, which it is not (these are tenant-facing forms) ·
  realtime: post-call · tool-surface: none · **deferred** — no model budget in this pass; note it for a future
  module-wide activity-log sub-module if one is ever scoped, never a dedicated `agents` table.

## Compliance & provider constraints

- **Provider credentials are encrypted at rest and write-only in forms** — `CLAUDE.md`'s Vulnerability rule 3 is
  itself the compliance requirement here: `twilio_auth_token` must never appear in `Meta.fields` as a readable
  value, never be rendered, never be logged at any level, never appear in `messages.*`. This is **REQUIRED**, not
  a priority tier — it is the reason this sub-module is called "the highest-security sub-module in the product."
  The **encryption-at-rest mechanism** is Fernet (symmetric, authenticated) via the `cryptography` package,
  keyed from `settings.ENCRYPTION_KEY`:
  - `Fernet(settings.ENCRYPTION_KEY.encode())` — `ENCRYPTION_KEY` must be a valid Fernet key: 32 raw bytes,
    URL-safe-base64-encoded (44 ASCII characters ending in `=`), generated once via `Fernet.generate_key()` and
    stored in `.env`, never regenerated in place (a lost/rotated key makes every existing encrypted token
    permanently undecryptable — a documented ops gotcha, not a Django-specific one).
  - Encrypt: `Fernet(key).encrypt(plaintext.encode()).decode()` → store the resulting token string.
    Decrypt: `Fernet(key).decrypt(ciphertext.encode()).decode()` — only called from the connection-check service
    and (later) Module 3's telephony adapter, **never** from a view that renders to a browser response.
  - **Why the ciphertext needs a LARGER `max_length` than the ERD's `Char(128)`, and what to use.** A Fernet
    token's binary form is `version(1) + timestamp(8) + IV(16) + ciphertext(padded) + HMAC(32)` — a fixed 57-byte
    overhead plus the PKCS7-padded ciphertext, then the whole thing is base64-encoded (≈33% larger again). Worked
    example for a real Twilio auth token (32 raw characters): padded ciphertext = 48 bytes → 105 bytes binary →
    **140 base64 characters**. For a defensively-sized 128-byte plaintext (the ERD's own bound, if read as a
    plaintext limit): padded ciphertext = 144 bytes → 201 bytes binary → **268 base64 characters** — already past
    `Char(128)` by more than double, and past even `Char(255)`. **Recommendation: store the encrypted value in a
    `models.CharField(max_length=512)` (or a `TextField` if the team prefers never revisiting this number again)**
    — 512 comfortably covers plaintexts up to several hundred characters with headroom for a future longer secret
    format, at negligible storage cost for a field with at most one row per location. The ERD's `Char(128)` is the
    *plaintext* bound implied by a real Twilio auth token's actual length (32 hex chars) — it was never meant as
    the ciphertext column width, and using it as one truncates every stored token silently in MySQL's default
    non-strict mode or raises `DataError` in strict mode. This is a correction to carry into the `todo` plan, not
    a deviation to flag against the ERD (the ERD's own text calls out only that the *field* is "encrypted at rest,
    write-only in forms" — it does not specify a ciphertext-safe column width).
  - **Write-only field implementation** (blank submit = unchanged, not erase): the Django `ModelForm` field is
    `twilio_auth_token = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False),
    help_text="Leave blank to keep the current token.")`. The form never sets `instance.twilio_auth_token`
    directly from `cleaned_data` (that would let an empty POST body erase it, since an unbound `ModelForm.save()`
    on a blank field would otherwise write `""`). Instead, `AgentSetting` grows one plain method:
    ```python
    def set_twilio_auth_token(self, plaintext: str) -> None:
        self.twilio_auth_token = encrypt_secret(plaintext)  # Fernet, from apps/agents/crypto.py

    @property
    def has_twilio_auth_token(self) -> bool:
        return bool(self.twilio_auth_token)
    ```
    and the view/form's `save()` override does:
    ```python
    token = form.cleaned_data.get('twilio_auth_token', '').strip()
    if token:
        instance.set_twilio_auth_token(token)
    # else: leave instance.twilio_auth_token untouched — this is the "blank means unchanged" contract
    ```
  - **The set/not-set indicator** is `AgentSetting.has_twilio_auth_token` (a `bool(ciphertext)` check — it never
    calls `decrypt_secret`). The template renders `badge-green "Connected"` / `badge-muted "Not set"` from that
    boolean alone. No view, template, log line, or `messages.*` call ever calls the decrypt function except the
    connection-check service and (later) Module 3's Twilio adapter — both server-side, non-rendering code paths.
  - `apps/agents/crypto.py` (flat module, per the Backend Package Structure rule — single-purpose modules stay
    flat at the app root) is the right home for `encrypt_secret(plaintext) -> str` / `decrypt_secret(ciphertext)
    -> str`, wrapping `Fernet` and raising a clear error if `settings.ENCRYPTION_KEY` is unset — this must fail
    loudly at startup/first-use, not silently store plaintext.
- **`inbound_phone_number` global uniqueness and its collision error.** Required because it is the sole routing
  key Module 3's webhook uses to resolve tenant *and* location from the dialed number (`AgentSetting.objects.get
  (inbound_phone_number=to_number)` — ERD §1); two locations, in the same tenant or different tenants, can never
  share a DID. The collision error is a cross-tenant information-disclosure control: it must say only that the
  number is taken, **never** which tenant/business holds it, and must use identical wording regardless of whether
  the existing owner is the same tenant or a different one (differential wording between "your own other location
  already has this number" and "another business has this number" would itself leak tenant boundaries).
- **`twilio_account_sid` is not encrypted but is still not a value to log.** The ERD explicitly says "the same
  rule covers `twilio_account_sid` in logs — a sid plus a leaked token is a live Twilio account." It CAN be
  pre-filled/redisplayed in the edit form (it functions more like a username/identifier than a full secret — this
  matches Twilio's own Account SID being visible throughout their console), but it must never appear in a log
  line, and the connection-check service's error handling must not echo the raw SID/token pair back in an
  exception message that reaches logs.
- **No real Twilio call from a non-`live` `PROVIDER_MODE`.** The Connection Check is an external-provider call by
  definition (it hits Twilio's REST API). Per `CLAUDE.md`'s Vulnerability rule 7 and the Realtime rules, this
  sub-module must define a **thin telephony-control seam** now — a small interface this sub-module owns
  (e.g. `apps/agents/telephony.py`, flat module) with exactly the two operations this bullet needs:
  `verify_credentials(account_sid, auth_token) -> bool` and `verify_number_ownership(account_sid, auth_token,
  phone_number) -> bool`, resolved by `PROVIDER_MODE` (`fake` returns deterministic canned results with no
  network call at all; `live` calls the real Twilio REST endpoints named above; `sandbox` is reserved for Module
  3's later, richer sandbox definition). **This is explicitly a stand-in, not the final home** — when Module 3
  builds `apps/runtime/providers/`, this seam's `live`/`fake` split moves under a `telephony` provider adapter
  there and `apps/agents/telephony.py` becomes a thin caller of it. Document this handoff plainly in code comments
  so Module 3 doesn't duplicate the Twilio REST calls.
- **No PCI/HIPAA-specific obligation triggers from this sub-module specifically** — recording consent, two-party
  consent announcements and HIPAA/GDPR retention belong to `3.5` (Recording, Teardown & Diagnostics) and Module 5,
  not to binding a number. The only compliance-grade obligation this sub-module carries is credential
  confidentiality (covered above) and the tenant-blind collision behavior (also covered above).
- **Cost lines:** none. The Connection Check is a free, non-billable Twilio metadata call (per Twilio's own Test
  Credentials guidance) — it must never touch `calls.CallSession.usage` (there is no session; this isn't a call)
  and never places a billable call, SMS, or number lookup with per-unit cost. `2.4`'s **Test Call** is the
  sub-module that actually spends a voice minute, not `2.2`.
- **Rate limits / concurrency:** the Connection Check should be debounced client-side (disable the button while a
  check is in flight) to avoid a tenant hammering Twilio's REST API from repeated clicks — Twilio does apply
  per-account rate limits to its REST API, and a naive retry loop on a bad-credentials response would burn through
  it for no benefit. No server-side queue/cap is needed at this scale (one check per click, one location's row at
  a time).

## Recommended build scope (this pass)

**CRUD sub-module — but it introduces ZERO new models.** `agents.AgentSetting` already exists as the target model
per the brief and the ERD (model #5 of 11); `2.2` adds **fields it already owns** (`twilio_account_sid`,
`twilio_auth_token`, `inbound_phone_number`) via its own scoped form, not a new table. Per the eleven-model
ceiling and the brief's explicit instruction, this sub-module recommends:

- **No new model.** `agents.AgentSetting` (tenant + location scoped, unique on `(tenant, location)`) is reused,
  with its `twilio_account_sid` (Char(64)), `twilio_auth_token` (recommend `CharField(max_length=512)` — see the
  ciphertext-sizing math above, not the ERD's literal `Char(128)`), and `inbound_phone_number` (Char(32), E.164,
  **globally unique with no tenant/location in the constraint**) fields as the persisted surface for this
  sub-module. FKs: `tenant` → `tenants.Tenant` (verified), `location` → `tenants.Location` (verified).
- **New non-model code this sub-module owns:**
  - `apps/agents/crypto.py` — `encrypt_secret` / `decrypt_secret` (Fernet wrapper over `settings.ENCRYPTION_KEY`).
  - `apps/agents/telephony.py` — the thin `verify_credentials` / `verify_number_ownership` seam,
    `PROVIDER_MODE`-resolved, with a `fake` implementation as the default and a documented handoff comment for
    Module 3's future `apps/runtime/providers/telephony.py`.
  - `apps/agents/forms/TwilioConnection/AgentSetting.py` — the scoped `ModelForm` (SID + write-only token +
    inbound number only; NOT the `2.1` greeting/prompt fields or the `2.3` transfer fields on the same row).
  - `apps/agents/views/TwilioConnection/AgentSetting.py` — the edit view + a `connection_check_view` (HTMX
    partial or a small JSON endpoint) that calls the telephony seam and returns a three-state result.
  - `apps/agents/models/TwilioConnection/AgentSetting.py` **only if** `2.1` has not already created the entity
    file for `AgentSetting` under a different sub-module folder — if `2.1` runs first in the actual build order,
    its `apps/agents/models/AgentConfiguration/AgentSetting.py` (or equivalent) already owns the model class, and
    `2.2` adds `set_twilio_auth_token`/`has_twilio_auth_token` as methods on that same class file, not a second
    model file. (Confirm the actual `2.1` sub-module folder name at build time — this is a note for the `todo`
    agent, not a decision this research file can make ahead of `2.1`'s own build.)
  - `templates/agents/twilio/agentsetting/form.html` and `templates/agents/twilio/agentsetting/detail.html` (or
    folded into a single settings page) per the two-level template rule (`agents` is not a foundation app) —
    sub-module folder `twilio/`, entity folder `agentsetting/`.
  - `LIVE_LINKS["2.2"]` entry in `apps/accounts/navigation.py` pointing at the Twilio connection settings page.

## Belongs to sibling sub-modules (parked, not scoped here)

- Enable toggle, voice-provider mode, greeting, prompt authoring, prompt variables → `2.1` (same `AgentSetting`
  row, different fields/form).
- Transfer enable, primary/secondary transfer numbers, transfer working hours, transfer keywords → `2.3` (same
  row, different fields/form).
- Placed test call, fake-mode test call, setup readiness check → `2.4` — this is the sub-module that actually
  dials (even if only through the fake adapter); do not fold "Connection Check" and "Test Call" into one feature —
  the `2.2` bullet is explicit that the check "reports the result WITHOUT placing a call."
- The actual Twilio Voice webhook endpoint, signature verification, dialed-number resolution, idempotent webhook
  handling → `3.1` (Module 3, service module — `2.2` only *displays* the URL these endpoints will live at).
- The ASGI media-stream consumer that the displayed `wss://` URL ultimately points to → `3.2`.
- The live Twilio telephony adapter's final home (`apps/runtime/providers/telephony.py`) → Module 3; `2.2`'s
  `apps/agents/telephony.py` is an explicitly temporary stand-in for the Connection Check's two calls only.

## Out of scope for this product (outside the seven capabilities)

- **SIP trunking / Elastic SIP Trunk import** (Retell AI, ElevenLabs Agents, PolyAI all support connecting via SIP
  in addition to a REST-webhook Twilio number) — this product's telephony model is exactly one Twilio Voice
  webhook + one media-stream websocket per location (per `NavAIReceptionist.md` §3.1–3.2); a second telephony
  transport is not one of the seven capabilities and would double Module 3's surface for no requirement anyone
  asked for.
- **Automatic number provisioning / buying a new Twilio number through the product's own UI** (Vapi, Synthflow and
  Bland AI all also let a customer buy a fresh number without leaving their dashboard) — this product only *binds*
  a number the tenant already owns in their own Twilio account; provisioning is Twilio-console work, not a feature
  of this app.
- **Multi-provider telephony (Telnyx, Vonage, direct SIP carriers)** — the brief and every module doc name Twilio
  specifically as the telephony provider; a provider-choice dropdown here is scope creep, not a researched gap.
- **Granular API-key-style permission scoping** (à la Stripe's restricted keys, or Twilio API Keys with scoped
  permissions instead of the full Account SID + Auth Token) — Twilio's Auth Token is account-wide by nature; this
  product accepts that as the credential shape it stores. Recommending "use an API Key instead of the Auth Token"
  is a real Twilio best practice but is an operator choice made in the Twilio console, not a field this product
  needs to model differently.

## Deferred (later passes / integrations)

- **Credential-change email notice** (the `0.2`-style account-takeover tripwire, applied to Twilio credentials) —
  deferred until `0.2`'s email-notice plumbing is confirmed reusable from `apps/agents`; not part of this pass's
  minimum four bullets.
- **Audit log of credential changes** — no model budget in the eleven-model ceiling; revisit only if a
  product-wide activity-log sub-module is ever scoped explicitly.
- **Auto-configuring the Twilio number's Voice URL via the Twilio API** (ElevenLabs Agents' pattern) — the
  documented `2.2` bullet specifies *display*, not *write*; auto-configuration is a real, buildable enhancement
  but is explicitly beyond this pass's scope bullet and should not be pulled forward.
- **Caching the last Connection Check result** (e.g., a "last verified at" timestamp) — would need a new field on
  `AgentSetting` or a `metadata`-style JSON column the ERD does not currently define for this model; defer rather
  than widen the schema for a nice-to-have status label. The check is cheap enough to re-run on page load or on
  click without persisting its result.
- **`sandbox` `PROVIDER_MODE` behavior for the telephony seam** — this pass treats `sandbox` the same as `fake`
  for the two Connection Check calls (deterministic canned response, no network call); a real sandbox distinction
  (e.g., hitting Twilio's actual API with test credentials, per Twilio's own Test Credentials feature) is better
  scoped once Module 3's provider adapters exist and can define what `sandbox` means product-wide.
