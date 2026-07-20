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

    # Set when a data-subject erasure request is honoured. The row survives with
    # its primary key intact — `Appointment.contact` is PROTECT, so hard-deleting
    # a contact who has ever booked is refused, and the calendar must not grow
    # holes to satisfy a privacy request. Everything identifying is blanked
    # instead; what remains is an appointment that happened, attached to nobody.
    #
    # NOT in NavAIReceptionist-ERD.md. The ERD is intent and the code is truth:
    # erasure has no other durable marker, and without one an erased contact is
    # indistinguishable from a caller who simply never gave a name.
    anonymized_at = models.DateTimeField(null=True, blank=True)  # noqa: F405

    class Meta:
        ordering = ['last_name', 'first_name', '-created_at']
        indexes = [
            # The inbound-call hot path: resolve a caller from `From` on every
            # ring. Deliberately NOT unique — a household, an office switchboard
            # or a shared mobile legitimately maps to several people, and a
            # unique constraint here would make the second one unsaveable.
            #
            # This composite is the ONLY index `phone_e164` needs. A bare
            # single-column `db_index=True` on the field as well would serve no
            # query in this app — every lookup is tenant-scoped by Invariant, so
            # the composite's leading column already covers it — while costing a
            # second index write on every insert.
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
        if self.anonymized_at:
            return 'Erased contact'
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

    @property
    def is_anonymized(self):
        """Whether this row has been through a data-subject erasure request."""
        return self.anonymized_at is not None

    def anonymize(self):
        """Irreversibly blank every identifying field, keeping the row.

        The GDPR/CCPA erasure path for a contact who cannot be hard-deleted
        because they have booking history behind a PROTECT FK. This is the whole
        reason the method exists: without it, "delete me" is unanswerable for
        exactly the people who have used the business most.

        **Erasure cascades to linked callback requests.** Blanking this row's own
        columns is not sufficient, because `CallbackRequest.contact` is SET_NULL
        rather than PROTECT: those rows carry their OWN free-text
        `caller_name` / `caller_phone`, captured before the agent knew who was
        ringing and often a different number from the one on this row. They are
        independent copies of the caller's identity, so an erasure that stopped
        here would leave that PII standing in the callback queue — and would
        eventually orphan it entirely, since the FK nulls itself the moment this
        contact is removed. `_scrub_linked_callback_requests()` closes that.

        `CallbackRequest.reason` and `.notes` are deliberately NOT scrubbed. They
        are the queue's operational message — what the callback was about and
        what happened when someone rang back — not caller identity, and erasing
        them would destroy the front desk's working record of its own shift. A
        stricter policy that also scrubs them is a deliberate future decision,
        not something this method should quietly expand into.

        Idempotent: the guard below returns before anything is written, so a
        second call cannot re-stamp `anonymized_at` (the honest record of when
        erasure actually happened) and cannot re-run the cascade. The cascade is
        independently safe to repeat anyway — it blanks fields to a constant.
        """
        if self.anonymized_at:
            return self

        self.first_name = ''
        self.last_name = ''
        self.phone_e164 = ''
        self.email = ''
        self.date_of_birth = None
        self.notes = ''
        self.anonymized_at = timezone.now()  # noqa: F405
        self.save(update_fields=[
            'first_name', 'last_name', 'phone_e164', 'email',
            'date_of_birth', 'notes', 'anonymized_at', 'updated_at',
        ])
        self._scrub_linked_callback_requests()
        return self

    def delete(self, *args, **kwargs):
        """Scrub the callbacks' copy of this caller's identity, then delete.

        `anonymize()` is the soft path and cascades on its own; this is the hard
        one, and without this override it erased LESS than the soft one did.
        `CallbackRequest.contact` is `SET_NULL`, so deleting a contact who has a
        callback but no appointment succeeds — the FK quietly nulls and the
        `caller_name` / `caller_phone` duplicated onto that callback row survive,
        no longer attached to anything that could ever be found and erased again.
        For a delete whose entire purpose is a GDPR/CCPA erasure request, leaving
        the identity behind on a sibling table is the exact failure the request
        was meant to prevent.

        Overriding `delete()` rather than patching `contact_delete_view` covers
        every instance-delete path at once — the view, the admin, the shell, and
        whatever calls it next — instead of the one call site that happens to
        exist today.

        NOT triggered by a queryset `.delete()`, which Django executes in bulk
        without instantiating rows. The only bulk delete of contacts in this
        project is `seed_scheduling --flush`, which deletes the callbacks in the
        same pass, so nothing is stranded there. A future bulk erasure path must
        scrub explicitly.
        """
        self._scrub_linked_callback_requests()
        return super().delete(*args, **kwargs)

    def _scrub_linked_callback_requests(self):
        """Blank the caller identity duplicated onto this contact's callbacks.

        Called by BOTH erasure paths — `anonymize()` (soft) and `delete()`
        (hard) — so the two cannot drift into erasing different amounts. See
        `anonymize()` for why this exists and why `reason` / `notes` are out of
        scope; this method only carries out that decision.

        The import is local because `CallbackRequest` FKs `Contact` — importing
        it at module level would be a circular import through the models
        package. Same lazy-import reasoning as
        `views/ContactDirectory/Contacts.py::_appointments_for`, though this one
        needs no `ImportError` guard: `CallbackRequest` ships in this app.

        `tenant_id` is redundant given the `contact=self` match and is included
        anyway — an erasure query is the last place to rely on a single
        predicate being enough, and it keeps the filter honest if the FK ever
        gains a cross-tenant escape hatch.

        `.update()` is a single UPDATE that bypasses `save()`, so `auto_now` on
        `updated_at` never fires — hence stamping it by hand. Doing this row by
        row instead would issue one query per callback for no benefit: there is
        nothing to validate and no `save()` side effect worth triggering.
        """
        from apps.scheduling.models import CallbackRequest

        CallbackRequest.objects.filter(
            contact=self, tenant_id=self.tenant_id
        ).update(caller_name='', caller_phone='', updated_at=timezone.now())  # noqa: F405
