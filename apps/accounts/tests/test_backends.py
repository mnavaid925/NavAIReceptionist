"""Direct unit tests for `apps/accounts/backends.py`.

Most of `CustomerScopedBackend`'s behaviour is already exercised end-to-end
through `login_view` in `test_auth_views.py`; this file covers the paths that
view never reaches — the tenant-less `/admin/` staff path, `get_user()`, and
calling `authenticate()` directly with no request object at all.
"""
import pytest
from django.contrib.auth import authenticate

from apps.accounts.backends import CustomerScopedBackend
from apps.accounts.models import User

from conftest import DEMO_PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture
def backend():
    return CustomerScopedBackend()


# --------------------------------------------------------------------------- #
# Tenant-scoped path
# --------------------------------------------------------------------------- #

def test_authenticate_by_email_succeeds(backend, tenant_a, admin_user):
    user = backend.authenticate(
        None, customer_id=tenant_a.customer_id, identifier=admin_user.email, password=DEMO_PASSWORD,
    )
    assert user == admin_user


def test_authenticate_by_username_succeeds(backend, tenant_a, member_user):
    member_user.username = 'frontdesk-be'
    member_user.save(update_fields=['username'])
    user = backend.authenticate(
        None, customer_id=tenant_a.customer_id, identifier='frontdesk-be', password=DEMO_PASSWORD,
    )
    assert user == member_user


def test_authenticate_works_without_a_request_object(backend, tenant_a, admin_user):
    """Every failure/throttle path reads `request` defensively — `None` must
    not raise."""
    user = backend.authenticate(
        None, customer_id=tenant_a.customer_id, identifier=admin_user.email, password='wrong',
    )
    assert user is None


def test_authenticate_unknown_customer_id_returns_none(backend, admin_user):
    assert backend.authenticate(
        None, customer_id='NOPE', identifier=admin_user.email, password=DEMO_PASSWORD,
    ) is None


def test_authenticate_blank_customer_id_returns_none(backend, admin_user):
    assert backend.authenticate(
        None, customer_id='', identifier=admin_user.email, password=DEMO_PASSWORD,
    ) is None


def test_authenticate_inactive_tenant_returns_none(backend, tenant_a, admin_user):
    tenant_a.is_active = False
    tenant_a.save(update_fields=['is_active'])
    assert backend.authenticate(
        None, customer_id=tenant_a.customer_id, identifier=admin_user.email, password=DEMO_PASSWORD,
    ) is None


def test_authenticate_suspended_user_returns_none(backend, tenant_a, admin_user):
    admin_user.status = User.STATUS_SUSPENDED
    admin_user.save(update_fields=['status'])
    assert backend.authenticate(
        None, customer_id=tenant_a.customer_id, identifier=admin_user.email, password=DEMO_PASSWORD,
    ) is None


def test_authenticate_via_django_dispatches_to_this_backend(tenant_a, admin_user):
    """`AUTHENTICATION_BACKENDS` names only this backend — going through
    Django's `authenticate()` shim must resolve here."""
    user = authenticate(
        customer_id=tenant_a.customer_id, identifier=admin_user.email, password=DEMO_PASSWORD,
    )
    assert user == admin_user


# --------------------------------------------------------------------------- #
# Tenant-less platform-staff path (/admin/)
# --------------------------------------------------------------------------- #

def test_platform_staff_path_authenticates_a_tenantless_superuser(backend):
    superuser = User.objects.create_superuser(email='root-be@platform.example', password='pw12345678')
    user = backend.authenticate(None, username=superuser.email, password='pw12345678')
    assert user == superuser


def test_platform_staff_path_rejects_a_tenant_user(backend, admin_user):
    """A tenant user must not be reachable through the tenant-less /admin/ path,
    even with a correct password."""
    user = backend.authenticate(None, username=admin_user.email, password=DEMO_PASSWORD)
    assert user is None


def test_platform_staff_path_rejects_wrong_password(backend):
    User.objects.create_superuser(email='root-be2@platform.example', password='pw12345678')
    user = backend.authenticate(None, username='root-be2@platform.example', password='wrong')
    assert user is None


def test_platform_staff_path_rejects_inactive_superuser(backend):
    superuser = User.objects.create_superuser(
        email='root-be3@platform.example', password='pw12345678', status=User.STATUS_SUSPENDED,
    )
    user = backend.authenticate(None, username=superuser.email, password='pw12345678')
    assert user is None


def test_platform_staff_path_rejects_unknown_email(backend):
    assert backend.authenticate(None, username='ghost@platform.example', password='whatever') is None


# --------------------------------------------------------------------------- #
# get_user()
# --------------------------------------------------------------------------- #

def test_get_user_returns_the_matching_user(backend, admin_user):
    assert backend.get_user(admin_user.pk) == admin_user


def test_get_user_returns_none_for_an_unknown_pk(backend):
    assert backend.get_user(999999) is None
