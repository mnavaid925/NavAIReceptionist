"""Model tests for `scheduling.Service` and `scheduling.Resource` (sub-module 4.2)."""
import pytest
from django.db import IntegrityError, transaction

from apps.scheduling.models import Resource, Service

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# Service — nullable location
# --------------------------------------------------------------------------- #

def test_service_defaults(tenant_a, make_service):
    service = make_service(tenant_a)
    assert service.is_active is True
    assert service.duration_minutes == 30
    assert service.buffer_minutes == 0
    assert service.requires_resource is False
    assert service.display_order == 0


def test_service_str_returns_name(tenant_a, make_service):
    service = make_service(tenant_a, name='Deep Tissue Massage')
    assert str(service) == 'Deep Tissue Massage'


def test_service_location_defaults_to_null(tenant_a, make_service):
    service = make_service(tenant_a)
    assert service.location_id is None


def test_service_is_all_locations_true_when_location_is_null(tenant_a, make_service):
    service = make_service(tenant_a, location=None)
    assert service.is_all_locations is True


def test_service_is_all_locations_false_when_location_is_set(tenant_a, location_a1, make_service):
    service = make_service(tenant_a, location=location_a1)
    assert service.is_all_locations is False


def test_service_location_label_all_locations(tenant_a, make_service):
    service = make_service(tenant_a, location=None)
    assert service.location_label == 'All locations'


def test_service_location_label_named_location(tenant_a, location_a1, make_service):
    service = make_service(tenant_a, location=location_a1)
    assert service.location_label == location_a1.name


def test_service_total_minutes_sums_duration_and_buffer(tenant_a, make_service):
    service = make_service(tenant_a, duration_minutes=45, buffer_minutes=15)
    assert service.total_minutes == 60


def test_service_total_minutes_with_zero_buffer(tenant_a, make_service):
    service = make_service(tenant_a, duration_minutes=30, buffer_minutes=0)
    assert service.total_minutes == 30


# -- is_offered_at() --------------------------------------------------------- #

def test_is_offered_at_true_for_any_location_when_service_is_all_locations(
    tenant_a, location_a1, location_a2, make_service,
):
    service = make_service(tenant_a, location=None)
    assert service.is_offered_at(location_a1) is True
    assert service.is_offered_at(location_a2) is True


def test_is_offered_at_true_when_no_location_given_and_service_is_all_locations(
    tenant_a, make_service,
):
    service = make_service(tenant_a, location=None)
    assert service.is_offered_at(None) is True


def test_is_offered_at_true_for_the_pinned_location(tenant_a, location_a1, make_service):
    service = make_service(tenant_a, location=location_a1)
    assert service.is_offered_at(location_a1) is True


def test_is_offered_at_false_for_a_different_location(
    tenant_a, location_a1, location_a2, make_service,
):
    service = make_service(tenant_a, location=location_a1)
    assert service.is_offered_at(location_a2) is False


def test_is_offered_at_false_when_no_location_given_and_service_is_pinned(
    tenant_a, location_a1, make_service,
):
    service = make_service(tenant_a, location=location_a1)
    assert service.is_offered_at(None) is False


def test_service_ordering_is_display_order_then_name(tenant_a, make_service):
    third = make_service(tenant_a, name='Zebra', display_order=0)
    first = make_service(tenant_a, name='Alpha', display_order=0)
    second = make_service(tenant_a, name='Massage', display_order=1)

    assert list(Service.objects.filter(tenant=tenant_a)) == [first, third, second]


def test_service_name_not_unique_across_scopes_at_db_level(
    tenant_a, location_a1, location_a2, make_service,
):
    """The DB itself places no uniqueness on `Service.name` — the whole point of
    the nullable `location` shape is that scoping the uniqueness check is a form
    concern (`ServiceForm.clean`), not a DB constraint. Two same-named services
    at two different locations must both simply save.
    """
    one = make_service(tenant_a, name='Haircut', location=location_a1)
    two = make_service(tenant_a, name='Haircut', location=location_a2)
    assert one.pk != two.pk


# --------------------------------------------------------------------------- #
# Resource — (location, name) uniqueness
# --------------------------------------------------------------------------- #

def test_resource_defaults(tenant_a, location_a1, make_resource):
    resource = make_resource(tenant_a, location_a1)
    assert resource.is_active is True
    assert resource.display_order == 0


def test_resource_same_name_at_two_different_locations_is_allowed(
    tenant_a, location_a1, location_a2, make_resource,
):
    one = make_resource(tenant_a, location_a1, name='Room 1')
    two = make_resource(tenant_a, location_a2, name='Room 1')
    assert one.pk != two.pk
    assert Resource.objects.filter(tenant=tenant_a, name='Room 1').count() == 2


def test_resource_duplicate_name_at_the_same_location_is_rejected(
    tenant_a, location_a1, make_resource,
):
    make_resource(tenant_a, location_a1, name='Room 1')

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_resource(tenant_a, location_a1, name='Room 1')


def test_resource_display_label_with_resource_number(tenant_a, location_a1, make_resource):
    resource = make_resource(tenant_a, location_a1, name='Suite', resource_number='2')
    assert resource.display_label == 'Suite (2)'


def test_resource_display_label_without_resource_number(tenant_a, location_a1, make_resource):
    resource = make_resource(tenant_a, location_a1, name='Suite', resource_number='')
    assert resource.display_label == 'Suite'


def test_resource_str_delegates_to_display_label(tenant_a, location_a1, make_resource):
    resource = make_resource(tenant_a, location_a1, name='Suite', resource_number='2')
    assert str(resource) == resource.display_label == 'Suite (2)'


def test_resource_ordering_is_display_order_then_name(tenant_a, location_a1, make_resource):
    third = make_resource(tenant_a, location_a1, name='Zebra Room', display_order=0)
    first = make_resource(tenant_a, location_a1, name='Alpha Room', display_order=0)
    second = make_resource(tenant_a, location_a1, name='Middle Room', display_order=1)

    assert list(Resource.objects.filter(tenant=tenant_a, location=location_a1)) == [
        first, third, second,
    ]
