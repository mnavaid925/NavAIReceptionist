"""View tests for sub-module 1.2 — Location Directory.

`tenants.Location` is tenant-scoped but NOT location-scoped (it IS the
location) — every queryset here filters on `tenant=request.tenant` alone. Covers
list (search/filter/pagination), detail, create, edit, deactivate (never a hard
delete), the tier gate (`MANAGEMENT_TIERS = owner, manager`), and the
cross-tenant IDOR boundary on every pk-taking view.
"""
import pytest
from django.test import Client
from django.urls import reverse

from apps.tenants.models import Location

pytestmark = pytest.mark.django_db


def _url(name, *args):
    return reverse(f'tenants:{name}', args=args)


# --------------------------------------------------------------------------- #
# location_list_view — auth / tier gate
# --------------------------------------------------------------------------- #

def test_list_anonymous_redirects_to_login(client):
    response = client.get(_url('location_list'))
    assert response.status_code == 302


def test_list_blocks_staff_tier(member_client):
    response = member_client.get(_url('location_list'))
    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')


def test_list_blocks_staff_tier_shows_permission_message(member_client):
    response = member_client.get(_url('location_list'), follow=True)
    messages_seen = [str(m) for m in response.context['messages']]
    assert any('do not have permission' in m for m in messages_seen)


def test_list_open_to_owner(client_a):
    response = client_a.get(_url('location_list'))
    assert response.status_code == 200


def test_list_open_to_manager_tier(manager_client):
    response = manager_client.get(_url('location_list'))
    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# location_list_view — tenant scoping
# --------------------------------------------------------------------------- #

def test_list_renders_expected_template_and_context(client_a, location_a1, location_a2):
    response = client_a.get(_url('location_list'))
    assert 'tenants/location/list.html' in [t.name for t in response.templates]
    assert set(response.context['locations']) == {location_a1, location_a2}
    assert response.context['total_count'] == 2


def test_list_never_contains_another_tenants_rows(client_a, location_a1, location_b1):
    response = client_a.get(_url('location_list'))
    results = list(response.context['locations'])
    assert location_a1 in results
    assert location_b1 not in results


# --------------------------------------------------------------------------- #
# location_list_view — search / filters
# --------------------------------------------------------------------------- #

def test_search_by_name(client_a, location_a1, location_a2):
    response = client_a.get(_url('location_list'), {'q': 'Downtown'})
    assert list(response.context['locations']) == [location_a1]


def test_search_by_city(client_a, tenant_a):
    match = Location.objects.create(tenant=tenant_a, name='City Match', slug='city-match', city='Springfield')
    response = client_a.get(_url('location_list'), {'q': 'Springfield'})
    assert match in list(response.context['locations'])


def test_search_by_phone(client_a, tenant_a):
    match = Location.objects.create(tenant=tenant_a, name='Phone Match', slug='phone-match', phone='+13125559999')
    response = client_a.get(_url('location_list'), {'q': '5559999'})
    assert match in list(response.context['locations'])


def test_filter_status_active(client_a, tenant_a, location_a1):
    inactive = Location.objects.create(tenant=tenant_a, name='Inactive Site', slug='inactive-site', is_active=False)
    response = client_a.get(_url('location_list'), {'status': 'active'})
    results = list(response.context['locations'])
    assert location_a1 in results
    assert inactive not in results


def test_filter_status_inactive(client_a, tenant_a, location_a1):
    inactive = Location.objects.create(tenant=tenant_a, name='Inactive Site 2', slug='inactive-site-2', is_active=False)
    response = client_a.get(_url('location_list'), {'status': 'inactive'})
    assert list(response.context['locations']) == [inactive]


def test_junk_status_degrades_to_no_filter(client_a, location_a1, location_a2):
    response = client_a.get(_url('location_list'), {'status': 'bogus-status'})
    assert response.status_code == 200
    assert set(response.context['locations']) == {location_a1, location_a2}


# --------------------------------------------------------------------------- #
# location_list_view — pagination
# --------------------------------------------------------------------------- #

def test_junk_page_degrades_to_page_1(client_a, location_a1):
    response = client_a.get(_url('location_list'), {'page': 'abc'})
    assert response.status_code == 200
    assert response.context['page_obj'].number == 1


def test_page_2_when_rows_exceed_page_size(client_a, tenant_a):
    for i in range(30):
        Location.objects.create(tenant=tenant_a, name=f'Bulk {i:03d}', slug=f'bulk-{i:03d}')
    response = client_a.get(_url('location_list'), {'page': '2'})
    assert response.status_code == 200
    assert response.context['page_obj'].number == 2


def test_page_past_the_end_degrades_to_last_valid_page(client_a, tenant_a):
    for i in range(30):
        Location.objects.create(tenant=tenant_a, name=f'Bulk2 {i:03d}', slug=f'bulk2-{i:03d}')
    response = client_a.get(_url('location_list'), {'page': '99999'})
    assert response.status_code == 200
    assert response.context['page_obj'].number == response.context['page_obj'].paginator.num_pages


def test_list_query_count_stays_bounded(client_a, tenant_a, django_assert_max_num_queries):
    for i in range(10):
        Location.objects.create(tenant=tenant_a, name=f'QCount {i:03d}', slug=f'qcount-{i:03d}')
    with django_assert_max_num_queries(25):
        client_a.get(_url('location_list'))


# --------------------------------------------------------------------------- #
# location_detail_view
# --------------------------------------------------------------------------- #

def test_detail_renders_for_own_tenant(client_a, location_a1):
    response = client_a.get(_url('location_detail', location_a1.pk))
    assert response.status_code == 200
    assert response.context['obj'] == location_a1
    assert 'tenants/location/detail.html' in [t.name for t in response.templates]


def test_detail_marks_the_active_location(client_a, location_a1, location_a2):
    response = client_a.get(_url('location_detail', location_a1.pk))
    assert response.context['is_active_location'] is True
    response2 = client_a.get(_url('location_detail', location_a2.pk))
    assert response2.context['is_active_location'] is False


def test_detail_includes_assignments(client_a, admin_user, location_a1):
    response = client_a.get(_url('location_detail', location_a1.pk))
    assignments = list(response.context['assignments'])
    assert any(a.user_id == admin_user.pk for a in assignments)


def test_detail_cross_tenant_pk_is_404(client_a, location_b1):
    response = client_a.get(_url('location_detail', location_b1.pk))
    assert response.status_code == 404


def test_detail_blocks_staff_tier(member_client, location_a1):
    response = member_client.get(_url('location_detail', location_a1.pk))
    assert response.status_code == 302


def test_detail_nonexistent_pk_is_404(client_a):
    response = client_a.get(_url('location_detail', 999999))
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# location_create_view
# --------------------------------------------------------------------------- #

def test_create_get_is_the_form(client_a):
    response = client_a.get(_url('location_create'))
    assert response.status_code == 200
    assert response.context['is_edit'] is False


def test_create_blocks_staff_tier(member_client):
    response = member_client.get(_url('location_create'))
    assert response.status_code == 302


def test_create_stamps_the_request_tenant(client_a, tenant_a):
    response = client_a.post(_url('location_create'), {
        'name': 'New Site', 'slug': 'new-site', 'timezone': 'UTC', 'country': 'US',
    })
    obj = Location.objects.get(slug='new-site')
    assert obj.tenant_id == tenant_a.pk
    assert response.status_code == 302


def test_create_cannot_smuggle_a_foreign_tenant(client_a, tenant_a, tenant_b):
    """`TenantModelForm` never exposes `tenant` as a field — posting one must be
    inert, and the row must still land under the REQUEST tenant."""
    client_a.post(_url('location_create'), {
        'name': 'Smuggled Site', 'slug': 'smuggled-site', 'timezone': 'UTC', 'country': 'US',
        'tenant': tenant_b.pk,
    })
    obj = Location.objects.get(slug='smuggled-site')
    assert obj.tenant_id == tenant_a.pk


def test_create_generates_slug_from_name_when_blank(client_a):
    client_a.post(_url('location_create'), {
        'name': 'Auto Slug Site', 'slug': '', 'timezone': 'UTC', 'country': 'US',
    })
    assert Location.objects.filter(slug='auto-slug-site').exists()


def test_create_rejects_duplicate_slug_within_tenant(client_a, location_a1):
    response = client_a.post(_url('location_create'), {
        'name': 'Dup Slug Site', 'slug': location_a1.slug, 'timezone': 'UTC', 'country': 'US',
    })
    assert response.status_code == 200
    assert 'slug' in response.context['form'].errors


def test_create_allows_same_slug_as_another_tenants_location(client_a, tenant_a, location_b1):
    """Only (tenant, slug) is unique — another business's slug is no clash."""
    response = client_a.post(_url('location_create'), {
        'name': 'Cross Tenant Slug', 'slug': location_b1.slug, 'timezone': 'UTC', 'country': 'US',
    })
    assert response.status_code == 302
    assert Location.objects.filter(tenant=tenant_a, slug=location_b1.slug).exists()


def test_create_rejects_unrecognised_timezone(client_a):
    response = client_a.post(_url('location_create'), {
        'name': 'Bad TZ Site', 'slug': 'bad-tz-site', 'timezone': 'Not/ARealZone', 'country': 'US',
    })
    assert response.status_code == 200
    assert 'timezone' in response.context['form'].errors
    assert not Location.objects.filter(slug='bad-tz-site').exists()


def test_create_requires_a_name(client_a):
    response = client_a.post(_url('location_create'), {'slug': 'no-name-site', 'timezone': 'UTC'})
    assert response.status_code == 200
    assert not Location.objects.filter(slug='no-name-site').exists()


def test_create_csrf_enforced(admin_user):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = csrf_client.post(_url('location_create'), {
        'name': 'CSRF Site', 'slug': 'csrf-site', 'timezone': 'UTC', 'country': 'US',
    })
    assert response.status_code == 403
    assert not Location.objects.filter(slug='csrf-site').exists()


# --------------------------------------------------------------------------- #
# location_edit_view
# --------------------------------------------------------------------------- #

def test_edit_get_renders_form(client_a, location_a1):
    response = client_a.get(_url('location_edit', location_a1.pk))
    assert response.status_code == 200
    assert response.context['is_edit'] is True
    assert response.context['obj'] == location_a1


def test_edit_blocks_staff_tier(member_client, location_a1):
    response = member_client.get(_url('location_edit', location_a1.pk))
    assert response.status_code == 302


def test_edit_updates_fields(client_a, location_a1):
    response = client_a.post(_url('location_edit', location_a1.pk), {
        'name': 'Downtown Renamed', 'slug': location_a1.slug, 'timezone': 'UTC', 'country': 'US',
    })
    assert response.status_code == 302
    location_a1.refresh_from_db()
    assert location_a1.name == 'Downtown Renamed'


def test_edit_cross_tenant_pk_is_404(client_a, location_b1):
    response = client_a.get(_url('location_edit', location_b1.pk))
    assert response.status_code == 404


def test_edit_cross_tenant_post_is_404_and_leaves_row_untouched(client_a, location_b1):
    original_name = location_b1.name
    response = client_a.post(_url('location_edit', location_b1.pk), {
        'name': 'Hacked', 'slug': location_b1.slug, 'timezone': 'UTC', 'country': 'US',
    })
    assert response.status_code == 404
    location_b1.refresh_from_db()
    assert location_b1.name == original_name


def test_edit_cross_location_same_tenant_pk_succeeds(client_a, location_a2):
    """`Location` is tenant-scoped, NOT location-scoped (it IS the location) — an
    A1-active client editing A2 is legitimate, unlike every location-SCOPED model
    tested elsewhere in this suite."""
    response = client_a.post(_url('location_edit', location_a2.pk), {
        'name': 'Uptown Renamed', 'slug': location_a2.slug, 'timezone': 'UTC', 'country': 'US',
    })
    assert response.status_code == 302
    location_a2.refresh_from_db()
    assert location_a2.name == 'Uptown Renamed'


def test_edit_cannot_smuggle_a_foreign_tenant(client_a, tenant_a, location_a1, tenant_b):
    client_a.post(_url('location_edit', location_a1.pk), {
        'name': location_a1.name, 'slug': location_a1.slug, 'timezone': 'UTC', 'country': 'US',
        'tenant': tenant_b.pk,
    })
    location_a1.refresh_from_db()
    assert location_a1.tenant_id == tenant_a.pk


def test_edit_csrf_enforced(admin_user, location_a1):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = csrf_client.post(_url('location_edit', location_a1.pk), {
        'name': 'Should Not Save', 'slug': location_a1.slug, 'timezone': 'UTC', 'country': 'US',
    })
    assert response.status_code == 403
    location_a1.refresh_from_db()
    assert location_a1.name != 'Should Not Save'


# --------------------------------------------------------------------------- #
# location_delete_view — deactivation, POST-only, never a hard delete
# --------------------------------------------------------------------------- #

def test_delete_get_is_405(client_a, location_a1, location_a2):
    response = client_a.get(_url('location_delete', location_a2.pk))
    assert response.status_code == 405
    location_a2.refresh_from_db()
    assert location_a2.is_active is True


def test_delete_deactivates_not_deletes(client_a, location_a1, location_a2):
    response = client_a.post(_url('location_delete', location_a2.pk))
    assert response.status_code == 302
    assert Location.objects.filter(pk=location_a2.pk).exists()
    location_a2.refresh_from_db()
    assert location_a2.is_active is False


def test_delete_blocks_staff_tier(member_client, location_a2):
    response = member_client.post(_url('location_delete', location_a2.pk))
    assert response.status_code == 302
    location_a2.refresh_from_db()
    assert location_a2.is_active is True


def test_delete_cross_tenant_pk_is_404(client_a, location_b1):
    response = client_a.post(_url('location_delete', location_b1.pk))
    assert response.status_code == 404
    location_b1.refresh_from_db()
    assert location_b1.is_active is True


def test_delete_refuses_the_only_active_location(client_a, tenant_a, location_a1):
    """`location_a1` (root fixture) plus `location_a2` are tenant A's two
    locations — deactivate A2 first, leaving A1 as the ONLY active site."""
    location_a2 = Location.objects.get(tenant=tenant_a, slug='uptown')
    location_a2.is_active = False
    location_a2.save(update_fields=['is_active'])

    response = client_a.post(_url('location_delete', location_a1.pk))
    assert response.status_code == 302
    location_a1.refresh_from_db()
    assert location_a1.is_active is True


def test_delete_already_inactive_is_a_noop_message(client_a, tenant_a, location_a1, location_a2):
    location_a2.is_active = False
    location_a2.save(update_fields=['is_active'])
    response = client_a.post(_url('location_delete', location_a2.pk), follow=True)
    messages_seen = [str(m) for m in response.context['messages']]
    assert any('already inactive' in m for m in messages_seen)


def test_delete_clears_active_location_from_session_when_deactivating_it(client_a, location_a1, location_a2):
    """`client_a` is active at A1 (root fixture default); deactivating A1 must
    drop it from the session rather than leave a stale, now-invalid active id."""
    from apps.accounts.middleware import ACTIVE_LOCATION_SESSION_KEY

    client_a.post(_url('location_delete', location_a1.pk))
    assert client_a.session.get(ACTIVE_LOCATION_SESSION_KEY) is None


def test_delete_csrf_enforced(admin_user, location_a2):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = csrf_client.post(_url('location_delete', location_a2.pk))
    assert response.status_code == 403
    location_a2.refresh_from_db()
    assert location_a2.is_active is True
