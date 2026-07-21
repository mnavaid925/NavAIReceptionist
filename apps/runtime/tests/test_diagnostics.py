"""The runtime diagnostics page — renders, is tenant+location scoped, gated.

Reuses Module 5's audited scoping helper, so the isolation guarantees are the call
log's own: a user sees only the active location's resolved calls, never another
location's and never another tenant's.
"""
import pytest
from django.test import Client
from django.urls import reverse

from apps.calls.models import CallSession

pytestmark = pytest.mark.django_db


def _mk_session(tenant, location, sid, **kw):
    defaults = dict(
        from_number='+13125550101', to_number='+13125550140',
        status=CallSession.STATUS_COMPLETED, mode=CallSession.MODE_LIVE,
    )
    defaults.update(kw)
    return CallSession.objects.create(
        tenant=tenant, location=location, provider_call_sid=sid, **defaults
    )


def test_diagnostics_renders_for_admin(client_a):
    resp = client_a.get(reverse('runtime:diagnostics'))
    assert resp.status_code == 200
    assert b'Runtime diagnostics' in resp.content


def test_diagnostics_shows_only_active_location(
    client_a, tenant_a, location_a1, location_a2
):
    _mk_session(tenant_a, location_a1, 'CA-here-0001')
    _mk_session(tenant_a, location_a2, 'CA-elsewhere-0001')  # a sibling location

    body = client_a.get(reverse('runtime:diagnostics')).content.decode()

    assert 'CA-here-0001' in body           # the active location's call
    assert 'CA-elsewhere-0001' not in body  # cross-location must not leak


def test_diagnostics_cross_tenant_isolation(client_a, tenant_b, location_b1):
    _mk_session(tenant_b, location_b1, 'CA-globex-0001')
    resp = client_a.get(reverse('runtime:diagnostics'))
    assert b'CA-globex-0001' not in resp.content


def test_diagnostics_no_active_location_shows_guidance(admin_user):
    # admin_user has TWO locations and has not switched → request.location is None.
    client = Client()
    client.force_login(admin_user)
    resp = client.get(reverse('runtime:diagnostics'))
    assert resp.status_code == 200
    assert b'Choose a location' in resp.content


def test_diagnostics_requires_login(db):
    resp = Client().get(reverse('runtime:diagnostics'))
    assert resp.status_code == 302  # @login_required → redirect to login
