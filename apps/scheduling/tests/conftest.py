"""Fixtures for `apps.scheduling`'s suite — domain records only.

Tenant/location/user/client fixtures come from the ROOT `conftest.py`; this file
adds nothing but `Contact`-shaped data on top of them, per the project's testing
convention (an app-level `conftest.py` only adds domain records).
"""
import pytest

from apps.scheduling.models import Contact


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
