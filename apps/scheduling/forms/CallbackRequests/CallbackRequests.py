"""Callback request forms (sub-module 4.5).

Two forms, split the same way 4.3 splits booking from administering:

* `CallbackRequestForm` — the general CRUD form. Any of the three statuses is
  selectable, because a callback is explicitly NOT a linear state machine (see
  `CallbackRequest.STATUS_CHOICES`) and a mis-click must stay correctable.
* `CallbackResolveForm` — status and notes only, and only the two statuses that
  move a queue item FORWARD. The dedicated one-transition form, structurally the
  sibling of `AppointmentCancelForm`.

`tenant` and `location` are stamped by `TenantLocationModelForm`. `source` is not
a field either: it is the provenance record — whether the agent, a receptionist
or the web form created this row — and a staff member editing a callback the
agent logged must not be able to rewrite it into a manually-created one.
"""
from apps.scheduling.forms._common import *  # noqa: F401,F403
from apps.scheduling.models import CallbackRequest, Contact
from apps.scheduling.services import normalize_e164

__all__ = ['CallbackRequestForm', 'CallbackResolveForm']

# Strip these and a plain dialling string is left as bare digits; anything that
# still isn't a digit run carries human text ("x204", "ask for Dana"). That is
# the whole test in `clean_caller_phone` for whether normalising is safe —
# `normalize_e164` discards every non-digit, so it must not be let near a value
# whose non-digits are the part a person needs to complete the call.
_DIALLING_PUNCTUATION = str.maketrans('', '', '+()-. \t')


class CallbackRequestForm(TenantLocationModelForm):  # noqa: F405
    """Log or edit one callback request."""

    #: Contact is business-wide (Invariant 1), so it is narrowed to the tenant
    #: and deliberately NOT to the location: a caller who normally visits another
    #: site can still ask THIS site to ring them back, which is precisely the
    #: cross-site case the seeder covers.
    tenant_scoped_fields = ('contact',)

    class Meta:
        model = CallbackRequest
        fields = (
            'contact',
            'caller_name',
            'caller_phone',
            'reason',
            'status',
            'notes',
        )
        labels = {
            'caller_name': 'Caller name',
            'caller_phone': 'Callback number',
        }
        help_texts = {
            'contact': 'Leave blank if you do not know who rang — that is a '
                       'normal outcome on an inbound call, not a gap to fill in.',
            'caller_name': 'What the caller gave, even if they are not in your '
                           'directory.',
            'caller_phone': 'The number to ring BACK on, which is often not the '
                            'one they rang from. An extension or a "ask for …" '
                            'note is kept as typed.',
            'reason': 'What they want. Shown to whoever picks the callback up.',
            'notes': 'What happened when you rang back.',
        }
        widgets = {
            'reason': forms.Textarea(attrs={'rows': 3}),  # noqa: F405
            'notes': forms.Textarea(attrs={'rows': 3}),  # noqa: F405
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # An erased contact must not be re-attachable — pointing a fresh callback
        # at them would partly undo the erasure, and 4.5's own anonymize cascade
        # would then have to scrub this row a second time. Same rule and same
        # queryset shape as `AppointmentForm.__init__`.
        contact_field = self.fields['contact']
        if self.tenant is not None:
            contact_field.queryset = Contact.objects.filter(
                tenant=self.tenant, anonymized_at__isnull=True
            ).order_by('last_name', 'first_name')
        else:
            contact_field.queryset = Contact.objects.none()

        contact_field.required = False
        contact_field.empty_label = 'Unidentified caller'

        # Which of the three identifying fields is present is decided in
        # `clean()`, so none of them is individually required.
        for name in ('caller_name', 'caller_phone'):
            self.fields[name].required = False

        style_widgets(self)  # noqa: F405

    def clean_caller_phone(self):
        """Normalise to E.164 ONLY when the value is unambiguously just a number.

        A deliberate departure from `ContactForm.clean_phone_e164`, which
        normalises unconditionally and raises on failure. Two reasons this field
        cannot do that:

        * `CallbackRequest.caller_phone` is not a lookup key. Nothing dedupes or
          resolves a caller by it the way `Contact.phone_e164` does, so the
          uniform storage shape that justifies destructive normalisation there
          buys nothing here.
        * The value frequently is not purely a number. "312 555 0142 x204" and
          "312 555 0142, ask for Dana" are what a receptionist and an agent
          actually capture, and `normalize_e164` strips every non-digit — it
          would turn both into a bare line that reaches the wrong person, or
          nobody.

        So: normalise when the raw value contains nothing but dialling
        characters (which makes the `tel:` link in the templates reliable and
        matches the contact directory's shape), otherwise keep it verbatim. It
        NEVER raises. A partially-heard number is still the best lead anyone has
        for reaching this caller; rejecting it at the form would throw away the
        only thing the call produced.
        """
        raw = (self.cleaned_data.get('caller_phone') or '').strip()
        if not raw:
            return ''

        if not raw.translate(_DIALLING_PUNCTUATION).isdigit():
            return raw

        return normalize_e164(raw) or raw

    def clean(self):
        cleaned = super().clean()

        contact = cleaned.get('contact')
        name = (cleaned.get('caller_name') or '').strip()
        phone = (cleaned.get('caller_phone') or '').strip()

        # A callback with no contact, no name and no number is not a callback —
        # it is a row nobody can act on, sitting in the queue forever because
        # there is no one to ring. Same posture as `ContactForm.clean()`'s
        # "at least one identifying field" rule.
        if contact is None and not name and not phone:
            raise ValidationError(  # noqa: F405
                'Pick a contact, or enter a name or a number to call back on. '
                'A callback nobody can be reached on cannot be worked.'
            )

        return cleaned


class CallbackResolveForm(forms.ModelForm):  # noqa: F405
    """Move one callback forward: rang them, or done with it.

    A plain `ModelForm`, not a `TenantLocationModelForm`, because it never
    creates a row. The view fetches the instance through the tenant- AND
    location-scoped queryset before binding, so the scoping is already proved by
    the time this form exists; re-stamping `tenant`/`location` from the request
    would add a second, weaker copy of that guarantee and nothing else.
    """

    class Meta:
        model = CallbackRequest
        fields = ('status', 'notes')
        labels = {
            'notes': 'What happened',
        }
        help_texts = {
            'notes': 'Kept on the row even if the contact is later erased — it '
                     'is the queue\'s working record, not identity.',
        }
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),  # noqa: F405
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Resolving only ever moves a callback FORWARD. Offering `pending` here
        # would make the quick-resolve control on the list row able to silently
        # undo someone else's work mid-shift; putting a row back into the queue
        # is a correction, and corrections go through the general edit form.
        self.fields['status'].choices = [
            (CallbackRequest.STATUS_CONTACTED, 'Contacted'),
            (CallbackRequest.STATUS_CLOSED, 'Closed'),
        ]

        style_widgets(self)  # noqa: F405
