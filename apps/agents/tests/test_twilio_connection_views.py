"""View tests for sub-module 2.2 — Twilio Connection.

The highest-risk views in the product: `twilio_auth_token` must never reach a
response body, `messages.*`, or the log line these views write. Like 2.1, there
is no pk in any route — location scoping is proven by switching the ACTIVE
location, not by tampering with an id.
"""
import pytest
from django.db import connection
from django.test import Client
from django.urls import reverse

from apps.agents.models import AgentSetting

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _pin_webhook_base(settings):
    settings.TWILIO_WEBHOOK_BASE_URL = 'https://voice.example.test'


def _raw_token(pk):
    with connection.cursor() as cursor:
        cursor.execute('SELECT twilio_auth_token FROM agents_agentsetting WHERE id = %s', [pk])
        return cursor.fetchone()[0]


# --------------------------------------------------------------------------- #
# twilio_connection_view — detail
# --------------------------------------------------------------------------- #

def test_twilio_connection_anonymous_redirects_to_login(client):
    response = client.get(reverse('agents:twilio_connection'))
    assert response.status_code == 302


def test_twilio_connection_blocks_staff_tier(member_client):
    response = member_client.get(reverse('agents:twilio_connection'))
    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')


def test_twilio_connection_allows_owner_and_manager(client_a, manager_client):
    assert client_a.get(reverse('agents:twilio_connection')).status_code == 200
    assert manager_client.get(reverse('agents:twilio_connection')).status_code == 200


def test_twilio_connection_detail_context_and_template(client_a):
    response = client_a.get(reverse('agents:twilio_connection'))
    assert 'agents/twilio/detail.html' in [t.name for t in response.templates]
    assert 'setting' in response.context
    assert 'urls' in response.context
    assert response.context['provider_mode'] == 'fake'


def test_twilio_connection_urls_resolve_from_real_routes(client_a):
    response = client_a.get(reverse('agents:twilio_connection'))
    urls = response.context['urls']
    assert urls['voice'] == 'https://voice.example.test' + reverse('runtime:voice_webhook')
    assert urls['stream'].startswith('wss://voice.example.test')


def test_twilio_connection_urls_empty_when_no_public_base_configured(client_a, settings):
    settings.TWILIO_WEBHOOK_BASE_URL = ''
    response = client_a.get(reverse('agents:twilio_connection'))
    assert response.context['urls'] == {}


def test_twilio_connection_detail_never_leaks_the_token_value(client_a, tenant_a, location_a1, make_agent_setting):
    make_agent_setting(tenant_a, location_a1, twilio_auth_token='leak-check-secret-value')
    response = client_a.get(reverse('agents:twilio_connection'))
    assert b'leak-check-secret-value' not in response.content


# --------------------------------------------------------------------------- #
# twilio_connection_edit_view
# --------------------------------------------------------------------------- #

def test_twilio_connection_edit_anonymous_redirects_to_login(client):
    response = client.get(reverse('agents:twilio_connection_edit'))
    assert response.status_code == 302


def test_twilio_connection_edit_blocks_staff_tier(member_client):
    response = member_client.get(reverse('agents:twilio_connection_edit'))
    assert response.status_code == 302


def test_twilio_connection_edit_get_never_renders_the_token_field(
    client_a, tenant_a, location_a1, make_agent_setting,
):
    make_agent_setting(tenant_a, location_a1, twilio_auth_token='leak-check-secret-value-2')
    response = client_a.get(reverse('agents:twilio_connection_edit'))
    assert 'twilio_auth_token' not in response.context['form'].fields
    assert b'leak-check-secret-value-2' not in response.content


def test_twilio_connection_edit_post_creates_encrypted_credentials(client_a, tenant_a, location_a1):
    response = client_a.post(reverse('agents:twilio_connection_edit'), {
        'twilio_account_sid': 'AC' + '1' * 32,
        'inbound_phone_number': '+13125550177',
        'new_auth_token': 'brand-new-plaintext-token',
    })
    assert response.status_code == 302
    assert response.url == reverse('agents:twilio_connection')

    setting = AgentSetting.objects.get(tenant=tenant_a, location=location_a1)
    assert setting.twilio_account_sid == 'AC' + '1' * 32
    assert setting.inbound_phone_number == '+13125550177'
    assert setting.twilio_auth_token == 'brand-new-plaintext-token'  # decrypted read-back

    assert 'brand-new-plaintext-token' not in _raw_token(setting.pk)


def test_twilio_connection_edit_blank_submit_preserves_the_existing_token(
    client_a, tenant_a, location_a1, make_agent_setting,
):
    make_agent_setting(
        tenant_a, location_a1, twilio_account_sid='AC' + '2' * 32,
        twilio_auth_token='keep-me-unchanged', inbound_phone_number='+13125550178',
    )
    response = client_a.post(reverse('agents:twilio_connection_edit'), {
        'twilio_account_sid': 'AC' + '2' * 32,
        'inbound_phone_number': '+13125550178',
        'new_auth_token': '',
    })
    assert response.status_code == 302

    setting = AgentSetting.objects.get(tenant=tenant_a, location=location_a1)
    assert setting.twilio_auth_token == 'keep-me-unchanged'


def test_twilio_connection_edit_success_message_never_contains_the_token(client_a):
    response = client_a.post(reverse('agents:twilio_connection_edit'), {
        'twilio_account_sid': 'AC' + '3' * 32,
        'inbound_phone_number': '',
        'new_auth_token': 'message-leak-check-token',
    }, follow=True)
    messages_seen = [str(m) for m in response.context['messages']]
    assert not any('message-leak-check-token' in m for m in messages_seen)
    assert any('saved' in m.lower() for m in messages_seen)


def test_twilio_connection_edit_rejects_a_number_claimed_by_another_tenant(
    client_a, tenant_b, location_b1, make_agent_setting,
):
    make_agent_setting(tenant_b, location_b1, inbound_phone_number='+13125550199')
    response = client_a.post(reverse('agents:twilio_connection_edit'), {
        'twilio_account_sid': '', 'inbound_phone_number': '+13125550199', 'new_auth_token': '',
    })
    assert response.status_code == 200  # re-rendered with an error, not saved
    error = str(response.context['form'].errors['inbound_phone_number'])
    assert 'not available' in error.lower()
    assert tenant_b.name not in error


def test_twilio_connection_edit_csrf_enforced(admin_user):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = csrf_client.post(reverse('agents:twilio_connection_edit'), {
        'twilio_account_sid': '', 'inbound_phone_number': '', 'new_auth_token': 'x',
    })
    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# LOCATION / TENANT scoping
# --------------------------------------------------------------------------- #

def test_editing_one_locations_twilio_connection_never_touches_the_other(
    client_a, tenant_a, location_a1, location_a2, make_agent_setting,
):
    setting_a1 = make_agent_setting(tenant_a, location_a1, twilio_auth_token='a1-token')
    setting_a2 = make_agent_setting(tenant_a, location_a2, twilio_auth_token='a2-token')

    client_a.post(reverse('agents:twilio_connection_edit'), {
        'twilio_account_sid': 'AC' + '9' * 32, 'inbound_phone_number': '', 'new_auth_token': 'a1-new-token',
    })

    setting_a1.refresh_from_db()
    setting_a2.refresh_from_db()
    assert setting_a1.twilio_auth_token == 'a1-new-token'
    assert setting_a2.twilio_auth_token == 'a2-token'  # untouched


def test_tenant_a_and_tenant_b_twilio_connections_are_independent(
    client_a, client_b, tenant_a, tenant_b, location_a1, location_b1, make_agent_setting,
):
    make_agent_setting(tenant_a, location_a1, twilio_account_sid='AC' + 'A' * 32)
    make_agent_setting(tenant_b, location_b1, twilio_account_sid='AC' + 'B' * 32)

    resp_a = client_a.get(reverse('agents:twilio_connection'))
    resp_b = client_b.get(reverse('agents:twilio_connection'))

    assert resp_a.context['setting'].twilio_account_sid == 'AC' + 'A' * 32
    assert resp_b.context['setting'].twilio_account_sid == 'AC' + 'B' * 32


# --------------------------------------------------------------------------- #
# twilio_check_view — POST-only, never places a call
# --------------------------------------------------------------------------- #

def test_twilio_check_get_is_405(client_a):
    response = client_a.get(reverse('agents:twilio_check'))
    assert response.status_code == 405


def test_twilio_check_anonymous_redirects_to_login(client):
    response = client.post(reverse('agents:twilio_check'))
    assert response.status_code == 302


def test_twilio_check_blocks_staff_tier(member_client):
    response = member_client.post(reverse('agents:twilio_check'))
    assert response.status_code == 302


def test_twilio_check_reports_missing_credentials(client_a):
    response = client_a.post(reverse('agents:twilio_check'), follow=True)
    messages_seen = [str(m) for m in response.context['messages']]
    assert any('not connected' in m.lower() for m in messages_seen)


def test_twilio_check_ok_when_configured(client_a, tenant_a, location_a1, make_agent_setting, settings):
    make_agent_setting(
        tenant_a, location_a1, twilio_account_sid='AC' + '1' * 32,
        twilio_auth_token='tok', inbound_phone_number='+13125550166',
    )
    response = client_a.post(reverse('agents:twilio_check'), follow=True)
    messages_seen = [str(m) for m in response.context['messages']]
    assert any('simulated' in m.lower() for m in messages_seen)
    assert settings.PROVIDER_MODE == 'fake'


def test_twilio_check_message_never_contains_the_token(client_a, tenant_a, location_a1, make_agent_setting):
    make_agent_setting(
        tenant_a, location_a1, twilio_account_sid='AC' + '1' * 32,
        twilio_auth_token='check-view-secret-token', inbound_phone_number='+13125550166',
    )
    response = client_a.post(reverse('agents:twilio_check'), follow=True)
    messages_seen = [str(m) for m in response.context['messages']]
    assert not any('check-view-secret-token' in m for m in messages_seen)


def test_twilio_check_csrf_enforced(admin_user):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = csrf_client.post(reverse('agents:twilio_check'))
    assert response.status_code == 403
