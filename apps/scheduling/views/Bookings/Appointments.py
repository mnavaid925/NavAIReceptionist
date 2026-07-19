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
    book_slot,
    cancel_appointment,
    find_available_slots,
    local_day_bounds_utc,
    reschedule_appointment,
)
from apps.scheduling.forms import AppointmentCancelForm, AppointmentForm
from apps.scheduling.models import Appointment, Contact, Resource, Service
from apps.scheduling.views._common import *  # noqa: F401,F403
from apps.scheduling.views._helpers import save_or_report_conflict

logger = logging.getLogger(__name__)

__all__ = [
    'appointment_list_view',
    'appointment_create_view',
    'appointment_detail_view',
    'appointment_edit_view',
    'appointment_delete_view',
    'appointment_slots_view',
    'appointment_book_view',
    'appointment_reschedule_view',
    'appointment_cancel_view',
]


def _location_appointments(request):
    """The base queryset. Tenant AND location scoped, always.

    Returns nothing when no location is active — the safe direction. A user who
    has not chosen a site sees an empty calendar and the global
    "choose a location" banner, never another site's bookings.
    """
    if request.location is None:
        return Appointment.objects.none()
    return Appointment.objects.filter(
        tenant=request.tenant, location=request.location
    ).select_related('contact', 'service', 'resource', 'provider', 'location')


def _parse_local_date(raw):
    """Parse `YYYY-MM-DD` from a query string, or None. Never raises."""
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _authorised_pk(request, model_queryset, raw):
    """Resolve a pk from a query string against an already-scoped queryset.

    `.isdecimal()`, not `.isdigit()`: `isdigit()` is True for characters such as
    '²' and fullwidth '１' that `int()` then refuses, turning a junk filter into
    a 500. Returns None for anything not found, so a foreign pk degrades to
    "no filter" rather than leaking or raising.
    """
    raw = (raw or '').strip()
    if not raw.isdecimal():
        return None
    return model_queryset.filter(pk=int(raw)).first()


@login_required  # noqa: F405
def appointment_list_view(request):
    """Bookings at the active location, with date, status and FK filters."""
    queryset = _location_appointments(request)

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
    date_from = _parse_local_date(request.GET.get('from'))
    date_to = _parse_local_date(request.GET.get('to'))
    if location is not None and date_from is not None:
        lo, _ = local_day_bounds_utc(location, date_from)
        queryset = queryset.filter(start_at__gte=lo)
    if location is not None and date_to is not None:
        _, hi = local_day_bounds_utc(location, date_to)
        queryset = queryset.filter(start_at__lt=hi)

    providers = _location_providers(request)
    services = _bookable_services(request)
    resources = _location_resources(request)

    provider = _authorised_pk(request, providers, request.GET.get('provider'))
    if provider is not None:
        queryset = queryset.filter(provider=provider)

    service = _authorised_pk(request, services, request.GET.get('service'))
    if service is not None:
        queryset = queryset.filter(service=service)

    resource = _authorised_pk(request, resources, request.GET.get('resource'))
    if resource is not None:
        queryset = queryset.filter(resource=resource)

    page_obj, elided_page_range = paginate(request, queryset)  # noqa: F405

    return render(request, 'scheduling/bookings/appointment/list.html', {  # noqa: F405
        'appointments': page_obj.object_list,
        'page_obj': page_obj,
        'elided_page_range': elided_page_range,
        'total_count': page_obj.paginator.count,
        # Every filter dropdown's data, passed explicitly — a template cannot
        # conjure a queryset it was not given, and a silently empty <select> is
        # the classic broken-filter bug.
        'status_choices': Appointment.STATUS_CHOICES,
        'providers': providers,
        'services': services,
        'resources': resources,
    })


def _location_providers(request):
    """Providers assigned to the active location."""
    from apps.accounts.models import User

    if request.location is None:
        return User.objects.none()
    return User.objects.filter(
        tenant=request.tenant,
        is_provider=True,
        user_locations__location=request.location,
    ).distinct().order_by('full_name', 'email')


def _bookable_services(request):
    """Services bookable at the active location — this site's PLUS all-location.

    Additive, never `filter(location=...)`, which would hide every business-wide
    service.
    """
    if request.tenant is None:
        return Service.objects.none()
    queryset = Service.objects.filter(tenant=request.tenant, is_active=True)
    if request.location is not None:
        queryset = queryset.filter(
            Q(location=request.location) | Q(location__isnull=True)
        )
    return queryset.order_by('display_order', 'name')


def _location_resources(request):
    if request.location is None:
        return Resource.objects.none()
    return Resource.objects.filter(
        tenant=request.tenant, location=request.location, is_active=True
    ).order_by('display_order', 'name')


@login_required  # noqa: F405
def appointment_detail_view(request, pk):
    """One booking."""
    obj = get_object_or_404(_location_appointments(request), pk=pk)  # noqa: F405

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

    form = AppointmentForm(request.POST or None, request=request)

    if request.method == 'POST' and form.is_valid():
        obj = save_or_report_conflict(
            form, 'Someone just booked that time. Pick another.'
        )
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
    obj = get_object_or_404(_location_appointments(request), pk=pk)  # noqa: F405
    form = AppointmentForm(request.POST or None, instance=obj, request=request)

    if request.method == 'POST' and form.is_valid():
        if save_or_report_conflict(
            form, 'Someone just booked that time. Pick another.'
        ) is not None:
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
    obj = get_object_or_404(_location_appointments(request), pk=pk)  # noqa: F405
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

    services = _bookable_services(request)
    providers = _location_providers(request)
    resources = _location_resources(request)

    service = _authorised_pk(request, services, request.GET.get('service'))
    provider = _authorised_pk(request, providers, request.GET.get('provider'))
    resource = _authorised_pk(request, resources, request.GET.get('resource'))

    date_from = _parse_local_date(request.GET.get('from'))
    date_to = _parse_local_date(request.GET.get('to'))

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
    contact = _authorised_pk(
        request,
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
    obj = get_object_or_404(_location_appointments(request), pk=pk)  # noqa: F405
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
        return redirect('scheduling:appointment_detail', pk=obj.pk)  # noqa: F405

    messages.success(  # noqa: F405
        request, f'Moved to {obj.local_start():%a %d %b at %H:%M}.'
    )
    return redirect('scheduling:appointment_detail', pk=obj.pk)  # noqa: F405


@login_required  # noqa: F405
@require_POST  # noqa: F405
def appointment_cancel_view(request, pk):
    """Cancel with a reason. Frees the slot, keeps the record."""
    obj = get_object_or_404(_location_appointments(request), pk=pk)  # noqa: F405
    form = AppointmentCancelForm(request.POST)
    reason = form.cleaned_data.get('reason', '') if form.is_valid() else ''

    try:
        cancel_appointment(appointment=obj, reason=reason)
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
