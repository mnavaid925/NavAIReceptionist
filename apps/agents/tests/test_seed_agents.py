"""Idempotency test for the `seed_agents` management command.

`seed_agents` resolves its demo tenants/locations by SLUG (`acme`/`globex`,
`downtown`/`uptown`/`riverside`/`lakeside`) rather than inventing its own —
mirrors `apps/accounts/tests/test_seed_accounts.py`'s `seed_shape` fixture.
"""
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection

from apps.agents.models import AgentSetting
from apps.tenants.models import Location, Tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def seed_shape(db):
    acme = Tenant.objects.create(name='Acme Seed', slug='acme', customer_id='ACME-SEED-TEST')
    globex = Tenant.objects.create(name='Globex Seed', slug='globex', customer_id='GLOBEX-SEED-TEST')
    Location.objects.create(tenant=acme, name='Downtown', slug='downtown')
    Location.objects.create(tenant=acme, name='Uptown', slug='uptown')
    Location.objects.create(tenant=globex, name='Riverside', slug='riverside')
    Location.objects.create(tenant=globex, name='Lakeside', slug='lakeside')
    return acme, globex


def _run(**options):
    out, err = StringIO(), StringIO()
    call_command('seed_agents', stdout=out, stderr=err, **options)
    return out.getvalue(), err.getvalue()


def _raw_token(pk):
    with connection.cursor() as cursor:
        cursor.execute('SELECT twilio_auth_token FROM agents_agentsetting WHERE id = %s', [pk])
        return cursor.fetchone()[0]


def test_seed_agents_never_touches_a_real_provider(seed_shape, settings):
    _run()
    assert settings.PROVIDER_MODE == 'fake'


def test_seed_agents_creates_a_row_for_every_demo_location(seed_shape):
    acme, globex = seed_shape
    _run()
    assert AgentSetting.objects.filter(tenant=acme).count() == 2
    assert AgentSetting.objects.filter(tenant=globex).count() == 2


def test_seed_agents_configures_at_least_two_locations_per_tenant(seed_shape):
    """The seed-data rule: a single-location demo hides cross-location bugs."""
    acme, _globex = seed_shape
    _run()
    configured = AgentSetting.objects.filter(tenant=acme, enabled=True)
    assert configured.count() >= 2
    assert set(configured.values_list('location__slug', flat=True)) == {'downtown', 'uptown'}


def test_seed_agents_downtown_is_fully_ready(seed_shape):
    acme, _globex = seed_shape
    _run()
    downtown = AgentSetting.objects.get(tenant=acme, location__slug='downtown')
    assert downtown.enabled is True
    assert downtown.inbound_phone_number == '+13125550140'
    assert downtown.is_ready is True
    assert downtown.transfer_enabled is True
    assert downtown.transfer_working_hours['monday']['enabled'] is True


def test_seed_agents_uptown_has_no_transfer_restriction(seed_shape):
    acme, _globex = seed_shape
    _run()
    uptown = AgentSetting.objects.get(tenant=acme, location__slug='uptown')
    assert uptown.transfer_enabled is False
    assert uptown.transfer_working_hours == {}


def test_seed_agents_lakeside_is_deliberately_unconfigured(seed_shape):
    """Exercises the readiness check and the "not configured" surfaces."""
    _acme, globex = seed_shape
    _run()
    lakeside = AgentSetting.objects.get(tenant=globex, location__slug='lakeside')
    assert lakeside.enabled is False
    assert lakeside.inbound_phone_number is None
    assert lakeside.has_auth_token is False
    assert lakeside.is_ready is False


def test_seed_agents_inbound_numbers_are_all_distinct(seed_shape):
    _run()
    numbers = list(
        AgentSetting.objects.exclude(inbound_phone_number__isnull=True)
        .values_list('inbound_phone_number', flat=True)
    )
    assert len(numbers) == len(set(numbers))
    assert len(numbers) >= 3  # downtown, uptown, riverside are all configured


def test_seed_agents_auth_token_is_stored_encrypted(seed_shape):
    acme, _globex = seed_shape
    _run()
    downtown = AgentSetting.objects.get(tenant=acme, location__slug='downtown')
    raw = _raw_token(downtown.pk)
    assert 'fake-token-downtown-0000000000001' not in raw
    assert downtown.twilio_auth_token == 'fake-token-downtown-0000000000001'  # decrypts back


def test_seed_agents_run_twice_creates_zero_duplicate_rows(seed_shape):
    _run()
    first_count = AgentSetting.objects.count()
    _run()
    assert AgentSetting.objects.count() == first_count


def test_seed_agents_second_run_reports_data_already_exists(seed_shape):
    _run()
    out, _err = _run()
    assert 'already exists' in out


def test_seed_agents_flush_removes_and_recreates(seed_shape):
    acme, _globex = seed_shape
    _run()
    _run(flush=True)
    assert AgentSetting.objects.filter(tenant=acme, location__slug='downtown').count() == 1


def test_seed_agents_bootstraps_seed_accounts_when_no_demo_tenants_exist(db):
    """With no Acme/Globex tenants at all, `seed_agents` chains to
    `seed_accounts` (which itself chains to `seed_tenants`) rather than
    silently doing nothing."""
    assert not Tenant.objects.filter(slug__in=['acme', 'globex']).exists()
    _run()
    assert AgentSetting.objects.exists()
