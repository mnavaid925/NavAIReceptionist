"""`scheduling.Service` — a bookable service (sub-module 4.2).

The catalogue the voice agent reads from. `description` exists so the agent has
something to SAY when a caller asks what a service involves; `duration_minutes`
and `buffer_minutes` are what 4.3's availability search turns into slots.

**Tenant-scoped with a NULLABLE location.** This is the one shape in the project
no abstract base expresses, so the FK is declared here rather than inherited:

* `location = None` — offered at every site the business has. The common case for
  a business whose branches all do the same work.
* `location = <a Location>` — offered at that one site only.

`TenantOwned` would lose the per-site case; `TenantLocationOwned` would make the
FK mandatory and force a duplicate row per location for a service every branch
offers. Neither is right, hence the hand-declared field.
"""
from apps.scheduling.models._base import *  # noqa: F401,F403

__all__ = ['Service']


class Service(TenantOwned):  # noqa: F405
    """Something a caller can book."""

    # Hand-declared rather than inherited from TenantLocationOwned, because it is
    # NULLABLE — see the module docstring. `related_name` is explicit for the same
    # reason (the base's `%(class)ss` convention does not apply here).
    location = models.ForeignKey(  # noqa: F405
        'tenants.Location',
        on_delete=models.CASCADE,  # noqa: F405
        related_name='services',
        null=True,
        blank=True,
        help_text='Leave blank to offer this service at every location.',
    )

    name = models.CharField(max_length=255)  # noqa: F405
    description = models.TextField(  # noqa: F405
        blank=True,
        help_text='Read aloud by the agent when a caller asks what this involves. '
                  'Write it the way you would say it, not the way you would print it.',
    )

    duration_minutes = models.PositiveIntegerField(  # noqa: F405
        default=30,
        help_text='How long the appointment itself lasts.',
    )
    buffer_minutes = models.PositiveIntegerField(  # noqa: F405
        default=0,
        help_text='Extra time held AFTER the appointment — cleaning down, notes, '
                  'turnaround. The next slot cannot start inside it.',
    )

    requires_resource = models.BooleanField(  # noqa: F405
        default=False,
        help_text='Tick if this service needs a room, chair or piece of equipment. '
                  'Availability will only offer a slot when a resource is free.',
    )

    is_active = models.BooleanField(  # noqa: F405
        default=True,
        help_text='Inactive services keep their booking history but are never '
                  'offered to a caller.',
    )
    display_order = models.PositiveIntegerField(  # noqa: F405
        default=0,
        help_text='Lower numbers are offered first. Ties fall back to name.',
    )

    class Meta:
        ordering = ['display_order', 'name']
        indexes = [
            models.Index(fields=['tenant', 'location', 'is_active'],  # noqa: F405
                         name='idx_service_tenant_loc_active'),
        ]

    def __str__(self):
        return self.name

    @property
    def is_all_locations(self):
        """Whether this service is offered business-wide."""
        return self.location_id is None

    @property
    def location_label(self):
        """A human label for the location column that is never blank."""
        return self.location.name if self.location_id else 'All locations'

    @property
    def total_minutes(self):
        """Duration plus buffer — the real span this service occupies.

        This, not `duration_minutes`, is what 4.3 must subtract from a provider's
        working window when deciding whether a slot fits.
        """
        return self.duration_minutes + self.buffer_minutes

    def is_offered_at(self, location):
        """Whether this service can be booked at `location`."""
        if self.location_id is None:
            return True
        return location is not None and self.location_id == location.pk
