"""Shared model toolkit — the abstract bases every app in the project inherits.

This module is the CROSS-APP home for the tenant/location abstract bases, exactly
as `apps/accounts/forms/_common.py` is the cross-app home for `TenantModelForm`.
Other apps' `models/_base.py` re-export from here rather than redefining, so the
`tenant` / `location` FK declaration exists once.

Entity modules pull the toolkit with `from apps.accounts.models._base import *`.

Every FK below is declared as a STRING reference (`'tenants.Tenant'`). That is
deliberate: `accounts.User` FKs `tenants.Tenant` while other apps FK back to the
user model, so a direct import would be an import cycle at module-load time.
FKs to the user model always use `settings.AUTH_USER_MODEL`.
"""
from django.conf import settings  # noqa: F401  (re-exported for entity modules)
from django.core.exceptions import ValidationError  # noqa: F401
from django.db import models, transaction
from django.utils import timezone  # noqa: F401

__all__ = [
    'settings',
    'models',
    'transaction',
    'timezone',
    'ValidationError',
    'TimeStamped',
    'TenantOwned',
    'TenantLocationOwned',
    'TenantNumbered',
]


class TimeStamped(models.Model):
    """Creation and modification stamps, on everything."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantOwned(TimeStamped):
    """A row belonging to exactly one business.

    The isolation root. Every queryset over a subclass carries
    `tenant=request.tenant` — no exceptions.
    """

    # `%(class)ss` yields readable reverse accessors — tenant.locations,
    # tenant.appointments, tenant.users. It relies on model names being unique
    # across the whole project, which holds for all eleven models in the ERD; a
    # twelfth model reusing an existing class name would clash here and Django
    # would refuse to start, which is the failure mode we want (loud, not silent).
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='%(class)ss',
    )

    class Meta:
        abstract = True


class TenantLocationOwned(TenantOwned):
    """A row belonging to one business AND one of its sites.

    Location is a real isolation boundary in this product, not a label: Twilio
    numbers, agents, calendars, resources and staff are all per-location. Every
    queryset over a subclass carries BOTH `tenant=request.tenant` and
    `location=request.location`, and so does every `get_object_or_404`.
    """

    location = models.ForeignKey(
        'tenants.Location',
        on_delete=models.CASCADE,
        related_name='%(class)ss',
    )

    class Meta:
        abstract = True


class TenantNumbered(TenantOwned):
    """A tenant-scoped row carrying a human-readable sequential number.

    Subclasses set `NUMBER_PREFIX` (e.g. `'APPT'`) and get `APPT-00001` counting
    per tenant. The number is assigned inside `save()` under a row lock so two
    concurrent writers cannot mint the same one, and an existing number is never
    reassigned — which is what makes an idempotent seeder possible.
    """

    NUMBER_PREFIX = 'REC'
    NUMBER_PADDING = 5

    number = models.CharField(max_length=32, blank=True, db_index=True)

    class Meta:
        abstract = True

    def _mint_number(self):
        prefix = f'{self.NUMBER_PREFIX}-'
        latest = (
            type(self)
            .objects.select_for_update()
            .filter(tenant=self.tenant, number__startswith=prefix)
            .order_by('-number')
            .values_list('number', flat=True)
            .first()
        )
        try:
            nxt = int(latest.split('-')[-1]) + 1 if latest else 1
        except (AttributeError, ValueError):
            nxt = 1
        return f'{prefix}{nxt:0{self.NUMBER_PADDING}d}'

    def save(self, *args, **kwargs):
        if not self.number:
            with transaction.atomic():
                self.number = self._mint_number()
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)
