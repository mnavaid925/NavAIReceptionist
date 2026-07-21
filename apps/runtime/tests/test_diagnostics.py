"""The runtime diagnostics page — renders, is tenant+location scoped, gated.

Reuses Module 5's audited scoping helper, so the isolation guarantees are the call
log's own: a user sees only the active location's resolved calls, never another
location's and never another tenant's.
"""
from types import SimpleNamespace

import pytest
from django.db.models import Count, Q
from django.test import Client
from django.urls import reverse

from apps.agents.models import AgentSetting
from apps.calls.models import CallSession
from apps.runtime.views._helpers import location_sessions, recent_location_sessions

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


# --------------------------------------------------------------------------- #
# Query count — measured against the VIEW'S OWN database cost (the exact
# sequence `runtime_diagnostics_view` runs: the `AgentSetting` lookup, the
# stats `aggregate()`, then `recent_location_sessions()`), not through `Client`
# — a `Client` request carries several constant queries of session/auth/
# active-location middleware overhead unrelated to this view, the same
# reasoning `apps/calls/tests/test_views.py` and
# `apps/scheduling/tests/test_callback_views.py` use for their own list/detail
# query-count guards.
# --------------------------------------------------------------------------- #

def test_diagnostics_view_query_count_bounded_with_active_location(
    django_assert_max_num_queries, tenant_a, location_a1, make_agent_setting,
):
    make_agent_setting(tenant_a, location_a1)
    for i in range(5):
        _mk_session(tenant_a, location_a1, f'CA-qc-{i:04d}')

    request = SimpleNamespace(tenant=tenant_a, location=location_a1)

    # AgentSetting lookup (1) + stats aggregate (1) + sessions select (1) +
    # booked_appointments prefetch (1) = 4, after the two-total aggregate()
    # consolidation that folds `active`/`total` into one round trip.
    with django_assert_max_num_queries(4):
        setting = (
            AgentSetting.objects.filter(tenant=tenant_a, location=location_a1)
            .select_related('location').first()
        )
        scoped = location_sessions(request)
        stats = scoped.aggregate(
            active=Count('pk', filter=Q(status=CallSession.STATUS_IN_PROGRESS)),
            total=Count('pk'),
        )
        sessions = list(recent_location_sessions(request))

    assert setting is not None
    assert stats['total'] == 5
    assert len(sessions) == 5


def test_diagnostics_view_query_count_is_zero_with_no_active_location(
    django_assert_max_num_queries,
):
    # `location_sessions` short-circuits to `.none()` when there is no active
    # location, and `.none().aggregate(...)` never touches the database — so the
    # view's own session/stats cost is exactly zero queries. The `AgentSetting`
    # lookup itself is skipped entirely in this branch (guarded by `if location
    # is not None` in the view), so it costs nothing either.
    request = SimpleNamespace(tenant=None, location=None)

    with django_assert_max_num_queries(0):
        scoped = location_sessions(request)
        stats = scoped.aggregate(
            active=Count('pk', filter=Q(status=CallSession.STATUS_IN_PROGRESS)),
            total=Count('pk'),
        )
        sessions = list(recent_location_sessions(request))

    assert stats == {'active': 0, 'total': 0}
    assert sessions == []


# --------------------------------------------------------------------------- #
# Stats aggregate — the active/total counts rendered on the page, scoped to
# exactly the active location (a sibling location's or another tenant's rows
# must not inflate them).
# --------------------------------------------------------------------------- #

def test_diagnostics_stats_count_active_and_total_for_active_location_only(
    client_a, tenant_a, location_a1, location_a2, tenant_b, location_b1,
):
    for i in range(2):
        _mk_session(
            tenant_a, location_a1, f'CA-active-{i:04d}',
            status=CallSession.STATUS_IN_PROGRESS,
        )
    for i in range(3):
        _mk_session(
            tenant_a, location_a1, f'CA-done-{i:04d}',
            status=CallSession.STATUS_COMPLETED,
        )
    # Same tenant, sibling location — must not count.
    _mk_session(
        tenant_a, location_a2, 'CA-sibling-0001',
        status=CallSession.STATUS_IN_PROGRESS,
    )
    # Another tenant entirely — must not count.
    _mk_session(
        tenant_b, location_b1, 'CA-other-tenant-0001',
        status=CallSession.STATUS_IN_PROGRESS,
    )

    resp = client_a.get(reverse('runtime:diagnostics'))

    assert resp.status_code == 200
    assert resp.context['stats']['active'] == 2
    assert resp.context['stats']['total'] == 5
