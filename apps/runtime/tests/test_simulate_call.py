"""`manage.py simulate_call` — the 3.2 observable surface, driven synchronously.

The command calls `asyncio.run()` internally, so it MUST be exercised from a
SYNC test via `call_command` — calling it from an `async def` test would nest
one event loop inside another and raise `RuntimeError: asyncio.run() cannot be
called from a running event loop`.

`transaction=True`: the command's own event loop hands the ORM work to a real
OS thread (`database_sync_to_async(..., thread_sensitive=False)`), which needs
its own real connection — a plain `django_db`-wrapped test holds SQLite in one
open transaction on the test's thread, and the consumer's thread then finds the
table locked. `transaction=True` (matching `test_media_consumer.py`) commits for
real instead, so the two threads share a database rather than one wrapped
transaction.
"""
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.calls.models import CallSession

pytestmark = pytest.mark.django_db(transaction=True)


def _run(**options):
    out = StringIO()
    call_command('simulate_call', stdout=out, **options)
    return out.getvalue()


def test_exits_clean_and_reports_a_terminal_status(
    tenant_a, location_a1, make_agent_setting,
):
    make_agent_setting(tenant_a, location_a1)
    text = _run()

    assert 'CallSession SIM-' in text
    status = text.split('status=')[1].split()[0]
    assert status != CallSession.STATUS_IN_PROGRESS
    assert status in dict(CallSession.STATUS_CHOICES)


def test_creates_exactly_one_session_via_the_real_consumer(
    tenant_a, location_a1, make_agent_setting,
):
    make_agent_setting(tenant_a, location_a1)
    before = CallSession.objects.count()
    _run()
    assert CallSession.objects.count() == before + 1

    session = CallSession.objects.latest('created_at')
    assert session.provider_call_sid.startswith('SIM-')
    assert session.tenant_id == tenant_a.pk and session.location_id == location_a1.pk
    assert session.transcript  # the real turn loop ran and wrote real turns


def test_refuses_under_live_mode(settings, tenant_a, location_a1, make_agent_setting):
    make_agent_setting(tenant_a, location_a1)
    settings.PROVIDER_MODE = 'live'
    with pytest.raises(CommandError):
        _run()
    # And it never even got as far as minting a session.
    assert not CallSession.objects.filter(provider_call_sid__startswith='SIM-').exists()


def test_no_enabled_agent_setting_raises_command_error(db):
    with pytest.raises(CommandError):
        _run()


def test_tenant_and_location_options_narrow_the_resolved_setting(
    tenant_a, location_a1, location_a2, make_agent_setting,
):
    make_agent_setting(
        tenant_a, location_a1,
        inbound_phone_number='+13125550140',
    )
    make_agent_setting(
        tenant_a, location_a2,
        inbound_phone_number='+13125550141',
    )
    text = _run(tenant=tenant_a.slug, location=location_a2.slug)
    session = CallSession.objects.filter(provider_call_sid__in=[
        line.split('CallSession ')[1].split(' —')[0]
        for line in text.splitlines() if line.startswith('CallSession ')
    ]).first()
    assert session is not None
    assert session.location_id == location_a2.pk


def test_disabled_only_setting_is_not_selected(tenant_a, location_a1, make_agent_setting):
    make_agent_setting(tenant_a, location_a1, enabled=False)
    with pytest.raises(CommandError):
        _run()
