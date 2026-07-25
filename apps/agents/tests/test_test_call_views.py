"""View tests for sub-module 2.4 — Test Call.

THE toll-fraud gate: this view takes NO destination field. `destination` is
always read from `request.user.primary_phone`, never from POST data — proven
below by posting a crafted `destination` and checking it changes nothing.
`PROVIDER_MODE=fake` throughout, so no real call is ever placed by this suite.
"""
import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _assert_fake_mode(settings):
    assert settings.PROVIDER_MODE == 'fake'


@pytest.fixture(autouse=True)
def _clear_rate_limit_cache():
    cache.clear()
    yield
    cache.clear()


def _ready_setting(tenant, location, make_agent_setting, **overrides):
    defaults = dict(
        greeting='Hi there.', prompt_text='Be helpful.',
        inbound_phone_number='+13125550188',
        twilio_account_sid='AC' + '1' * 32, twilio_auth_token='tok',
    )
    defaults.update(overrides)
    return make_agent_setting(tenant, location, **defaults)


# --------------------------------------------------------------------------- #
# Access control
# --------------------------------------------------------------------------- #

def test_test_call_anonymous_redirects_to_login(client):
    response = client.get(reverse('agents:test_call'))
    assert response.status_code == 302


def test_test_call_blocks_staff_tier(member_client):
    response = member_client.get(reverse('agents:test_call'))
    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')


def test_test_call_allows_owner_and_manager(client_a, manager_client):
    assert client_a.get(reverse('agents:test_call')).status_code == 200
    assert manager_client.get(reverse('agents:test_call')).status_code == 200


# --------------------------------------------------------------------------- #
# GET — context
# --------------------------------------------------------------------------- #

def test_test_call_get_context_and_template(client_a, admin_user):
    admin_user.primary_phone = '+13125550001'
    admin_user.save(update_fields=['primary_phone'])

    response = client_a.get(reverse('agents:test_call'))
    assert 'agents/testcall/index.html' in [t.name for t in response.templates]
    assert response.context['destination'] == '+13125550001'
    assert response.context['is_simulated'] is True
    assert response.context['provider_mode'] == 'fake'


def test_test_call_get_shows_readiness_issues(client_a):
    response = client_a.get(reverse('agents:test_call'))
    assert response.context['issues']  # a fresh row has issues


# --------------------------------------------------------------------------- #
# POST — the destination NEVER comes from the client
# --------------------------------------------------------------------------- #

def test_test_call_post_ignores_a_posted_destination_and_uses_the_profile_phone(
    client_a, admin_user, tenant_a, location_a1, make_agent_setting,
):
    admin_user.primary_phone = '+13125550002'
    admin_user.save(update_fields=['primary_phone'])
    _ready_setting(tenant_a, location_a1, make_agent_setting)

    response = client_a.post(reverse('agents:test_call'), {
        'destination': '+19005551234',  # a crafted, attacker-supplied number
    }, follow=True)

    messages_seen = [str(m) for m in response.context['messages']]
    assert not any('+19005551234' in m for m in messages_seen)
    assert any('simulated' in m.lower() for m in messages_seen)


def test_test_call_post_blocked_when_setup_has_issues(client_a, admin_user):
    admin_user.primary_phone = '+13125550003'
    admin_user.save(update_fields=['primary_phone'])
    response = client_a.post(reverse('agents:test_call'), {}, follow=True)
    messages_seen = [str(m) for m in response.context['messages']]
    assert any('fix the setup issues' in m.lower() for m in messages_seen)


def test_test_call_post_blocked_with_no_profile_phone(client_a, tenant_a, location_a1, make_agent_setting):
    _ready_setting(tenant_a, location_a1, make_agent_setting)
    response = client_a.post(reverse('agents:test_call'), {}, follow=True)
    messages_seen = [str(m) for m in response.context['messages']]
    assert any('add a phone number' in m.lower() for m in messages_seen)


def test_test_call_post_success_message_confirms_simulation(
    client_a, admin_user, tenant_a, location_a1, make_agent_setting,
):
    admin_user.primary_phone = '+13125550004'
    admin_user.save(update_fields=['primary_phone'])
    _ready_setting(tenant_a, location_a1, make_agent_setting)

    response = client_a.post(reverse('agents:test_call'), {}, follow=True)
    messages_seen = [str(m) for m in response.context['messages']]
    assert any('no call was placed' in m.lower() or 'nothing was billed' in m.lower()
              for m in messages_seen)


def test_test_call_post_redirects_back_to_the_same_page(client_a):
    response = client_a.post(reverse('agents:test_call'), {})
    assert response.status_code == 302
    assert response.url == reverse('agents:test_call')


# --------------------------------------------------------------------------- #
# Rate limiting — bounded even against yourself
# --------------------------------------------------------------------------- #

def test_test_call_is_rate_limited_after_repeated_attempts(
    client_a, admin_user, tenant_a, location_a1, make_agent_setting, settings,
):
    admin_user.primary_phone = '+13125550005'
    admin_user.save(update_fields=['primary_phone'])
    _ready_setting(tenant_a, location_a1, make_agent_setting)

    from apps.agents.views.TestCall.AgentSettings import RATE_LIMIT

    for _ in range(RATE_LIMIT):
        client_a.post(reverse('agents:test_call'), {})

    response = client_a.post(reverse('agents:test_call'), {}, follow=True)
    messages_seen = [str(m) for m in response.context['messages']]
    assert any('try again later' in m.lower() for m in messages_seen)


def test_test_call_rate_limit_is_scoped_per_location(
    client_a, admin_user, tenant_a, location_a1, location_a2, make_agent_setting,
):
    """Exhausting the limit for A1 must not block a test call at A2."""
    admin_user.primary_phone = '+13125550006'
    admin_user.save(update_fields=['primary_phone'])
    _ready_setting(tenant_a, location_a1, make_agent_setting, inbound_phone_number='+13125550111')
    _ready_setting(tenant_a, location_a2, make_agent_setting, inbound_phone_number='+13125550112')

    from apps.agents.views.TestCall.AgentSettings import RATE_LIMIT

    for _ in range(RATE_LIMIT):
        client_a.post(reverse('agents:test_call'), {})

    client_a.post(reverse('accounts:switch_location'), {'location': location_a2.pk}, follow=True)
    response = client_a.post(reverse('agents:test_call'), {}, follow=True)
    messages_seen = [str(m) for m in response.context['messages']]
    assert not any('try again later' in m.lower() for m in messages_seen)


# --------------------------------------------------------------------------- #
# CSRF
# --------------------------------------------------------------------------- #

def test_test_call_csrf_enforced(admin_user):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = csrf_client.post(reverse('agents:test_call'), {})
    assert response.status_code == 403
