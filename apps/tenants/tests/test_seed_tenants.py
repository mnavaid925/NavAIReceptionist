"""Idempotency test for the `seed_tenants` management command.

Mirrors `apps/accounts/tests/test_seed_accounts.py`'s shape: run it, assert the
demo shape, run it again, assert zero new rows. `seed_tenants` seeds TWO demo
tenants with TWO locations each — the point of the exercise (a single-location
demo tenant hides every cross-location scoping bug).
"""
from io import StringIO

import pytest
from django.core.management import call_command

from apps.tenants.models import Location, Tenant

pytestmark = pytest.mark.django_db


def _run(**options):
    out, err = StringIO(), StringIO()
    call_command('seed_tenants', stdout=out, stderr=err, **options)
    return out.getvalue(), err.getvalue()


def test_seed_creates_two_demo_tenants():
    _run()
    assert Tenant.objects.filter(slug__in=['acme', 'globex']).count() == 2


def test_seed_creates_at_least_two_locations_per_demo_tenant():
    _run()
    acme = Tenant.objects.get(slug='acme')
    globex = Tenant.objects.get(slug='globex')
    assert Location.objects.filter(tenant=acme).count() >= 2
    assert Location.objects.filter(tenant=globex).count() >= 2


def test_seed_tenants_have_distinct_customer_ids():
    _run()
    acme = Tenant.objects.get(slug='acme')
    globex = Tenant.objects.get(slug='globex')
    assert acme.customer_id != globex.customer_id
    assert acme.customer_id == 'ACME-1001'
    assert globex.customer_id == 'GLBX-2002'


def test_seed_locations_are_active_by_default():
    _run()
    acme = Tenant.objects.get(slug='acme')
    assert Location.objects.filter(tenant=acme, is_active=False).count() == 0


def test_seed_run_twice_creates_zero_duplicate_rows():
    _run()
    first_tenant_count = Tenant.objects.count()
    first_location_count = Location.objects.count()

    _run()

    assert Tenant.objects.count() == first_tenant_count
    assert Location.objects.count() == first_location_count


def test_seed_second_run_reports_data_already_exists():
    _run()
    out, _err = _run()
    assert 'already exists' in out


def test_seed_flush_removes_and_recreates_identically():
    _run()
    original_acme_pk = Tenant.objects.get(slug='acme').pk

    _run(flush=True)

    acme_after = Tenant.objects.get(slug='acme')
    assert acme_after.pk != original_acme_pk  # actually re-created, not reused
    assert Tenant.objects.filter(slug='acme').count() == 1


def test_seed_does_not_touch_any_real_provider(settings):
    """The seeder builds tenants and locations only — no telephony/LLM call of
    any kind. `PROVIDER_MODE` stays pinned to "fake" throughout."""
    assert settings.PROVIDER_MODE == 'fake'
    _run()
    assert settings.PROVIDER_MODE == 'fake'
