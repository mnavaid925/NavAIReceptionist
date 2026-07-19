"""`tenants.Location` — one site of a business.

A location is the product's second isolation boundary and the unit almost
everything else hangs off: its own Twilio number and agent configuration
(`agents.AgentSetting`), its own resources, appointments, callbacks and call
logs. `accounts.UserLocation` decides who may switch into it.

Appointment times are evaluated in THIS row's `timezone`, never the server's and
never the browser's.
"""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.tenants.models._base import *  # noqa: F401,F403

__all__ = ['Location']


class Location(TenantOwned):  # noqa: F405
    """A physical site belonging to a tenant."""

    name = models.CharField(max_length=255)  # noqa: F405
    slug = models.SlugField(max_length=255)  # noqa: F405

    address_line1 = models.CharField(max_length=255, blank=True)  # noqa: F405
    address_line2 = models.CharField(max_length=255, blank=True)  # noqa: F405
    city = models.CharField(max_length=128, blank=True)  # noqa: F405
    state = models.CharField(max_length=64, blank=True)  # noqa: F405
    postal_code = models.CharField(max_length=32, blank=True)  # noqa: F405
    country = models.CharField(max_length=64, blank=True, default='US')  # noqa: F405

    timezone = models.CharField(  # noqa: F405
        max_length=64,
        default='UTC',
        help_text="IANA timezone name. This location's own — appointment and "
                  'transfer-hours calculations are evaluated in it.',
    )
    phone = models.CharField(  # noqa: F405
        max_length=32,
        blank=True,
        help_text='The public-facing number for this site. Not the agent inbound '
                  'number — that lives on the location\'s AgentSetting row.',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Deactivate rather than delete, so past appointments and call '
                  'logs stay readable.',
    )

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(  # noqa: F405
                fields=['tenant', 'slug'], name='uniq_location_tenant_slug'
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', 'is_active'],  # noqa: F405
                        name='idx_location_tenant_active'),
        ]

    def __str__(self):
        return self.name

    @property
    def full_address(self):
        """The address as a single comma-joined line, skipping blank parts."""
        parts = [
            self.address_line1,
            self.address_line2,
            self.city,
            self.state,
            self.postal_code,
            self.country,
        ]
        return ', '.join(part for part in parts if part)

    @property
    def tzinfo(self):
        """This location's `ZoneInfo`, degrading to UTC on a bad/unknown name.

        A stored timezone string can go stale when the host's tz database changes,
        and a raised `ZoneInfoNotFoundError` deep inside a calendar render or a
        live call is a far worse outcome than an hour's drift.
        """
        try:
            return ZoneInfo(self.timezone or 'UTC')
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo('UTC')

    def local_now(self):
        """Current wall-clock time at this site."""
        return timezone.now().astimezone(self.tzinfo)  # noqa: F405
