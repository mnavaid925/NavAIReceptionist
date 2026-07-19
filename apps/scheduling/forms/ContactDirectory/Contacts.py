"""Contact form (sub-module 4.1).

`tenant` is never a field — `TenantModelForm` pops it and stamps it from
`request.tenant` in `save()`. `source` is not a field either: it records how the
row came into existence, which is an audit fact the server knows and the user
must not be able to overwrite. A receptionist editing a contact the agent created
on a call does not turn it into a manually-created one.
"""
from apps.scheduling.forms._common import *  # noqa: F401,F403
from apps.scheduling.models import Contact
from apps.scheduling.services import normalize_e164

__all__ = ['ContactForm']


class ContactForm(TenantModelForm):  # noqa: F405
    """Create or edit one contact."""

    class Meta:
        model = Contact
        fields = (
            'first_name',
            'last_name',
            'phone_e164',
            'email',
            'date_of_birth',
            'notes',
        )
        labels = {
            'phone_e164': 'Phone number',
            'date_of_birth': 'Date of birth',
        }
        help_texts = {
            'phone_e164': 'Any format is accepted — it is stored as +13125550142 '
                          'so a repeat caller is recognised however it was typed.',
            'date_of_birth': 'Optional. Only collect this if your business '
                             'actually needs it to identify someone.',
            'notes': 'Visible to your staff on the contact page and during a call. '
                     'Do not record anything you would not want read aloud.',
        }
        widgets = {
            'date_of_birth': forms.DateInput(  # noqa: F405
                attrs={'type': 'date'}, format='%Y-%m-%d'
            ),
            'notes': forms.Textarea(attrs={'rows': 4}),  # noqa: F405
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A contact with neither a name nor a number is not a contact. Which of
        # the two is present is checked in `clean()`, so neither field is
        # individually required.
        for name in ('first_name', 'last_name', 'phone_e164', 'email'):
            self.fields[name].required = False
        self.fields['date_of_birth'].input_formats = ['%Y-%m-%d']
        style_widgets(self)  # noqa: F405

    def clean_phone_e164(self):
        """Normalise here too, so the duplicate check in `clean()` compares like
        with like — `save()` would otherwise normalise only AFTER the lookup.
        """
        raw = (self.cleaned_data.get('phone_e164') or '').strip()
        if not raw:
            return ''

        normalized = normalize_e164(raw)
        if not normalized:
            raise ValidationError(  # noqa: F405
                'That does not look like a phone number. Enter it with the '
                'country code, for example +1 312 555 0142.'
            )
        return normalized

    def clean_date_of_birth(self):
        """A birth date in the future is a typo, always."""
        value = self.cleaned_data.get('date_of_birth')
        if value and value > timezone.localdate():  # noqa: F405
            raise ValidationError('That date is in the future.')  # noqa: F405
        return value

    def clean(self):
        cleaned = super().clean()

        first = (cleaned.get('first_name') or '').strip()
        last = (cleaned.get('last_name') or '').strip()
        phone = (cleaned.get('phone_e164') or '').strip()
        email = (cleaned.get('email') or '').strip()

        if not (first or last or phone or email):
            raise ValidationError(  # noqa: F405
                'Enter at least a name, a phone number or an email address.'
            )

        # Warn on an exact number match rather than blocking it. A shared line —
        # a household, a switchboard, a couple on one mobile — is a real thing,
        # and refusing the second person would make them unbookable. The check is
        # tenant-scoped: two businesses may each know the same number.
        if phone and self.tenant is not None:
            clash = Contact.objects.filter(tenant=self.tenant, phone_e164=phone)
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            self.existing_with_same_phone = list(clash[:5])
        else:
            self.existing_with_same_phone = []

        return cleaned
