"""Form tests for Module 0 — `apps/accounts/forms/`.

Covers the auth forms (0.1/0.2) and the user-directory/profile split (0.3): the
uniform-failure posture of the auth forms is proven at the VIEW level in
`test_auth_views.py` — here the concern is field-level validation, and the
security-critical split between `UserAdminForm` (privileged fields, tier-gated
views only) and `OwnProfileForm` (name/phone only, reachable by everyone).
"""
import pytest
from django.core.exceptions import ValidationError

from apps.accounts.forms import (
    ChangeEmailRequestForm,
    ChangePasswordForm,
    LoginForm,
    OwnProfileForm,
    PasswordResetRequestForm,
    SetNewPasswordForm,
    UserAdminForm,
)
from apps.accounts.models import User

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# LoginForm
# --------------------------------------------------------------------------- #

def test_login_form_requires_all_three_fields():
    form = LoginForm({})
    assert not form.is_valid()
    assert set(form.errors) == {'customer_id', 'identifier', 'password'}


def test_login_form_strips_customer_id_and_identifier():
    form = LoginForm({
        'customer_id': '  ACME-TEST  ',
        'identifier': '  admin@acme-test.example  ',
        'password': 'whatever',
    })
    assert form.is_valid(), form.errors
    assert form.cleaned_data['customer_id'] == 'ACME-TEST'
    assert form.cleaned_data['identifier'] == 'admin@acme-test.example'


def test_login_form_does_not_strip_password():
    form = LoginForm({
        'customer_id': 'ACME-TEST', 'identifier': 'admin@acme-test.example',
        'password': '  pw with spaces  ',
    })
    assert form.is_valid(), form.errors
    assert form.cleaned_data['password'] == '  pw with spaces  '


# --------------------------------------------------------------------------- #
# PasswordResetRequestForm
# --------------------------------------------------------------------------- #

def test_password_reset_request_form_requires_email():
    form = PasswordResetRequestForm({})
    assert not form.is_valid()
    assert 'email' in form.errors


def test_password_reset_request_form_strips_email():
    form = PasswordResetRequestForm({'email': '  someone@example.test  '})
    assert form.is_valid(), form.errors
    assert form.cleaned_data['email'] == 'someone@example.test'


# --------------------------------------------------------------------------- #
# SetNewPasswordForm
# --------------------------------------------------------------------------- #

def test_set_new_password_form_rejects_mismatched_passwords(admin_user):
    form = SetNewPasswordForm(
        {'new_password1': 'a-strong-password-1', 'new_password2': 'a-different-one-1'},
        user=admin_user,
    )
    assert not form.is_valid()
    assert 'The two passwords do not match.' in form.errors['new_password2']


def test_set_new_password_form_rejects_too_short(admin_user):
    form = SetNewPasswordForm({'new_password1': 'short1', 'new_password2': 'short1'}, user=admin_user)
    assert not form.is_valid()
    assert 'new_password1' in form.errors


def test_set_new_password_form_rejects_common_password(admin_user):
    form = SetNewPasswordForm({'new_password1': 'password', 'new_password2': 'password'}, user=admin_user)
    assert not form.is_valid()
    assert 'new_password1' in form.errors


def test_set_new_password_form_rejects_numeric_only_password(admin_user):
    form = SetNewPasswordForm({'new_password1': '19283746', 'new_password2': '19283746'}, user=admin_user)
    assert not form.is_valid()
    assert 'new_password1' in form.errors


def test_set_new_password_form_rejects_password_similar_to_user_attributes(tenant_a):
    user = User.objects.create_user(
        tenant=tenant_a, email='similar@acme-test.example', password='irrelevant-1234',
        first_name='Marguerite', last_name='Okafor',
    )
    form = SetNewPasswordForm({'new_password1': 'Marguerite1', 'new_password2': 'Marguerite1'}, user=user)
    assert not form.is_valid()
    assert 'new_password1' in form.errors


def test_set_new_password_form_saves_and_hashes(admin_user):
    form = SetNewPasswordForm(
        {'new_password1': 'a-brand-new-pass-1', 'new_password2': 'a-brand-new-pass-1'},
        user=admin_user,
    )
    assert form.is_valid(), form.errors
    form.save()
    admin_user.refresh_from_db()
    assert admin_user.check_password('a-brand-new-pass-1')


# --------------------------------------------------------------------------- #
# ChangePasswordForm — current-password gate
# --------------------------------------------------------------------------- #

def test_change_password_form_rejects_wrong_current_password(admin_user):
    form = ChangePasswordForm({
        'current_password': 'totally-wrong',
        'new_password1': 'a-brand-new-pass-1', 'new_password2': 'a-brand-new-pass-1',
    }, user=admin_user)
    assert not form.is_valid()
    assert 'That is not your current password.' in form.errors['current_password']


def test_change_password_form_rejects_same_as_current(admin_user):
    from conftest import DEMO_PASSWORD

    form = ChangePasswordForm({
        'current_password': DEMO_PASSWORD,
        'new_password1': DEMO_PASSWORD, 'new_password2': DEMO_PASSWORD,
    }, user=admin_user)
    assert not form.is_valid()
    assert 'new_password1' in form.errors


def test_change_password_form_succeeds_with_correct_current_password(admin_user):
    from conftest import DEMO_PASSWORD

    form = ChangePasswordForm({
        'current_password': DEMO_PASSWORD,
        'new_password1': 'a-brand-new-pass-2', 'new_password2': 'a-brand-new-pass-2',
    }, user=admin_user)
    assert form.is_valid(), form.errors


# --------------------------------------------------------------------------- #
# ChangeEmailRequestForm
# --------------------------------------------------------------------------- #

def test_change_email_form_rejects_wrong_current_password(admin_user):
    form = ChangeEmailRequestForm({
        'new_email': 'new@acme-test.example', 'current_password': 'wrong',
    }, user=admin_user)
    assert not form.is_valid()
    assert 'current_password' in form.errors


def test_change_email_form_rejects_same_as_current(admin_user):
    from conftest import DEMO_PASSWORD

    form = ChangeEmailRequestForm({
        'new_email': admin_user.email, 'current_password': DEMO_PASSWORD,
    }, user=admin_user)
    assert not form.is_valid()
    assert 'That is already the address on this account.' in form.errors['new_email']


def test_change_email_form_rejects_address_taken_within_the_same_tenant(tenant_a, admin_user, member_user):
    from conftest import DEMO_PASSWORD

    form = ChangeEmailRequestForm({
        'new_email': member_user.email, 'current_password': DEMO_PASSWORD,
    }, user=admin_user)
    assert not form.is_valid()
    assert 'Another user in this business already uses that address.' in form.errors['new_email']


def test_change_email_form_allows_address_used_in_another_tenant(admin_user, admin_b):
    from conftest import DEMO_PASSWORD

    form = ChangeEmailRequestForm({
        'new_email': admin_b.email, 'current_password': DEMO_PASSWORD,
    }, user=admin_user)
    assert form.is_valid(), form.errors


# --------------------------------------------------------------------------- #
# UserAdminForm — the tier-gated management form
# --------------------------------------------------------------------------- #

def test_user_admin_form_meta_fields_exclude_tenant_and_password():
    form = UserAdminForm(tenant=None)
    assert 'tenant' not in form.fields
    assert 'password' not in form.fields
    assert set(form.fields) == {
        'email', 'username', 'first_name', 'last_name', 'full_name',
        'primary_phone', 'tier', 'status', 'is_provider',
    }


def test_user_admin_form_email_required(tenant_a):
    form = UserAdminForm({}, tenant=tenant_a)
    assert not form.is_valid()
    assert 'email' in form.errors


def test_user_admin_form_rejects_duplicate_email_within_tenant(tenant_a, admin_user):
    form = UserAdminForm({
        'email': admin_user.email, 'tier': User.TIER_STAFF, 'status': User.STATUS_ACTIVE,
    }, tenant=tenant_a)
    assert not form.is_valid()
    assert 'Another user in this business already uses that address.' in form.errors['email']


def test_user_admin_form_rejects_duplicate_username_within_tenant(tenant_a, member_user):
    member_user.username = 'frontdesk'
    member_user.save(update_fields=['username'])
    form = UserAdminForm({
        'email': 'new@acme-test.example', 'username': 'frontdesk',
        'tier': User.TIER_STAFF, 'status': User.STATUS_ACTIVE,
    }, tenant=tenant_a)
    assert not form.is_valid()
    assert 'Another user in this business already uses that username.' in form.errors['username']


def test_user_admin_form_blank_username_normalizes_to_none(tenant_a):
    form = UserAdminForm({
        'email': 'blank-username@acme-test.example', 'username': '   ',
        'tier': User.TIER_STAFF, 'status': User.STATUS_ACTIVE,
    }, tenant=tenant_a)
    assert form.is_valid(), form.errors
    assert form.cleaned_data['username'] is None


def test_user_admin_form_two_blank_usernames_do_not_clash(tenant_a, member_user):
    """`member_user` (root fixture) has no username; a second blank-username
    submission must not be treated as a duplicate."""
    form = UserAdminForm({
        'email': 'second-blank@acme-test.example',
        'tier': User.TIER_STAFF, 'status': User.STATUS_ACTIVE,
    }, tenant=tenant_a)
    assert form.is_valid(), form.errors


def test_user_admin_form_save_stamps_the_given_tenant_never_from_posted_data(tenant_a, tenant_b):
    form = UserAdminForm({
        'email': 'stamped@acme-test.example', 'tier': User.TIER_STAFF, 'status': User.STATUS_ACTIVE,
        # 'tenant' is not a real field on this form — posting one must be inert.
        'tenant': tenant_b.pk,
    }, tenant=tenant_a)
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.tenant_id == tenant_a.pk


def test_user_admin_form_editing_excludes_self_from_the_duplicate_check(tenant_a, admin_user):
    form = UserAdminForm({
        'email': admin_user.email, 'tier': admin_user.tier, 'status': admin_user.status,
    }, instance=admin_user, tenant=tenant_a)
    assert form.is_valid(), form.errors


# --------------------------------------------------------------------------- #
# OwnProfileForm — no privileged field reachable
# --------------------------------------------------------------------------- #

def test_own_profile_form_excludes_privileged_fields():
    form = OwnProfileForm(tenant=None)
    assert set(form.fields) == {'first_name', 'last_name', 'full_name', 'primary_phone'}
    for privileged in ('tier', 'status', 'is_provider', 'email', 'username'):
        assert privileged not in form.fields


def test_own_profile_form_ignores_a_smuggled_tier_field(tenant_a, member_user):
    form = OwnProfileForm({
        'first_name': 'Sam', 'last_name': 'Staff', 'full_name': '', 'primary_phone': '',
        'tier': User.TIER_OWNER,  # not a bound field — must be silently ignored
    }, instance=member_user, tenant=tenant_a)
    assert form.is_valid(), form.errors
    obj = form.save()
    obj.refresh_from_db()
    assert obj.tier == User.TIER_STAFF
