"""Appointment CRUD, availability search and the slot-booking path (4.3).

`Appointment` is fully location-scoped, so every queryset carries BOTH
`tenant=request.tenant` and `location=request.location`.

**Date filters never use `start_at__date`.** Django's `__date` lookup converts
using the ACTIVE timezone rather than the location's, and on MySQL it compiles to
`CONVERT_TZ()`, which returns NULL unless the server's timezone tables have been
loaded — so a `__date` filter passes in the SQLite test settings and silently
returns zero rows in production. It also cannot use `idx_appt_tenant_loc_start`.
Every date filter here converts a local calendar day to a half-open UTC range via
`availability.local_day_bounds_utc`.
"""
import logging
from datetime import datetime, timedelta

from django.db.models import Q
from django.utils import timezone as dj_timezone

from apps.scheduling.availability import (
    MAX_OFFERED_SLOTS,
    SlotError,
    _lock_contended_rows,
    book_slot,
    cancel_appointment,
    find_available_slots,
    local_day_bounds_utc,
    overlapping_appointments,
    reschedule_appointment,
)
from apps.scheduling.forms import AppointmentCancelForm, AppointmentForm
from apps.scheduling.models import Appointment, Contact
from apps.scheduling.views._common import *  # noqa: F401,F403
from apps.scheduling.views._helpers import (
    authorised_pk,
    bookable_providers,
    bookable_resources,
    bookable_services,
    location_appointments,
    parse_local_date,
)

logger = logging.getLogger(__name__)

__all__ = [
    'appointment_list_view',
    'appointment_create_view',
    'appointment_detail_view',
    'appointment_edit_view',
    'appointment_delete_view',
    'appointment_mark_view',
    'appointment_slots_view',
    'appointment_book_view',
    'appointment_reschedule_view',
    'appointment_cancel_view',
]


def _parse_local_datetime(request, raw):
    """Parse a `YYYY-MM-DDTHH:MM` click-through value, or None. Never raises.

    Interpreted in the LOCATION's timezone, because that is the clock the
    calendar grid was drawn against — parsing it as UTC would land the pre-filled
    booking hours away from the cell the user actually clicked.

    Returns a NAIVE local datetime: `AppointmentForm.start_at` renders through a
    `datetime-local` input and Django localises it on the way back in, so handing
    it an aware UTC value would display the wrong wall clock in the field.
    """
    raw = (raw or '').strip()
    if not raw or request.location is None:
        return None
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M'):
        try:
            naive = datetime.strptime(raw, fmt)
        except (TypeError, ValueError):
            continue
        # Sanity-bound it the same way `parse_local_date` bounds a date, so a
        # absurd year cannot reach the arithmetic downstream.
        if not (1900 <= naive.year <= 2200):
            return None
        return naive
    return None


def _save_booking_under_lock(form, request):
    """Persist a manual booking with the SAME race protection as the token path.

    `save_or_report_conflict` cannot help here: it converts an `IntegrityError`,
    and `Appointment` declares no database constraint that could raise one — MySQL
    cannot express "these two time ranges must not overlap". So without this, the
    form's unlocked pre-check plus a plain `save()` is textbook check-then-act and
    two receptionists submitting at once BOTH succeed.

    Returns the saved appointment, or None after adding an error to the form.
    """
    from django.db import transaction
    from django.db.utils import OperationalError

    instance = form.instance
    provider = form.cleaned_data.get('provider')
    resource = form.cleaned_data.get('resource')
    service = form.cleaned_data.get('service')
    start_at = form.cleaned_data.get('start_at')

    try:
        with transaction.atomic():
            _lock_contended_rows(
                tenant=request.tenant, location=request.location,
                provider_id=getattr(provider, 'pk', None),
                resource_id=getattr(resource, 'pk', None),
            )
            if service is not None and start_at is not None:
                clash = overlapping_appointments(
                    tenant=request.tenant, location=request.location,
                    start_utc=start_at,
                    end_utc=start_at + timedelta(minutes=service.total_minutes),
                    provider=provider, resource=resource,
                    exclude_pk=instance.pk or None,
                    for_update=True,
                )
                if clash.exists():
                    form.add_error(
                        None,
                        'Someone just booked that time. Pick another.',
                    )
                    return None
            return form.save()
    except OperationalError as exc:
        # Deadlock (1213) or lock-wait timeout (1205): another writer got there.
        logger.warning('Manual booking lost a lock race: %s', exc)
        form.add_error(None, 'Someone just booked that time. Pick another.')
        return None


def _quick_ranges(location):
    """Today / This week / Upcoming as `?from=&to=` fragments, or None.

    Sugar over the SAME `?from=`/`?to=` machinery the filter bar already posts —
    nothing here reaches the database, and the values land back in
    `parse_local_date` + `local_day_bounds_utc` like any hand-typed date.

    "Today" is read off `location.local_now()`, not `timezone.localdate()`: the
    active Django timezone is the SERVER's, so a site three hours west would get
    a "Today" button that jumps a day either side of its own midnight — the very
    drift this module's date handling exists to avoid.
    """
    if location is None:
        return None

    today = location.local_now().date()
    # Monday-based, matching the week grid 4.4 already draws.
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    return {
        'today': f'?from={today:%Y-%m-%d}&to={today:%Y-%m-%d}',
        'week': f'?from={week_start:%Y-%m-%d}&to={week_end:%Y-%m-%d}',
        # Deliberately open-ended: no `to=`, so "Upcoming" keeps running forward
        # rather than silently stopping at some arbitrary horizon.
        'upcoming': f'?from={today:%Y-%m-%d}',
    }


@login_required  # noqa: F405
def appointment_list_view(request):
    """Bookings at the active location, with date, status and FK filters."""
    queryset = location_appointments(request)

    search = request.GET.get('q', '').strip()
    if search:
        queryset = queryset.filter(
            Q(contact__first_name__icontains=search)
            | Q(contact__last_name__icontains=search)
            | Q(contact__phone_e164__icontains=search)
            | Q(reason__icontains=search)
        )

    status = request.GET.get('status', '').strip()
    if status in dict(Appointment.STATUS_CHOICES):
        queryset = queryset.filter(status=status)

    location = request.location
    date_from = parse_local_date(request.GET.get('from'))
    date_to = parse_local_date(request.GET.get('to'))
    if location is not None and date_from is not None:
        lo, _ = local_day_bounds_utc(location, date_from)
        queryset = queryset.filter(start_at__gte=lo)
    if location is not None and date_to is not None:
        _, hi = local_day_bounds_utc(location, date_to)
        queryset = queryset.filter(start_at__lt=hi)

    providers = bookable_providers(request)
    services = bookable_services(request)
    resources = bookable_resources(request)

    provider = authorised_pk(providers, request.GET.get('provider'))
    if provider is not None:
        queryset = queryset.filter(provider=provider)

    service = authorised_pk(services, request.GET.get('service'))
    if service is not None:
        queryset = queryset.filter(service=service)

    resource = authorised_pk(resources, request.GET.get('resource'))
    if resource is not None:
        queryset = queryset.filter(resource=resource)

    page_obj, elided_page_range = paginate(request, queryset)  # noqa: F405

    return render(request, 'scheduling/bookings/appointment/list.html', {  # noqa: F405
        'appointments': page_obj.object_list,
        'page_obj': page_obj,
        'elided_page_range': elided_page_range,
        'total_count': page_obj.paginator.count,
        'quick_ranges': _quick_ranges(location),
        # Every filter dropdown's data, passed explicitly — a template cannot
        # conjure a queryset it was not given, and a silently empty <select> is
        # the classic broken-filter bug.
        'status_choices': Appointment.STATUS_CHOICES,
        'providers': providers,
        'services': services,
        'resources': resources,
    })


@login_required  # noqa: F405
def appointment_detail_view(request, pk):
    """One booking."""
    obj = get_object_or_404(location_appointments(request), pk=pk)  # noqa: F405

    return render(request, 'scheduling/bookings/appointment/detail.html', {  # noqa: F405
        'obj': obj,
        'cancel_form': AppointmentCancelForm(),
    })


@login_required  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def appointment_create_view(request):
    """Book by hand, with the calendar in front of you."""
    if request.location is None:
        messages.error(  # noqa: F405
            request, 'Choose a location before booking into its calendar.'
        )
        return redirect('scheduling:appointment_list')  # noqa: F405

    # Slot click-through from 4.4's calendar: `?start=…&resource=…&provider=…`.
    # Every id is authorised against an already-scoped queryset before it is
    # offered as an initial value — a raw pk from a query string is never trusted,
    # even to pre-fill a form the user must still submit.
    initial = {}
    if request.method == 'GET':
        start_at = _parse_local_datetime(request, request.GET.get('start'))
        if start_at is not None:
            initial['start_at'] = start_at
        resource = authorised_pk(
            bookable_resources(request), request.GET.get('resource')
        )
        if resource is not None:
            initial['resource'] = resource.pk
        provider = authorised_pk(
            bookable_providers(request), request.GET.get('provider')
        )
        if provider is not None:
            initial['provider'] = provider.pk

    form = AppointmentForm(
        request.POST or None, request=request, initial=initial or None
    )

    if request.method == 'POST' and form.is_valid():
        obj = _save_booking_under_lock(form, request)
        if obj is not None:
            # Provenance is a server fact. A booking made through this form was
            # made by a person at a desk, whatever the client posted.
            if obj.source != Appointment.SOURCE_MANUAL:
                obj.source = Appointment.SOURCE_MANUAL
                obj.save(update_fields=['source', 'updated_at'])
            logger.info(
                'Appointment created appointment_id=%s tenant_id=%s '
                'location_id=%s by user_id=%s',
                obj.pk, request.tenant.pk, request.location.pk, request.user.pk,
            )
            messages.success(  # noqa: F405
                request,
                f'Booked {obj.contact.display_name} for '
                f'{obj.local_start():%a %d %b at %H:%M}.',
            )
            return redirect('scheduling:appointment_detail', pk=obj.pk)  # noqa: F405

    return render(request, 'scheduling/bookings/appointment/form.html', {  # noqa: F405
        'form': form,
        'is_edit': False,
    })


@login_required  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def appointment_edit_view(request, pk):
    """Edit a booking. Moving it in time is `reschedule`, not this."""
    obj = get_object_or_404(location_appointments(request), pk=pk)  # noqa: F405

    # A closed-out booking is a record of what happened. Without this guard a
    # direct POST could reopen a cancelled appointment, or flip a completed one
    # back to scheduled, with no audit of either.
    if not obj.is_open:
        messages.error(  # noqa: F405
            request,
            f'This appointment is {obj.get_status_display().lower()} and can no '
            'longer be changed. Book a new one instead.',
        )
        return redirect('scheduling:appointment_detail', pk=obj.pk)  # noqa: F405

    form = AppointmentForm(request.POST or None, instance=obj, request=request)

    if request.method == 'POST' and form.is_valid():
        if _save_booking_under_lock(form, request) is not None:
            logger.info('Appointment updated appointment_id=%s by user_id=%s',
                        obj.pk, request.user.pk)
            messages.success(request, 'Appointment updated.')  # noqa: F405
            return redirect('scheduling:appointment_detail', pk=obj.pk)  # noqa: F405

    return render(request, 'scheduling/bookings/appointment/form.html', {  # noqa: F405
        'form': form,
        'obj': obj,
        'is_edit': True,
    })


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
@require_POST  # noqa: F405
def appointment_delete_view(request, pk):
    """Delete a booking outright.

    Almost always the wrong action — CANCELLING keeps the record and frees the
    slot, which is what the front desk actually wants. Deleting is for a booking
    that should never have existed (a test row, a mis-keyed duplicate), so it is
    management-only and says so.
    """
    obj = get_object_or_404(location_appointments(request), pk=pk)  # noqa: F405
    label = obj.contact.display_name
    obj.delete()

    logger.info('Appointment deleted appointment_id=%s tenant_id=%s by user_id=%s',
                pk, request.tenant.pk, request.user.pk)
    messages.success(  # noqa: F405
        request,
        f'The booking for {label} has been deleted. To keep a record of a '
        'booking that was called off, cancel it instead of deleting it.',
    )
    return redirect('scheduling:appointment_list')  # noqa: F405


@login_required  # noqa: F405
@require_POST  # noqa: F405
def appointment_mark_view(request, pk, new_status):
    """Close a booking out in one click — completed, or a no-show.

    No tier gate: marking who turned up is front-desk work, the same posture as
    `appointment_edit_view`.

    `cancelled` is NOT reachable here even though it is a valid status. A
    cancellation has to free the slot and record WHY, which is
    `appointment_cancel_view`'s reasoned flow — routing it through a bare
    one-click button would leave the calendar holding a slot nobody is coming to
    and no note explaining it.
    """
    obj = get_object_or_404(location_appointments(request), pk=pk)  # noqa: F405

    # `new_status` arrives from the URL path, so it is caller-controlled text —
    # an allow-list, never a `dict(STATUS_CHOICES)` membership test, which would
    # happily accept `cancelled` and `scheduled` too.
    if new_status not in (Appointment.STATUS_COMPLETED, Appointment.STATUS_NO_SHOW):
        messages.error(  # noqa: F405
            request, 'That is not an outcome a booking can be marked with.'
        )
        return redirect('scheduling:appointment_detail', pk=obj.pk)  # noqa: F405

    # Same closed-out rule `appointment_edit_view` enforces: a booking that has
    # already been completed, cancelled or no-showed is a record of what
    # happened, and a second POST must not quietly rewrite it.
    if not obj.is_open:
        messages.error(  # noqa: F405
            request,
            f'This appointment is already {obj.get_status_display().lower()} and '
            'its outcome can no longer be changed.',
        )
        return redirect('scheduling:appointment_detail', pk=obj.pk)  # noqa: F405

    # A conditional UPDATE, not `obj.save()`. The `is_open` test above and the
    # write are otherwise check-then-act: two receptionists clicking "completed"
    # and "no-show" on the same row at the same moment both pass the check and
    # the later write silently wins, with no sign the other ever happened.
    # Folding the precondition into the WHERE clause makes the database settle
    # it — the loser matches zero rows and is told so, rather than believing it
    # succeeded. No lock needed: this is one row and one statement.
    updated = location_appointments(request).filter(
        pk=obj.pk, status__in=Appointment.OPEN_STATUSES,
    ).update(status=new_status, updated_at=dj_timezone.now())

    if not updated:
        messages.error(  # noqa: F405
            request,
            'Someone else closed this booking out a moment ago. Reload to see '
            'where it landed.',
        )
        return redirect('scheduling:appointment_detail', pk=obj.pk)  # noqa: F405

    # Set locally rather than re-reading. Winning the UPDATE above already tells
    # us what the row holds: the WHERE clause required an OPEN status, and
    # `OPEN_STATUSES` shares no value with `completed`/`no_show`, so the row can
    # no longer match any other mark's precondition. A second SELECT could only
    # return what we just wrote.
    obj.status = new_status

    logger.info('Appointment marked appointment_id=%s new_status=%s by user_id=%s',
                obj.pk, new_status, request.user.pk)
    messages.success(  # noqa: F405
        request, f'Marked as {obj.get_status_display().lower()}.'
    )
    # Both the list row and the detail page offer these buttons, so honour the
    # posted `next` — a receptionist working down a filtered list must land back
    # on that list, query string intact, not on the booking they just closed.
    return redirect(safe_redirect_target(  # noqa: F405
        request,
        default=reverse('scheduling:appointment_detail', args=[obj.pk]),  # noqa: F405
    ))


# --------------------------------------------------------------------------- #
# Availability + the slot-token booking path
# --------------------------------------------------------------------------- #

@login_required  # noqa: F405
def appointment_slots_view(request):
    """Search open slots for a service. The same engine Module 3.3 will call.

    Every id in the query string is authorised against an already-scoped
    queryset before use — a raw `?service=` pk would otherwise be a cross-tenant
    read, and a Downtown service could mint Uptown slots.
    """
    if request.location is None:
        messages.error(  # noqa: F405
            request, 'Choose a location before searching its calendar.'
        )
        return redirect('scheduling:appointment_list')  # noqa: F405

    services = bookable_services(request)
    providers = bookable_providers(request)
    resources = bookable_resources(request)

    service = authorised_pk(services, request.GET.get('service'))
    provider = authorised_pk(providers, request.GET.get('provider'))
    resource = authorised_pk(resources, request.GET.get('resource'))

    date_from = parse_local_date(request.GET.get('from'))
    date_to = parse_local_date(request.GET.get('to'))

    # RESCHEDULE MODE. `?reschedule=<pk>` turns this page into "find a new time
    # for THIS booking" — the slot forms then post to `appointment_reschedule`,
    # which MOVES the existing row. Without it the page always posts to
    # `appointment_book`, so a staff "reschedule" would silently create a second
    # live appointment and leave the original standing.
    #
    # Resolved through the scoped queryset, so a foreign pk cannot be rescheduled
    # and simply falls back to normal booking.
    rescheduling = authorised_pk(
        location_appointments(request), request.GET.get('reschedule')
    )
    if rescheduling is not None and not rescheduling.is_open:
        messages.error(  # noqa: F405
            request,
            'That appointment is closed out and can no longer be moved.',
        )
        return redirect('scheduling:appointment_detail', pk=rescheduling.pk)  # noqa: F405

    slots = []
    if service is not None:
        slots = find_available_slots(
            tenant=request.tenant, location=request.location, service=service,
            date_from=date_from, date_to=date_to,
            provider=provider, resource=resource,
        )

    return render(request, 'scheduling/bookings/appointment/slots.html', {  # noqa: F405
        'slots': slots,
        'service': service,
        'services': services,
        'providers': providers,
        'resources': resources,
        'rescheduling': rescheduling,
        'contacts': Contact.objects.filter(
            tenant=request.tenant, anonymized_at__isnull=True
        ).order_by('last_name', 'first_name')[:500],
        'max_slots': MAX_OFFERED_SLOTS,
        'searched': service is not None,
    })


@login_required  # noqa: F405
@require_POST  # noqa: F405
def appointment_book_view(request):
    """Book an offered slot by its opaque token.

    The time, provider, resource and service are ALL taken from the signed token,
    never from posted fields. Only the contact and the free-text reason come from
    the request, and the contact is re-authorised against the tenant here because
    this path bypasses the form that would normally narrow it.
    """
    if request.location is None:
        messages.error(request, 'Choose a location first.')  # noqa: F405
        return redirect('scheduling:appointment_list')  # noqa: F405

    token = (request.POST.get('token') or '').strip()
    contact = authorised_pk(
        Contact.objects.filter(tenant=request.tenant, anonymized_at__isnull=True),
        request.POST.get('contact'),
    )

    if contact is None:
        messages.error(request, 'Choose who the appointment is for.')  # noqa: F405
        return redirect('scheduling:appointment_slots')  # noqa: F405

    try:
        appointment = book_slot(
            tenant=request.tenant, location=request.location, token=token,
            contact=contact, reason=(request.POST.get('reason') or '').strip(),
            source=Appointment.SOURCE_MANUAL,
        )
    except SlotError as exc:
        logger.info('Slot booking refused code=%s', exc.code)
        messages.error(request, exc.message)  # noqa: F405
        return redirect('scheduling:appointment_slots')  # noqa: F405

    messages.success(  # noqa: F405
        request,
        f'Booked {appointment.contact.display_name} for '
        f'{appointment.local_start():%a %d %b at %H:%M}.',
    )
    return redirect('scheduling:appointment_detail', pk=appointment.pk)  # noqa: F405


@login_required  # noqa: F405
@require_POST  # noqa: F405
def appointment_reschedule_view(request, pk):
    """Move an appointment onto another offered slot."""
    obj = get_object_or_404(location_appointments(request), pk=pk)  # noqa: F405
    token = (request.POST.get('token') or '').strip()

    try:
        reschedule_appointment(
            tenant=request.tenant, location=request.location,
            appointment=obj, token=token,
            reason=(request.POST.get('reason') or '').strip(),
        )
    except SlotError as exc:
        logger.info('Reschedule refused code=%s appointment_id=%s', exc.code, obj.pk)
        messages.error(request, exc.message)  # noqa: F405
        # Back to the slot search, still in reschedule mode, so the user can pick
        # a different time rather than losing what they were doing.
        return redirect(
            f"{reverse('scheduling:appointment_slots')}?reschedule={obj.pk}"  # noqa: F405
            f"{'&service=' + str(obj.service_id) if obj.service_id else ''}"
        )

    messages.success(  # noqa: F405
        request, f'Moved to {obj.local_start():%a %d %b at %H:%M}.'
    )
    return redirect('scheduling:appointment_detail', pk=obj.pk)  # noqa: F405


@login_required  # noqa: F405
@require_POST  # noqa: F405
def appointment_cancel_view(request, pk):
    """Cancel with a reason. Frees the slot, keeps the record."""
    obj = get_object_or_404(location_appointments(request), pk=pk)  # noqa: F405
    form = AppointmentCancelForm(request.POST)
    reason = form.cleaned_data.get('reason', '') if form.is_valid() else ''

    try:
        cancel_appointment(
            appointment=obj, tenant=request.tenant, location=request.location,
            reason=reason,
        )
    except SlotError as exc:
        messages.error(request, exc.message)  # noqa: F405
        return redirect('scheduling:appointment_detail', pk=obj.pk)  # noqa: F405

    logger.info('Appointment cancelled appointment_id=%s by user_id=%s',
                obj.pk, request.user.pk)
    messages.success(  # noqa: F405
        request,
        'Appointment cancelled. The slot is free again and the record is kept.',
    )
    return redirect('scheduling:appointment_detail', pk=obj.pk)  # noqa: F405
