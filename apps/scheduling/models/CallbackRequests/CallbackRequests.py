"""`scheduling.CallbackRequest` — "ring this person back" (sub-module 4.5).

Location-scoped: a callback is worked by the staff at the site that took the
call, and the queue is read per location exactly like the calendar is.

**An operational queue item, not booking history.** That single distinction is
what makes this model's `contact` FK `SET_NULL` where `Appointment.contact` is
`PROTECT`. An appointment is the record that a person was seen, so erasing the
person must never be allowed to delete it; a callback is a note-to-self that
someone wants ringing back, and once the person is gone the note is stale
paperwork. Blocking a contact's removal over one would be the tail wagging the
dog. The row survives with `contact` nulled so the queue does not develop holes
mid-shift, and the free-text `caller_name` / `caller_phone` it carries are
scrubbed by `Contact.anonymize()` — see that method, which is the only reason
those two fields are not orphaned PII.

**Invariant 1 holds even for a caller nobody identified.** An unknown caller
does NOT get some lighter-weight `Lead` row: `contact` is simply left null and
whatever the agent managed to capture lands in `caller_name` / `caller_phone`.
The moment the caller IS identified, the row points at a `scheduling.Contact`
like everything else in the product.

**Future write target, no writer yet.** Module 3.3's `request_callback(reason,
caller_name?, caller_phone?)` tool and Module 3.4's off-hours / no-answer
transfer fallback both land here; neither module exists, so 4.5 ships the shape
and nothing else — the same way 4.3 shipped `Appointment` as `book_appointment`'s
target without registering a tool. When they arrive, `tenant_id`, `location_id`
and `contact_id` come from server-side session state (Invariant 3) and are never
tool parameters: the caller is speaking to the model, so anything the model
supplies about WHO this is would be caller-controlled input.

**No FK to `calls.CallSession`.** Unlike `Appointment` — whose ERD entry does
specify one and whose docstring therefore records an omission — the ERD's
`CallbackRequest` specifies no session FK at all. There is nothing deferred
here, and no placeholder column: `source` carries provenance on its own.
"""
from apps.scheduling.models._base import *  # noqa: F401,F403

__all__ = ['CallbackRequest']


class CallbackRequest(TenantLocationOwned):  # noqa: F405
    """Someone asked to be called back, and nobody has done it yet."""

    STATUS_PENDING = 'pending'
    STATUS_CONTACTED = 'contacted'
    STATUS_CLOSED = 'closed'

    #: Deliberately NOT a linear state machine. A callback can be closed without
    #: ever being marked contacted (the caller rang back themselves), and the
    #: general edit form permits any of the three so a mis-click stays
    #: correctable. Only the dedicated resolve action narrows the choices.
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_CONTACTED, 'Contacted'),
        (STATUS_CLOSED, 'Closed'),
    ]

    SOURCE_AI_PHONE = 'ai_phone'
    SOURCE_MANUAL = 'manual'
    SOURCE_WEB = 'web'

    SOURCE_CHOICES = [
        (SOURCE_AI_PHONE, 'AI phone call'),
        (SOURCE_MANUAL, 'Added manually'),
        (SOURCE_WEB, 'Web'),
    ]

    contact = models.ForeignKey(  # noqa: F405
        'scheduling.Contact',
        on_delete=models.SET_NULL,  # noqa: F405
        null=True,
        blank=True,
        related_name='callback_requests',
        help_text='SET_NULL, not PROTECT: a callback is a transient queue item, '
                  'so it must survive a contact being removed rather than block '
                  'the removal. Null also means "we never found out who this '
                  'was" — see caller_name / caller_phone.',
    )

    # Free text, not a mirror of the contact's fields. The agent captures a name
    # and a callback number BEFORE it knows whether the caller is already in the
    # directory, and the number given is often not the one they rang from —
    # "call my mobile instead". Reading these off `contact` would lose that.
    caller_name = models.CharField(max_length=255, blank=True)  # noqa: F405
    caller_phone = models.CharField(  # noqa: F405
        max_length=32,
        blank=True,
        help_text='The number to ring back on, as the caller gave it. Not '
                  'normalised to E.164 like Contact.phone_e164: nothing looks a '
                  'callback up by number, and an extension or "ask for Dana" '
                  'note would be destroyed by normalisation.',
    )

    reason = models.TextField(blank=True)  # noqa: F405

    status = models.CharField(  # noqa: F405
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    source = models.CharField(  # noqa: F405
        max_length=32,
        choices=SOURCE_CHOICES,
        default=SOURCE_AI_PHONE,
        help_text='How this callback came about. Server-stamped, never a form '
                  'field — it is the provenance record. Defaults to ai_phone '
                  'because the agent is the writer that cannot choose.',
    )

    notes = models.TextField(  # noqa: F405
        blank=True,
        help_text='What happened when you rang back. Kept through a contact '
                  'erasure — it is the queue\'s working record, not identity.',
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            # The queue's only index. Every page of this model is "the open
            # callbacks at MY site", which is tenant + location + status in
            # exactly that order.
            models.Index(fields=['tenant', 'location', 'status'],  # noqa: F405
                         name='idx_callback_tenant_loc_status'),
        ]

    def __str__(self):
        return f'{self.display_caller} — {self.get_status_display()}'

    # -- derived ----------------------------------------------------------- #

    @property
    def display_caller(self):
        """A human label that is never empty.

        Falls through identified contact → whatever name the agent captured →
        a stable placeholder. A blank cell in the queue reads as a rendering
        bug rather than as "this caller never said who they were", which is a
        routine and expected outcome on an inbound call.
        """
        if self.contact_id:
            return self.contact.display_name
        if self.caller_name:
            return self.caller_name
        return 'Unidentified caller'

    @property
    def is_resolved(self):
        """Whether this callback is finished with.

        The guard on the resolve controls, and it keys on `closed` alone:
        `contacted` is not an end state — a callback that has been rung once
        and is awaiting a reply still needs closing out, so hiding the resolve
        action from it would strand the row in the queue forever.
        """
        return self.status == self.STATUS_CLOSED
