"""Business settings form (sub-module 1.1).

Only `name` and `timezone` are editable, and the omissions are deliberate:

* `customer_id` is the key a user types at login to resolve their business. Let a
  business edit it and they can lock every one of their own staff out with a typo,
  with no way back in through the product.
* `slug` is an identifier nothing in the product surfaces yet; exposing a field
  with no user-visible effect invites changes whose consequences nobody can see.
* `is_active` suspends the business. That is a platform action — a business
  cannot be allowed to switch itself off from inside a page its own staff reach,
  because doing so blocks their next login (`CustomerScopedBackend` filters on
  `is_active`) and nobody left has a way to undo it.

All three still RENDER on the settings page, read-only. Hiding them entirely
would leave a user unable to find the Customer ID they need in order to sign in.
"""
from apps.tenants.forms._common import *  # noqa: F401,F403
from apps.tenants.models import Tenant

__all__ = ['BusinessSettingsForm', 'COMMON_TIMEZONES']

# A short, curated list beats 590 IANA zones in a <select>. "Other" cases go
# through the admin; the field itself accepts any valid name.
COMMON_TIMEZONES = [
    'UTC',
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Phoenix',
    'America/Los_Angeles',
    'America/Anchorage',
    'Pacific/Honolulu',
    'America/Toronto',
    'America/Vancouver',
    'Europe/London',
    'Europe/Dublin',
    'Europe/Paris',
    'Europe/Berlin',
    'Europe/Madrid',
    'Europe/Warsaw',
    'Asia/Dubai',
    'Asia/Karachi',
    'Asia/Kolkata',
    'Asia/Singapore',
    'Asia/Tokyo',
    'Australia/Sydney',
    'Pacific/Auckland',
]


def timezone_choices(current=None):
    """The curated list, with the row's own value added if it is not in it."""
    values = list(COMMON_TIMEZONES)
    if current and current not in values:
        values.insert(0, current)
    return [(value, value.replace('_', ' ')) for value in values]


class BusinessSettingsForm(forms.ModelForm):  # noqa: F405
    """Edit the business record. Owner-only — see the view's tier gate.

    A plain `ModelForm`, not `TenantModelForm`: this form's instance IS the
    tenant, so there is no `tenant` FK to stamp or strip.
    """

    class Meta:
        model = Tenant
        fields = ('name', 'timezone')
        help_texts = {
            'name': 'Used in confirmations and anywhere the agent names your '
                    'business to a caller.',
            'timezone': 'The default for new locations. Each location keeps its '
                        'own timezone, and appointment times are always evaluated '
                        "in the location's.",
        }

    def __init__(self, *args, **kwargs):
        # Swallow `request=` so the view can pass it uniformly alongside the
        # TenantModelForm-based forms elsewhere in this module.
        kwargs.pop('request', None)
        super().__init__(*args, **kwargs)
        self.fields['name'].required = True
        self.fields['timezone'] = forms.ChoiceField(  # noqa: F405
            label='Default timezone',
            choices=timezone_choices(self.instance.timezone if self.instance else None),
            help_text=self.Meta.help_texts['timezone'],
        )
        style_widgets(self)  # noqa: F405

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        if not name:
            raise ValidationError('The business needs a name.')  # noqa: F405
        return name
