"""`scheduling.Resource` — a bookable room, chair or piece of equipment (4.2).

Fully location-scoped: a treatment room at the Downtown branch is not a treatment
room at Uptown. Unlike `Service`, there is no all-locations case — a physical
thing is at one site by definition.

**A Resource is not a person.** There is deliberately no FK to the user model
here. The staff member performing an appointment is a separate `provider` FK on
4.3's `Appointment`, and merging the two would make "room 2 is busy" and "Dr Chen
is busy" the same constraint when they are independent ones.

**No `capacity` field either.** A room or a chair is exclusive — one appointment
at a time. Capacity only matters for group classes, which this product does not
have (there is no attendee model, and Invariant 1 says there never will be a
second identity table to build one from).
"""
from apps.scheduling.models._base import *  # noqa: F401,F403

__all__ = ['Resource']


class Resource(TenantLocationOwned):  # noqa: F405
    """A physical thing an appointment occupies."""

    name = models.CharField(max_length=255)  # noqa: F405
    resource_number = models.CharField(  # noqa: F405
        max_length=32,
        blank=True,
        help_text='Whatever your staff actually call it — "3", "B", "Suite 2".',
    )
    description = models.TextField(blank=True)  # noqa: F405

    is_active = models.BooleanField(  # noqa: F405
        default=True,
        help_text='Inactive resources keep their booking history but are never '
                  'offered when the agent looks for a free slot.',
    )
    display_order = models.PositiveIntegerField(  # noqa: F405
        default=0,
        help_text='Lower numbers are offered first. Ties fall back to name.',
    )

    class Meta:
        ordering = ['display_order', 'name']
        constraints = [
            # Two rooms called "Room 1" at the same site would make every
            # conversation about them ambiguous. Scoped to location, not tenant:
            # Downtown and Uptown may each have a Room 1.
            models.UniqueConstraint(  # noqa: F405
                fields=['location', 'name'], name='uniq_resource_location_name'
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', 'location', 'is_active'],  # noqa: F405
                         name='idx_resource_tenant_loc_active'),
        ]

    def __str__(self):
        return self.display_label

    @property
    def display_label(self):
        """Name plus the number staff use for it, when there is one."""
        if self.resource_number:
            return f'{self.name} ({self.resource_number})'
        return self.name
