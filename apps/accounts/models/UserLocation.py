"""`accounts.UserLocation` — which locations a user may work in.

This table is the authority the active-location switcher validates against.
`ActiveLocationMiddleware` re-checks the session's active location against it on
EVERY request: trusting a location id from a session, a form field, a URL kwarg or
a query string without re-checking here is a cross-location IDOR.

Exactly one assignment is active per session.

Tenant-scoped but deliberately not "location-scoped" in the query sense — this IS
the table that decides which locations are reachable, so scoping reads of it by an
active location would be circular.
"""
from apps.accounts.models._base import *  # noqa: F401,F403

__all__ = ['UserLocation']


class UserLocation(TenantOwned):  # noqa: F405
    """A user's assignment to one location."""

    user = models.ForeignKey(  # noqa: F405
        settings.AUTH_USER_MODEL,  # noqa: F405
        on_delete=models.CASCADE,  # noqa: F405
        related_name='user_locations',
    )
    location = models.ForeignKey(  # noqa: F405
        'tenants.Location',
        on_delete=models.CASCADE,  # noqa: F405
        related_name='user_assignments',
    )

    class Meta:
        ordering = ['location__name']
        constraints = [
            models.UniqueConstraint(  # noqa: F405
                fields=['user', 'location'], name='uniq_userlocation_user_location'
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', 'user'],  # noqa: F405
                        name='idx_userlocation_tenant_user'),
        ]

    def __str__(self):
        return f'{self.user} @ {self.location}'

    def clean(self):
        """A user may only be assigned to a location inside their own business."""
        super().clean()
        if self.user_id and self.location_id:
            if self.user.tenant_id != self.location.tenant_id:
                raise ValidationError(  # noqa: F405
                    'A user cannot be assigned to a location in another business.'
                )
