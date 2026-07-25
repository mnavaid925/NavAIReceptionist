"""View tests for sub-module 1.1 — Business Settings.

There is exactly one `tenants.Tenant` row per business and `request.tenant` IS
it, so there is no pk anywhere in this sub-module's URLs — a user can only ever
read/edit their OWN tenant, never another one's, by construction. The read view
is open to any signed-in tier; the edit view is owner-only.
"""
import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _url(name):
    return reverse(f'tenants:{name}')


# --------------------------------------------------------------------------- #
# business_settings_view — read
# --------------------------------------------------------------------------- #

def test_business_settings_anonymous_redirects_to_login(client):
    response = client.get(_url('business_settings'))
    assert response.status_code == 302


def test_business_settings_renders_for_owner(client_a, tenant_a):
    response = client_a.get(_url('business_settings'))
    assert response.status_code == 200
    assert 'tenants/business/detail.html' in [t.name for t in response.templates]
    assert response.context['tenant'] == tenant_a


def test_business_settings_open_to_staff_tier_readonly(member_client):
    """Any signed-in tier may READ the business record — knowing the Customer ID
    matters because it is the first field on the sign-in form."""
    response = member_client.get(_url('business_settings'))
    assert response.status_code == 200
    assert response.context['can_edit'] is False


def test_business_settings_can_edit_true_for_owner(client_a):
    response = client_a.get(_url('business_settings'))
    assert response.context['can_edit'] is True


def test_business_settings_can_edit_false_for_manager(manager_client):
    response = manager_client.get(_url('business_settings'))
    assert response.context['can_edit'] is False


def test_business_settings_location_counts_are_tenant_scoped(client_a, location_a1, location_a2, tenant_b, location_b1):
    response = client_a.get(_url('business_settings'))
    assert response.context['location_count'] == 2
    assert response.context['active_location_count'] == 2


def test_business_settings_shows_own_tenant_only_never_anothers(client_a, client_b, tenant_a, tenant_b):
    response_a = client_a.get(_url('business_settings'))
    response_b = client_b.get(_url('business_settings'))
    assert response_a.context['tenant'] == tenant_a
    assert response_b.context['tenant'] == tenant_b
    assert response_a.context['tenant'] != response_b.context['tenant']


def test_business_settings_no_tenant_for_platform_superuser(db):
    from apps.accounts.models import User

    superuser = User.objects.create_superuser(email='root-biz@platform.example', password='pw12345678')
    client = Client()
    client.force_login(superuser)
    response = client.get(_url('business_settings'))
    assert response.status_code == 200
    assert response.context['tenant'] is None


# --------------------------------------------------------------------------- #
# business_settings_edit_view — owner-only, tenant-implicit
# --------------------------------------------------------------------------- #

def test_business_settings_edit_anonymous_redirects_to_login(client):
    response = client.get(_url('business_settings_edit'))
    assert response.status_code == 302


def test_business_settings_edit_blocks_staff_tier(member_client):
    response = member_client.get(_url('business_settings_edit'))
    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')


def test_business_settings_edit_blocks_manager_tier(manager_client):
    """Owner-only, deliberately narrower than `MANAGEMENT_TIERS` — these values
    are spoken to callers and inherited by every new location."""
    response = manager_client.get(_url('business_settings_edit'))
    assert response.status_code == 302


def test_business_settings_edit_get_renders_form_for_owner(client_a):
    response = client_a.get(_url('business_settings_edit'))
    assert response.status_code == 200
    assert 'tenants/business/form.html' in [t.name for t in response.templates]


def test_business_settings_edit_updates_own_tenant(client_a, tenant_a):
    response = client_a.post(_url('business_settings_edit'), {
        'name': 'Acme Corp Renamed', 'timezone': 'America/Chicago',
    })
    assert response.status_code == 302
    tenant_a.refresh_from_db()
    assert tenant_a.name == 'Acme Corp Renamed'
    assert tenant_a.timezone == 'America/Chicago'


def test_business_settings_edit_never_touches_another_tenant(client_a, tenant_a, tenant_b):
    """There is no pk in this URL — `instance` is always `request.tenant`, which
    is exactly what makes editing another business unreachable here."""
    original_b_name = tenant_b.name
    client_a.post(_url('business_settings_edit'), {
        'name': 'Should Only Affect A', 'timezone': 'UTC',
    })
    tenant_b.refresh_from_db()
    assert tenant_b.name == original_b_name


def test_business_settings_edit_cannot_smuggle_customer_id_or_slug(client_a, tenant_a):
    """`customer_id`/`slug`/`is_active` are not form fields — posting them must
    be silently ignored, per the form's own docstring."""
    original_customer_id = tenant_a.customer_id
    original_slug = tenant_a.slug
    client_a.post(_url('business_settings_edit'), {
        'name': 'Renamed Again', 'timezone': 'UTC',
        'customer_id': 'HACKED-ID', 'slug': 'hacked-slug', 'is_active': 'false',
    })
    tenant_a.refresh_from_db()
    assert tenant_a.customer_id == original_customer_id
    assert tenant_a.slug == original_slug
    assert tenant_a.is_active is True


def test_business_settings_edit_requires_a_name(client_a, tenant_a):
    original_name = tenant_a.name
    response = client_a.post(_url('business_settings_edit'), {'name': '', 'timezone': 'UTC'})
    assert response.status_code == 200
    tenant_a.refresh_from_db()
    assert tenant_a.name == original_name


def test_business_settings_edit_csrf_enforced(admin_user, tenant_a):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = csrf_client.post(_url('business_settings_edit'), {
        'name': 'Should Not Save', 'timezone': 'UTC',
    })
    assert response.status_code == 403
    tenant_a.refresh_from_db()
    assert tenant_a.name != 'Should Not Save'


def test_business_settings_edit_get_is_a_noop_for_platform_superuser(db):
    from apps.accounts.models import User

    superuser = User.objects.create_superuser(email='root-biz-edit@platform.example', password='pw12345678')
    client = Client()
    client.force_login(superuser)
    response = client.get(_url('business_settings_edit'), follow=True)
    assert response.status_code == 200
    assert response.redirect_chain
