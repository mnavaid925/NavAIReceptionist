"""Fixtures for `apps.calls`'s suite — domain records only.

Tenant/location/user/client fixtures come from the ROOT `conftest.py`; this file
adds nothing but `CallSession`-shaped data on top of them, per the project's
testing convention (an app-level `conftest.py` only adds domain records).
"""
import uuid

import pytest

from apps.calls.models import CallSession


@pytest.fixture
def make_call_session(db):
    """Factory: `make_call_session(tenant, location, **overrides)` -> a saved
    `CallSession`.

    `provider_call_sid` auto-generates a unique value per call unless a test
    overrides it — the field carries a DB-level unique constraint, so a fixed
    default here would collide the moment two rows are made in the same test.
    """
    def _make(tenant, location, **overrides):
        sid = overrides.pop('provider_call_sid', None) or f'CA{uuid.uuid4().hex[:30]}'
        defaults = {
            'from_number': '+13125550101',
            'to_number': '+13125550140',
            'mode': CallSession.MODE_LIVE,
            'status': CallSession.STATUS_COMPLETED,
        }
        defaults.update(overrides)
        return CallSession.objects.create(
            tenant=tenant, location=location, provider_call_sid=sid, **defaults
        )
    return _make


@pytest.fixture
def session_a1(tenant_a, location_a1, make_call_session):
    """A tenant A call session at location A1."""
    return make_call_session(tenant_a, location_a1, provider_call_sid='CA-A1-0001')


@pytest.fixture
def session_a2(tenant_a, location_a2, make_call_session):
    """Tenant A's SECOND location's call session — the cross-location isolation
    fixture.
    """
    return make_call_session(tenant_a, location_a2, provider_call_sid='CA-A2-0001')


@pytest.fixture
def session_b(tenant_b, location_b1, make_call_session):
    """A tenant B call session — the cross-tenant isolation fixture."""
    return make_call_session(tenant_b, location_b1, provider_call_sid='CA-B1-0001')
