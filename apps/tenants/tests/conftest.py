"""Fixtures for `apps.tenants`'s suite — domain records only.

Tenant/location/user/client fixtures come from the ROOT `conftest.py`; this file
adds tenants-specific domain records (a manager-tier user, a third location for
pagination, a factory for one-off users) on top of them, per the project's
testing convention (an app-level `conftest.py` only adds domain records).
"""
import uuid

import pytest
from django.test import Client

from apps.accounts.models import User, UserLocation
from apps.tenants.models import Location

from conftest import DEMO_PASSWORD

__all__ = ['DEMO_PASSWORD']


@pytest.fixture
def make_user(db):
    """Factory: `make_user(tenant, locations=(), **overrides)` -> a saved `User`,
    optionally assigned to one or more locations via `UserLocation`.
    """
    def _make(tenant, locations=(), password=DEMO_PASSWORD, **overrides):
        email = overrides.pop('email', None) or f'user-{uuid.uuid4().hex[:10]}@{tenant.slug}.example'
        defaults = {'tier': User.TIER_STAFF, 'status': User.STATUS_ACTIVE}
        defaults.update(overrides)
        user = User.objects.create_user(tenant=tenant, email=email, password=password, **defaults)
        for location in locations:
            UserLocation.objects.create(tenant=tenant, user=user, location=location)
        return user
    return _make


@pytest.fixture
def manager_user(tenant_a, location_a1, location_a2, make_user):
    """A tenant A manager-tier user, assigned to BOTH of tenant A's locations.

    `MANAGEMENT_TIERS = ('owner', 'manager')` — this fixture proves a manager
    (not just the owner) can reach every Module 1 view the owner can.
    """
    return make_user(
        tenant_a, locations=[location_a1, location_a2],
        tier=User.TIER_MANAGER, email='manager@acme-test.example',
        first_name='Mona', last_name='Manager',
    )


@pytest.fixture
def manager_client(manager_user):
    """Tenant A's manager, logged in, with NO active location forced.

    Module 1's views (`location_list`, `staff_locations`, `provider_hours_report`,
    `business_settings`) are tenant-scoped only, so this client deliberately never
    calls `switch_location` — proving those pages do not depend on one.
    """
    client = Client()
    client.force_login(manager_user)
    return client


@pytest.fixture
def location_a3(tenant_a):
    """A third tenant A location — used for pagination / bulk-listing tests."""
    return Location.objects.create(tenant=tenant_a, name='Riverside Annex', slug='riverside-annex')


@pytest.fixture
def provider_a1(tenant_a, location_a1, make_user):
    """A tenant A provider (bookable clinician) assigned only to A1."""
    return make_user(
        tenant_a, locations=[location_a1], is_provider=True,
        email='provider-a1@acme-test.example', first_name='Priya', last_name='Provider',
    )
