"""`tenants.Tenant` — the business, and the isolation root of the whole product.

Every other model FKs this row; every queryset filters on it. Tenant itself is the
one model with no `tenant` FK, because it IS the tenant.
"""
from apps.tenants.models._base import *  # noqa: F401,F403

__all__ = ['Tenant']


class Tenant(TimeStamped):  # noqa: F405
    """A business using NavAIReceptionist.

    `customer_id` is what a user types at login: it resolves the tenant BEFORE
    authentication, which is what lets the same email address exist in more than
    one business without collision.
    """

    name = models.CharField(max_length=255)  # noqa: F405
    slug = models.SlugField(max_length=255, unique=True)  # noqa: F405
    customer_id = models.CharField(  # noqa: F405
        max_length=32,
        unique=True,
        help_text='The Customer ID a user enters at login to resolve this business.',
    )
    timezone = models.CharField(  # noqa: F405
        max_length=64,
        default='UTC',
        help_text='IANA timezone name. Each location may override it with its own.',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='An inactive tenant is blocked at login rather than mid-call.',
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'Business'
        verbose_name_plural = 'Businesses'

    def __str__(self):
        return self.name
