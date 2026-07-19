# Research — Sub-module 4.4: Calendar Views (Module 4 — Calendar & Bookings, scheduling)

## Repo state checked first

- `LIVE_LINKS` built so far in module 4 (`apps/accounts/navigation.py`, verified at run time):
  `'4.1': {'Contacts': 'scheduling:contact_list'}`,
  `'4.2': {'Services': 'scheduling:service_list', 'Resources': 'scheduling:resource_list'}`,
  `'4.3': {'Appointments': 'scheduling:appointment_list', 'Find a slot': 'scheduling:appointment_slots'}`.
  `4.4` has no entry — it is the next unbuilt sub-module, matching the invoking prompt.
- Sibling models available to read (all grep-verified to exist, none of them need to change):
  - `scheduling.Appointment` — `apps/scheduling/models/Bookings/Appointments.py` — tenant **and**
    location-scoped. `start_at`/`end_at` UTC, `status` choices `scheduled`/`confirmed`/`completed`/`cancelled`/
    `no_show`, FKs `contact` (PROTECT), `provider` (`settings.AUTH_USER_MODEL`, null, SET_NULL), `resource`
    (null, SET_NULL), `service` (null, SET_NULL). Members `local_start()`, `local_end()`, `is_open`,
    `OPEN_STATUSES`. Index `idx_appt_tenant_loc_start` on `(tenant, location, start_at)`.
  - `scheduling.Resource` — `apps/scheduling/models/ServicesResources/Resources.py` — tenant + location scoped,
    `is_active`, `display_order`, `display_label`.
  - `scheduling.Service` — `apps/scheduling/models/ServicesResources/Services.py` — nullable `location`.
  - `accounts.User` — `is_provider`, `status` (STATUS_ACTIVE gate), `user_locations` accessor to
    `accounts.UserLocation` for the assigned-location filter already used by
    `apps/scheduling/views/Bookings/Appointments.py::_location_providers`.
  - `tenants.Location` — `.tzinfo`, `.local_now()`; `ActiveLocationMiddleware` already calls
    `timezone.activate(request.location.tzinfo)`, so every template in this pass renders in the site's own zone
    for free.
  - `apps/scheduling/availability.py` — `local_day_bounds_utc(location, day)` (the ONLY correct way to build a
    day's UTC range — never `start_at__date`), `find_available_slots`, `SLOT_GRANULARITY_MINUTES=15`.
  - `templates/partials/_appointment_status_badge.html` — the single source of the status→colour map:
    `scheduled`→`badge-info`, `confirmed`→`badge-green`, `completed`→`badge-green`, `cancelled`→`badge-red`,
    `no_show`→`badge-amber`.
  - `static/css/theme.css` — already ships `.calendar-grid`, `.calendar-column`, `.calendar-column-head`,
    `.calendar-slot` (`.open`/`.booked`/`.blocked` states), `.calendar-event` with **per-status modifier classes
    already matching the badge partial 1:1** (`.calendar-event.scheduled/.confirmed/.completed/.cancelled/.no_show`),
    `.calendar-event-time`, `.calendar-event-title`, `.booking-card` family. No CSS work is implied by this
    catalog beyond using what exists.
  - `apps/scheduling/views/Bookings/Appointments.py` — `_location_appointments`, `_location_providers`,
    `_location_resources`, `_bookable_services`, `_authorised_pk`, `_parse_local_date`,
    `_save_booking_under_lock` (the manual-booking race guard) all already exist and are directly reusable by
    the grid's click-through path.
- Models verified NOT to exist: `grep "^class CallSession"` under `apps/` returns nothing — `apps/calls` has no
  files. `Appointment.booked_by_session` therefore still does not exist (4.3's research already recorded this;
  restated here only so 4.4 does not try to render an "originating call" link that has nowhere to point).
- **This confirms the invoking prompt: 4.4 adds ZERO models.** Every fact needed to draw a grid is already a
  column on `scheduling.Appointment` or a read through its FKs.

## Leaders surveyed (with source links)

1. **Acuity Scheduling** — day/week/month view switcher with per-calendar (staff) filtering and Rooms/Resources
   as a capacity control — [Managing your schedule](https://help.acuityscheduling.com/hc/en-us/articles/16676934756109-Managing-your-schedule), [Adding padding between appointments](https://help.acuityscheduling.com/hc/en-us/articles/16676926857101-Adding-padding-between-appointments)
2. **Square Appointments** — staff-colour-coded calendar with a "Combined" all-staff overlay vs. per-staff
   side-by-side, real-time double-booking prevention — [Set up calendar view filters](https://squareup.com/help/us/en/article/8442-set-up-calendar-view-filters-for-appointments), [Manage bookable staff schedules](https://squareup.com/help/us/en/article/8443-manage-staff-schedules-and-availability-with-square-appointments)
3. **Cal.com** — booker layouts (column / week / month), configurable slot-interval override for the time axis —
   [Calendar view atom](https://cal.com/docs/atoms/calendar-view), [Multiple booking layouts](https://cal.com/blog/enhanced-flexibility-take-advantage-of-cal-com-s-multiple-booking-layouts)
4. **Mindbody** — explicit **Staff View / Room View** toggle over the *same* day's data, day-at-a-time default,
   and the finding that **Week view narrows to one employee or room** rather than a full week×N-column matrix —
   [Calendar: Overview & FAQs](https://support.mindbodyonline.com/s/article/Calendar-Overview-FAQs-BKR?language=en_US), [Why can clients double book (capacity/prep-time misconfig)](https://support.mindbodyonline.com/s/article/203275113-Thor-Why-can-clients-double-book-Capacity-Prep-Times?language=en_US)
5. **Fresha** — click-an-empty-slot-to-book with the new appointment pre-coloured, and a configurable colour
   *source* (team member / service category / **status**) — [Update appointment statuses](https://www.fresha.com/help-center/knowledge-base/calendar/600-update-appointment-statuses), [Organize appointments by colour](https://www.fresha.com/help-center/knowledge-base/calendar/487-organize-appointments-by-color-in-your-calendar)
6. **Setmore** — the sharpest statement of the day-vs-week distinction: **Day view = many staff, one day**;
   **Week view = one staff member, seven days** — plus free-text status "labels" (Pending/Confirmed/Done/
   No-Show/Running Late) as a visual annotation layer on top of colour — [Default Calendar View](https://support.setmore.com/en/articles/490984-default-calendar-view), [Appointment Labels](https://support.setmore.com/en/articles/491015-appointment-labels)
7. **Jane App** — the clearest **mobile/narrow-screen degradation** pattern: a multi-column staff grid collapses
   to **one practitioner's column at a time** on a phone, swipe for the next, and week view requires landscape
   rotation — [Working With the Schedule](https://jane.app/guide/working-with-the-schedule), [Using Jane on a Smartphone](https://jane.app/guide/using-jane-on-a-smartphone)
8. **NexHealth** — the **operatory (room) is the capacity-limiting resource**, distinct from the provider, and
   scheduling can be set "by operatory" — the clearest real-world analog to this product's own
   resource-vs-provider split, since a provider can be double-booked across operatories but an operatory cannot —
   [NexHealth Scheduling](https://www.nexhealth.com/features/scheduling), [Operatories](https://docs.nexhealth.com/v2.2.2/reference/operatories-1)
9. **Google Calendar** — the reference implementation for the time axis and **overlap layout**: sort events by
   start time, group overlapping events, assign side-by-side sub-columns/widths so nothing is visually hidden —
   [Overlapping events discussion](https://support.google.com/calendar/thread/203429627/google-calendar-display-of-overlapping-events?hl=en), [Day View walkthrough](https://dev.to/arghya_majumder/google-calendar-day-view-42a0)

## Feature catalog (this sub-module only)

### Day & Week Grid
- **Day-at-a-time default, columns = the day's capacity units** — every leader (Mindbody, Jane, Square) treats
  Day as the primary working view: one date, N columns · seen in: Mindbody, Jane, Acuity · priority:
  table-stakes · model: reuses `scheduling.Appointment` filtered by `local_day_bounds_utc(location, date)`
  (tenant + location scoped, read-only) · realtime: **post-call** (a page, not the live-call hot path) ·
  tool-surface: pure UI · buildable now.
- **Week view narrows to ONE resource/provider, not a full week×N matrix** — the load-bearing finding from
  research: Mindbody's own help text is explicit ("review the weekly schedule for an Employee or Room ... the
  Calendar view refreshes and displays the Appointments for the week") and Setmore states the same rule flatly
  ("Week view shows all appointments for one team member at a time"). A week grid with 7 day-columns × N
  resource-sub-columns is not what any surveyed leader ships — it does not fit a screen and nobody builds it ·
  priority: table-stakes (recommended design decision, not just a nice-to-have — it prevents a doomed
  20-column week grid) · model: reuses `Appointment` filtered across 7×`local_day_bounds_utc` calls for one
  chosen provider or resource · realtime: post-call · tool-surface: pure UI, `?view=week&provider=<id>` or
  `&resource=<id>` (authorised against `_location_providers`/`_location_resources`, same pattern as
  `appointment_list_view`) · buildable now.
- **Fixed-height time axis at the booking engine's own granularity (15 min)** — the grid's implied slot
  boundaries should match what `find_available_slots` would actually offer, so a receptionist's eye and the
  agent's own slot search never disagree · seen in: general market convention (5/10/15-min row height), and
  this product's own `SLOT_GRANULARITY_MINUTES = 15` tunable · priority: table-stakes · model: reuses
  `availability.SLOT_GRANULARITY_MINUTES` as the CSS row-height/scale constant, no new field · realtime:
  post-call · tool-surface: pure UI · buildable now.
- **"Now" line and hour labels on the time axis** — a horizontal marker at the current wall-clock time in the
  location's own zone · seen in: Google Calendar (table stakes) · priority: common · model: reuses
  `Location.local_now()` · realtime: post-call · tool-surface: pure UI · buildable now.
- **Today / prev / next / explicit date-picker navigation** — every leader ships all four · priority:
  table-stakes · model: none — `?date=YYYY-MM-DD` parsed the same way `appointment_list_view` already parses
  `?from=`/`?to=` (`_parse_local_date`, degrades a junk value to "today" rather than raising) · realtime:
  post-call · tool-surface: pure UI · buildable now.
- **Half-open UTC range per day/week, never `__date`** — this sub-module's own HARD FACTS restated as a
  feature: every day/week boundary MUST go through `local_day_bounds_utc`, chained 7× for a week (Mon 00:00
  local → next Mon 00:00 local), never a single `start_at__range` built from naive dates · priority: REQUIRED
  (a `__date` grid silently renders empty in production MySQL while passing every SQLite test) · model: reuses
  `availability.local_day_bounds_utc` · realtime: post-call · tool-surface: pure UI (backend query
  construction) · buildable now.

### By Resource and By Provider
- **Column-source toggle that reuses the same base queryset** — Mindbody's Staff View/Room View dropdown and
  NexHealth's "by operatory" toggle are both a *grouping* choice over the same appointments, not a different
  query · seen in: Mindbody, NexHealth · priority: table-stakes (this is 4.4's own second bullet) · model:
  reuses `Appointment` (read-only); the SAME `_location_appointments(request)` queryset for the visible
  date/week is bucketed in Python by `.resource_id` or `.provider_id` depending on `?by=resource|provider` ·
  realtime: post-call · tool-surface: pure UI — the toggle changes only which FK is used to build columns, the
  SQL `WHERE` clause is unchanged · buildable now.
- **Column list comes from the active location's real resources/providers, not from what happens to have a
  booking today** — an empty room must still show as an empty column (so a receptionist can see it's free),
  not disappear · seen in: Acuity, Mindbody (both list every staff/room calendar whether or not it has bookings
  today) · priority: table-stakes · model: reuses `_location_resources(request)` /
  `_location_providers(request)` (already `is_active=True` / `status=User.STATUS_ACTIVE` filtered, per this
  sub-module's own HARD FACTS) as the column headers, independent of which columns have appointments ·
  realtime: post-call · tool-surface: pure UI · buildable now.
- **An explicit "Unassigned" catch-all column** — `Appointment.resource` and `.provider` are both nullable
  (per the ERD and the as-built model), so a phone-only service or a not-yet-assigned booking has neither; a
  strict resource/provider grouping must not silently drop it off the grid · seen in: this is this product's
  own consequence of a nullable FK, not copied from a single leader, but NexHealth's operatory-vs-provider
  split makes the same point (a booking can be provider-only, room-only, or neither) · priority: REQUIRED (a
  booking that exists in the database but never renders on the calendar is a data-integrity bug, not a cosmetic
  gap) · model: reuses `Appointment.resource`/`.provider` IS NULL · realtime: post-call · tool-surface: pure
  UI · buildable now.
- **Overlap-safe layout within a column** — Google Calendar's sort-then-bucket approach (sort by `start_at`,
  group overlapping events, assign side-by-side sub-lanes) so two appointments that land in the same
  resource/provider column at overlapping times are both visible rather than stacked illegibly · seen in:
  Google Calendar (the reference algorithm) · priority: common — **not REQUIRED**, because `Resource` carries
  no capacity and a genuine double-booking inside one column should be rare (the 4.3 booking path already
  locks against it); this is a defensive rendering rule for the edge cases that do slip through (a manual
  override, a rescheduled appointment landing on a stale row) rather than a load-bearing feature · model:
  pure view/template computation over the same `Appointment` rows, no new field · realtime: post-call ·
  tool-surface: pure UI · buildable now (simple two-events-side-by-side case; the full N-lane packing algorithm
  is explicitly not required for a small app — see Deferred).

### Slot Click-Through
- **Clicking an empty grid cell opens the existing manual-booking form, pre-filled** — Fresha and Google
  Calendar both create-with-prefill on an empty-slot click; this product already has that form
  (`appointment_create_view` / `AppointmentForm`, 4.3) — 4.4 only needs to pass `?date=&time=&resource=&
  provider=` through to it and have the form read those as `initial=` values · seen in: Fresha, Acuity, Google
  Calendar · priority: table-stakes (4.4's own third bullet) · model: reuses `scheduling.Appointment` via the
  **existing** `appointment_create_view`, no new view logic beyond querystring→`initial` plumbing · realtime:
  post-call · tool-surface: pure UI (small, additive change to `AppointmentForm.__init__` to accept prefill
  kwargs) · buildable now.
- **Clicking an existing block navigates to the read-only detail page, not create** — prevents an accidental
  double-booking through the grid itself; "move it" is a deliberate action (the "Reschedule" button on the
  detail page, which already routes into 4.3's slot-search-in-reschedule-mode) · seen in: Fresha, Google
  Calendar (click event → view/edit, distinct from click empty cell → create) · priority: table-stakes · model:
  reuses `appointment_detail_view` (4.3, unchanged) · realtime: post-call · tool-surface: pure UI · buildable
  now.
- **The grid-click path is the manual form, not the token-search-and-offer flow** — an important scoping
  decision from synthesizing the leaders against this product's own two existing booking paths (4.3 shipped
  both a direct manual form AND a `find_available_slots` → `slot_token` → `book_slot` search flow). A grid click
  means the staff member already looked at the calendar and chose an exact time/column visually — that is
  the manual-form use case, not "let the system suggest 3 times." Routing a grid click through the slot-search
  page instead would re-litigate a decision the person already made by clicking · priority: table-stakes
  (design clarification) · model: n/a (routing decision only) · realtime: post-call · tool-surface: pure UI.
- **Race protection on a grid-originated booking is already covered** — the click-through reuses
  `appointment_create_view`, which already calls `_save_booking_under_lock` (row-level lock + in-transaction
  overlap re-check); no new locking logic is implied by adding the grid as a second entry point into the same
  form · priority: REQUIRED (data integrity, already satisfied by reuse) · model: reuses
  `_save_booking_under_lock` · realtime: post-call · tool-surface: none (behaviour inherited) · buildable now.

### Status Colouring
- **One canonical colour source: `status`, via the existing shared badge contract** — Fresha ships a
  *configurable* colour source (team member / category / status); this product deliberately does not need that
  configurability because `.calendar-event.<status>` classes and `_appointment_status_badge.html` already
  define ONE map, and the sub-module's own bullet says "using the shared badge contract," not "a
  configurable one" · priority: REQUIRED (the sub-module's own 4th bullet, and reusing the existing map is
  what keeps the calendar and every other status display — list, detail — visually consistent) · model:
  reuses `Appointment.status` + `templates/partials/_appointment_status_badge.html` +
  `.calendar-event.{scheduled,confirmed,completed,cancelled,no_show}` (all already shipped, zero CSS work) ·
  realtime: post-call · tool-surface: pure UI (`class="calendar-event {{ obj.status }}"`) · buildable now.
- **Cancelled and no-show stay visible on the grid, not hidden or removed** — Fresha and Acuity render a
  distinct colour for these rather than deleting the block, so a receptionist scanning the day still sees
  "this slot WAS booked and fell through," which matters for follow-up · priority: common · model: reuses the
  same unfiltered `Appointment` queryset (no default status exclusion) · realtime: post-call · tool-surface:
  pure UI · buildable now.
- **A small legend/key next to the grid** — five colour chips labelled with the plain-English status name, so
  a receptionist glancing at the grid does not have to hover every block · seen in: Fresha, Setmore (status
  "labels" as an explicit visual annotation) · priority: common · model: none — a static partial listing the
  five `Appointment.STATUS_CHOICES` against their badge classes · realtime: post-call · tool-surface: pure
  UI · buildable now.

### Beyond the bullets
- **At-a-glance status counts for the visible day/week** ("6 scheduled · 2 confirmed · 1 cancelled") · seen
  in: Square, Mindbody (dashboard-style summary strips above the grid) · priority: differentiator · model:
  reuses `Appointment.objects.filter(...).values('status').annotate(Count('id'))` over the same scoped
  queryset, no new field · realtime: post-call · tool-surface: pure UI · buildable now (cheap, single grouped
  query).
- **Mobile/narrow-screen column collapse** — Jane App's pattern (one column visible at a time on a phone, with
  a `<select>`/swipe to change which resource or provider is showing) rather than requiring landscape rotation
  or an unreadable squeezed grid · seen in: Jane App · priority: table-stakes for a responsive product ·
  model: none — Tailwind responsive classes plus a `<select name="column">` that submits the same `?by=` /
  `?resource=`/`?provider=` query params already defined above, so mobile and desktop share one URL contract ·
  realtime: post-call · tool-surface: pure UI · buildable now.

## Compliance & provider constraints

- **No new compliance surface.** 4.4 places no Twilio, STT, TTS or LLM call and touches no recording or
  consent flow — it is a read-only page over `scheduling.Appointment`, mirroring 4.3's research finding that
  the REQUIRED items (recording consent basis, two-party-consent announcement, AI disclosure, HIPAA/GDPR
  retention) belong to Module 3 and Module 5, not to `scheduling`.
- **PII discipline still applies to what the grid renders.** Each `.calendar-event` block shows
  `contact.display_name` (a name) and, on hover/detail, the reason/notes text — the same caller-dictated PII
  already governed by the scheduling skill's convention: never log a name, number or note body at INFO, never
  render `notes` with `|safe`. This sub-module adds a rendering surface for that data; it does not relax the
  rule.
- **No cost line appended to `calls.CallSession.usage`.** This sub-module makes no provider call and
  `calls.CallSession` does not exist yet — nothing here is billed or metered.
- **Query cost, not provider cost, is the actual constraint.** A week view must not silently run seven
  unindexed table scans — every day/week boundary goes through `local_day_bounds_utc`, which is built to hit
  `idx_appt_tenant_loc_start`; the column-bucketing (resource vs provider) happens in Python on an already
  `.select_related('contact', 'service', 'resource', 'provider')` queryset (reused from `_location_appointments`)
  so grouping by column adds no extra query.

## Recommended build scope (this pass)

**VIEW sub-module — ZERO models and ZERO migrations.** `makemigrations scheduling --check` reporting "No
changes detected" is part of this sub-module's own acceptance criteria (stated in the invoking prompt), and
every feature above reads a table that already exists:

- **Tables READ:** `scheduling.Appointment` (primary — `start_at`/`end_at`/`status`/`contact`/`provider`/
  `resource`/`service`), `scheduling.Resource` (column headers when grouping "by resource"), `accounts.User`
  (column headers when grouping "by provider", via `is_provider`/`status`/`user_locations`), `tenants.Location`
  (timezone, `local_now()` for the "now" line), `scheduling.Contact` (display name on each block, already
  `select_related` by the reused queryset).
- **Pages:** a day grid (`templates/scheduling/calendar/day.html` — the standalone-page shape this project's
  own template rules name explicitly for this exact page) and a week grid
  (`templates/scheduling/calendar/week.html`, sibling standalone page, narrowed to one resource/provider per
  the Mindbody/Setmore finding above). Backend as a `CalendarViews/` folder under `views/` and `urls/` (no
  `models/`/`forms/` folder — this sub-module adds neither), re-exported from each package `__init__.py`.
- **Filters (all GET params, all degrading to a safe default on junk input, same pattern as
  `appointment_list_view`):** `date` (defaults to the location's "today," via `_parse_local_date`), `by`
  (`resource`|`provider`, defaults to one — recommend `provider`, since staff already navigate by provider name
  elsewhere in this app — but either default is defensible and the todo/build pass should pick one and note
  it), and for week mode a single `provider=<id>` or `resource=<id>` (authorised via `_authorised_pk` against
  `_location_providers`/`_location_resources`, exactly as `appointment_list_view` already authorises its own
  FK filters).
- **Click-through wiring (not a new page):** an additive change to `appointment_create_view`/`AppointmentForm`
  so a grid cell's `?date=&time=&resource=&provider=` becomes the form's `initial=` values — reuses the
  existing 4.3 form and its `_save_booking_under_lock` race guard rather than adding a second booking code
  path.
- **Exports:** none — the four bullets name no export/print surface, and none of the surveyed leaders' feature
  pages for *this* slice (day/week grid mechanics) call one out either. A printable day sheet (Jane's "Day
  Sheet") is real but unrequested — see Deferred.
- **`LIVE_LINKS["4.4"]`:** one entry pointing at the day grid, e.g. `{'Calendar': 'scheduling:calendar_day'}` —
  the week view is reached from within the day view (a "view full week" link per provider/resource column), not
  a second sidebar row.

## Belongs to sibling sub-modules (parked, not scoped here)

- Appointment list with date-range/status/provider/resource/service filters and contact search (the tabular,
  non-grid view) → **4.5 Bookings List & Callback Requests** — already built in 4.3 as `appointment_list_view`
  and stays there; 4.4 is the grid, not a second list page.
- `CallbackRequest` queue and resolution → **4.5**.
- `booked_by_session` FK / "originating call" panel on the appointment detail page → **Module 5**, once
  `calls.CallSession` exists (recorded already in 4.3's research; restated here only so 4.4 does not attempt to
  render a link that has nothing to point to).
- LLM tool registration for anything the calendar surfaces (there is none — this sub-module registers no tools,
  same posture as 4.1/4.2/4.3) → n/a, no sibling to park it to.

## Out of scope for this product (outside the seven capabilities)

- **External calendar sync (Google/Outlook two-way sync into this grid)** — several leaders' *day/week grid*
  pages are themselves views over a synced external calendar; this product's calendar **is**
  `scheduling.Appointment` and has no second calendar to reconcile against. Tempting to conflate because the
  research explicitly used Google Calendar as a mechanics reference — that reference is for layout algorithms
  only, not a sync integration.
- **Drag-and-drop rescheduling directly on the grid** — a real differentiator in Square, Fresha and Google
  Calendar, but not one of the four bullets (only "Slot Click-Through" is named) and not required to satisfy
  reschedule — the existing detail-page "Reschedule" button already routes into 4.3's slot-search-in-
  reschedule-mode. Building drag-and-drop now adds JS/HTMX complexity beyond what this pass asks for →
  Deferred, not Out of scope (it is within the calendar capability, simply unrequested).
- **SMS/email confirmations or reminders triggered from the grid** — outside the seven capabilities (no
  outbound notification channel in this product), same finding as 4.3's research.
- **Payments/deposit holds at booking time** — outside the seven capabilities, same finding as 4.3's research.

## Deferred (later passes / integrations)

- **Full N-lane overlap-packing algorithm** (Google Calendar's general case) — the simple two-events-side-by-
  side rule covers this product's realistic edge cases (Resource has no capacity, so true same-column overlaps
  are rare); a general N-lane packer is more machinery than a small app's actual overlap rate justifies.
- **Configurable colour source (team member / category / status), à la Fresha** — this product intentionally
  keeps ONE status-based colour map (the shared badge contract named in the sub-module's own bullet); adding
  configurability would fork that single source of truth for no requested benefit.
- **"Combined" all-staff overlay view (Square)** — an alternate rendering mode (everyone in one column,
  colour-coded by staff) that isn't asked for by the bullets and sits awkwardly against the "switch the grid's
  COLUMNS between resources and providers" requirement, which specifically wants columns, not an overlay.
- **Month view** — Acuity/Square both ship one; not named by any of 4.4's four bullets (which specifically say
  "Day & Week"), and a month view's information density (which cell shows what on a 30-day grid) is a
  meaningfully different UI problem better scoped on its own if ever requested.
- **Printable/exportable day sheet** (Jane App's "Day Sheet") — a real, low-effort addition later (this
  project already has print-page precedent at `calls/transcript/transcript_print.html`), but not named by any
  of 4.4's bullets — do not build speculatively.
- **Per-status "hide cancelled/no-show" toggle** — a small, plausible convenience filter, but not requested by
  the bullets, which explicitly want status *coloured*, not filtered out; deferring keeps the full-day picture
  intact by default as several leaders' research (Fresha, Acuity) also prefers.
