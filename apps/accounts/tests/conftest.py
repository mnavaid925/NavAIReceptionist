"""Fixtures for `apps.accounts`'s suite — domain records only.

Tenant/location/user/client fixtures come from the ROOT `conftest.py`; this file
adds accounts-specific domain records (extra users, an inactive location, a
tenant-only-scoped user) on top of them, per the project's testing convention (an
app-level `conftest.py` only adds domain records).
"""
import uuid

import pytest
from django.core.cache import cache

from apps.accounts.models import User, UserLocation
from apps.tenants.models import Location

from conftest import DEMO_PASSWORD

__all__ = ['DEMO_PASSWORD']


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """`throttling.py` is backed by the process-wide Django cache, not the
    per-test database transaction — without clearing it, a failed-login counter
    written by one test would still be sitting there for the next test that
    reuses the same (customer_id, identifier) pair from the shared root fixtures,
    making throttle tests order-dependent.
    """
    cache.clear()
    yield
    cache.clear()


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
def location_a2_inactive(tenant_a):
    """A tenant A location taken out of service — `is_active=False`.

    `User.assigned_locations()` filters on `is_active=True`; a `UserLocation`
    row pointing at a deactivated site must not make it switchable.
    """
    return Location.objects.create(
        tenant=tenant_a, name='Closed Branch', slug='closed-branch', is_active=False,
    )


@pytest.fixture
def user_a2_only(tenant_a, location_a2, make_user):
    """A tenant A user assigned ONLY to location A2.

    Proves the user directory is tenant-scoped only, never location-scoped: this
    user must still show up in `client_a`'s user list even though `client_a` is
    active at A1, not A2.
    """
    return make_user(
        tenant_a, locations=[location_a2],
        email='a2only@acme-test.example', first_name='Ana', last_name='Uptown',
    )
