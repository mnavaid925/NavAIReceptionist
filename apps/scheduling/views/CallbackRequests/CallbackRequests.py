"""Callback request CRUD and the resolve action (sub-module 4.5).

`CallbackRequest` is fully location-scoped, so every queryset here carries BOTH
`tenant=request.tenant` and `location=request.location`. A callback is worked by
the staff at the site that took the call; showing another site's queue would put
rows in front of people who cannot act on them and expose that site's callers.

**The list is a QUEUE, not a history.** It filters to `pending` by default,
because the page's job is "who still needs ringing back". Full history is one
click away through the filter bar's explicit "All" option — which is why the
status parameter distinguishes *absent* from *present-but-empty*, a distinction
no other list in this app has to make.

PII note: `caller_name`, `caller_phone` and `reason` are caller-supplied personal
data — a phone number and, often, why someone is calling a clinic. Nothing here
logs a field value; every log line below carries primary keys and ids only.
"""
import logging

from django.db.models import Q

from apps.scheduling.forms import CallbackRequestForm, CallbackResolveForm
from apps.scheduling.models import CallbackRequest
from apps.scheduling.views._common import *  # noqa: F401,F403

logger = logging.getLogger(__name__)

__all__ = [
    'callbackrequest_list_view',
    'callbackrequest_create_view',
    'callbackrequest_detail_view',
    'callbackrequest_edit_view',
    'callbackrequest_delete_view',
    'callbackrequest_resolve_view',
]


def _location_callbacks(request):
    """The queue at the active location. Tenant AND location scoped, always.

    Entity-local on purpose: only this module reads callbacks, so it stays here
    rather than in `views/_helpers.py`, which is reserved for helpers a SECOND
    sub-module actually shares (4.4's calendar reading 4.3's appointments is the
    case that file exists for).

    Returns nothing when no location is active — the safe direction, matching
    `location_appointments`. A user who has not chosen a site sees an empty queue
    and the global "choose a location" banner, never another site's callers.
    """
    if request.location is None:
        return CallbackRequest.objects.none()
    return CallbackRequest.objects.filter(
        tenant=request.tenant, location=request.location
    ).select_related('contact', 'location')


@login_required  # noqa: F405
def callbackrequest_list_view(request):
    """The callback queue: pending by default, searchable, filterable by status."""
    queryset = _location_callbacks(request)

    search = request.GET.get('q', '').strip()
    if search:
        # Both the free-text capture AND the linked contact, because the same
        # person can appear either way: the agent writes what it heard into
        # `caller_name`, and a receptionist who recognises them later attaches
        # the `Contact`. Searching only one half loses whichever rows took the
        # other path.
        queryset = queryset.filter(
            Q(caller_name__icontains=search)
            | Q(caller_phone__icontains=search)
            | Q(reason__icontains=search)
            | Q(contact__first_name__icontains=search)
            | Q(contact__last_name__icontains=search)
            | Q(contact__phone_e164__icontains=search)
        )

    # ABSENT and PRESENT-BUT-EMPTY are different requests, and `request.GET.get`
    # collapses them. No parameter at all means "I opened the queue" → pending;
    # `?status=` means "I picked All in the filter bar" → no status filter. Using
    # `.get('status', '')` here would make the All option unreachable, because it
    # posts exactly the empty string.
    if 'status' in request.GET:
        status = request.GET['status'].strip()
    else:
        status = CallbackRequest.STATUS_PENDING

    # A junk `?status=whatever` degrades to "no filter", never raises.
    if status in dict(CallbackRequest.STATUS_CHOICES):
        queryset = queryset.filter(status=status)
    else:
        status = ''

    page_obj, elided_page_range = paginate(request, queryset)  # noqa: F405

    return render(request, 'scheduling/callbacks/callbackrequest/list.html', {  # noqa: F405
        'callback_requests': page_obj.object_list,
        'page_obj': page_obj,
        'elided_page_range': elided_page_range,
        'total_count': page_obj.paginator.count,
        # The filter bar's <select> needs the choices; without this the dropdown
        # renders empty and the status filter silently does nothing.
        'status_choices': CallbackRequest.STATUS_CHOICES,
        # What the queue falls back to, so the filter bar can say so in words.
        'default_status': CallbackRequest.STATUS_PENDING,
        # The status ACTUALLY in force after the absent/empty/junk resolution
        # above — '' meaning "all". The template preselects against this rather
        # than re-deriving it from `request.GET`, which cannot tell an absent
        # parameter from an empty one.
        'selected_status': status,
    })


@login_required  # noqa: F405
def callbackrequest_detail_view(request, pk):
    """One callback, with the resolve card ready to post."""
    obj = get_object_or_404(_location_callbacks(request), pk=pk)  # noqa: F405

    return render(request, 'scheduling/callbacks/callbackrequest/detail.html', {  # noqa: F405
        'obj': obj,
        'resolve_form': CallbackResolveForm(instance=obj),
    })


@login_required  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def callbackrequest_create_view(request):
    """Log a callback by hand. The agent logs its own on an inbound call."""
    # `TenantLocationModelForm` stamps `location` from the request and skips it
    # when there is none, which would reach the database as a NOT NULL violation
    # — a 500 on the ordinary "logged in, no site chosen yet" path. Same guard,
    # same reason, as `appointment_create_view`.
    if request.location is None:
        messages.error(  # noqa: F405
            request, 'Choose a location before logging a callback for it.'
        )
        return redirect('scheduling:callbackrequest_list')  # noqa: F405

    form = CallbackRequestForm(request.POST or None, request=request)

    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        # Provenance is a server fact, not a form field — a callback typed into
        # this form was typed by a person at a desk, whatever the client posted.
        obj.source = CallbackRequest.SOURCE_MANUAL
        obj.save()

        logger.info(
            'Callback request created callback_id=%s tenant_id=%s '
            'location_id=%s by user_id=%s',
            obj.pk, request.tenant.pk, request.location.pk, request.user.pk,
        )
        messages.success(request, 'Callback request logged.')  # noqa: F405
        return redirect('scheduling:callbackrequest_detail', pk=obj.pk)  # noqa: F405

    return render(request, 'scheduling/callbacks/callbackrequest/form.html', {  # noqa: F405
        'form': form,
        'is_edit': False,
    })


@login_required  # noqa: F405
@require_http_methods(['GET', 'POST'])  # noqa: F405
def callbackrequest_edit_view(request, pk):
    """Edit a callback. Correctable at ANY status, including closed.

    Deliberately unlike `appointment_edit_view`, which refuses once a booking is
    closed out. An appointment is a record of something that happened, so
    reopening one rewrites history; a callback is a working note about something
    that has not happened yet, and closing the wrong row by mis-click is the
    ordinary mistake this page exists to undo. `source` is untouched either way —
    it records how the row began.
    """
    obj = get_object_or_404(_location_callbacks(request), pk=pk)  # noqa: F405

    form = CallbackRequestForm(request.POST or None, instance=obj, request=request)

    if request.method == 'POST' and form.is_valid():
        form.save()
        logger.info('Callback request updated callback_id=%s by user_id=%s',
                    obj.pk, request.user.pk)
        messages.success(request, 'Callback request updated.')  # noqa: F405
        return redirect('scheduling:callbackrequest_detail', pk=obj.pk)  # noqa: F405

    return render(request, 'scheduling/callbacks/callbackrequest/form.html', {  # noqa: F405
        'form': form,
        'obj': obj,
        'is_edit': True,
    })


@login_required  # noqa: F405
@tier_required(*MANAGEMENT_TIERS)  # noqa: F405
@require_POST  # noqa: F405
def callbackrequest_delete_view(request, pk):
    """Delete a callback outright.

    Usually the wrong action — CLOSING it keeps the record of a caller who was
    dealt with, which is what a manager reviewing the week actually wants.
    Deleting is for a row that should never have existed, so it is
    management-only.

    No `ProtectedError` branch: nothing points at a `CallbackRequest` with
    `on_delete=PROTECT`, so unlike `contact_delete_view` there is no related-rows
    case to catch. If a later module adds such a child, this needs the branch.
    """
    obj = get_object_or_404(_location_callbacks(request), pk=pk)  # noqa: F405
    obj.delete()

    logger.info('Callback request deleted callback_id=%s tenant_id=%s by user_id=%s',
                pk, request.tenant.pk, request.user.pk)
    messages.success(  # noqa: F405
        request,
        'Callback request deleted. To keep a record of a caller you have dealt '
        'with, close the callback instead of deleting it.',
    )
    return redirect('scheduling:callbackrequest_list')  # noqa: F405


@login_required  # noqa: F405
@require_POST  # noqa: F405
def callbackrequest_resolve_view(request, pk):
    """Mark a callback contacted or closed, with a note.

    Posted from two places — the quick-resolve control on a list row and the
    resolve card on the detail page — so the destination comes from a hidden
    `next` carrying `request.get_full_path`, run through `safe_redirect_target`.
    Sending everyone to the detail page instead would throw away the filtered,
    paginated queue a receptionist was working down.

    `CallbackResolveForm` refuses `pending`, so this action can only ever move a
    row forward; putting one back into the queue is a correction and goes
    through the edit form.
    """
    obj = get_object_or_404(_location_callbacks(request), pk=pk)  # noqa: F405
    destination = safe_redirect_target(  # noqa: F405
        request,
        default=reverse('scheduling:callbackrequest_detail', args=[obj.pk]),  # noqa: F405
    )

    form = CallbackResolveForm(request.POST, instance=obj)
    if not form.is_valid():
        # POST-only, so there is no bound form to re-render — report and return
        # the user where they were rather than 500 on a status the form's own
        # narrowed choices already rejected.
        messages.error(  # noqa: F405
            request,
            'That is not a status a callback can be resolved to. Use Edit to '
            'put it back into the queue.',
        )
        return redirect(destination)  # noqa: F405

    form.save()

    logger.info('Callback request resolved callback_id=%s status=%s by user_id=%s',
                obj.pk, obj.status, request.user.pk)
    messages.success(  # noqa: F405
        request, f'Callback marked {obj.get_status_display().lower()}.'
    )
    return redirect(destination)  # noqa: F405
