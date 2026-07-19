"""Location form (sub-module 1.2).

`tenant` is never a field — `TenantModelForm` pops it and stamps it from
`request.tenant` in `save()`. A form that let a user choose the business would
let them file a site under someone else's.
"""
from django.utils.text import slugify

from apps.tenants.forms.Business import timezone_choices
from apps.tenants.forms._common import *  # noqa: F401,F403
from apps.tenants.models import Location

__all__ = ['LocationForm', 'COUNTRY_CHOICES']

COUNTRY_CHOICES = [
    ('US', 'United States'),
    ('CA', 'Canada'),
    ('GB', 'United Kingdom'),
    ('IE', 'Ireland'),
    ('AU', 'Australia'),
    ('NZ', 'New Zealand'),
    ('DE', 'Germany'),
    ('FR', 'France'),
    ('ES', 'Spain'),
    ('AE', 'United Arab Emirates'),
    ('PK', 'Pakistan'),
    ('IN', 'India'),
    ('SG', 'Singapore'),
]


class LocationForm(TenantModelForm):  # noqa: F405
    """Create or edit one site."""

    class Meta:
        model = Location
        fields = (
            'name',
            'slug',
            'address_line1',
            'address_line2',
            'city',
            'state',
            'postal_code',
            'country',
            'timezone',
            'phone',
            'is_active',
        )
        help_texts = {
            'slug': 'A short identifier, unique within your business. Leave blank '
                    'to generate one from the name.',
            'timezone': 'Appointment and transfer-hours calculations at this site '
                        'are evaluated in this timezone.',
            'phone': 'The public number for this site. This is NOT the agent '
                     "inbound number — that is configured per location under Agent "
                     'Setup.',
            'is_active': 'Inactive sites keep their history but disappear from the '
                         'location switcher and cannot be worked in.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].required = True
        self.fields['slug'].required = False
        self.fields['country'] = forms.ChoiceField(  # noqa: F405
            label='Country', choices=COUNTRY_CHOICES, required=False,
            initial=self.instance.country or 'US',
        )
        default_tz = (
            self.instance.timezone
            or (self.tenant.timezone if self.tenant else 'UTC')
        )
        self.fields['timezone'] = forms.ChoiceField(  # noqa: F405
            label='Timezone',
            choices=timezone_choices(default_tz),
            initial=default_tz,
            help_text=self.Meta.help_texts['timezone'],
        )
        style_widgets(self)  # noqa: F405

    def clean_slug(self):
        """Derive a slug when blank, and keep `(tenant, slug)` unique.

        Validating here turns what would be a database IntegrityError 500 into a
        field error the user can act on.
        """
        slug = (self.cleaned_data.get('slug') or '').strip()
        if not slug:
            slug = slugify(self.data.get('name', ''))[:255]
        if not slug:
            raise ValidationError('Enter a name so a slug can be generated.')  # noqa: F405

        clash = Location.objects.filter(tenant=self.tenant, slug=slug)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError(  # noqa: F405
                'Another location in this business already uses that identifier.'
            )
        return slug

    def clean_timezone(self):
        """Reject a name `zoneinfo` cannot load.

        `Location.tzinfo` degrades to UTC on a bad name so a calendar render never
        explodes — which means a typo here would silently shift every appointment
        at this site by hours. Catching it at entry is the only place it is visible.
        """
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        value = (self.cleaned_data.get('timezone') or '').strip()
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError('That is not a recognised timezone name.')  # noqa: F405
        return value
