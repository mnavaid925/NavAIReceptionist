"""Model tests for `accounts.User` and `accounts.UserLocation`.

Covers the auth surface (`is_active`, display helpers), the two unique
constraints that carry the tenant-isolation design (`(tenant, email)` and
`(tenant, username)`, with NULL usernames deliberately non-colliding), and
`assigned_locations()` — the queryset the whole active-location switcher
authorizes against.
"""
from unittest.mock import PropertyMock, patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts.models import User, UserLocation
from apps.tenants.models import Location

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# UserManager
# --------------------------------------------------------------------------- #

def test_create_user_defaults(tenant_a):
    user = User.objects.create_user(tenant=tenant_a, email='plain@acme-test.example', password='pw12345678')
    assert user.tier == User.TIER_STAFF
    assert user.status == User.STATUS_ACTIVE
    assert user.is_staff is False
    assert user.is_superuser is False
    assert user.tenant_id == tenant_a.pk


def test_create_user_without_email_raises(tenant_a):
    with pytest.raises(ValueError):
        User.objects.create_user(tenant=tenant_a, email='', password='pw12345678')


def test_create_user_normalizes_email_domain(tenant_a):
    user = User.objects.create_user(tenant=tenant_a, email='Weird@ACME-TEST.EXAMPLE', password='pw12345678')
    assert user.email == 'Weird@acme-test.example'


def test_create_user_blank_username_stored_as_null(tenant_a):
    user = User.objects.create_user(tenant=tenant_a, email='nouser@acme-test.example', password='pw12345678', username='')
    assert user.username is None


def test_create_superuser_has_no_tenant(db):
    user = User.objects.create_superuser(email='root@platform.example', password='pw12345678')
    assert user.tenant_id is None
    assert user.is_staff is True
    assert user.is_superuser is True
    assert user.tier == User.TIER_OWNER


# --------------------------------------------------------------------------- #
# Unique constraints
# --------------------------------------------------------------------------- #

def test_email_unique_within_a_tenant_at_the_db_level(tenant_a):
    """Bypass `UserManager._create()` (which runs `full_clean()` first) so the
    underlying `UniqueConstraint` itself is what's being proven here.
    """
    User.objects.create(tenant=tenant_a, email='dup-db@acme-test.example', password='x')
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            User.objects.create(tenant=tenant_a, email='dup-db@acme-test.example', password='x')


def test_create_user_surfaces_a_duplicate_email_as_a_validation_error(tenant_a):
    """The path every real view uses (`create_user`) runs `full_clean()` before
    saving, so a duplicate surfaces as a friendly `ValidationError` rather than a
    raw `IntegrityError` bubbling out of the database.
    """
    User.objects.create_user(tenant=tenant_a, email='dup@acme-test.example', password='pw12345678')
    with pytest.raises(ValidationError):
        User.objects.create_user(tenant=tenant_a, email='dup@acme-test.example', password='pw12345678')


def test_same_email_allowed_across_different_tenants(tenant_a, tenant_b):
    User.objects.create_user(tenant=tenant_a, email='shared@example.test', password='pw12345678')
    # Must not raise: (tenant, email) is the unique pair, not email alone.
    User.objects.create_user(tenant=tenant_b, email='shared@example.test', password='pw12345678')


def test_username_unique_within_a_tenant_at_the_db_level(tenant_a):
    User.objects.create(tenant=tenant_a, email='u1db@acme-test.example', password='x', username='frontdesk')
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            User.objects.create(tenant=tenant_a, email='u2db@acme-test.example', password='x', username='frontdesk')


def test_create_user_surfaces_a_duplicate_username_as_a_validation_error(tenant_a):
    User.objects.create_user(tenant=tenant_a, email='u1@acme-test.example', password='pw12345678', username='frontdesk')
    with pytest.raises(ValidationError):
        User.objects.create_user(tenant=tenant_a, email='u2@acme-test.example', password='pw12345678', username='frontdesk')


def test_multiple_null_usernames_do_not_collide(tenant_a):
    """A plain unique index treats NULLs as distinct — this is what lets any
    number of users skip a username entirely.
    """
    User.objects.create_user(tenant=tenant_a, email='u1@acme-test.example', password='pw12345678')
    # Must not raise.
    User.objects.create_user(tenant=tenant_a, email='u2@acme-test.example', password='pw12345678')


# --------------------------------------------------------------------------- #
# Normalisation on save()
# --------------------------------------------------------------------------- #

def test_full_name_derived_from_first_and_last_when_blank(tenant_a):
    user = User.objects.create_user(
        tenant=tenant_a, email='derived@acme-test.example', password='pw12345678',
        first_name='Priya', last_name='Raman',
    )
    assert user.full_name == 'Priya Raman'


def test_explicit_full_name_is_preserved(tenant_a):
    user = User.objects.create_user(
        tenant=tenant_a, email='explicit@acme-test.example', password='pw12345678',
        first_name='Priya', last_name='Raman', full_name='Dr. Priya Raman',
    )
    assert user.full_name == 'Dr. Priya Raman'


def test_save_normalizes_blank_username_to_none_even_outside_the_manager(tenant_a):
    user = User.objects.create_user(tenant=tenant_a, email='savepath@acme-test.example', password='pw12345678')
    user.username = '   '
    user.save()
    user.refresh_from_db()
    assert user.username is None


# --------------------------------------------------------------------------- #
# Auth surface
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('status, expected', [
    (User.STATUS_ACTIVE, True),
    (User.STATUS_INACTIVE, False),
    (User.STATUS_SUSPENDED, False),
])
def test_is_active_mirrors_status(tenant_a, status, expected):
    user = User.objects.create_user(tenant=tenant_a, email=f'{status}@acme-test.example', password='pw12345678', status=status)
    assert user.is_active is expected


# --------------------------------------------------------------------------- #
# Display helpers
# --------------------------------------------------------------------------- #

def test_str_uses_display_name(admin_user):
    assert str(admin_user) == admin_user.display_name


def test_display_name_prefers_full_name(tenant_a):
    user = User.objects.create_user(
        tenant=tenant_a, email='fn@acme-test.example', password='pw12345678',
        first_name='Ada', last_name='Lovelace', username='ada',
    )
    assert user.display_name == 'Ada Lovelace'


def test_display_name_falls_back_to_the_username_field_when_no_name(tenant_a):
    """REGRESSION GUARD.

    `display_name` used to fall back to `self.get_username()`, which is
    `AbstractBaseUser.get_username()` — `getattr(self, USERNAME_FIELD)`. Since
    `USERNAME_FIELD = 'email'`, that always returned the email address and the
    model's own `username` handle was unreachable, so a user with a username but
    no name showed their email in the topbar and the user directory. The property
    now reads `self.username` directly.
    """
    user = User.objects.create_user(tenant=tenant_a, email='un@acme-test.example', password='pw12345678', username='handle')
    assert user.display_name == 'handle'


def test_display_name_falls_back_to_email_when_nothing_else(tenant_a):
    user = User.objects.create_user(tenant=tenant_a, email='onlyemail@acme-test.example', password='pw12345678')
    assert user.display_name == 'onlyemail@acme-test.example'


@pytest.mark.parametrize('first, last, expected', [
    ('Ada', 'Lovelace', 'AL'),
    ('Cher', '', 'CH'),
])
def test_initials_from_two_and_one_word_names(tenant_a, first, last, expected):
    user = User.objects.create_user(
        tenant=tenant_a, email=f'{first or "none"}{last or "none"}@acme-test.example',
        password='pw12345678', first_name=first, last_name=last,
    )
    assert user.initials == expected


def test_initials_falls_back_to_question_mark_when_display_name_is_blank(tenant_a):
    """`display_name` can never actually be blank in practice (email is
    required), so this exercises the `?` branch directly rather than relying on
    an unreachable real-world path.
    """
    user = User(tenant=tenant_a, email='blank-dn@acme-test.example')
    with patch.object(User, 'display_name', new_callable=PropertyMock, return_value=''):
        assert user.initials == '?'


# --------------------------------------------------------------------------- #
# assigned_locations() — the switcher's authorization boundary
# --------------------------------------------------------------------------- #

def test_assigned_locations_returns_only_assigned_active_locations(admin_user, location_a1, location_a2):
    result = set(admin_user.assigned_locations())
    assert result == {location_a1, location_a2}


def test_assigned_locations_excludes_locations_with_no_userlocation_row(member_user, location_a2):
    """`member_user` (root fixture) is assigned only to A1."""
    assert location_a2 not in set(member_user.assigned_locations())


def test_assigned_locations_excludes_deactivated_locations(tenant_a, member_user, location_a2_inactive):
    UserLocation.objects.create(tenant=tenant_a, user=member_user, location=location_a2_inactive)
    assert location_a2_inactive not in set(member_user.assigned_locations())


def test_assigned_locations_is_empty_for_a_tenantless_user(db):
    superuser = User.objects.create_superuser(email='root-al@platform.example', password='pw12345678')
    assert list(superuser.assigned_locations()) == []


def test_assigned_locations_never_crosses_tenants(admin_user, admin_b, location_b1):
    """Even if somehow a `UserLocation` pointed cross-tenant, the queryset
    itself is filtered by `tenant_id=self.tenant_id` as a second guard."""
    assert location_b1 not in set(admin_user.assigned_locations())


# --------------------------------------------------------------------------- #
# effective_inactivity_timeout
# --------------------------------------------------------------------------- #

def test_effective_inactivity_timeout_falls_back_to_setting(tenant_a, settings):
    settings.DEFAULT_INACTIVITY_TIMEOUT_MINUTES = 42
    user = User.objects.create_user(tenant=tenant_a, email='timeout@acme-test.example', password='pw12345678')
    assert user.effective_inactivity_timeout == 42


def test_effective_inactivity_timeout_uses_explicit_value(tenant_a):
    user = User.objects.create_user(
        tenant=tenant_a, email='timeout2@acme-test.example', password='pw12345678', inactivity_timeout=15,
    )
    assert user.effective_inactivity_timeout == 15


# --------------------------------------------------------------------------- #
# UserLocation
# --------------------------------------------------------------------------- #

def test_userlocation_str(admin_user, location_a1):
    ul = UserLocation.objects.get(user=admin_user, location=location_a1)
    assert str(ul) == f'{admin_user} @ {location_a1}'


def test_userlocation_unique_together(tenant_a, member_user, location_a1):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            UserLocation.objects.create(tenant=tenant_a, user=member_user, location=location_a1)


def test_userlocation_clean_rejects_cross_tenant_assignment(tenant_a, member_user, location_b1):
    ul = UserLocation(tenant=tenant_a, user=member_user, location=location_b1)
    with pytest.raises(Exception):
        ul.full_clean()


def test_userlocation_cascades_on_user_delete(tenant_a, location_a1):
    user = User.objects.create_user(tenant=tenant_a, email='cascade@acme-test.example', password='pw12345678')
    ul = UserLocation.objects.create(tenant=tenant_a, user=user, location=location_a1)
    user.delete()
    assert not UserLocation.objects.filter(pk=ul.pk).exists()


def test_userlocation_cascades_on_location_delete(tenant_a):
    location = Location.objects.create(tenant=tenant_a, name='Temp', slug='temp-cascade')
    user = User.objects.create_user(tenant=tenant_a, email='cascade2@acme-test.example', password='pw12345678')
    ul = UserLocation.objects.create(tenant=tenant_a, user=user, location=location)
    location.delete()
    assert not UserLocation.objects.filter(pk=ul.pk).exists()
