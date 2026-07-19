"""Fixtures for `apps.scheduling`'s suite — domain records only.

Tenant/location/user/client fixtures come from the ROOT `conftest.py`; this file
adds nothing but `Contact`-shaped data on top of them, per the project's testing
convention (an app-level `conftest.py` only adds domain records).
"""
import pytest

from apps.scheduling.models import Contact, Resource, Service


@pytest.fixture
def make_contact(db):
    """Factory: `make_contact(tenant, **overrides)` -> a saved `Contact`.

    Defaults describe a fully-identified, manually-added contact; override
    whatever a given test cares about.
    """
    def _make(tenant, **overrides):
        defaults = {
            'first_name': 'Jane',
            'last_name': 'Doe',
            'phone_e164': '',
            'email': '',
            'source': Contact.SOURCE_MANUAL,
        }
        defaults.update(overrides)
        return Contact.objects.create(tenant=tenant, **defaults)
    return _make


@pytest.fixture
def contact_a(tenant_a, make_contact):
    """One ordinary, fully-identified contact belonging to tenant A."""
    return make_contact(
        tenant_a, first_name='Priya', last_name='Raman',
        phone_e164='+13125550142', email='priya.raman@example.test',
    )


@pytest.fixture
def contact_b(tenant_b, make_contact):
    """A contact belonging to tenant B — the cross-tenant isolation fixture."""
    return make_contact(
        tenant_b, first_name='Theo', last_name='Nakamura',
        phone_e164='+15035550210', email='theo.nakamura@example.test',
    )


# --------------------------------------------------------------------------- #
# Service / Resource (sub-module 4.2)
# --------------------------------------------------------------------------- #

@pytest.fixture
def make_service(db):
    """Factory: `make_service(tenant, **overrides)` -> a saved `Service`.

    `location` defaults to `None` (offered at every site); override it to pin
    the service to one location.
    """
    def _make(tenant, **overrides):
        defaults = {
            'name': 'Consultation',
            'location': None,
            'duration_minutes': 30,
            'buffer_minutes': 0,
            'requires_resource': False,
            'is_active': True,
            'display_order': 0,
        }
        defaults.update(overrides)
        return Service.objects.create(tenant=tenant, **defaults)
    return _make


@pytest.fixture
def make_resource(db):
    """Factory: `make_resource(tenant, location, **overrides)` -> a saved `Resource`."""
    def _make(tenant, location, **overrides):
        defaults = {
            'name': 'Room 1',
            'resource_number': '',
            'description': '',
            'is_active': True,
            'display_order': 0,
        }
        defaults.update(overrides)
        return Resource.objects.create(tenant=tenant, location=location, **defaults)
    return _make


@pytest.fixture
def service_a1(tenant_a, location_a1, make_service):
    """A tenant A service pinned to location A1 only."""
    return make_service(tenant_a, name='Consultation A1', location=location_a1)


@pytest.fixture
def service_a2(tenant_a, location_a2, make_service):
    """Tenant A's service pinned to A2 — the cross-location isolation fixture."""
    return make_service(tenant_a, name='Consultation A2', location=location_a2)


@pytest.fixture
def service_all_a(tenant_a, make_service):
    """A tenant A service offered at every location (`location=None`)."""
    return make_service(tenant_a, name='General Checkup', location=None)


@pytest.fixture
def service_b(tenant_b, make_service):
    """A tenant B service — the cross-tenant isolation fixture."""
    return make_service(tenant_b, name='Consultation B')


@pytest.fixture
def resource_a1(tenant_a, location_a1, make_resource):
    """A tenant A resource at location A1."""
    return make_resource(tenant_a, location_a1, name='Room 1')


@pytest.fixture
def resource_a2(tenant_a, location_a2, make_resource):
    """Tenant A's SECOND location's resource — the cross-location isolation
    fixture. Deliberately shares its name with `resource_a1`: the whole point
    of the `(location, name)` constraint is that this is ALLOWED.
    """
    return make_resource(tenant_a, location_a2, name='Room 1')


@pytest.fixture
def resource_b(tenant_b, location_b1, make_resource):
    """A tenant B resource — the cross-tenant isolation fixture."""
    return make_resource(tenant_b, location_b1, name='Room 1')
