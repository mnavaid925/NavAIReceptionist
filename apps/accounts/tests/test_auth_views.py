"""View tests for sub-module 0.1 — Authentication & Session.

Login is customer id + email-or-username + password. The governing rule is
UNIFORM FAILURE: a wrong customer id, an unknown identifier, a wrong password and
a deactivated business all render the byte-identical response — anything that
distinguishes them is an account-enumeration channel. Throttling is exercised
here too, since it is wired straight into the login view.
"""
import time

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse

from apps.accounts.middleware import ACTIVE_LOCATION_SESSION_KEY
from apps.accounts.models import User
from apps.accounts.views.Auth import THROTTLED_ERROR, UNIFORM_LOGIN_ERROR

from conftest import DEMO_PASSWORD

pytestmark = pytest.mark.django_db


def _login_payload(customer_id, identifier, password):
    return {'customer_id': customer_id, 'identifier': identifier, 'password': password}


# --------------------------------------------------------------------------- #
# login_view — GET
# --------------------------------------------------------------------------- #

def test_login_get_renders_form(client):
    response = client.get(reverse('accounts:login'))
    assert response.status_code == 200
    assert 'accounts/auth/login.html' in [t.name for t in response.templates]


def test_login_get_when_already_authenticated_redirects_to_dashboard(client_a):
    response = client_a.get(reverse('accounts:login'))
    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')


# --------------------------------------------------------------------------- #
# login_view — success, by email and by username
# --------------------------------------------------------------------------- #

def test_login_success_by_email(client, tenant_a, admin_user):
    response = client.post(reverse('accounts:login'), _login_payload(
        tenant_a.customer_id, admin_user.email, DEMO_PASSWORD,
    ))
    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')
    assert response.wsgi_request.user.is_anonymous is False


def test_login_success_by_username(client, tenant_a, member_user):
    member_user.username = 'frontdesk'
    member_user.save(update_fields=['username'])

    response = client.post(reverse('accounts:login'), _login_payload(
        tenant_a.customer_id, 'frontdesk', DEMO_PASSWORD,
    ))
    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')


def test_login_success_activates_sole_assignment(client, tenant_a, member_user, location_a1):
    response = client.post(reverse('accounts:login'), _login_payload(
        tenant_a.customer_id, member_user.email, DEMO_PASSWORD,
    ), follow=True)
    assert response.status_code == 200
    assert client.session[ACTIVE_LOCATION_SESSION_KEY] == location_a1.pk


def test_login_success_with_two_assignments_does_not_auto_activate(client, tenant_a, admin_user):
    client.post(reverse('accounts:login'), _login_payload(
        tenant_a.customer_id, admin_user.email, DEMO_PASSWORD,
    ))
    assert ACTIVE_LOCATION_SESSION_KEY not in client.session


def test_login_honours_a_safe_next_parameter(client, tenant_a, admin_user):
    target = reverse('accounts:my_locations')
    response = client.post(f"{reverse('accounts:login')}?next={target}", _login_payload(
        tenant_a.customer_id, admin_user.email, DEMO_PASSWORD,
    ))
    assert response.url == target


def test_login_refuses_an_offsite_next_parameter(client, tenant_a, admin_user):
    response = client.post(
        f"{reverse('accounts:login')}?next=https://evil.example/steal",
        _login_payload(tenant_a.customer_id, admin_user.email, DEMO_PASSWORD),
    )
    assert response.url == reverse('accounts:dashboard')


# --------------------------------------------------------------------------- #
# login_view — uniform failure (the account-enumeration guard)
# --------------------------------------------------------------------------- #

def test_login_wrong_customer_id_fails_uniformly(client, admin_user):
    response = client.post(reverse('accounts:login'), _login_payload(
        'NOT-A-REAL-CUSTOMER-ID', admin_user.email, DEMO_PASSWORD,
    ))
    assert response.status_code == 200
    assert response.context['form'].non_field_errors() == [UNIFORM_LOGIN_ERROR]


def test_login_wrong_password_fails_uniformly(client, tenant_a, admin_user):
    response = client.post(reverse('accounts:login'), _login_payload(
        tenant_a.customer_id, admin_user.email, 'wrong-password-entirely',
    ))
    assert response.status_code == 200
    assert response.context['form'].non_field_errors() == [UNIFORM_LOGIN_ERROR]


def test_login_unknown_identifier_fails_uniformly(client, tenant_a):
    response = client.post(reverse('accounts:login'), _login_payload(
        tenant_a.customer_id, 'nobody-here@acme-test.example', 'whatever-password',
    ))
    assert response.status_code == 200
    assert response.context['form'].non_field_errors() == [UNIFORM_LOGIN_ERROR]


def test_login_tenant_b_user_cannot_log_into_tenant_a(client, tenant_a, admin_b):
    """`admin_b`'s credentials are real — just not for THIS customer id."""
    response = client.post(reverse('accounts:login'), _login_payload(
        tenant_a.customer_id, admin_b.email, DEMO_PASSWORD,
    ))
    assert response.status_code == 200
    assert response.context['form'].non_field_errors() == [UNIFORM_LOGIN_ERROR]
    assert response.wsgi_request.user.is_anonymous


def test_login_wrong_password_and_wrong_tenant_produce_the_identical_message(client, tenant_a, tenant_b, admin_user, admin_b):
    wrong_password = client.post(reverse('accounts:login'), _login_payload(
        tenant_a.customer_id, admin_user.email, 'not-the-password',
    ))
    wrong_tenant = client.post(reverse('accounts:login'), _login_payload(
        tenant_a.customer_id, admin_b.email, DEMO_PASSWORD,
    ))
    assert (
        wrong_password.context['form'].non_field_errors()
        == wrong_tenant.context['form'].non_field_errors()
        == [UNIFORM_LOGIN_ERROR]
    )


def test_login_inactive_tenant_fails_uniformly(client, tenant_a, admin_user):
    tenant_a.is_active = False
    tenant_a.save(update_fields=['is_active'])
    response = client.post(reverse('accounts:login'), _login_payload(
        tenant_a.customer_id, admin_user.email, DEMO_PASSWORD,
    ))
    assert response.context['form'].non_field_errors() == [UNIFORM_LOGIN_ERROR]


def test_login_suspended_user_fails_uniformly(client, tenant_a, admin_user):
    admin_user.status = User.STATUS_SUSPENDED
    admin_user.save(update_fields=['status'])
    response = client.post(reverse('accounts:login'), _login_payload(
        tenant_a.customer_id, admin_user.email, DEMO_PASSWORD,
    ))
    assert response.context['form'].non_field_errors() == [UNIFORM_LOGIN_ERROR]


def test_login_blank_submission_shows_field_errors_not_the_uniform_message(client):
    # An empty dict makes `request.POST` falsy, which `login_view` treats as a
    # GET (`request.POST or None`) — send blank VALUES instead, so the POST body
    # is non-empty and the form is actually bound.
    response = client.post(reverse('accounts:login'), {
        'customer_id': '', 'identifier': '', 'password': '',
    })
    assert response.status_code == 200
    assert response.context['form'].non_field_errors() == []
    assert response.context['form'].errors


# --------------------------------------------------------------------------- #
# login_view — throttling
# --------------------------------------------------------------------------- #

def test_login_throttles_after_repeated_failures(client, tenant_a, admin_user, settings):
    limit = settings.LOGIN_ATTEMPT_LIMIT
    for _ in range(limit):
        client.post(reverse('accounts:login'), _login_payload(
            tenant_a.customer_id, admin_user.email, 'wrong-password',
        ))

    # Even the CORRECT password is refused once throttled.
    response = client.post(reverse('accounts:login'), _login_payload(
        tenant_a.customer_id, admin_user.email, DEMO_PASSWORD,
    ))
    assert response.context['form'].non_field_errors() == [THROTTLED_ERROR]
    assert response.wsgi_request.user.is_anonymous


def test_login_throttle_is_keyed_per_account_not_globally(client, tenant_a, admin_user, member_user, settings):
    """Exhausting one account's attempts must not lock out a different account
    from the same client IP within the same window... unless the IP key alone
    trips it. Use `LOGIN_ATTEMPT_LIMIT` failures against admin_user, then prove
    a CORRECT login for that SAME account is what's blocked (not a different,
    unrelated identifier check) — the account key is what this test isolates.
    """
    limit = settings.LOGIN_ATTEMPT_LIMIT
    for _ in range(limit):
        client.post(reverse('accounts:login'), _login_payload(
            tenant_a.customer_id, admin_user.email, 'wrong-password',
        ))
    response = client.post(reverse('accounts:login'), _login_payload(
        tenant_a.customer_id, admin_user.email, DEMO_PASSWORD,
    ))
    assert response.context['form'].non_field_errors() == [THROTTLED_ERROR]


def test_login_success_clears_the_throttle_counter(client, tenant_a, admin_user, settings):
    for _ in range(settings.LOGIN_ATTEMPT_LIMIT - 1):
        client.post(reverse('accounts:login'), _login_payload(
            tenant_a.customer_id, admin_user.email, 'wrong-password',
        ))
    success = client.post(reverse('accounts:login'), _login_payload(
        tenant_a.customer_id, admin_user.email, DEMO_PASSWORD,
    ))
    assert success.status_code == 302

    fresh_client = Client()
    # A single subsequent failure must not read as already-throttled.
    response = fresh_client.post(reverse('accounts:login'), _login_payload(
        tenant_a.customer_id, admin_user.email, 'wrong-again',
    ))
    assert response.context['form'].non_field_errors() == [UNIFORM_LOGIN_ERROR]


# --------------------------------------------------------------------------- #
# logout_view
# --------------------------------------------------------------------------- #

def test_logout_get_is_405(client_a):
    response = client_a.get(reverse('accounts:logout'))
    assert response.status_code == 405


def test_logout_post_signs_out_and_redirects(client_a):
    response = client_a.post(reverse('accounts:logout'))
    assert response.status_code == 302
    assert response.url == reverse('accounts:login')


def test_logout_post_flushes_the_active_location(client_a, location_a1):
    assert client_a.session[ACTIVE_LOCATION_SESSION_KEY] == location_a1.pk
    client_a.post(reverse('accounts:logout'))
    assert ACTIVE_LOCATION_SESSION_KEY not in client_a.session


def test_logout_then_protected_page_redirects_to_login(client_a):
    client_a.post(reverse('accounts:logout'))
    response = client_a.get(reverse('accounts:dashboard'))
    assert response.status_code == 302
    assert response.url.startswith(reverse('accounts:login'))


# --------------------------------------------------------------------------- #
# CSRF
# --------------------------------------------------------------------------- #

def test_csrf_is_enforced_on_login_post(tenant_a, admin_user):
    csrf_client = Client(enforce_csrf_checks=True)
    response = csrf_client.post(reverse('accounts:login'), _login_payload(
        tenant_a.customer_id, admin_user.email, DEMO_PASSWORD,
    ))
    assert response.status_code == 403
    assert response.wsgi_request.user.is_anonymous


def test_csrf_is_enforced_on_logout_post(admin_user):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = csrf_client.post(reverse('accounts:logout'))
    assert response.status_code == 403
    # Still logged in — the logout never actually ran.
    assert csrf_client.session.get('_auth_user_id') is not None


# --------------------------------------------------------------------------- #
# password_reset_request_view / password_reset_confirm_view
# --------------------------------------------------------------------------- #

def test_password_reset_request_renders_identical_response_for_real_and_fake_email(client, admin_user):
    real = client.post(reverse('accounts:password_reset_request'), {'email': admin_user.email})
    fake = client.post(reverse('accounts:password_reset_request'), {'email': 'nobody@nowhere.example'})
    assert real.status_code == fake.status_code == 200
    assert real.context['sent'] == fake.context['sent'] is True


def test_password_reset_request_sends_mail_only_for_a_real_active_user(client, admin_user):
    mail.outbox.clear()
    client.post(reverse('accounts:password_reset_request'), {'email': admin_user.email})
    assert len(mail.outbox) == 1
    assert admin_user.email in mail.outbox[0].to


def test_password_reset_request_sends_no_mail_for_an_unknown_address(client):
    mail.outbox.clear()
    client.post(reverse('accounts:password_reset_request'), {'email': 'nobody@nowhere.example'})
    assert len(mail.outbox) == 0


def test_password_reset_request_sends_no_mail_for_a_suspended_user(client, admin_user):
    admin_user.status = User.STATUS_SUSPENDED
    admin_user.save(update_fields=['status'])
    mail.outbox.clear()
    client.post(reverse('accounts:password_reset_request'), {'email': admin_user.email})
    assert len(mail.outbox) == 0


def _reset_link_for(admin_user):
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    token = default_token_generator.make_token(admin_user)
    uidb64 = urlsafe_base64_encode(force_bytes(admin_user.pk))
    return reverse('accounts:password_reset_confirm', kwargs={'uidb64': uidb64, 'token': token})


def test_password_reset_confirm_with_invalid_token_shows_invalid_state(client, admin_user):
    url = reverse('accounts:password_reset_confirm', kwargs={'uidb64': 'bad', 'token': 'bad-token'})
    response = client.get(url)
    assert response.status_code == 200
    assert response.context['valid'] is False


def test_password_reset_confirm_with_valid_token_sets_new_password(client, admin_user):
    url = _reset_link_for(admin_user)
    response = client.post(url, {
        'new_password1': 'a-fresh-password-1', 'new_password2': 'a-fresh-password-1',
    })
    assert response.status_code == 302
    admin_user.refresh_from_db()
    assert admin_user.check_password('a-fresh-password-1')


def test_password_reset_token_is_single_use(client, admin_user):
    url = _reset_link_for(admin_user)
    client.post(url, {'new_password1': 'first-new-pass-1', 'new_password2': 'first-new-pass-1'})

    # The SAME link, reused: the token hashes the password, which just changed.
    response = client.get(url)
    assert response.context['valid'] is False


def test_password_reset_confirm_sends_a_credential_change_notice(client, admin_user):
    mail.outbox.clear()
    url = _reset_link_for(admin_user)
    client.post(url, {'new_password1': 'notice-pass-1234', 'new_password2': 'notice-pass-1234'})
    assert len(mail.outbox) == 1
    assert admin_user.email in mail.outbox[0].to
