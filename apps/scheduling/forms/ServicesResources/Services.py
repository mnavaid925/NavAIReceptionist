"""Service form (sub-module 4.2).

**`location` IS a field here, and that is the one deliberate exception to the
project's "never render location in a form" rule.** Elsewhere a rendered location
`<select>` is a cross-location IDOR — it lets a user file a record under a site
they were never assigned to. Here the choice is the actual product decision the
user came to make: is this service offered at one site or all of them? The leak
is closed by narrowing the queryset to the locations THIS user is assigned to,
not merely to the tenant's.
"""
from apps.scheduling.forms._common import *  # noqa: F401,F403
from apps.scheduling.models import Service

__all__ = ['ServiceForm']


class ServiceForm(TenantModelForm):  # noqa: F405
    """Create or edit one service."""

    class Meta:
        model = Service
        fields = (
            'name',
            'location',
            'description',
            'duration_minutes',
            'buffer_minutes',
            'requires_resource',
            'is_active',
            'display_order',
        )
        labels = {
            'location': 'Offered at',
            'duration_minutes': 'Duration (minutes)',
            'buffer_minutes': 'Buffer after (minutes)',
            'requires_resource': 'Needs a room or resource',
        }
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),  # noqa: F405
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # `TenantModelForm.__init__` pops `tenant` but leaves `location` alone,
        # which is what we want here — see the module docstring. Narrow it to the
        # user's OWN assigned locations: filtering by tenant alone would let a
        # single-site receptionist pin a service to a branch they cannot reach.
        location_field = self.fields['location']
        user = getattr(self.request, 'user', None) if self.request else None
        if user is not None and user.is_authenticated:
            location_field.queryset = user.assigned_locations()
        elif self.tenant is not None:
            from apps.tenants.models import Location

            location_field.queryset = Location.objects.filter(
                tenant=self.tenant, is_active=True
            )
        else:
            location_field.queryset = location_field.queryset.none()

        location_field.required = False
        location_field.empty_label = 'All locations'

        self.fields['name'].required = True
        style_widgets(self)  # noqa: F405

    def clean_duration_minutes(self):
        """A zero-length appointment is not bookable.

        `PositiveIntegerField` permits 0, which would produce slots that start and
        end at the same instant — the calendar would render them as invisible
        zero-height blocks and availability would offer infinitely many.
        """
        value = self.cleaned_data.get('duration_minutes')
        if value is not None and value < 1:
            raise ValidationError(  # noqa: F405
                'A service has to last at least a minute.'
            )
        if value is not None and value > 24 * 60:
            raise ValidationError(  # noqa: F405
                'A single appointment cannot be longer than a day.'
            )
        return value

    def clean(self):
        cleaned = super().clean()

        # A service every branch offers, and a service at one branch, may share a
        # name across DIFFERENT branches — but two identically-named services with
        # the same scope would be indistinguishable to a caller on the phone.
        name = (cleaned.get('name') or '').strip()
        location = cleaned.get('location')
        if name and self.tenant is not None:
            clash = Service.objects.filter(tenant=self.tenant, name__iexact=name,
                                           location=location)
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                where = location.name if location else 'all locations'
                raise ValidationError(  # noqa: F405
                    f'You already offer a service called "{name}" at {where}. '
                    'Give this one a different name so the agent can tell them '
                    'apart on a call.'
                )

        return cleaned
