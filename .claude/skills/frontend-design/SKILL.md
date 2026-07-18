---
name: frontend-design
description: The NavAIReceptionist design-system pattern reference — the static/css/theme.css class contract, copy-pasteable list/detail/form page skeletons, the filter-bar pattern (view context + template comparison), the pagination partial and its page-2 guard, the badge status maps (including the canonical call-status map), the empty-state and confirm-delete patterns, the calendar and booking surfaces, and the voice components (.transcript-turn, .call-status-dot, .live-badge, .waveform, the audio-player partial). Use when building or changing anything under templates/, when a list page needs working filters or an Actions column, when adding a badge/stat card/pagination block, when rendering the calendar, a booking form, transcripts, live-call state or recordings, or when the user invokes /frontend-design.
---

# frontend-design — NavAIReceptionist UI pattern reference

This is the constructive counterpart to the `frontend-reviewer` agent. That agent tells you what is wrong; this
skill gives you the exact markup to write so it never is.

The stack is server-rendered Django templates + Tailwind (Play CDN) + HTMX + Lucide, over the design system in
`static/css/theme.css`. There is no SPA, no React, no client-side router. Live surfaces use Django Channels
websocket consumers, not polling.

**Read this before you write a template. Copy the skeletons; do not improvise a second visual language.**

---

## 0. The one rule that outranks the rest

`static/css/theme.css` is the **source of truth**, this file is a description of it. Before using any modifier
class, confirm it exists:

```powershell
Get-Content static/css/theme.css | Select-String -Pattern '\.(badge-[a-z]+|stat-icon(\.[a-z]+)?|text-[a-z]+)' -AllMatches
```

or the portable form the reviewer uses:

```
grep -oE '\.(badge-[a-z]+|stat-icon(\.[a-z]+)?|text-[a-z]+)' static/css/theme.css | sort -u
```

A class that does not exist renders as an **unstyled** pill or icon tile. Nothing else in the toolchain catches
that — no test, no type checker, no Python reviewer sees a cosmetic-only failure. When in doubt, copy a sibling
template verbatim rather than inventing a name.

---

## 1. The theme.css class contract

The design system is **colour-named and fixed**. There are **no semantic variants**: `badge-success`,
`badge-danger`, `badge-warning`, `stat-icon red`, `stat-icon amber` do not exist and never will.

### Layout & page chrome
| Class | Use |
|---|---|
| `.page-header` | wrapper for the title row at the top of every page |
| `.page-title` | the H1 text |
| `.breadcrumb` | right-aligned trail, e.g. `NavAIReceptionist › Call Logs › Call Log` |
| `.card` / `.card-header` / `.card-body` | the universal white panel |
| `.stat-card` | KPI tile: icon tile + big metric + label + faint sparkline |
| `.stat-icon` + one of `blue` `green` `orange` `purple` `slate` | the soft-tinted icon tile inside a stat card (compound selector — `.stat-icon.green`) |
| `.location-switcher` | the active-location control in the topbar (see §9) |

### Controls
| Class | Use |
|---|---|
| `.btn` | base button; always combined with a variant |
| `.btn-primary` | the single primary action on the page |
| `.btn-outline` | secondary actions, Back-to-List |
| `.btn-danger` | delete / destructive submit |
| `.btn-icon` | icon-only square button (requires `aria-label` or `title`) |

### Data display
| Class | Use |
|---|---|
| `.badge` + one of `badge-green` `badge-red` `badge-amber` `badge-info` `badge-muted` `badge-slate` | status pills (see §5) |
| `.table-wrap` | **required** wrapper around every `.table` — gives horizontal scroll on mobile |
| `.table` | the data table |
| `.table-actions` | the right-aligned Actions cell contents |
| `.empty-state` | the zero-rows block (see §6) |
| `.pagination` | the pager (see §4) |
| `.avatar-initial` | initials circle for a contact/user without a photo |
| `.progress` / `.progress-bar` | horizontal progress bars in list widgets |

### Forms
`.form-group` · `.form-label` · `.form-input` · `.form-select` · `.form-textarea` · `.form-error`

### Calendar & booking components (product-specific — see §8)
`.calendar-grid` · `.calendar-column` · `.calendar-slot` (+ `.calendar-slot.open` / `.booked` / `.blocked`) ·
`.calendar-event` · `.booking-card`

### Voice components (product-specific — see §9)
`.call-status-dot` · `.transcript-turn` (+ `.transcript-turn.agent` / `.transcript-turn.user`) · `.waveform` ·
`.live-badge`

---

## 2. Page skeletons

Every page extends `base.html`. `base.html` and `templates/partials/` live at the templates root and are never
copied into a module folder. Template paths follow CLAUDE.md's Template Folder Structure rule:
`templates/<app>/<submodule>/<entity>/<page>.html` for the domain apps (`agents` / `runtime` / `scheduling` /
`calls`), `templates/<app>/<entity>/<page>.html` for the flat foundation apps (`accounts` / `tenants`).

### 2.1 List page — `templates/calls/calllog/callsession/list.html`

```django
{% extends "base.html" %}
{% block title %}Call Log{% endblock %}

{% block content %}
<div class="page-header">
  <h1 class="page-title">Call Log</h1>
  <nav class="breadcrumb" aria-label="Breadcrumb">
    NavAIReceptionist › Call Logs › {{ request.location.name }}
  </nav>
</div>

{% include "calls/calllog/callsession/_filters.html" %}

<div class="card">
  <div class="card-header">
    <span>{{ page_obj.paginator.count }} call{{ page_obj.paginator.count|pluralize }}</span>
  </div>
  <div class="card-body">
    {% if call_sessions %}
    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th scope="col">Caller</th>
            <th scope="col">To</th>
            <th scope="col">Started</th>
            <th scope="col">Duration</th>
            <th scope="col">Status</th>
            <th scope="col" class="text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {% for r in call_sessions %}
          <tr>
            <td>
              {% if r.contact %}{{ r.contact.first_name }} {{ r.contact.last_name }}
              {% else %}{{ r.from_number|phone_e164 }}{% endif %}
            </td>
            <td>{{ r.to_number|phone_e164 }}</td>
            <td>{{ r.started_at|date:"d M Y, H:i" }}</td>
            <td>{{ r.duration_display|default:"—" }}</td>
            <td>{% include "partials/_call_status_badge.html" with obj=r %}</td>
            <td class="table-actions">
              <a class="btn btn-icon" title="View" aria-label="View call from {{ r.from_number }}"
                 href="{% url 'calls:callsession_detail' r.pk %}"><i data-lucide="eye"></i></a>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% include "partials/_pagination.html" %}
    {% else %}
      {% include "partials/_empty_state.html" with icon="phone-off" title="No calls yet" message="Calls answered at this location will appear here." %}
    {% endif %}
  </div>
</div>
{% endblock %}
```

Notes that are not optional:
- The loop variable name **must** match the view's context key (`call_sessions` here), and field names must match
  the model (`from_number`, not `from_e164`). A mismatch renders a silently blank region — HTTP 200, no error.
- The nullable-FK guard on `r.contact` is required. Unknown and blocked caller ID is normal traffic here, so
  `{{ r.contact.first_name|default:r.from_number }}` **500s** — a `None` FK inside a *filter argument* raises,
  while a bare lookup only renders blank. Use `{% if %}`.
- **`CallSession` rows are written by the runtime and have no Edit or Delete controls.** Their absence is correct;
  an unguarded Delete button on a call log is the bug.
- Every location-scoped list page shows **which location's data it is** — the breadcrumb here, or the
  `.location-switcher` in the topbar.

### 2.2 Detail page — `templates/calls/calllog/callsession/detail.html`

```django
{% extends "base.html" %}
{% block title %}Call {{ obj.pk }}{% endblock %}

{% block content %}
<div class="page-header">
  <h1 class="page-title">{{ obj.from_number|phone_e164 }}</h1>
  <nav class="breadcrumb" aria-label="Breadcrumb">NavAIReceptionist › Call Logs › {{ obj.location.name }}</nav>
</div>

<div class="grid gap-4 lg:grid-cols-3">
  <div class="lg:col-span-2 space-y-4">
    <div class="card">
      <div class="card-header"><span>Summary</span>
        {% include "partials/_call_status_badge.html" with obj=obj %}</div>
      <div class="card-body">
        <dl class="grid gap-3 sm:grid-cols-2">
          <div><dt class="form-label">From</dt><dd>{{ obj.from_number|phone_e164 }}</dd></div>
          <div><dt class="form-label">To</dt><dd>{{ obj.to_number|phone_e164 }}</dd></div>
          <div><dt class="form-label">Location</dt><dd>{{ obj.location.name }}</dd></div>
          <div><dt class="form-label">Contact</dt>
            <dd>{% if obj.contact %}
                  <a href="{% url 'scheduling:contact_detail' obj.contact.pk %}">
                    {{ obj.contact.first_name }} {{ obj.contact.last_name }}</a>
                {% else %}<span class="badge badge-muted">Unknown caller</span>{% endif %}</dd></div>
        </dl>
      </div>
    </div>

    {% include "partials/_transcript.html" with session=obj turns=turns %}
    {% include "partials/_transfer_outcome.html" with transfer=obj.transfer %}
    {% include "partials/_audio_player.html" with session=obj recording_url=recording_url %}
  </div>

  <aside class="space-y-4">
    <div class="card">
      <div class="card-header"><span>Cost</span></div>
      <div class="card-body">
        {# total_cost_usd is summed in the VIEW over CallSession.usage — no stored total #}
        <p class="text-2xl">${{ total_cost_usd|floatformat:4 }}</p>
        <p class="text-muted text-sm">{{ obj.usage|length }} turn{{ obj.usage|length|pluralize }}</p>
      </div>
    </div>
    <div class="card">
      <div class="card-header"><span>Actions</span></div>
      <div class="card-body">
        <a class="btn btn-outline w-full" href="{% url 'calls:callsession_list' %}">
          <i data-lucide="arrow-left"></i> Back to List</a>
      </div>
    </div>
  </aside>
</div>
{% endblock %}
```

A call log is read-only: there is no Edit and no Delete in this sidebar, and that absence is correct.

### 2.3 Form page — `templates/scheduling/bookings/appointment/form.html`

One template serves create **and** edit; the view passes the bound-or-empty form and an `is_edit` flag.

```django
{% extends "base.html" %}
{% block title %}{% if is_edit %}Edit{% else %}New{% endif %} Appointment{% endblock %}

{% block content %}
<div class="page-header">
  <h1 class="page-title">{% if is_edit %}Edit Appointment{% else %}New Appointment{% endif %}</h1>
  <nav class="breadcrumb" aria-label="Breadcrumb">NavAIReceptionist › Calendar &amp; Bookings › Appointments</nav>
</div>

<form method="post" novalidate>
  {% csrf_token %}
  <div class="card">
    <div class="card-body grid gap-4 sm:grid-cols-2">
      {% for field in form %}
      <div class="form-group{% if field.field.widget.input_type == 'textarea' %} sm:col-span-2{% endif %}">
        <label class="form-label" for="{{ field.id_for_label }}">{{ field.label }}</label>
        {{ field }}
        {% if field.help_text %}<p class="text-muted text-sm">{{ field.help_text }}</p>{% endif %}
        {% for error in field.errors %}<p class="form-error">{{ error }}</p>{% endfor %}
      </div>
      {% endfor %}
      {% for error in form.non_field_errors %}<p class="form-error sm:col-span-2">{{ error }}</p>{% endfor %}
    </div>
    <div class="card-header">
      <a class="btn btn-outline" href="{% url 'scheduling:appointment_list' %}">Cancel</a>
      <button type="submit" class="btn btn-primary">
        <i data-lucide="check"></i> {% if is_edit %}Save Changes{% else %}Create{% endif %}
      </button>
    </div>
  </div>
</form>
{% endblock %}
```

The form class must render `.form-input` / `.form-select` / `.form-textarea` via widget `attrs` (set once in the
shared `TenantModelForm`), so templates never hand-style inputs. `tenant` and `location` are **excluded** from
every form — they come from `request.tenant` / `request.location`, never from a posted field, and a form that
exposes `location` as a `<select>` is a cross-location IDOR.

Never put a provider credential in `Meta.fields` — `AgentSetting.twilio_auth_token` in a `ModelForm` ships in the
edit page's `value=` attribute in plaintext. It is **write-only**: a blank-means-unchanged password input, never a
rendered value.

---

## 3. The filter bar — CLAUDE.md's Filter Implementation Rules end to end

Every list page has working filters. Filters are a **GET** form; they are applied to the queryset **before**
pagination; and a junk value degrades to "no filter" instead of raising.

### 3.1 The view side (pass everything the template reads)

```python
@login_required
def callsession_list_view(request):
    qs = (CallSession.objects
          .filter(tenant=request.tenant, location=request.location)   # BOTH, always
          .select_related('contact')
          .order_by('-started_at'))

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(from_number__icontains=q) |
                       Q(contact__first_name__icontains=q) |
                       Q(contact__last_name__icontains=q))

    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)

    contact_id = request.GET.get('contact', '')
    if contact_id.isdigit():        # junk (?contact=abc) degrades to "no filter", never 500s
        qs = qs.filter(contact_id=int(contact_id))

    page_obj = Paginator(qs, 25).get_page(request.GET.get('page'))
    return render(request, 'calls/calllog/callsession/list.html', {
        'call_sessions': page_obj.object_list,   # the template loops over THIS name
        'page_obj': page_obj,
        'status_choices': CallSession.STATUS_CHOICES,      # for the status <select>
        'contacts': Contact.objects.filter(tenant=request.tenant),   # for the FK <select>
    })
```

Rules: never assume the template gets data the view did not explicitly pass; pass `status_choices` for status
dropdowns and the queryset itself for FK dropdowns (locations, services, resources, providers, contacts); apply
every filter before the `Paginator`. **Every FK dropdown queryset is itself tenant-scoped — and location-scoped
when the model is** — or the filter bar leaks another location's resource names.

### 3.2 The template side — `_filters.html`

```django
<form method="get" class="card card-body flex flex-wrap items-end gap-3">
  <div class="form-group grow">
    <label class="form-label" for="f-q">Search</label>
    <input class="form-input" type="search" id="f-q" name="q"
           value="{{ request.GET.q|default:'' }}" placeholder="Number, caller name…">
  </div>

  <div class="form-group">
    <label class="form-label" for="f-status">Status</label>
    <select class="form-select" id="f-status" name="status">
      <option value="">All statuses</option>
      {% for value, label in status_choices %}
        <option value="{{ value }}" {% if request.GET.status == value %}selected{% endif %}>{{ label }}</option>
      {% endfor %}
    </select>
  </div>

  <div class="form-group">
    <label class="form-label" for="f-contact">Contact</label>
    <select class="form-select" id="f-contact" name="contact">
      <option value="">All contacts</option>
      {% for c in contacts %}
        <option value="{{ c.pk }}"
                {% if request.GET.contact == c.pk|stringformat:"d" %}selected{% endif %}>
          {{ c.first_name }} {{ c.last_name }}</option>
      {% endfor %}
    </select>
  </div>

  <div class="form-group">
    <button type="submit" class="btn btn-primary"><i data-lucide="filter"></i> Filter</button>
    <a class="btn btn-outline" href="{{ request.path }}">Reset</a>
  </div>
</form>
```

**Comparison rules — memorize these two:**
- String/choice field: `{% if request.GET.status == value %}selected{% endif %}`
- FK / pk: `{% if request.GET.contact == c.pk|stringformat:"d" %}selected{% endif %}` — **never `|slugify`.**
  `|slugify` on a pk produces a string that never matches the raw GET value, so the dropdown silently forgets the
  selection after every submit.

---

## 4. Pagination — the partial and the page-2 guard

`page_obj.previous_page_number` and `page_obj.next_page_number` **raise `EmptyPage`** when there is no such page.
With small seed data page 2 never exists, so the bug is invisible in development and a 500 in production. They must
sit inside their `has_previous` / `has_next` guards.

Filter and search params must survive pagination — otherwise page 2 shows the unfiltered list.

`templates/partials/_pagination.html`:

```django
{% if page_obj.paginator.num_pages > 1 %}
{% querystring_without_page as qs %}   {# helper filter/tag that strips only `page` #}
<nav class="pagination" aria-label="Pagination">
  <span class="text-muted">
    Showing {{ page_obj.start_index }}–{{ page_obj.end_index }} of {{ page_obj.paginator.count }}
  </span>

  {% if page_obj.has_previous %}
    <a class="btn btn-icon" aria-label="Previous page"
       href="?page={{ page_obj.previous_page_number }}{{ qs }}"><i data-lucide="chevron-left"></i></a>
  {% endif %}

  {% for n in page_obj.paginator.page_range %}
    {% if n == page_obj.number %}
      <span class="btn btn-primary" aria-current="page">{{ n }}</span>
    {% else %}
      <a class="btn btn-outline" href="?page={{ n }}{{ qs }}">{{ n }}</a>
    {% endif %}
  {% endfor %}

  {% if page_obj.has_next %}
    <a class="btn btn-icon" aria-label="Next page"
       href="?page={{ page_obj.next_page_number }}{{ qs }}"><i data-lucide="chevron-right"></i></a>
  {% endif %}
</nav>
{% endif %}
```

If no querystring helper exists yet, the explicit form is acceptable and equally correct:
`?page={{ n }}&q={{ request.GET.q|default:'' }}&status={{ request.GET.status|default:'' }}`.

---

## 5. Badge status maps

A badge is coloured from the model's **exact** CHOICES value and always ends in an `{% else %}` fallback that
prints `{{ obj.get_FIELD_display }}`. Value drift is the classic trap: `'in_progress'` vs `'inprogress'`,
`'no_show'` vs `'noshow'`. Grep the model before you write the branch.

### 5.1 Canonical call-status map — `templates/partials/_call_status_badge.html`

**This section is the single source of truth for the call-status badge map.** Every other file that reproduces it
must state all five rows exactly as below.

| Status value | Class |
|---|---|
| `in_progress` | `badge-info` |
| `completed` | `badge-green` |
| `abandoned` | `badge-muted` |
| `transferred` | `badge-info` |
| `failed` | `badge-red` |

Five statuses share four badge classes; `badge-info` is intentionally used twice. **There is no `badge-purple`** —
`purple` exists only as a `stat-icon` variant (§1), so writing `badge-purple` for `transferred` names a class this
same design system forbids and renders an unstyled pill.

```django
{% if obj.status == 'in_progress' %}<span class="badge badge-info">In Progress</span>
{% elif obj.status == 'completed' %}<span class="badge badge-green">Completed</span>
{% elif obj.status == 'abandoned' %}<span class="badge badge-muted">Abandoned</span>
{% elif obj.status == 'transferred' %}<span class="badge badge-info">Transferred</span>
{% elif obj.status == 'failed' %}<span class="badge badge-red">Failed</span>
{% else %}<span class="badge badge-muted">{{ obj.get_status_display }}</span>{% endif %}
```

The trailing `{% else %}` is mandatory even though all five values are branched — a status added to the model
later must still render something, and `{{ obj.get_status_display }}` is what it renders.

### 5.2 Other recurring maps

| Domain | Value → class |
|---|---|
| Appointment | `scheduled`→`badge-info`, `confirmed`→`badge-green`, `completed`→`badge-green`, `cancelled`→`badge-red`, `no_show`→`badge-amber` |
| Callback request | `pending`→`badge-amber`, `contacted`→`badge-info`, `closed`→`badge-muted` |
| Transfer outcome | `connected`→`badge-green`, `off_hours`→`badge-amber`, `disabled`→`badge-muted`, `failed`→`badge-red` |
| User status | `active`→`badge-green`, `inactive`→`badge-muted`, `suspended`→`badge-red` |
| Agent setting | `{% if obj.enabled %}badge-green Enabled{% else %}badge-muted Disabled{% endif %}` |
| Generic active flag | `{% if obj.is_active %}badge-green Active{% else %}badge-muted Inactive{% endif %}` |

Do not write a chain whose branches are all the same colour — that is noise; use one badge with
`{{ obj.get_FIELD_display }}`.

---

## 6. Empty state

`templates/partials/_empty_state.html`:

```django
<div class="empty-state">
  <i data-lucide="{{ icon|default:'inbox' }}"></i>
  <h3>{{ title|default:"Nothing here yet" }}</h3>
  <p class="text-muted">{{ message|default:"" }}</p>
  {% if action_url %}<a class="btn btn-primary" href="{{ action_url }}">{{ action_label }}</a>{% endif %}
</div>
```

Every list page needs one. An empty `<tbody>` with column headers and no explanation reads as a broken page.

---

## 7. Confirm-delete pattern

Delete is **always** a POST form with `{% csrf_token %}` and a confirm dialog — never a bare `<a href>`, because a
GET delete is triggered by a link prefetcher, a crawler, or a browser accelerator.

```django
<form method="post" action="{% url 'scheduling:contact_delete' obj.pk %}"
      onclick="return confirm('Delete {{ obj.first_name|escapejs }} {{ obj.last_name|escapejs }}? This cannot be undone.');">
  {% csrf_token %}
  <button type="submit" class="btn btn-danger"><i data-lucide="trash-2"></i> Delete</button>
</form>
```

Hiding the control is not enforcing it — the view enforces the same condition server-side, scoped to
`tenant=request.tenant` **and** `location=request.location`. A delete view that omits the location filter lets a
user destroy another location's record by guessing a pk.

---

## 8. Calendar & booking surfaces

The calendar is the product's main working screen: day and week views, columned **by resource** or **by
provider**, for the active location only.

### 8.1 The calendar — `templates/scheduling/calendar.html`

A standalone page at the sub-module root, not an entity CRUD page. It renders a fixed time axis and one
`.calendar-column` per resource (or provider), with `.calendar-event` blocks positioned by start/duration.

```django
<div class="card">
  <div class="card-header">
    <span>{{ day|date:"l, d M Y" }} · {{ request.location.name }}</span>
    <div class="page-actions">
      {# prev / today / next are plain GET links carrying ?date= and ?view= #}
      <a class="btn btn-primary" href="{% url 'scheduling:appointment_create' %}">
        <i data-lucide="plus"></i> New Appointment</a>
    </div>
  </div>
  <div class="card-body">
    {% if columns %}
    <div class="calendar-grid" style="--calendar-columns: {{ columns|length }}">
      {% for col in columns %}
        <div class="calendar-column">
          <h3 class="form-label">{{ col.label }}</h3>
          {% for a in col.appointments %}
            <a class="calendar-event" href="{% url 'scheduling:appointment_detail' a.pk %}"
               style="--slot-start: {{ a.offset_minutes }}; --slot-span: {{ a.duration_minutes }}">
              <span class="calendar-event-time">{{ a.start_at|date:"H:i" }}</span>
              <span class="calendar-event-title">{{ a.contact.first_name }} {{ a.contact.last_name }}</span>
            </a>
          {% empty %}<p class="text-muted text-sm">No appointments</p>{% endfor %}
        </div>
      {% endfor %}
    </div>
    {% else %}
      {% include "partials/_empty_state.html" with icon="calendar-off" title="No resources" message="Add a resource to this location to start booking." %}
    {% endif %}
  </div>
</div>
```

Rules:
- **Positioning goes through CSS custom properties** (`--slot-start`, `--slot-span`) computed in the **view**, not
  through arithmetic in the template. Django templates cannot do arithmetic, and a filter chain that fakes it is
  how columns end up one row off.
- The calendar reads `tenant=request.tenant, location=request.location`. There is **no** all-locations calendar —
  a combined view would show a user rooms they cannot book.
- Times render in the **location's** timezone. A calendar rendered in the server timezone silently shifts every
  appointment.
- Navigation is plain GET links with `?date=` and `?view=`, so a day is bookmarkable and the back button works.
- A day with 200 appointments must not render 200 nodes unbounded — window the range in the view.

### 8.2 Booking cards — `.booking-card`

The compact appointment summary used on a contact detail page and in the booking list. It is a link to the
appointment detail, never an inline editor.

```django
<a class="booking-card" href="{% url 'scheduling:appointment_detail' a.pk %}">
  <time class="booking-card-time" datetime="{{ a.start_at|date:'c' }}">{{ a.start_at|date:"d M, H:i" }}</time>
  <span class="booking-card-body">
    <strong>{% if a.service %}{{ a.service.name }}{% else %}Appointment{% endif %}</strong>
    <span class="text-muted text-sm">
      {{ a.location.name }}{% if a.resource %} · {{ a.resource.name }}{% endif %}</span>
  </span>
  {% include "partials/_appointment_status_badge.html" with obj=a %}
</a>
```

`a.service`, `a.resource` and `a.provider` are all nullable — guard each with `{% if %}`. Show the source
(`ai_phone` / `manual` / `web`) on the detail page so staff can tell what the agent booked; a booking made by the
agent links back to its `CallSession` via `booked_by_session`.

---

## 9. Voice components

### 9.1 `.location-switcher` and `.call-status-dot`

The topbar carries the **active-location switcher**. It POSTs (it mutates session state) and lists only the
locations the user is assigned to via `accounts.UserLocation` — the view re-validates the choice server-side and
rejects anything else.

```django
<form method="post" action="{% url 'accounts:switch_location' %}" class="location-switcher">
  {% csrf_token %}
  <label class="form-label sr-only" for="loc">Active location</label>
  <select class="form-select" id="loc" name="location" onchange="this.form.submit()">
    {% for l in user_locations %}
      <option value="{{ l.pk }}" {% if request.location.pk == l.pk %}selected{% endif %}>{{ l.name }}</option>
    {% endfor %}
  </select>
</form>
```

A coloured dot alone is never sufficient state: it fails colour-blind users and screen readers both. Always pair it
with a text label or an `aria-label`.

```django
<span class="call-status-dot {{ call.status }}" aria-hidden="true"></span>
<span class="live-badge" aria-label="Call in progress">In Progress</span>
```

`.live-badge` is the pulsing chip used in the topbar's live-call count and on the live-call monitor card. It must
be driven by a websocket consumer, or by a **bounded** HTMX poll with an explicit stop condition
(`hx-trigger="every 5s"` plus a swap that removes the trigger when the call ends). An unbounded 1-second poll on a
list page is a defect.

### 9.2 `.transcript-turn` — `templates/partials/_transcript.html`

The transcript is a **view over `CallSession.transcript`** — a JSON list of `{sequence, role, text, at, offset}`.
There is no transcript table. Transcript text is caller-controlled input: it is **never** `|safe`, never
interpolated into an inline `style`, and never dropped into an inline JS string without `json_script`.

```django
<div class="card">
  <div class="card-header"><span>Transcript</span>
    <a class="btn btn-outline" href="{% url 'calls:transcript_print' session.pk %}">
      <i data-lucide="printer"></i> Print</a></div>
  <div class="card-body">
    <div class="transcript-scroll">   {# scrolls inside its own container #}
      {% for t in turns %}
        <div class="transcript-turn {% if t.role == 'agent' %}agent{% else %}user{% endif %}">
          <span class="transcript-speaker">{% if t.role == 'agent' %}Agent{% else %}Caller{% endif %}</span>
          <time datetime="{{ t.at }}">{{ t.offset }}s</time>
          <p>{{ t.text }}</p>
        </div>
      {% empty %}
        {% include "partials/_empty_state.html" with icon="message-square-off" title="No transcript" message="This call produced no transcribed turns." %}
      {% endfor %}
    </div>
  </div>
</div>
```

A 400-turn call must not render 400 nodes into a list page — window or paginate the turns **in the view**, which
is also where the JSON list is sliced.

### 9.3 `.waveform`

A lightweight amplitude strip under the live monitor and the recording player. It is decorative — mark it
`aria-hidden="true"` and never make it the only indicator of playback position.

```django
{# the view passes peaks_dom_id = f"peaks-{session.pk}" #}
<div class="waveform" aria-hidden="true" data-peaks-id="{{ peaks_dom_id }}"></div>
{{ session.waveform_peaks|json_script:peaks_dom_id }}
```

Peak data goes through `json_script`, never an inline JS literal. Build the element id in the **view** and pass it
in — `json_script`'s argument is the id itself, so it cannot be assembled with a filter chain in the template
(`|json_script:"peaks-"|add:session.pk` appends the pk *after* the closing `</script>` tag and leaves the id
`peaks-`, silently breaking the lookup).

### 9.4 Audio player — `templates/partials/_audio_player.html`

```django
{% if session.recording_blob %}
<div class="card">
  <div class="card-header"><span>Recording</span>
    <span class="badge badge-slate">{{ consent_basis_label }}</span></div>
  <div class="card-body space-y-2">
    <audio controls preload="none" class="w-full"
           aria-label="Call recording from {{ session.from_number }}"
           src="{{ recording_url }}"></audio>
    <div class="waveform" aria-hidden="true"></div>
    <p class="text-muted text-sm">
      {{ session.duration_display }} · retained until {{ retention_until|date:"d M Y" }}
    </p>
    {% if can_download %}
      <a class="btn btn-outline" href="{{ download_url }}"><i data-lucide="download"></i> Download</a>
    {% endif %}
  </div>
</div>
{% endif %}
```

Hard rules: `recording_url` is a **short-lived signed URL** produced by the view — never a permanent public media
path, never a provider URL rendered straight into the page. Show the consent basis and the retention date. Offer
Download only when policy allows, and let the view — not the template — decide. Recordings, transcripts and full
caller numbers are PII; render them only inside the role gate the view enforces.

### 9.5 Phone numbers

Render every number through one template filter (`{{ value|phone_e164 }}` or the locale variant). Never slice a
number ad hoc in a template — inconsistent formatting across pages makes the same caller look like two people.

---

## 10. The multi-line `{# #}` trap

A Django comment must open and close on the **same line**. A multi-line `{# ... #}` is not a comment — everything
after the first line renders as **visible page text**, and it passes every check in the toolchain because it is a
valid template that produces a 200.

```django
{# ✅ fine: a single-line note #}

{# ❌ WRONG — line 2 onward renders on the page
   this text is visible to the user #}

{% comment %}
  ✅ correct for anything spanning lines.
{% endcomment %}
```

---

## 11. HTMX, icons, dark mode, RTL, a11y

- HTMX POSTs carry the CSRF header (set `hx-headers` once on `<body>` in `base.html`).
- Re-run `lucide.createIcons()` after `htmx:afterSwap`, or swapped-in icons render as empty `<i>` tags.
- Never put a secret in a data attribute — no Twilio SID, no auth token, no signed URL in markup that is cached
  or logged.
- Bumped `?v=` cache-buster on any changed static include.
- Raw Tailwind colour utilities need their `dark:` variant; prefer a theme.css class, which already handles it.
- No hard-coded `left`/`right` — use logical properties or Tailwind's `ms-`/`me-` so RTL does not break.
- Every input has `<label for>` matching an `id`; every icon-only button has `aria-label` or `title`; `<img>` has
  `alt`; focus states stay visible; audio controls are labelled.

---

## 12. Checklist before you commit a template

1. Extends `base.html`; uses theme.css classes, no ad-hoc styling.
2. Every `badge-*` / `stat-icon <x>` / `text-*` modifier verified against `static/css/theme.css`.
3. Loop variable and field names match the view context and the model exactly.
4. Filters: `q` + status + FK selects, `|stringformat:"d"` on pk comparisons, junk values degrade.
5. Pagination guarded by `has_previous` / `has_next`, filter params preserved.
6. Actions column: view / edit / POST-delete-with-confirm; detail page has the actions sidebar. Runtime-written
   `CallSession` rows have neither, correctly.
7. Empty state present.
8. Nullable FKs guarded with `{% if %}`, not `|default:` inside a filter argument.
9. Every `{% url %}` name exists with the right args.
10. `.table-wrap` around the table; no multi-line `{# #}`.
11. The page makes the **active location** visible, and no form exposes `tenant` or `location` as an input.
12. Transcript and caller text never `|safe`; recordings behind a signed URL with consent basis and retention shown.
13. Calendar positioning computed in the view; times rendered in the location's timezone.
14. Live surfaces use a consumer or a bounded poll, and clean up on teardown.

Commit one file per commit, PowerShell-safe:
`git add 'templates/scheduling/calendar.html'; git commit -m 'feat(scheduling): day/week calendar page'` — and
never `git push`.
