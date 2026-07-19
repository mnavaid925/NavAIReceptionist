"""`scheduling.Contact` — the single identity table (sub-module 4.1).

**Invariant 1.** Callers, bookers and attendees are rows in THIS table. There is
no `Lead`, `Caller`, `Patient` or `Attendee` model and there must never be one:
the whole point is that the person the agent identified on a call and the person
a receptionist booked at the front desk are the same row, so a repeat caller's
history is one history.

**Not location-scoped, deliberately.** Every other bookable thing in this module
carries a `location` FK; `Contact` does not. A caller belongs to the BUSINESS and
may book at any of its sites — someone who usually visits Acme Downtown ringing
about an appointment at Acme Uptown is one person, not two. Adding a `location`
FK here would fragment that identity and break the ANI lookup the runtime does on
an inbound call, which knows the dialed number's location but has no idea which
site the caller has used before.
"""
from apps.scheduling.models._base import *  # noqa: F401,F403
from apps.scheduling.services import normalize_e164

__all__ = ['Contact']


class Contact(TenantOwned):  # noqa: F405
    """A person the business knows: a caller, a booker, or both."""

    SOURCE_AI_PHONE = 'ai_phone'
    SOURCE_MANUAL = 'manual'
    SOURCE_WEB = 'web'

    #: How this row first came into existence. Stamped by whatever created it —
    #: never chosen by the user, so it stays a trustworthy audit of provenance.
    SOURCE_CHOICES = [
        (SOURCE_AI_PHONE, 'AI phone call'),
        (SOURCE_MANUAL, 'Added manually'),
        (SOURCE_WEB, 'Web'),
    ]

    first_name = models.CharField(max_length=128, blank=True)  # noqa: F405
    last_name = models.CharField(max_length=128, blank=True)  # noqa: F405

    # Blank-tolerant on purpose: the agent creates a contact the moment an unknown
    # number rings, long before it has asked anyone their name. A NOT NULL name
    # here would mean either inventing a placeholder or not logging the caller.
    phone_e164 = models.CharField(  # noqa: F405
        max_length=16,
        blank=True,
        db_index=True,
        help_text='Stored in E.164 form (+13125550142). Normalised on save so a '
                  'repeat caller matches however the number was typed.',
    )
    email = models.EmailField(blank=True)  # noqa: F405
    date_of_birth = models.DateField(null=True, blank=True)  # noqa: F405
    notes = models.TextField(blank=True)  # noqa: F405

    source = models.CharField(  # noqa: F405
        max_length=16,
        choices=SOURCE_CHOICES,
        default=SOURCE_MANUAL,
        db_index=True,
    )

    class Meta:
        ordering = ['last_name', 'first_name', '-created_at']
        indexes = [
            # The inbound-call hot path: resolve a caller from `From` on every
            # ring. Deliberately NOT unique — a household, an office switchboard
            # or a shared mobile legitimately maps to several people, and a
            # unique constraint here would make the second one unsaveable.
            models.Index(fields=['tenant', 'phone_e164'],  # noqa: F405
                         name='idx_contact_tenant_phone'),
            models.Index(fields=['tenant', 'last_name', 'first_name'],  # noqa: F405
                         name='idx_contact_tenant_name'),
        ]

    def __str__(self):
        return self.display_name

    def save(self, *args, **kwargs):
        """Normalise the phone number on every write.

        Done in `save()` rather than only in the form because the form is not the
        only writer: sub-module 3.3's `create_contact` tool and the seeder both
        write rows directly, and a number that skipped normalisation would be
        invisible to the ANI lookup forever after.
        """
        self.phone_e164 = normalize_e164(self.phone_e164)
        return super().save(*args, **kwargs)

    @property
    def display_name(self):
        """A human label that is never empty.

        An unknown caller has no name yet, so fall back to the number, then to a
        stable placeholder — a blank cell in the directory reads as a rendering
        bug rather than as "we do not know yet".
        """
        full = f'{self.first_name} {self.last_name}'.strip()
        if full:
            return full
        if self.phone_e164:
            return self.phone_e164
        return 'Unknown caller'

    @property
    def has_name(self):
        """Whether anyone has actually told us who this is."""
        return bool(self.first_name or self.last_name)
