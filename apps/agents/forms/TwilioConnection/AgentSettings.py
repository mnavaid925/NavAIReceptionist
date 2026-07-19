"""Twilio connection form (sub-module 2.2) — the highest-risk form in the product.

`twilio_auth_token` is **not in `Meta.fields`**. That is the whole defence, and it
has to be structural rather than a convention: a `ModelForm` binds every field it
names to its current value, so listing the token there would render it into the
edit page's `value=` attribute in plaintext — cached by the browser, visible in
view-source, and captured by any intermediary that logs response bodies.

Instead a separate, always-empty `new_auth_token` field is offered, and a blank
submit means "leave the stored one alone" rather than "erase it". The page shows
only a set / not-set indicator, never the value.
"""
import re

from apps.agents.forms._common import *  # noqa: F401,F403
from apps.agents.models import AgentSetting

__all__ = ['TwilioConnectionForm']

E164 = re.compile(r'^\+[1-9]\d{7,14}$')


class TwilioConnectionForm(TenantLocationModelForm):  # noqa: F405
    """Bind a Twilio account and inbound number to this location."""

    new_auth_token = forms.CharField(  # noqa: F405
        label='Auth token',
        required=False,
        strip=True,
        widget=forms.PasswordInput(  # noqa: F405
            render_value=False,
            attrs={'autocomplete': 'new-password', 'placeholder': 'Leave blank to keep the current token'},
        ),
        help_text='Stored encrypted. It is never shown again once saved — to '
                  'change it, paste a new one.',
    )

    class Meta:
        model = AgentSetting
        # twilio_auth_token is ABSENT on purpose. See the module docstring.
        fields = ('twilio_account_sid', 'inbound_phone_number')
        labels = {
            'twilio_account_sid': 'Account SID',
            'inbound_phone_number': 'Inbound phone number',
        }
        help_texts = {
            'twilio_account_sid': 'Starts with "AC". Safe to display — it is an '
                                  'identifier, not a secret.',
            'inbound_phone_number': 'E.164, e.g. +13125550142. This is the number '
                                    'callers dial to reach this location.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['twilio_account_sid'].required = False
        self.fields['inbound_phone_number'].required = False
        style_widgets(self)  # noqa: F405

    def clean_twilio_account_sid(self):
        sid = (self.cleaned_data.get('twilio_account_sid') or '').strip()
        if sid and not sid.startswith('AC'):
            raise ValidationError('A Twilio account SID starts with "AC".')  # noqa: F405
        return sid

    def clean_inbound_phone_number(self):
        """Validate E.164 and enforce the GLOBAL uniqueness carefully.

        The number is unique across every tenant, because an inbound webhook
        resolves the tenant and location from it. So a collision may well be with
        another business — and the error must NOT say so. "Already in use" leaks
        that some other customer of this platform owns that number; the wording
        below deliberately does not distinguish the two cases.
        """
        number = (self.cleaned_data.get('inbound_phone_number') or '').strip()
        if not number:
            return None  # NULL, never '' — empty strings collide in a unique index

        if not E164.match(number):
            raise ValidationError(  # noqa: F405
                'Enter the number in E.164 format, starting with + and the country '
                'code, e.g. +13125550142.'
            )

        clash = AgentSetting.objects.filter(inbound_phone_number=number)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError(  # noqa: F405
                'That number is not available. Each number can only be connected '
                'to one location.'
            )
        return number

    def clean(self):
        cleaned = super().clean()
        sid = cleaned.get('twilio_account_sid')
        token = cleaned.get('new_auth_token')
        has_token = bool(token) or bool(self.instance.twilio_auth_token)

        if sid and not has_token:
            self.add_error(
                'new_auth_token',
                'An account SID without its auth token cannot authenticate. Paste '
                'the token as well.',
            )
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        # Only overwrite when something was actually typed. This is what makes a
        # blank submit mean "unchanged" instead of wiping a working credential.
        new_token = self.cleaned_data.get('new_auth_token')
        if new_token:
            instance.twilio_auth_token = new_token
        if commit:
            instance.save()
        return instance
