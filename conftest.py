"""Root pytest fixtures — shared across every app's test suite.

Two tenants, and deliberately TWO locations under `tenant_a` (`location_a1`,
`location_a2`): cross-tenant isolation needs a second tenant, cross-LOCATION
isolation needs a second location under the SAME tenant, and this repo's whole
point is that both are real isolation boundaries. A single-location demo tenant
would hide every cross-location bug, exactly as the seed-data rule says.

App-level `conftest.py` files add domain records on top of these — never a
second tenant/location/user convention alongside them.
"""
import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User, UserLocation
from apps.tenants.models import Location, Tenant

DEMO_PASSWORD = 'nav-test-pass-1234'


# --------------------------------------------------------------------------- #
# Tenants & locations
# --------------------------------------------------------------------------- #

@pytest.fixture
def tenant_a(db):
    """The primary tenant under test. Carries TWO locations — see module docstring."""
    return Tenant.objects.create(
        name='Acme Corp', slug='acme-test', customer_id='ACME-TEST',
    )


@pytest.fixture
def tenant_b(db):
    """A second, wholly unrelated tenant — the cross-tenant isolation fixture."""
    return Tenant.objects.create(
        name='Globex LLC', slug='globex-test', customer_id='GLOBEX-TEST',
    )


@pytest.fixture
def location_a1(tenant_a):
    return Location.objects.create(tenant=tenant_a, name='Downtown', slug='downtown')


@pytest.fixture
def location_a2(tenant_a):
    """Tenant A's SECOND location — the cross-location isolation fixture."""
    return Location.objects.create(tenant=tenant_a, name='Uptown', slug='uptown')


@pytest.fixture
def location_b1(tenant_b):
    return Location.objects.create(tenant=tenant_b, name='Riverside', slug='riverside')


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #

@pytest.fixture
def admin_user(tenant_a, location_a1, location_a2):
    """Tenant A owner, assigned to BOTH of tenant A's locations."""
    user = User.objects.create_user(
        tenant=tenant_a, email='admin@acme-test.example', password=DEMO_PASSWORD,
        tier=User.TIER_OWNER, first_name='Ada', last_name='Owner',
    )
    UserLocation.objects.create(tenant=tenant_a, user=user, location=location_a1)
    UserLocation.objects.create(tenant=tenant_a, user=user, location=location_a2)
    return user


@pytest.fixture
def member_user(tenant_a, location_a1):
    """A tenant A front-desk (staff-tier) user, assigned ONLY to location A1."""
    user = User.objects.create_user(
        tenant=tenant_a, email='member@acme-test.example', password=DEMO_PASSWORD,
        tier=User.TIER_STAFF, first_name='Sam', last_name='Staff',
    )
    UserLocation.objects.create(tenant=tenant_a, user=user, location=location_a1)
    return user


@pytest.fixture
def admin_b(tenant_b, location_b1):
    """Tenant B's owner — used to prove tenant B users cannot reach tenant A."""
    user = User.objects.create_user(
        tenant=tenant_b, email='admin@globex-test.example', password=DEMO_PASSWORD,
        tier=User.TIER_OWNER, first_name='Bea', last_name='Owner',
    )
    UserLocation.objects.create(tenant=tenant_b, user=user, location=location_b1)
    return user


# --------------------------------------------------------------------------- #
# Logged-in clients, with the active location set as the switcher itself sets it
# --------------------------------------------------------------------------- #

def _logged_in_client(user, location):
    """`force_login`, then activate `location` through the real switcher endpoint.

    Going through `accounts:switch_location` (rather than poking the session
    directly) means every fixture-built client is authorized the same way a real
    user is — via `user.assigned_locations()` — so a fixture can never grant a
    location the user was not actually assigned to.
    """
    client = Client()
    client.force_login(user)
    if location is not None:
        response = client.post(
            reverse('accounts:switch_location'),
            {'location': location.pk},
            follow=True,
        )
        assert response.status_code == 200, (
            f'Fixture setup could not activate location {location!r} for '
            f'{user!r}: {response.status_code}'
        )
    return client


@pytest.fixture
def client_a(admin_user, location_a1):
    """Tenant A's owner, logged in, with location A1 active."""
    return _logged_in_client(admin_user, location_a1)


@pytest.fixture
def client_b(admin_b, location_b1):
    """Tenant B's owner, logged in, with location B1 active."""
    return _logged_in_client(admin_b, location_b1)


@pytest.fixture
def member_client(member_user, location_a1):
    """Tenant A's staff-tier user, logged in, with location A1 active."""
    return _logged_in_client(member_user, location_a1)
