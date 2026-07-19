"""CRUD, search, filter and pagination tests for the service/resource catalogue
views (sub-module 4.2).

Cross-tenant/location isolation and tier-gating live in `test_catalog_security.py`.
"""
import pytest
from django.test import Client
from django.urls import reverse

from apps.scheduling.models import Resource, Service

pytestmark = pytest.mark.django_db


def _url(name, *args):
    return reverse(f'scheduling:{name}', args=args)


def _service_post(**overrides):
    data = {
        'name': 'Consult',
        'duration_minutes': '30',
        'buffer_minutes': '0',
        'display_order': '0',
    }
    data.update(overrides)
    return data


def _resource_post(**overrides):
    data = {'name': 'Room 1', 'display_order': '0'}
    data.update(overrides)
    return data


# --------------------------------------------------------------------------- #
# service_list_view
# --------------------------------------------------------------------------- #

def test_service_list_view_renders_for_tenant_admin(client_a, service_a1):
    response = client_a.get(_url('service_list'))

    assert response.status_code == 200
    assert 'scheduling/catalog/service/list.html' in [t.name for t in response.templates]
    assert list(response.context['services']) == [service_a1]
    assert response.context['total_count'] == 1


def test_service_list_view_search_by_name(client_a, tenant_a, make_service):
    haircut = make_service(tenant_a, name='Haircut')
    make_service(tenant_a, name='Massage')

    response = client_a.get(_url('service_list'), {'q': 'hair'})

    assert response.status_code == 200
    assert list(response.context['services']) == [haircut]


def test_service_list_view_search_by_description(client_a, tenant_a, make_service):
    match = make_service(tenant_a, name='X', description='includes a deep clean')
    make_service(tenant_a, name='Y', description='unrelated')

    response = client_a.get(_url('service_list'), {'q': 'deep clean'})

    assert list(response.context['services']) == [match]


def test_service_list_view_status_filter(client_a, tenant_a, make_service):
    active = make_service(tenant_a, name='Active One', is_active=True)
    make_service(tenant_a, name='Inactive One', is_active=False)

    response = client_a.get(_url('service_list'), {'status': 'active'})

    assert list(response.context['services']) == [active]


def test_service_list_view_junk_status_filter_degrades_to_200(client_a, service_a1):
    response = client_a.get(_url('service_list'), {'status': 'not-a-real-status'})
    assert response.status_code == 200
    assert list(response.context['services']) == [service_a1]


def test_service_list_view_scope_here_is_additive_not_exclusive(
    client_a, service_a1, service_a2, service_all_a,
):
    """THE BUG THIS SUB-MODULE IS SHAPED AROUND: `scope=here` (client_a active at
    A1) must include this-location AND all-location services, never just the
    former.
    """
    response = client_a.get(_url('service_list'), {'scope': 'here'})

    results = list(response.context['services'])
    assert service_a1 in results
    assert service_all_a in results
    assert service_a2 not in results


def test_service_list_view_scope_all_locations_returns_only_business_wide(
    client_a, service_a1, service_a2, service_all_a,
):
    response = client_a.get(_url('service_list'), {'scope': 'all_locations'})

    results = list(response.context['services'])
    assert results == [service_all_a]


def test_service_list_view_scope_specific_location_pk_authorised(
    client_a, admin_user, location_a2, service_a1, service_a2, service_all_a,
):
    """`admin_user` (client_a) is assigned to BOTH A1 and A2, so a `scope=<A2 pk>`
    is authorised and narrows to exactly that location's own services.
    """
    response = client_a.get(_url('service_list'), {'scope': str(location_a2.pk)})

    results = list(response.context['services'])
    assert results == [service_a2]


def test_service_list_view_scope_pk_the_user_is_not_assigned_to_is_ignored(
    member_client, location_a2, service_a1, service_a2, service_all_a,
):
    """`member_client` is assigned ONLY to A1. A `scope=<A2 pk>` it cannot reach
    is authorised against `assigned_locations()`, fails, and the filter is
    simply SKIPPED — not silently narrowed to nothing, not a 500.
    """
    response = member_client.get(_url('service_list'), {'scope': str(location_a2.pk)})

    assert response.status_code == 200
    results = list(response.context['services'])
    # Unfiltered: every one of the tenant's services, including the one the
    # unauthorised pk would have named.
    assert service_a1 in results
    assert service_a2 in results
    assert service_all_a in results


def test_service_list_view_scope_superscript_digit_degrades_to_200_not_500(
    client_a, service_a1,
):
    """`'²'.isdigit()` is True but `int('²')` raises — the view guards with
    `.isdecimal()` specifically to avoid turning this into an unhandled
    `ValueError` (a 500 from a query string).
    """
    response = client_a.get(_url('service_list'), {'scope': '²'})
    assert response.status_code == 200


def test_service_list_view_scope_fullwidth_digit_does_not_500(client_a, service_a1):
    """Fullwidth digits (e.g. `'１'` = '1') ARE `.isdecimal()` and ARE
    accepted by `int()`, so this path is exercised as a normal pk lookup
    rather than skipped — still must not 500.
    """
    response = client_a.get(_url('service_list'), {'scope': '１'})
    assert response.status_code == 200


def test_service_list_view_scope_junk_letters_degrades_to_200(client_a, service_a1):
    response = client_a.get(_url('service_list'), {'scope': 'not-a-pk'})
    assert response.status_code == 200
    assert list(response.context['services']) == [service_a1]


def test_service_list_view_page_past_the_end_degrades_to_200(client_a, service_a1):
    response = client_a.get(_url('service_list'), {'page': '999'})
    assert response.status_code == 200


def test_service_list_view_page_2_when_rows_exceed_page_size(client_a, tenant_a, make_service):
    for i in range(30):
        make_service(tenant_a, name=f'Service{i:02d}')

    response = client_a.get(_url('service_list'), {'page': '2'})

    assert response.status_code == 200
    assert response.context['page_obj'].number == 2
    assert len(response.context['services']) == 5


def test_service_list_view_query_count_does_not_grow_with_row_count(client_a, tenant_a, make_service):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    for i in range(3):
        make_service(tenant_a, name=f'Small{i}')
    with CaptureQueriesContext(connection) as small:
        response = client_a.get(_url('service_list'))
    assert response.status_code == 200

    for i in range(30):
        make_service(tenant_a, name=f'Big{i}')
    with CaptureQueriesContext(connection) as big:
        response = client_a.get(_url('service_list'))
    assert response.status_code == 200

    # `select_related('location')` in `_tenant_services` is what keeps this flat
    # — each row's `location.name` in the template must not re-query.
    assert len(big.captured_queries) == len(small.captured_queries)


# --------------------------------------------------------------------------- #
# service_create_view
# --------------------------------------------------------------------------- #

def test_service_create_view_get_renders_form(client_a):
    response = client_a.get(_url('service_create'))
    assert response.status_code == 200
    assert 'scheduling/catalog/service/form.html' in [t.name for t in response.templates]
    assert response.context['is_edit'] is False


def test_service_create_view_saves_with_the_request_tenant(client_a, tenant_a):
    response = client_a.post(_url('service_create'), _service_post(name='New Service'))

    assert response.status_code == 302
    obj = Service.objects.get(name='New Service')
    assert obj.tenant_id == tenant_a.pk


def test_service_create_view_leaving_location_blank_offers_at_all_locations(
    client_a, location_a1,
):
    """`Service.location` is a real user choice, NOT auto-stamped from
    `request.location` — unlike every other location-scoped form. Leaving it
    unset must save `location=None`, even though A1 is the active location.
    """
    response = client_a.post(_url('service_create'), _service_post(name='All Sites Service'))

    assert response.status_code == 302
    obj = Service.objects.get(name='All Sites Service')
    assert obj.location_id is None


def test_service_create_view_picking_a_location_pins_it(client_a, location_a1):
    response = client_a.post(
        _url('service_create'), _service_post(name='Pinned Service', location=str(location_a1.pk)),
    )

    assert response.status_code == 302
    obj = Service.objects.get(name='Pinned Service')
    assert obj.location_id == location_a1.pk


def test_service_create_view_invalid_submission_rerenders_form_with_errors(client_a):
    response = client_a.post(_url('service_create'), {'name': ''})

    assert response.status_code == 200
    assert not response.context['form'].is_valid()
    assert Service.objects.count() == 0


# --------------------------------------------------------------------------- #
# service_detail_view
# --------------------------------------------------------------------------- #

def test_service_detail_view_renders_for_tenant_admin(client_a, service_a1):
    response = client_a.get(_url('service_detail', service_a1.pk))
    assert response.status_code == 200
    assert response.context['obj'] == service_a1


def test_service_detail_view_bookable_here_true_at_the_pinned_location(client_a, service_a1):
    """`client_a` is active at A1, `service_a1` is pinned to A1."""
    response = client_a.get(_url('service_detail', service_a1.pk))
    assert response.context['bookable_here'] is True


def test_service_detail_view_bookable_here_false_at_a_different_location(client_a, service_a2):
    """The catalogue is business-wide for READING — `client_a` can view a
    service pinned to A2 even while active at A1, but it is not bookable here.
    """
    response = client_a.get(_url('service_detail', service_a2.pk))
    assert response.status_code == 200
    assert response.context['bookable_here'] is False


def test_service_detail_view_bookable_here_true_for_an_all_locations_service(
    client_a, service_all_a,
):
    response = client_a.get(_url('service_detail', service_all_a.pk))
    assert response.context['bookable_here'] is True


def test_service_detail_view_appointment_count_is_none_until_4_3_lands(client_a, service_a1):
    """`scheduling.Appointment` (4.3) does not exist yet, so `_appointment_count`
    degrades to `None` (import-guarded) rather than raising `ImportError`.
    """
    response = client_a.get(_url('service_detail', service_a1.pk))
    assert response.context['appointment_count'] is None


# --------------------------------------------------------------------------- #
# service_edit_view
# --------------------------------------------------------------------------- #

def test_service_edit_view_get_renders_prefilled_form(client_a, service_a1):
    response = client_a.get(_url('service_edit', service_a1.pk))
    assert response.status_code == 200
    assert response.context['is_edit'] is True
    assert response.context['form'].instance == service_a1


def test_service_edit_view_saves_changes(client_a, service_a1):
    response = client_a.post(
        _url('service_edit', service_a1.pk),
        _service_post(name='Updated Name', location=str(service_a1.location_id)),
    )

    assert response.status_code == 302
    service_a1.refresh_from_db()
    assert service_a1.name == 'Updated Name'


# --------------------------------------------------------------------------- #
# service_delete_view — happy path for a management-tier user
# --------------------------------------------------------------------------- #

def test_service_delete_view_removes_the_row(client_a, service_a1):
    pk = service_a1.pk
    response = client_a.post(_url('service_delete', pk))
    assert response.status_code == 302
    assert not Service.objects.filter(pk=pk).exists()


# --------------------------------------------------------------------------- #
# resource_list_view
# --------------------------------------------------------------------------- #

def test_resource_list_view_renders_for_tenant_admin(client_a, resource_a1):
    response = client_a.get(_url('resource_list'))

    assert response.status_code == 200
    assert 'scheduling/catalog/resource/list.html' in [t.name for t in response.templates]
    assert list(response.context['resources']) == [resource_a1]
    assert response.context['total_count'] == 1


def test_resource_list_view_is_scoped_to_the_active_location(
    client_a, resource_a1, resource_a2,
):
    """`client_a` is active at A1 — A2's same-named resource must not appear."""
    response = client_a.get(_url('resource_list'))
    results = list(response.context['resources'])
    assert resource_a1 in results
    assert resource_a2 not in results


def test_resource_list_view_empty_when_no_active_location(admin_user, resource_a1):
    """`admin_user` is assigned to TWO locations, so nothing auto-activates on
    login — with no active location the view returns nothing rather than
    leaking either site's rooms.
    """
    client = Client()
    client.force_login(admin_user)

    response = client.get(_url('resource_list'))

    assert response.status_code == 200
    assert list(response.context['resources']) == []


def test_resource_list_view_search_by_name(client_a, tenant_a, location_a1, make_resource):
    match = make_resource(tenant_a, location_a1, name='Treatment Room')
    make_resource(tenant_a, location_a1, name='Storage Closet')

    response = client_a.get(_url('resource_list'), {'q': 'treatment'})
    assert list(response.context['resources']) == [match]


def test_resource_list_view_search_by_resource_number(client_a, tenant_a, location_a1, make_resource):
    match = make_resource(tenant_a, location_a1, name='Room A', resource_number='B12')
    make_resource(tenant_a, location_a1, name='Room B', resource_number='C99')

    response = client_a.get(_url('resource_list'), {'q': 'b12'})
    assert list(response.context['resources']) == [match]


def test_resource_list_view_status_inactive_filter_narrows_correctly(
    client_a, tenant_a, location_a1, make_resource,
):
    make_resource(tenant_a, location_a1, name='Active Room', is_active=True)
    inactive = make_resource(tenant_a, location_a1, name='Inactive Room', is_active=False)

    response = client_a.get(_url('resource_list'), {'status': 'inactive'})
    assert list(response.context['resources']) == [inactive]


def test_resource_list_view_junk_status_filter_degrades_to_200(client_a, resource_a1):
    response = client_a.get(_url('resource_list'), {'status': 'bogus'})
    assert response.status_code == 200
    assert list(response.context['resources']) == [resource_a1]


def test_resource_list_view_page_past_the_end_degrades_to_200(client_a, resource_a1):
    response = client_a.get(_url('resource_list'), {'page': '999'})
    assert response.status_code == 200


def test_resource_list_view_page_2_when_rows_exceed_page_size(client_a, tenant_a, location_a1, make_resource):
    for i in range(30):
        make_resource(tenant_a, location_a1, name=f'Room{i:02d}')

    response = client_a.get(_url('resource_list'), {'page': '2'})

    assert response.status_code == 200
    assert response.context['page_obj'].number == 2
    assert len(response.context['resources']) == 5


def test_resource_list_view_query_count_does_not_grow_with_row_count(
    client_a, tenant_a, location_a1, make_resource,
):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    for i in range(3):
        make_resource(tenant_a, location_a1, name=f'Small{i}')
    with CaptureQueriesContext(connection) as small:
        response = client_a.get(_url('resource_list'))
    assert response.status_code == 200

    for i in range(30):
        make_resource(tenant_a, location_a1, name=f'Big{i}')
    with CaptureQueriesContext(connection) as big:
        response = client_a.get(_url('resource_list'))
    assert response.status_code == 200

    assert len(big.captured_queries) == len(small.captured_queries)


# --------------------------------------------------------------------------- #
# resource_create_view
# --------------------------------------------------------------------------- #

def test_resource_create_view_get_renders_form(client_a):
    response = client_a.get(_url('resource_create'))
    assert response.status_code == 200
    assert 'scheduling/catalog/resource/form.html' in [t.name for t in response.templates]
    assert response.context['is_edit'] is False


def test_resource_create_view_saves_with_tenant_and_active_location(client_a, tenant_a, location_a1):
    response = client_a.post(_url('resource_create'), _resource_post(name='New Room'))

    assert response.status_code == 302
    obj = Resource.objects.get(name='New Room')
    assert obj.tenant_id == tenant_a.pk
    assert obj.location_id == location_a1.pk


def test_resource_create_view_refuses_without_an_active_location(admin_user, resource_a1):
    client = Client()
    client.force_login(admin_user)

    response = client.post(_url('resource_create'), _resource_post(name='Orphan Room'), follow=True)

    assert response.status_code == 200
    assert response.redirect_chain[-1][0] == _url('resource_list')
    assert not Resource.objects.filter(name='Orphan Room').exists()


def test_resource_create_view_invalid_submission_rerenders_form_with_errors(client_a):
    response = client_a.post(_url('resource_create'), {'name': ''})
    assert response.status_code == 200
    assert not response.context['form'].is_valid()
    assert Resource.objects.count() == 0


def test_resource_create_view_duplicate_name_at_active_location_is_rejected(
    client_a, resource_a1,
):
    response = client_a.post(_url('resource_create'), _resource_post(name=resource_a1.name))

    assert response.status_code == 200
    assert not response.context['form'].is_valid()
    assert Resource.objects.filter(name=resource_a1.name).count() == 1


# --------------------------------------------------------------------------- #
# resource_detail_view
# --------------------------------------------------------------------------- #

def test_resource_detail_view_renders_for_tenant_admin(client_a, resource_a1):
    response = client_a.get(_url('resource_detail', resource_a1.pk))
    assert response.status_code == 200
    assert response.context['obj'] == resource_a1


def test_resource_detail_view_appointment_count_is_none_until_4_3_lands(client_a, resource_a1):
    response = client_a.get(_url('resource_detail', resource_a1.pk))
    assert response.context['appointment_count'] is None


# --------------------------------------------------------------------------- #
# resource_edit_view
# --------------------------------------------------------------------------- #

def test_resource_edit_view_get_renders_prefilled_form(client_a, resource_a1):
    response = client_a.get(_url('resource_edit', resource_a1.pk))
    assert response.status_code == 200
    assert response.context['is_edit'] is True
    assert response.context['form'].instance == resource_a1


def test_resource_edit_view_saves_changes(client_a, resource_a1):
    response = client_a.post(
        _url('resource_edit', resource_a1.pk), _resource_post(name='Renamed Room'),
    )

    assert response.status_code == 302
    resource_a1.refresh_from_db()
    assert resource_a1.name == 'Renamed Room'


# --------------------------------------------------------------------------- #
# resource_delete_view — happy path for a management-tier user
# --------------------------------------------------------------------------- #

def test_resource_delete_view_removes_the_row(client_a, resource_a1):
    pk = resource_a1.pk
    response = client_a.post(_url('resource_delete', pk))
    assert response.status_code == 302
    assert not Resource.objects.filter(pk=pk).exists()
