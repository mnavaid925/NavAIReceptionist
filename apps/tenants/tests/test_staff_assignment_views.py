"""View tests for sub-module 1.3 — Staff & Location Assignment.

The assignment matrix writes `accounts.UserLocation` — the exact row
`ActiveLocationMiddleware` re-validates on every request and
`switch_location_view` filters a posted id through — so a forged pair naming
another business's user or location must match nothing and be silently dropped,
never written.
"""
import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import UserLocation

pytestmark = pytest.mark.django_db


def _url(name, *args):
    return reverse(f'tenants:{name}', args=args)


# --------------------------------------------------------------------------- #
# staff_locations_view — auth / tier gate
# --------------------------------------------------------------------------- #

def test_matrix_anonymous_redirects_to_login(client):
    response = client.get(_url('staff_locations'))
    assert response.status_code == 302


def test_matrix_blocks_staff_tier(member_client):
    response = member_client.get(_url('staff_locations'))
    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')


def test_matrix_open_to_owner(client_a):
    response = client_a.get(_url('staff_locations'))
    assert response.status_code == 200
    assert 'tenants/staff/matrix.html' in [t.name for t in response.templates]


def test_matrix_open_to_manager(manager_client):
    response = manager_client.get(_url('staff_locations'))
    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# staff_locations_view GET — tenant scoping, matrix shape
# --------------------------------------------------------------------------- #

def test_matrix_rows_are_tenant_scoped_users_only(client_a, admin_user, admin_b):
    response = client_a.get(_url('staff_locations'))
    row_users = [row['user'] for row in response.context['rows']]
    assert admin_user in row_users
    assert admin_b not in row_users


def test_matrix_columns_are_tenant_scoped_active_locations_only(client_a, location_a1, location_a2, location_b1):
    response = client_a.get(_url('staff_locations'))
    locations = list(response.context['locations'])
    assert location_a1 in locations
    assert location_a2 in locations
    assert location_b1 not in locations


def test_matrix_columns_exclude_inactive_locations(client_a, tenant_a):
    from apps.tenants.models import Location

    inactive = Location.objects.create(tenant=tenant_a, name='Closed', slug='closed', is_active=False)
    response = client_a.get(_url('staff_locations'))
    assert inactive not in list(response.context['locations'])


def test_matrix_marks_existing_assignments_as_checked(client_a, admin_user, location_a1, location_a2):
    response = client_a.get(_url('staff_locations'))
    row = next(r for r in response.context['rows'] if r['user'] == admin_user)
    checked_locations = {cell['location'] for cell in row['cells'] if cell['checked']}
    assert checked_locations == {location_a1, location_a2}


def test_matrix_highlight_user_from_query_string(client_a, admin_user):
    response = client_a.get(_url('staff_locations'), {'user': str(admin_user.pk)})
    assert response.context['highlight_user'] == admin_user.pk


def test_matrix_highlight_location_from_query_string(client_a, location_a2):
    response = client_a.get(_url('staff_locations'), {'location': str(location_a2.pk)})
    assert response.context['highlight_location'] == location_a2.pk


def test_matrix_junk_highlight_params_degrade_to_none_not_500(client_a):
    response = client_a.get(_url('staff_locations'), {'user': 'abc', 'location': 'xyz'})
    assert response.status_code == 200
    assert response.context['highlight_user'] is None
    assert response.context['highlight_location'] is None


# --------------------------------------------------------------------------- #
# staff_locations_view POST — legitimate assignment changes
# --------------------------------------------------------------------------- #

def test_post_adds_a_new_assignment(client_a, tenant_a, admin_user, member_user, location_a1, location_a2):
    """`member_user` (root fixture) is assigned only to A1; assign them to A2 too.

    The matrix posts the FULL checked set, not a diff — every box that should
    stay checked must be submitted, or it reads as "unchecked" and gets removed
    (proven separately by `test_post_removes_an_assignment_when_another_remains`).
    """
    assert not UserLocation.objects.filter(user=member_user, location=location_a2).exists()
    response = client_a.post(_url('staff_locations'), {
        'assign': [
            f'{admin_user.pk}:{location_a1.pk}',
            f'{admin_user.pk}:{location_a2.pk}',
            f'{member_user.pk}:{location_a1.pk}',
            f'{member_user.pk}:{location_a2.pk}',
        ],
    })
    assert response.status_code == 302
    assert UserLocation.objects.filter(tenant=tenant_a, user=member_user, location=location_a2).exists()


def test_post_removes_an_assignment_when_another_remains(client_a, tenant_a, admin_user, location_a1, location_a2):
    """`admin_user` is assigned to BOTH A1 and A2 (root fixture) — removing A2
    from the submission leaves them with A1, so no stranding guard fires."""
    response = client_a.post(_url('staff_locations'), {
        'assign': [f'{admin_user.pk}:{location_a1.pk}'],
    })
    assert response.status_code == 302
    assert not UserLocation.objects.filter(user=admin_user, location=location_a2).exists()
    assert UserLocation.objects.filter(user=admin_user, location=location_a1).exists()


def test_post_with_no_checkboxes_at_all_leaves_the_sole_owner_untouched_pending_confirm(client_a, admin_user, location_a1, location_a2):
    """Submitting nothing checked would strand `admin_user` at zero locations —
    the confirm guard must intercept before any row is deleted."""
    response = client_a.post(_url('staff_locations'), {})
    assert response.status_code == 302
    assert UserLocation.objects.filter(user=admin_user, location=location_a1).exists()
    assert UserLocation.objects.filter(user=admin_user, location=location_a2).exists()


def test_post_confirm_flag_allows_stranding_after_warning(client_a, admin_user, location_a1, location_a2, member_user):
    """With `confirm=1`, the guard is bypassed and the removal actually applies.

    (`admin_user` ends up with zero UserLocation rows — a business decision the
    matrix explicitly allows once confirmed; the middleware then simply resolves
    `request.location` to None on their next request.)
    """
    response = client_a.post(_url('staff_locations'), {
        'assign': [f'{member_user.pk}:{location_a1.pk}'],
        'confirm': '1',
    })
    assert response.status_code == 302
    assert not UserLocation.objects.filter(user=admin_user).exists()


# --------------------------------------------------------------------------- #
# staff_locations_view POST — cross-tenant forgery is rejected
# --------------------------------------------------------------------------- #

def test_post_forged_pair_naming_another_tenants_user_is_dropped(client_a, tenant_a, location_a1, admin_b):
    """`admin_b` belongs to tenant B — a pair naming them must match nothing in
    tenant A's own queryset and be silently ignored, never written."""
    response = client_a.post(_url('staff_locations'), {
        'assign': [f'{admin_b.pk}:{location_a1.pk}'],
    })
    assert response.status_code == 302
    assert not UserLocation.objects.filter(user=admin_b, location=location_a1).exists()
    assert not UserLocation.objects.filter(tenant=tenant_a, user_id=admin_b.pk).exists()


def test_post_forged_pair_naming_another_tenants_location_is_dropped(client_a, member_user, location_b1):
    """`location_b1` belongs to tenant B — assigning tenant A's own user to it
    must be rejected, not silently create a cross-tenant UserLocation row."""
    response = client_a.post(_url('staff_locations'), {
        'assign': [f'{member_user.pk}:{location_b1.pk}'],
    })
    assert response.status_code == 302
    assert not UserLocation.objects.filter(user=member_user, location=location_b1).exists()


def test_post_forged_pair_naming_both_a_foreign_user_and_location_is_dropped(
    client_a, tenant_a, admin_user, location_a1, admin_b, location_b1,
):
    """`admin_b`/`location_b1` are both tenant B's own (root fixture already
    assigns `admin_b` there) — the point is that tenant A's matrix POST must
    leave that row exactly as it was, never touch it."""
    before = UserLocation.objects.filter(location=location_b1).count()
    response = client_a.post(_url('staff_locations'), {
        'assign': [f'{admin_user.pk}:{location_a1.pk}', f'{admin_b.pk}:{location_b1.pk}'],
    })
    assert response.status_code == 302
    after = UserLocation.objects.filter(location=location_b1).count()
    assert after == before
    assert not UserLocation.objects.filter(tenant=tenant_a, user_id=admin_b.pk).exists()


def test_post_malformed_pair_is_ignored_not_500(client_a):
    response = client_a.post(_url('staff_locations'), {'assign': ['not-a-valid-pair', '1:2:3', 'abc:def']})
    assert response.status_code == 302


def test_post_csrf_enforced(admin_user, member_user, location_a2):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = csrf_client.post(_url('staff_locations'), {
        'assign': [f'{member_user.pk}:{location_a2.pk}'],
    })
    assert response.status_code == 403
    assert not UserLocation.objects.filter(user=member_user, location=location_a2).exists()


def test_matrix_post_blocks_staff_tier(member_client, member_user, location_a2):
    response = member_client.post(_url('staff_locations'), {
        'assign': [f'{member_user.pk}:{location_a2.pk}'],
    })
    assert response.status_code == 302
    assert not UserLocation.objects.filter(user=member_user, location=location_a2).exists()


# --------------------------------------------------------------------------- #
# toggle_provider_view
# --------------------------------------------------------------------------- #

def test_toggle_provider_flips_the_flag(client_a, member_user):
    assert member_user.is_provider is False
    response = client_a.post(_url('toggle_provider', member_user.pk))
    assert response.status_code == 302
    member_user.refresh_from_db()
    assert member_user.is_provider is True


def test_toggle_provider_get_is_405(client_a, member_user):
    response = client_a.get(_url('toggle_provider', member_user.pk))
    assert response.status_code == 405
    member_user.refresh_from_db()
    assert member_user.is_provider is False


def test_toggle_provider_blocks_staff_tier(member_client, member_user):
    response = member_client.post(_url('toggle_provider', member_user.pk))
    assert response.status_code == 302
    member_user.refresh_from_db()
    assert member_user.is_provider is False


def test_toggle_provider_cross_tenant_pk_is_404(client_a, admin_b):
    response = client_a.post(_url('toggle_provider', admin_b.pk))
    assert response.status_code == 404
    admin_b.refresh_from_db()
    assert admin_b.is_provider is False


def test_toggle_provider_csrf_enforced(admin_user, member_user):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = csrf_client.post(_url('toggle_provider', member_user.pk))
    assert response.status_code == 403
    member_user.refresh_from_db()
    assert member_user.is_provider is False
