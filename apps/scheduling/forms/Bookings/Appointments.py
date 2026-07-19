"""Appointment forms (sub-module 4.3).

Two distinct forms, because booking and administering are different acts:

* `AppointmentForm` — the manual, staff-facing booking. It renders `start_at` and
  chooses the FKs directly. This is the front desk taking a booking with the
  calendar in front of them.
* `AppointmentCancelForm` — a reason, nothing else.

**There is no form for the token path.** A slot-token booking never binds a
ModelForm: the whole point of the opaque token is that the time, provider and
resource come from what the SERVER minted, not from posted fields. That path goes
through `availability.book_slot`.

`tenant` and `location` are stamped by `TenantLocationModelForm`; `source`,
`cancelled_at`, `cancellation_reason` and `end_at` are all server-owned and are
not fields.
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone as dj_timezone

from apps.scheduling.forms._common import *  # noqa: F401,F403
from apps.scheduling.models import Appointment, Contact, Resource, Service

__all__ = ['AppointmentForm', 'AppointmentCancelForm']


class AppointmentForm(TenantLocationModelForm):  # noqa: F405
    """Create or edit one appointment by hand."""

    #: Narrowed to the active tenant by `TenantModelForm`. Contact is business-
    #: wide (Invariant 1), so it is tenant-scoped only — deliberately NOT
    #: location-scoped, or a caller who usually visits another site could not be
    #: booked here.
    tenant_scoped_fields = ('contact', 'service', 'resource')

    #: Narrowed to the active location. `service` is NOT here: its location is
    #: nullable, so the additive filter is applied by hand in `__init__`.
    location_scoped_fields = ('resource',)

    class Meta:
        model = Appointment
        fields = (
            'contact',
            'service',
            'provider',
            'resource',
            'start_at',
            'status',
            'reason',
            'notes',
        )
        labels = {
            'start_at': 'Starts at',
            'reason': 'Reason for visit',
        }
        help_texts = {
            'start_at': 'In this location\'s local time. The end time is worked '
                        'out from the service duration.',
            'reason': 'What the appointment is for, in the caller\'s own words '
                      'where you have them.',
        }
        widgets = {
            'start_at': forms.DateTimeInput(  # noqa: F405
                attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'
            ),
            'notes': forms.Textarea(attrs={'rows': 3}),  # noqa: F405
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Services offered here = this location's own PLUS the all-location ones.
        # A plain `location=` filter would hide every business-wide service,
        # which is most of a typical catalogue. Same additive rule as 4.2's
        # `_bookable_here`, applied to a form queryset rather than a list view.
        service_field = self.fields['service']
        if self.tenant is not None:
            service_field.queryset = (
                Service.objects.filter(tenant=self.tenant, is_active=True)
                .filter(Q(location=self.location) | Q(location__isnull=True))
                .order_by('display_order', 'name')
            )
        else:
            service_field.queryset = Service.objects.none()

        resource_field = self.fields['resource']
        if self.location is not None:
            resource_field.queryset = Resource.objects.filter(
                tenant=self.tenant, location=self.location, is_active=True
            ).order_by('display_order', 'name')
        else:
            resource_field.queryset = Resource.objects.none()

        # Providers are staff assigned to THIS location — not every user in the
        # tenant. `user_locations` is the accessor from User to UserLocation.
        # `status=STATUS_ACTIVE` mirrors `availability._candidate_providers`: a
        # suspended provider cannot be offered a slot, so the manual-booking
        # dropdown must not offer them either, or a front-desk user could book
        # directly against someone `find_available_slots` would refuse.
        provider_field = self.fields['provider']
        if self.location is not None:
            from apps.accounts.models import User

            provider_field.queryset = User.objects.filter(
                tenant=self.tenant,
                is_provider=True,
                status=User.STATUS_ACTIVE,
                user_locations__location=self.location,
            ).distinct().order_by('full_name', 'email')
        else:
            from apps.accounts.models import User

            provider_field.queryset = User.objects.none()

        contact_field = self.fields['contact']
        if self.tenant is not None:
            # An erased contact must not be bookable — re-attaching them to a new
            # appointment would partly defeat the erasure.
            contact_field.queryset = Contact.objects.filter(
                tenant=self.tenant, anonymized_at__isnull=True
            ).order_by('last_name', 'first_name')
        else:
            contact_field.queryset = Contact.objects.none()

        # `cancelled` is NOT selectable here. Cancelling stamps `cancelled_at`
        # and `cancellation_reason`, which only `availability.cancel_appointment`
        # does — setting the status through this form would free the slot while
        # leaving no record of when or why, and flipping back off `cancelled`
        # would strand a stale timestamp. `completed` and `no_show` stay, because
        # this form is their only transition path.
        self.fields['status'].choices = [
            (value, label) for value, label in Appointment.STATUS_CHOICES
            if value != Appointment.STATUS_CANCELLED
        ]

        self.fields['provider'].required = False
        self.fields['resource'].required = False
        self.fields['start_at'].input_formats = [
            '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S',
        ]
        style_widgets(self)  # noqa: F405

    def clean_start_at(self):
        """Reject a start in the past on a NEW booking.

        Allowed when editing, because correcting the record of something that
        already happened is legitimate — marking a past appointment completed
        must not be blocked by a validator meant for new bookings.
        """
        value = self.cleaned_data.get('start_at')
        if value is None:
            return value
        if not self.instance.pk and value < dj_timezone.now():
            raise ValidationError(  # noqa: F405
                'That time has already passed. Pick a time in the future.'
            )
        return value

    def clean(self):
        cleaned = super().clean()

        service = cleaned.get('service')
        start_at = cleaned.get('start_at')
        provider = cleaned.get('provider')
        resource = cleaned.get('resource')

        if service is not None and service.requires_resource and resource is None:
            self.add_error(
                'resource',
                f'{service.name} needs a room or resource. Pick one.',
            )

        # Moving off `cancelled` must not leave the cancellation stamps behind,
        # or the record would read as both live and cancelled.
        status = cleaned.get('status')
        if status and status != Appointment.STATUS_CANCELLED:
            self.instance.cancelled_at = None
            self.instance.cancellation_reason = ''

        if service is not None and start_at is not None:
            # `end_at` is derived, never posted: duration is the service's, and a
            # user-supplied end could silently disagree with it.
            self.instance.end_at = start_at + timedelta(
                minutes=service.duration_minutes
            )

            # A FRIENDLY PRE-CHECK ONLY — not the enforcement.
            #
            # This runs unlocked, so between it and the insert another writer can
            # take the slot. The view wraps the save in `transaction.atomic()`,
            # locks the contended rows and re-runs this check with
            # `for_update=True`; that locked re-check is what actually prevents a
            # double booking. This one exists so the common case gets a good
            # message pointing at the field, instead of a bare form error.
            if self.tenant is not None and self.location is not None:
                from apps.scheduling.availability import overlapping_appointments

                clash = overlapping_appointments(
                    tenant=self.tenant, location=self.location,
                    start_utc=start_at,
                    end_utc=start_at + timedelta(minutes=service.total_minutes),
                    provider=provider, resource=resource,
                    exclude_pk=self.instance.pk or None,
                )
                first = clash.select_related('contact', 'resource').first()
                if first is not None:
                    where = first.resource.name if first.resource_id else 'that slot'
                    raise ValidationError(  # noqa: F405
                        f'That time is already taken — {where} is booked from '
                        f'{first.local_start():%H:%M}. Pick another time.'
                    )

        return cleaned


class AppointmentCancelForm(forms.Form):  # noqa: F405
    """Why an appointment is being cancelled."""

    reason = forms.CharField(  # noqa: F405
        label='Reason',
        max_length=255,
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),  # noqa: F405
        help_text='Recorded against the booking. A cancelled slot is freed for '
                  'someone else, but the record stays so the history is honest.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_widgets(self)  # noqa: F405
