"""View tests for sub-module 0.2 — Credential Management.

Both flows require the CURRENT password before anything changes. The email
change writes NOTHING until the confirmation link — sent to the NEW address — is
opened, and the account-takeover tripwire email always goes to the address that
was true BEFORE the change (the old email, for an email change).
"""
import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse

from conftest import DEMO_PASSWORD

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# change_password_view
# --------------------------------------------------------------------------- #

def test_change_password_anonymous_redirects_to_login(client):
    response = client.get(reverse('accounts:change_password'))
    assert response.status_code == 302
    assert response.url.startswith(reverse('accounts:login'))


def test_change_password_requires_the_current_password(client_a):
    response = client_a.post(reverse('accounts:change_password'), {
        'current_password': 'wrong-one',
        'new_password1': 'a-brand-new-pass-9', 'new_password2': 'a-brand-new-pass-9',
    })
    assert response.status_code == 200
    assert 'That is not your current password.' in response.context['form'].errors['current_password']


def test_change_password_success_updates_the_hash(client_a, admin_user):
    response = client_a.post(reverse('accounts:change_password'), {
        'current_password': DEMO_PASSWORD,
        'new_password1': 'a-brand-new-pass-9', 'new_password2': 'a-brand-new-pass-9',
    })
    assert response.status_code == 302
    admin_user.refresh_from_db()
    assert admin_user.check_password('a-brand-new-pass-9')


def test_change_password_keeps_the_current_session_signed_in(client_a):
    """`update_session_auth_hash` must run — otherwise Django's own session auth
    hash check signs this exact request out immediately after succeeding."""
    client_a.post(reverse('accounts:change_password'), {
        'current_password': DEMO_PASSWORD,
        'new_password1': 'a-brand-new-pass-9', 'new_password2': 'a-brand-new-pass-9',
    })
    response = client_a.get(reverse('accounts:dashboard'))
    assert response.status_code == 200


def test_change_password_success_sends_a_notice_email(client_a, admin_user):
    mail.outbox.clear()
    client_a.post(reverse('accounts:change_password'), {
        'current_password': DEMO_PASSWORD,
        'new_password1': 'a-brand-new-pass-9', 'new_password2': 'a-brand-new-pass-9',
    })
    assert len(mail.outbox) == 1
    assert admin_user.email in mail.outbox[0].to


def test_change_password_invalidates_other_sessions(client_a, admin_user):
    """Changing the password rotates the session auth hash — a second, older
    session for the same account must be signed out on its next request."""
    other_session = Client()
    other_session.force_login(admin_user)

    client_a.post(reverse('accounts:change_password'), {
        'current_password': DEMO_PASSWORD,
        'new_password1': 'a-brand-new-pass-9', 'new_password2': 'a-brand-new-pass-9',
    })

    response = other_session.get(reverse('accounts:dashboard'))
    assert response.status_code == 302
    assert response.url.startswith(reverse('accounts:login'))


def test_change_password_csrf_enforced(admin_user):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = csrf_client.post(reverse('accounts:change_password'), {
        'current_password': DEMO_PASSWORD,
        'new_password1': 'a-brand-new-pass-9', 'new_password2': 'a-brand-new-pass-9',
    })
    assert response.status_code == 403
    admin_user.refresh_from_db()
    assert admin_user.check_password(DEMO_PASSWORD)


def test_change_password_throttles_after_repeated_bad_current_passwords(client_a, settings):
    for _ in range(settings.LOGIN_ATTEMPT_LIMIT):
        client_a.post(reverse('accounts:change_password'), {
            'current_password': 'wrong', 'new_password1': 'x', 'new_password2': 'x',
        })
    response = client_a.post(reverse('accounts:change_password'), {
        'current_password': DEMO_PASSWORD,
        'new_password1': 'a-brand-new-pass-9', 'new_password2': 'a-brand-new-pass-9',
    })
    assert 'Too many sign-in attempts' in response.context['form'].non_field_errors()[0]


# --------------------------------------------------------------------------- #
# change_email_request_view — writes nothing, confirms at the new address
# --------------------------------------------------------------------------- #

def test_change_email_request_anonymous_redirects_to_login(client):
    response = client.get(reverse('accounts:change_email'))
    assert response.status_code == 302


def test_change_email_request_requires_the_current_password(client_a):
    response = client_a.post(reverse('accounts:change_email'), {
        'new_email': 'new@acme-test.example', 'current_password': 'wrong',
    })
    assert response.status_code == 200
    assert 'current_password' in response.context['form'].errors


def test_change_email_request_writes_nothing_to_the_user_row(client_a, admin_user):
    original_email = admin_user.email
    client_a.post(reverse('accounts:change_email'), {
        'new_email': 'pending@acme-test.example', 'current_password': DEMO_PASSWORD,
    })
    admin_user.refresh_from_db()
    assert admin_user.email == original_email


def test_change_email_request_sends_the_confirmation_to_the_new_address(client_a):
    mail.outbox.clear()
    client_a.post(reverse('accounts:change_email'), {
        'new_email': 'pending@acme-test.example', 'current_password': DEMO_PASSWORD,
    })
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ['pending@acme-test.example']


def test_change_email_request_csrf_enforced(admin_user):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = csrf_client.post(reverse('accounts:change_email'), {
        'new_email': 'pending@acme-test.example', 'current_password': DEMO_PASSWORD,
    })
    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# email_change_confirm_view
# --------------------------------------------------------------------------- #

def _confirm_link(client, admin_user, new_email='confirmed@acme-test.example'):
    mail.outbox.clear()
    client.post(reverse('accounts:change_email'), {
        'new_email': new_email, 'current_password': DEMO_PASSWORD,
    })
    body = mail.outbox[0].body
    for line in body.splitlines():
        if line.startswith('http'):
            from urllib.parse import urlparse
            return urlparse(line).path
    raise AssertionError('No confirmation URL found in the email body')


def test_email_change_confirm_requires_login(client, tenant_a, admin_user):
    logged_in = Client()
    logged_in.force_login(admin_user)
    url = _confirm_link(logged_in, admin_user)

    anonymous = Client()
    response = anonymous.get(url)
    assert response.status_code == 302
    assert response.url.startswith(reverse('accounts:login'))


def test_email_change_confirm_applies_the_change(client_a, admin_user):
    url = _confirm_link(client_a, admin_user)
    response = client_a.get(url)
    assert response.status_code == 200
    assert response.context['valid'] is True
    admin_user.refresh_from_db()
    assert admin_user.email == 'confirmed@acme-test.example'


def test_email_change_confirm_is_single_use(client_a, admin_user):
    url = _confirm_link(client_a, admin_user)
    client_a.get(url)  # first use — applies
    second = client_a.get(url)  # replay
    assert second.context['valid'] is False


def test_email_change_confirm_rejects_a_token_for_a_different_signed_in_user(client_a, client_b, admin_user, admin_b):
    """The token embeds the uid it was issued for; opening it while signed in as
    someone else must not repoint THAT account's email."""
    url = _confirm_link(client_a, admin_user)
    original_b_email = admin_b.email

    response = client_b.get(url)

    assert response.context['valid'] is False
    admin_b.refresh_from_db()
    assert admin_b.email == original_b_email


def test_email_change_confirm_rechecks_uniqueness_at_apply_time(client_a, tenant_a, admin_user, member_user):
    """Between REQUEST and CONFIRM, someone else in the tenant may have taken the
    address — this must degrade to a friendly `taken` state, not an
    IntegrityError 500."""
    url = _confirm_link(client_a, admin_user, new_email='raced@acme-test.example')

    member_user.email = 'raced@acme-test.example'
    member_user.save(update_fields=['email'])

    response = client_a.get(url)
    assert response.status_code == 200
    assert response.context['valid'] is False
    assert response.context.get('taken') is True


def test_email_change_confirm_sends_the_tripwire_to_the_old_address(client_a, admin_user):
    old_email = admin_user.email
    url = _confirm_link(client_a, admin_user)
    mail.outbox.clear()

    client_a.get(url)

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [old_email]


def test_email_change_confirm_malformed_token_is_handled_gracefully(client_a):
    response = client_a.get(
        reverse('accounts:email_change_confirm', kwargs={'token': 'not-a-real-token'})
    )
    assert response.status_code == 200
    assert response.context['valid'] is False
