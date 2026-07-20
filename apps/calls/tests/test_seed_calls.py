"""Idempotency test for the `seed_calls` management command (sub-module 5.1).

`seed_calls` resolves its demo tenants/locations by SLUG (`acme`/`globex`,
`downtown`/`uptown`/`riverside`/`lakeside`) rather than inventing its own — this
test builds just enough of that shape (no `seed_scheduling` contacts) to prove
the dedupe key (`provider_call_sid`) does its job: rows whose seeded contact
cannot be resolved are skipped rather than half-created, and running the
command twice must not mint a single duplicate row.
"""
from io import StringIO

import pytest
from django.core.management import call_command

from apps.calls.models import CallSession
from apps.tenants.models import Location, Tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def seed_shape(db):
    """The minimal tenant/location slugs `seed_calls` looks up.

    Deliberately WITHOUT `seed_scheduling`'s contacts — the rows that name a
    contact tuple are then unresolvable and skipped, which is itself a real
    path through the command (`unresolved` in its own output), and the rows
    that carry `contact: None` are still created normally.
    """
    acme = Tenant.objects.create(name='Acme Seed', slug='acme', customer_id='ACME-SEED-TEST')
    globex = Tenant.objects.create(name='Globex Seed', slug='globex', customer_id='GLOBEX-SEED-TEST')
    Location.objects.create(tenant=acme, name='Downtown', slug='downtown')
    Location.objects.create(tenant=acme, name='Uptown', slug='uptown')
    Location.objects.create(tenant=globex, name='Riverside', slug='riverside')
    Location.objects.create(tenant=globex, name='Lakeside', slug='lakeside')
    return acme, globex


def _run():
    out, err = StringIO(), StringIO()
    call_command('seed_calls', stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def test_seed_calls_creates_rows_for_unidentified_callers(seed_shape):
    """Sanity check before the idempotency assertion: the command must
    actually create something out of this minimal shape, or the "run twice"
    assertion below would trivially pass on zero rows both times.
    """
    _run()
    count = CallSession.objects.filter(tenant__slug__in=['acme', 'globex']).count()
    assert count > 0


def test_seed_calls_run_twice_creates_zero_duplicate_rows(seed_shape):
    _run()
    first_count = CallSession.objects.filter(tenant__slug__in=['acme', 'globex']).count()
    first_sids = set(
        CallSession.objects.filter(tenant__slug__in=['acme', 'globex'])
        .values_list('provider_call_sid', flat=True)
    )

    _run()
    second_count = CallSession.objects.filter(tenant__slug__in=['acme', 'globex']).count()
    second_sids = set(
        CallSession.objects.filter(tenant__slug__in=['acme', 'globex'])
        .values_list('provider_call_sid', flat=True)
    )

    assert second_count == first_count
    assert second_sids == first_sids
    # No duplicate provider_call_sid was ever minted — the dedupe key itself.
    all_sids = list(
        CallSession.objects.filter(tenant__slug__in=['acme', 'globex'])
        .values_list('provider_call_sid', flat=True)
    )
    assert len(all_sids) == len(set(all_sids))


def test_seed_calls_third_run_is_still_a_no_op(seed_shape):
    """Not just "twice" — repeated runs must stay stable indefinitely."""
    _run()
    _run()
    stable_count = CallSession.objects.filter(tenant__slug__in=['acme', 'globex']).count()

    _run()

    assert CallSession.objects.filter(tenant__slug__in=['acme', 'globex']).count() == stable_count


def test_seed_calls_skips_rows_whose_contact_is_unresolved(seed_shape):
    """Without `seed_scheduling`'s contacts, a spec naming `('Dana', 'Whitfield')`
    must be skipped rather than created with a guessed or null contact — a
    silently different demo shape would be worse than an honest skip.
    """
    _run()
    acme = Tenant.objects.get(slug='acme')
    assert not CallSession.objects.filter(
        tenant=acme, from_number='+13125550101',
    ).exists()
