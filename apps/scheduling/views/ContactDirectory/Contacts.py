"""Contact directory CRUD (sub-module 4.1).

`scheduling.Contact` is tenant-scoped but NOT location-scoped — a caller belongs
to the business and may book at any of its sites. So every queryset here filters
on `tenant=request.tenant` and nothing else. Adding `location=request.location`
would hide a caller from the very site they are ringing about, and would not
even be expressible: the model has no `location` column.

PII note: a contact row is a name, a phone number and possibly a date of birth.
Nothing in this module logs a field value — the log lines below carry primary
keys only, so an INFO-level log is never a PII leak.
"""
import logging

from django.db.models import ProtectedError, Q

from apps.scheduling.forms import ContactForm
from apps.scheduling.models import Contact
from apps.scheduling.views._common import *  # noqa: F401,F403

logger = logging.getLogger(__name__)

__all__ = [
    'contact_list_view',
    'contact_create_view',
    'contact_detail_view',
    'contact_edit_view',
    'contact_delete_view',
    'contact_forget_view',
]


def _tenant_contacts(request):
    """The base queryset. Tenant-scoped, always — and never location-scoped."""
    return Contact.objects.filter(tenant=request.tenant)


@login_required  # noqa: F405
def contact_list_view(request):
    """The directory: search across name, phone and email, filtered by source."""
    queryset = _tenant_contacts(request)

    search = request.GET.get('q', '').strip()
    if search:
        # The number is stored E.164 but people search for it however they
        # remember it, so match the digits of the query against the stored form
        # as well as the raw string.
        from apps.scheduling.services import normalize_e164

        digits = normalize_e164(search)
        phone_q = Q(phone_e164__icontains=search)
        if digits:
            phone_q |= Q(phone_e164__icontains=digits)

        queryset = queryset.filter(
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
            | phone_q
        )

    # A junk `?source=whatever` must degrade to "no filter", never raise.
    source = request.GET.get('source', '').strip()
    if source in dict(Contact.SOURCE_CHOICES):
        queryset = queryset.filter(source=source)

    page_obj, elided_page_range = paginate(request, queryset)  # noqa: F405

    return render(request, 'scheduling/directory/contact/list.html', {  # noqa: F405
        'contacts': page_obj.object_list,
        'page_obj': page_obj,
        'elided_page_range': elided_page_range,
        # The paginator already counted the filtered queryset to work out how
        # many pages there are. Calling .count() again would run that COUNT twice
        # on every list render for the same number.
        'total_count': page_obj.paginator.count,
        # The filter bar's <select> needs the choices; without this the dropdown
        # renders empty and the source filter silently does nothing.
        'source_choices': Contact.SOURCE_CHOICES,
    })


@login_required  # noqa: F405
def contact_detail_view(request, pk):
    """One contact, with whatever history the built modules can supply."""
    obj = get_object_or_404(_tenant_contacts(request), pk=pk)  # noqa: F405

    return render(request, 'scheduling/directory/contact/detail.html', {  # noqa: F405
        'obj': obj,
        'also_on_this_number': _also_on_this_number(obj),
        'appointments': _appointments_for(obj),
        'call_sessions': _call_sessions_for(obj),
    })


def _also_on_this_number(contact):
    """Other people in this business reachable on the same line.

    Surfaced because `phone_e164` is deliberately not unique — when the agent
    answers a call from a shared household or office line it has several
    candidates, and the front desk needs to see that ambiguity rather than
    discover it mid-call.
    """
    if not contact.phone_e164:
        return Contact.objects.none()
    return (
        Contact.objects.filter(
            tenant_id=contact.tenant_id, phone_e164=contact.phone_e164
        )
        .exclude(pk=contact.pk)
        .order_by('last_name', 'first_name')[:10]
    )


def _appointments_for(contact):
    """This contact's bookings, or None while sub-module 4.3 is unbuilt.

    Import-guarded rather than assumed: `Appointment` does not exist yet, and a
    hard import would make the whole contact directory un-importable until it
    does. When 4.3 lands this starts returning real rows with no edit here.
    """
    try:
        from apps.scheduling.models import Appointment
    except ImportError:
        return None
    return (
        Appointment.objects.filter(
            tenant_id=contact.tenant_id, contact=contact
        )
        .select_related('location', 'service')
        .order_by('-starts_at')[:10]
    )


def _call_sessions_for(contact):
    """This contact's calls, or None while Module 5 is unbuilt.

    Same import guard, for the same reason — `apps.calls` is a later module.
    """
    try:
        from apps.calls.models import CallSession
    except (ImportError, ModuleNotFoundError):
        return None
    return (
        CallSession.objects.filter(
            tenant_id=contact.tenant_id, contact=contact
        )
        .select_related('location')
        .order_by('-started_at')[:10]
    )


@login_required  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def contact_create_view(request):
    """Add a contact by hand. The agent creates its own on an inbound call."""
    form = ContactForm(request.POST or None, request=request)

    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        # Provenance is a server fact, not a form field — see ContactForm.
        obj.source = Contact.SOURCE_MANUAL
        obj.save()

        logger.info('Contact created contact_id=%s tenant_id=%s by user_id=%s',
                    obj.pk, request.tenant.pk, request.user.pk)
        messages.success(request, f'{obj.display_name} has been added.')  # noqa: F405
        _warn_about_shared_number(request, form)
        return redirect('scheduling:contact_detail', pk=obj.pk)  # noqa: F405

    return render(request, 'scheduling/directory/contact/form.html', {  # noqa: F405
        'form': form,
        'is_edit': False,
    })


@login_required  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def contact_edit_view(request, pk):
    """Edit a contact. `source` is untouched — it records how the row began."""
    obj = get_object_or_404(_tenant_contacts(request), pk=pk)  # noqa: F405

    # Re-populating an erased contact would undo the erasure. Refuse rather than
    # render a form whose whole purpose would be to defeat a right-to-be-forgotten
    # request that has already been honoured.
    if obj.is_anonymized:
        messages.error(  # noqa: F405
            request,
            'This contact was erased at their request and cannot be edited. '
            'Add a new contact if they get back in touch.',
        )
        return redirect('scheduling:contact_detail', pk=obj.pk)  # noqa: F405

    form = ContactForm(request.POST or None, instance=obj, request=request)

    if request.method == 'POST' and form.is_valid():
        form.save()
        logger.info('Contact updated contact_id=%s by user_id=%s',
                    obj.pk, request.user.pk)
        messages.success(request, f'{obj.display_name} has been updated.')  # noqa: F405
        _warn_about_shared_number(request, form)
        return redirect('scheduling:contact_detail', pk=obj.pk)  # noqa: F405

    return render(request, 'scheduling/directory/contact/form.html', {  # noqa: F405
        'form': form,
        'obj': obj,
        'is_edit': True,
    })


def _warn_about_shared_number(request, form):
    """Tell the user when they have just saved onto an already-known number.

    Informational, not an error: shared lines are legitimate. But silently
    creating a second row for what the user thought was an existing contact is
    how a directory rots, so the ambiguity is surfaced at the moment it is made.
    """
    others = getattr(form, 'existing_with_same_phone', None)
    if not others:
        return
    names = ', '.join(contact.display_name for contact in others)
    messages.info(  # noqa: F405
        request,
        f'That number is also on file for {names}. Shared lines are fine — but '
        'if this is the same person, merge them rather than keeping both.',
    )


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
@require_POST  # noqa: F405
def contact_delete_view(request, pk):
    """Erase a contact.

    Deleting is genuinely correct here, unlike `Location` — a contact is a person,
    and a person who asks to be forgotten under GDPR/CCPA must actually go. What
    protects the calendar is the FK direction: sub-module 4.3's
    `Appointment.contact` uses `on_delete=PROTECT`, so a contact with bookings
    raises `ProtectedError` instead of silently taking appointment history with
    it. That branch is unreachable until 4.3 lands and is written now so the
    behaviour never depends on which sub-module happened to be built.
    """
    obj = get_object_or_404(_tenant_contacts(request), pk=pk)  # noqa: F405
    label = obj.display_name

    try:
        obj.delete()
    except ProtectedError:
        logger.info('Contact delete blocked by related rows contact_id=%s', obj.pk)
        messages.error(  # noqa: F405
            request,
            f'{label} has appointments on file, so the record cannot be removed '
            'without leaving holes in the calendar. Use "Erase personal details" '
            'instead — it clears everything identifying and keeps the booking '
            'history attached to nobody.',
        )
        return redirect('scheduling:contact_detail', pk=obj.pk)  # noqa: F405

    logger.info('Contact deleted contact_id=%s tenant_id=%s by user_id=%s',
                pk, request.tenant.pk, request.user.pk)
    messages.success(request, f'{label} has been deleted.')  # noqa: F405
    return redirect('scheduling:contact_list')  # noqa: F405


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
@require_POST  # noqa: F405
def contact_forget_view(request, pk):
    """Honour a data-subject erasure request without deleting the row.

    The GDPR/CCPA counterpart to `contact_delete_view`, and the one that actually
    works for a contact with history: `Appointment.contact` is PROTECT, so a
    caller who has ever booked cannot be hard-deleted — which would make "delete
    my data" unanswerable for precisely the people who have used the business
    most. Blanking in place answers it while leaving the calendar intact.

    Irreversible by design. There is no un-erase, because an un-erase would mean
    the data was never really gone.
    """
    obj = get_object_or_404(_tenant_contacts(request), pk=pk)  # noqa: F405

    if obj.is_anonymized:
        messages.info(request, 'That contact has already been erased.')  # noqa: F405
        return redirect('scheduling:contact_detail', pk=obj.pk)  # noqa: F405

    obj.anonymize()

    # Deliberately no name, number or email in this line — logging the details of
    # an erasure would leave the very PII the erasure was meant to remove sitting
    # in the log file.
    logger.info('Contact anonymized contact_id=%s tenant_id=%s by user_id=%s',
                obj.pk, request.tenant.pk, request.user.pk)
    messages.success(  # noqa: F405
        request,
        'Personal details erased. The record remains so past appointments still '
        'add up, but it no longer identifies anyone.',
    )
    return redirect('scheduling:contact_detail', pk=obj.pk)  # noqa: F405
