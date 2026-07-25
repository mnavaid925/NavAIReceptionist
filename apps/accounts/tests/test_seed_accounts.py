"""Idempotency test for the `seed_accounts` management command (sub-module 0.3
/ Module 1's staff-assignment shape).

`seed_accounts` resolves its demo tenants/locations by SLUG (`acme`/`globex`,
`downtown`/`uptown`/`riverside`/`lakeside`) rather than inventing its own —
mirrors `apps/calls/tests/test_seed_calls.py`'s `seed_shape` fixture. This
proves the command creates the platform superuser plus the demo owners and
single-site staff, stamps `UserLocation` assignments and provider hours, and
running it twice mints zero duplicate rows.
"""
from io import StringIO

import pytest
from django.core.management import call_command

from apps.accounts.models import User, UserLocation
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
    call_command('seed_accounts', stdout=out, stderr=err, **options)
    return out.getvalue(), err.getvalue()


def test_seed_accounts_creates_the_platform_superuser(seed_shape):
    _run()
    superuser = User.objects.filter(email='admin@navai.local').first()
    assert superuser is not None
    assert superuser.tenant_id is None
    assert superuser.is_superuser is True


def test_seed_accounts_creates_the_full_access_owner_for_each_tenant(seed_shape):
    acme, globex = seed_shape
    _run()
    owner = User.objects.get(tenant=acme, email='admin@acme.test')
    assert owner.tier == User.TIER_OWNER
    assert set(owner.assigned_locations().values_list('slug', flat=True)) == {'downtown', 'uptown'}


def test_seed_accounts_creates_the_single_site_isolation_probe(seed_shape):
    acme, _globex = seed_shape
    _run()
    manager = User.objects.get(tenant=acme, email='downtown.manager@acme.test')
    assert list(manager.assigned_locations().values_list('slug', flat=True)) == ['downtown']


def test_seed_accounts_stamps_provider_hours_for_providers(seed_shape):
    acme, _globex = seed_shape
    _run()
    provider = User.objects.get(tenant=acme, email='downtown.manager@acme.test')
    downtown = Location.objects.get(tenant=acme, slug='downtown')
    assert str(downtown.pk) in (provider.provider_hours or {})


def test_seed_accounts_run_twice_creates_zero_duplicate_rows(seed_shape):
    _run()
    first_user_count = User.objects.count()
    first_assignment_count = UserLocation.objects.count()

    _run()

    assert User.objects.count() == first_user_count
    assert UserLocation.objects.count() == first_assignment_count


def test_seed_accounts_second_run_reports_data_already_exists(seed_shape):
    _run()
    out, _err = _run()
    assert 'already exists' in out


def test_seed_accounts_flush_removes_demo_users_before_reseeding(seed_shape):
    _run()
    _run(flush=True)
    # Re-created identically — still exactly one owner for Acme.
    assert User.objects.filter(tenant__slug='acme', email='admin@acme.test').count() == 1
