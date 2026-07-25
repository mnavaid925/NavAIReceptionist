"""Model tests for `tenants.Tenant` and `tenants.Location`.

Covers the two unique constraints that carry Module 1's isolation design
(`Tenant.customer_id`/`slug` globally unique, `Location(tenant, slug)` unique per
business), `__str__`, ordering, the tenant cascade, and `Location.tzinfo`'s
explicit degrade-to-UTC guard on a bad/unknown timezone name.
"""
from zoneinfo import ZoneInfo

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.tenants.models import Location, Tenant

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# Tenant — uniqueness
# --------------------------------------------------------------------------- #

def test_customer_id_is_globally_unique():
    Tenant.objects.create(name='First Biz', slug='first-biz', customer_id='DUP-ID')
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Tenant.objects.create(name='Second Biz', slug='second-biz', customer_id='DUP-ID')


def test_slug_is_globally_unique():
    Tenant.objects.create(name='First Biz', slug='dup-slug', customer_id='CID-1')
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Tenant.objects.create(name='Second Biz', slug='dup-slug', customer_id='CID-2')


def test_different_tenants_may_share_no_field_but_are_otherwise_independent(tenant_a, tenant_b):
    assert tenant_a.customer_id != tenant_b.customer_id
    assert tenant_a.slug != tenant_b.slug


# --------------------------------------------------------------------------- #
# Tenant — defaults, __str__, ordering
# --------------------------------------------------------------------------- #

def test_tenant_defaults():
    tenant = Tenant.objects.create(name='Defaults Co', slug='defaults-co', customer_id='DEF-001')
    assert tenant.timezone == 'UTC'
    assert tenant.is_active is True


def test_tenant_str_is_name(tenant_a):
    assert str(tenant_a) == 'Acme Corp'


def test_tenant_ordering_is_by_name():
    Tenant.objects.create(name='Zebra Co', slug='zebra-co', customer_id='Z-001')
    Tenant.objects.create(name='Alpha Co', slug='alpha-co', customer_id='A-001')
    names = list(Tenant.objects.values_list('name', flat=True))
    assert names == sorted(names)


# --------------------------------------------------------------------------- #
# Tenant — cascade
# --------------------------------------------------------------------------- #

def test_deleting_tenant_cascades_to_its_locations(tenant_a, location_a1, location_a2):
    tenant_a.delete()
    assert not Location.objects.filter(pk=location_a1.pk).exists()
    assert not Location.objects.filter(pk=location_a2.pk).exists()


def test_deleting_tenant_cascades_to_its_users(tenant_a, admin_user):
    tenant_a.delete()
    assert not User.objects.filter(pk=admin_user.pk).exists()


def test_deleting_one_tenant_leaves_another_tenants_locations_alone(tenant_a, tenant_b, location_a1, location_b1):
    tenant_a.delete()
    assert Location.objects.filter(pk=location_b1.pk).exists()


# --------------------------------------------------------------------------- #
# Location — uniqueness (tenant, slug)
# --------------------------------------------------------------------------- #

def test_location_slug_unique_within_a_tenant(tenant_a):
    Location.objects.create(tenant=tenant_a, name='First', slug='dup-loc-slug')
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Location.objects.create(tenant=tenant_a, name='Second', slug='dup-loc-slug')


def test_location_slug_may_repeat_across_different_tenants(tenant_a, tenant_b):
    Location.objects.create(tenant=tenant_a, name='Shared Slug A', slug='shared-slug')
    # Must not raise: the constraint is (tenant, slug), not slug alone.
    Location.objects.create(tenant=tenant_b, name='Shared Slug B', slug='shared-slug')


# --------------------------------------------------------------------------- #
# Location — defaults, __str__, ordering
# --------------------------------------------------------------------------- #

def test_location_defaults(tenant_a):
    location = Location.objects.create(tenant=tenant_a, name='Defaults Site', slug='defaults-site')
    assert location.timezone == 'UTC'
    assert location.country == 'US'
    assert location.is_active is True


def test_location_str_is_name(location_a1):
    assert str(location_a1) == 'Downtown'


def test_location_ordering_is_by_name(tenant_a):
    Location.objects.create(tenant=tenant_a, name='Zeta Site', slug='zeta-site')
    Location.objects.create(tenant=tenant_a, name='Alpha Site', slug='alpha-site')
    names = list(Location.objects.filter(tenant=tenant_a).values_list('name', flat=True))
    assert names == sorted(names)


# --------------------------------------------------------------------------- #
# Location.full_address
# --------------------------------------------------------------------------- #

def test_full_address_joins_non_blank_parts(tenant_a):
    location = Location.objects.create(
        tenant=tenant_a, name='Full Addr', slug='full-addr',
        address_line1='123 Main St', city='Chicago', state='IL',
        postal_code='60601', country='US',
    )
    assert location.full_address == '123 Main St, Chicago, IL, 60601, US'


def test_full_address_skips_blank_parts(tenant_a):
    location = Location.objects.create(
        tenant=tenant_a, name='Partial Addr', slug='partial-addr',
        address_line1='', address_line2='', city='Chicago', state='',
        postal_code='', country='',
    )
    assert location.full_address == 'Chicago'


def test_full_address_is_empty_string_when_nothing_set(tenant_a):
    location = Location.objects.create(
        tenant=tenant_a, name='No Addr', slug='no-addr', country='',
    )
    assert location.full_address == ''


# --------------------------------------------------------------------------- #
# Location.tzinfo — the explicit degrade-to-UTC guard
# --------------------------------------------------------------------------- #

def test_tzinfo_resolves_a_valid_iana_name(tenant_a):
    location = Location.objects.create(
        tenant=tenant_a, name='Valid TZ', slug='valid-tz', timezone='America/Chicago',
    )
    assert location.tzinfo == ZoneInfo('America/Chicago')


def test_tzinfo_degrades_to_utc_on_an_unknown_name(tenant_a):
    """REGRESSION GUARD for the explicit `ZoneInfoNotFoundError` catch in
    `Location.tzinfo` (apps/tenants/models/Location.py). A stored tz string can go
    stale when the host's tz database changes; a raised error here would explode a
    calendar render or a live call instead of degrading safely.
    """
    location = Location.objects.create(
        tenant=tenant_a, name='Bad TZ', slug='bad-tz', timezone='Not/ARealZone',
    )
    assert location.tzinfo == ZoneInfo('UTC')


def test_tzinfo_degrades_to_utc_on_an_empty_string(tenant_a):
    location = Location(tenant=tenant_a, name='Empty TZ', slug='empty-tz', timezone='')
    assert location.tzinfo == ZoneInfo('UTC')


def test_tzinfo_degrades_to_utc_on_garbage_value(tenant_a):
    location = Location(tenant=tenant_a, name='Garbage TZ', slug='garbage-tz', timezone='!!!not-a-tz!!!')
    assert location.tzinfo == ZoneInfo('UTC')


def test_local_now_uses_the_locations_own_timezone(tenant_a):
    location = Location.objects.create(
        tenant=tenant_a, name='LA Site', slug='la-site', timezone='America/Los_Angeles',
    )
    now = location.local_now()
    assert now.tzinfo == ZoneInfo('America/Los_Angeles')
