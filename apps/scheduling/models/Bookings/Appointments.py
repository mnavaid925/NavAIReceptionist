"""`scheduling.Appointment` — one booking (sub-module 4.3).

Location-scoped: a booking happens at exactly one site, and the calendar is read
per location. All times are stored in UTC (`USE_TZ = True`) and evaluated in the
LOCATION's timezone, never the server's and never the browser's.

**`end_at` is `start_at + service.duration_minutes` — the buffer is NOT in it.**
`Service.buffer_minutes` is time held AFTER the appointment (turnaround, notes,
cleaning down), so folding it into `end_at` would make every appointment render
longer than it really is on the calendar. The buffer only ever affects what may
be booked NEXT, which is `availability.overlapping_appointments`' job.

**`booked_by_session` now exists.** It records which call produced an AI booking,
and 4.3 shipped without it for one reason: `apps.calls` did not exist, and Django
refuses to migrate a relation to an uninstalled app ("field defines a relation
with model 'calls.CallSession', which is either not installed, or is abstract").
A placeholder integer column would have been worse than nothing — it would look
like a foreign key and enforce none of the integrity of one — so `source` carried
provenance alone until sub-module 5.1 created `calls.CallSession` and added this
field as an additive migration. `source` still says HOW a booking came about;
this FK says WHICH call, and for `ai_phone` the two are now checkable against
each other rather than taken on trust.
"""
from datetime import timedelta

from apps.scheduling.models._base import *  # noqa: F401,F403

__all__ = ['Appointment']


class Appointment(TenantLocationOwned):  # noqa: F405
    """A booked slot in one location's calendar."""

    STATUS_SCHEDULED = 'scheduled'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_NO_SHOW = 'no_show'

    #: The exact values the shared badge partial branches on. `no_show`, with the
    #: underscore — `partials/_appointment_status_badge.html` matches this
    #: literally, and `noshow` would silently fall through to the muted default.
    STATUS_CHOICES = [
        (STATUS_SCHEDULED, 'Scheduled'),
        (STATUS_CONFIRMED, 'Confirmed'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_NO_SHOW, 'No show'),
    ]

    #: Statuses from which an appointment may still be edited, moved or cancelled.
    OPEN_STATUSES = (STATUS_SCHEDULED, STATUS_CONFIRMED)

    SOURCE_AI_PHONE = 'ai_phone'
    SOURCE_MANUAL = 'manual'
    SOURCE_WEB = 'web'

    SOURCE_CHOICES = [
        (SOURCE_AI_PHONE, 'AI phone call'),
        (SOURCE_MANUAL, 'Booked manually'),
        (SOURCE_WEB, 'Web'),
    ]

    contact = models.ForeignKey(  # noqa: F405
        'scheduling.Contact',
        on_delete=models.PROTECT,  # noqa: F405
        related_name='appointments',
        help_text='PROTECT, not CASCADE: deleting a person must never silently '
                  'delete the record that they were seen. A contact with '
                  'bookings is erased in place instead (Contact.anonymize).',
    )
    provider = models.ForeignKey(  # noqa: F405
        settings.AUTH_USER_MODEL,  # noqa: F405
        on_delete=models.SET_NULL,  # noqa: F405
        null=True,
        blank=True,
        related_name='appointments',
        help_text='The staff member seeing this contact. Null for a service that '
                  'needs nobody in particular, such as a phone consultation.',
    )
    resource = models.ForeignKey(  # noqa: F405
        'scheduling.Resource',
        on_delete=models.SET_NULL,  # noqa: F405
        null=True,
        blank=True,
        related_name='appointments',
    )
    service = models.ForeignKey(  # noqa: F405
        'scheduling.Service',
        on_delete=models.SET_NULL,  # noqa: F405
        null=True,
        blank=True,
        related_name='appointments',
    )

    start_at = models.DateTimeField(db_index=True)  # noqa: F405
    end_at = models.DateTimeField()  # noqa: F405

    status = models.CharField(  # noqa: F405
        max_length=24,
        choices=STATUS_CHOICES,
        default=STATUS_SCHEDULED,
        db_index=True,
    )
    reason = models.CharField(max_length=255, blank=True)  # noqa: F405
    notes = models.TextField(blank=True)  # noqa: F405

    source = models.CharField(  # noqa: F405
        max_length=16,
        choices=SOURCE_CHOICES,
        default=SOURCE_MANUAL,
        db_index=True,
        help_text='How this booking came about. Server-stamped, never chosen by '
                  'a user — it is the provenance record.',
    )

    booked_by_session = models.ForeignKey(  # noqa: F405
        'calls.CallSession',
        on_delete=models.SET_NULL,  # noqa: F405
        null=True,
        blank=True,
        related_name='booked_appointments',
        help_text='The call that produced this booking — the provenance link '
                  'behind source=ai_phone, server-stamped by the runtime and '
                  'never chosen by a user. SET_NULL, not CASCADE: call logs are '
                  'retention-purged and callers are erased, and neither may take '
                  'the booking down with them. Plural related_name because one '
                  'call can book more than one appointment.',
    )

    cancelled_at = models.DateTimeField(null=True, blank=True)  # noqa: F405
    cancellation_reason = models.CharField(max_length=255, blank=True)  # noqa: F405

    class Meta:
        ordering = ['start_at']
        indexes = [
            # The calendar's index. Every calendar and availability query carries
            # tenant AND location and filters a start_at range, in that order.
            models.Index(fields=['tenant', 'location', 'start_at'],  # noqa: F405
                         name='idx_appt_tenant_loc_start'),
            models.Index(fields=['tenant', 'status'],  # noqa: F405
                         name='idx_appt_tenant_status'),
            models.Index(fields=['tenant', 'contact'],  # noqa: F405
                         name='idx_appt_tenant_contact'),
        ]

    def __str__(self):
        return f'{self.contact} — {self.start_at:%Y-%m-%d %H:%M}'

    # -- derived ----------------------------------------------------------- #

    @property
    def duration_minutes(self):
        """Real length of the appointment, from the stored span."""
        return int((self.end_at - self.start_at).total_seconds() // 60)

    @property
    def buffer_minutes(self):
        """Turnaround held after this appointment.

        Read from the service each time rather than copied onto the row: a
        `SET_NULL` service leaves no buffer to honour, and there is no sensible
        buffer for an appointment whose service was deleted.
        """
        return self.service.buffer_minutes if self.service_id else 0

    @property
    def blocks_until(self):
        """The instant the slot is genuinely free again — `end_at` plus buffer.

        This, not `end_at`, is what the next booking must clear.
        """
        return self.end_at + timedelta(minutes=self.buffer_minutes)

    @property
    def is_open(self):
        """Whether this booking can still be edited, moved or cancelled."""
        return self.status in self.OPEN_STATUSES

    @property
    def is_cancelled(self):
        return self.status == self.STATUS_CANCELLED

    def local_start(self):
        """`start_at` in the LOCATION's timezone.

        Every human-facing rendering of an appointment time goes through this or
        through the request's activated timezone — never through the raw UTC
        value, and never through the server's `TIME_ZONE`.
        """
        return self.start_at.astimezone(self.location.tzinfo)

    def local_end(self):
        return self.end_at.astimezone(self.location.tzinfo)
