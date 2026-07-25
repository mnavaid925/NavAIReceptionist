"""View tests for sub-module 2.1 — Per-Location Agent Configuration.

**No route in this module takes a pk** — every view resolves its row from
`request.tenant` and `request.location` alone (`get_setting_for_active_location`),
so cross-tenant/cross-location isolation here is proven by showing that
switching the ACTIVE location changes which row a view reads and writes, never
by tampering with an id in the URL (there is none to tamper with).
"""
import pytest
from django.test import Client
from django.urls import reverse

from apps.agents.models import AgentSetting

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# agent_setup_view — no tier gate, any signed-in user with an active location
# --------------------------------------------------------------------------- #

def test_agent_setup_anonymous_redirects_to_login(client):
    response = client.get(reverse('agents:agent_setup'))
    assert response.status_code == 302
    assert response.url.startswith(reverse('accounts:login'))


def test_agent_setup_with_no_active_location_redirects_to_my_locations(admin_user):
    """`admin_user` is assigned to TWO locations and has not switched into
    either yet — `request.location` is None (see `ActiveLocationMiddleware`)."""
    client = Client()
    client.force_login(admin_user)
    response = client.get(reverse('agents:agent_setup'))
    assert response.status_code == 302
    assert response.url == reverse('accounts:my_locations')


def test_agent_setup_get_or_creates_the_row_for_the_active_location(client_a, tenant_a, location_a1):
    assert not AgentSetting.objects.filter(tenant=tenant_a, location=location_a1).exists()
    response = client_a.get(reverse('agents:agent_setup'))
    assert response.status_code == 200
    assert AgentSetting.objects.filter(tenant=tenant_a, location=location_a1).count() == 1


def test_agent_setup_renders_the_expected_template_and_context(client_a, tenant_a, location_a1):
    response = client_a.get(reverse('agents:agent_setup'))
    assert 'agents/setup/detail.html' in [t.name for t in response.templates]
    assert response.context['setting'].location_id == location_a1.pk
    assert 'issues' in response.context
    assert 'rendered_greeting' in response.context
    assert 'variable_count' in response.context


def test_agent_setup_staff_tier_can_view(member_client):
    """No `tier_required` on the read-only overview — staff may VIEW it."""
    response = member_client.get(reverse('agents:agent_setup'))
    assert response.status_code == 200


def test_agent_setup_readiness_issues_reflect_the_stored_row(client_a, tenant_a, location_a1, make_agent_setting):
    make_agent_setting(tenant_a, location_a1, greeting='', prompt_text='')
    response = client_a.get(reverse('agents:agent_setup'))
    assert any('greeting' in i.lower() for i in response.context['issues'])


# --------------------------------------------------------------------------- #
# LOCATION scoping — the active location is what changes which row is used
# --------------------------------------------------------------------------- #

def test_switching_the_active_location_shows_a_different_setting_row(
    client_a, tenant_a, location_a1, location_a2, make_agent_setting,
):
    make_agent_setting(tenant_a, location_a1, greeting='Greeting for A1')
    make_agent_setting(tenant_a, location_a2, greeting='Greeting for A2')

    at_a1 = client_a.get(reverse('agents:agent_setup'))
    assert at_a1.context['setting'].greeting == 'Greeting for A1'

    client_a.post(reverse('accounts:switch_location'), {'location': location_a2.pk}, follow=True)
    at_a2 = client_a.get(reverse('agents:agent_setup'))
    assert at_a2.context['setting'].greeting == 'Greeting for A2'


def test_editing_one_locations_agent_never_touches_the_other(
    client_a, tenant_a, location_a1, location_a2, make_agent_setting,
):
    setting_a1 = make_agent_setting(tenant_a, location_a1, greeting='Original A1')
    setting_a2 = make_agent_setting(tenant_a, location_a2, greeting='Original A2')

    client_a.post(reverse('agents:agent_setup_edit'), {
        'voice_provider': AgentSetting.VOICE_LIVE,
        'greeting': 'Updated A1 greeting',
        'prompt_text': 'Updated prompt.',
        'variables_text': '',
    })

    setting_a1.refresh_from_db()
    setting_a2.refresh_from_db()
    assert setting_a1.greeting == 'Updated A1 greeting'
    assert setting_a2.greeting == 'Original A2'  # untouched


# --------------------------------------------------------------------------- #
# TENANT scoping
# --------------------------------------------------------------------------- #

def test_tenant_a_and_tenant_b_agent_setup_are_fully_independent(
    client_a, client_b, tenant_a, tenant_b, location_a1, location_b1, make_agent_setting,
):
    make_agent_setting(tenant_a, location_a1, greeting='Tenant A greeting')
    make_agent_setting(tenant_b, location_b1, greeting='Tenant B greeting')

    resp_a = client_a.get(reverse('agents:agent_setup'))
    resp_b = client_b.get(reverse('agents:agent_setup'))

    assert resp_a.context['setting'].greeting == 'Tenant A greeting'
    assert resp_b.context['setting'].greeting == 'Tenant B greeting'


# --------------------------------------------------------------------------- #
# agent_setup_edit_view — tier-gated, GET+POST
# --------------------------------------------------------------------------- #

def test_agent_setup_edit_anonymous_redirects_to_login(client):
    response = client.get(reverse('agents:agent_setup_edit'))
    assert response.status_code == 302


def test_agent_setup_edit_blocks_staff_tier(member_client):
    response = member_client.get(reverse('agents:agent_setup_edit'))
    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')


def test_agent_setup_edit_allows_owner(client_a):
    response = client_a.get(reverse('agents:agent_setup_edit'))
    assert response.status_code == 200


def test_agent_setup_edit_allows_manager(manager_client):
    response = manager_client.get(reverse('agents:agent_setup_edit'))
    assert response.status_code == 200


def test_agent_setup_edit_get_renders_form(client_a):
    response = client_a.get(reverse('agents:agent_setup_edit'))
    assert 'agents/setup/form.html' in [t.name for t in response.templates]
    assert 'form' in response.context


def test_agent_setup_edit_post_saves_and_redirects(client_a, tenant_a, location_a1):
    response = client_a.post(reverse('agents:agent_setup_edit'), {
        'enabled': 'on',
        'voice_provider': AgentSetting.VOICE_LIVE,
        'greeting': 'Thanks for calling us.',
        'prompt_text': 'Be helpful and brief.',
        'variables_text': '',
    })
    assert response.status_code == 302
    assert response.url == reverse('agents:agent_setup')

    setting = AgentSetting.objects.get(tenant=tenant_a, location=location_a1)
    assert setting.enabled is True
    assert setting.greeting == 'Thanks for calling us.'


def test_agent_setup_edit_post_success_message(client_a):
    response = client_a.post(reverse('agents:agent_setup_edit'), {
        'voice_provider': AgentSetting.VOICE_LIVE, 'greeting': 'Hi.', 'prompt_text': 'Help.',
        'variables_text': '',
    }, follow=True)
    messages_seen = [str(m) for m in response.context['messages']]
    assert any('saved' in m.lower() for m in messages_seen)


def test_agent_setup_edit_malformed_variables_line_is_a_200_not_a_500(client_a):
    """Negative-input hardening: a malformed `variables_text` line must render
    the form again with an error, never crash the request."""
    response = client_a.post(reverse('agents:agent_setup_edit'), {
        'voice_provider': AgentSetting.VOICE_LIVE, 'greeting': '', 'prompt_text': '',
        'variables_text': 'not-a-valid-line-at-all',
    })
    assert response.status_code == 200
    assert response.context['form'].errors


def test_agent_setup_edit_csrf_enforced(admin_user, location_a1):
    """CSRF is enforced by middleware BEFORE any view code runs — no active
    location needs to be set up for this to be true."""
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = csrf_client.post(reverse('agents:agent_setup_edit'), {
        'voice_provider': AgentSetting.VOICE_LIVE, 'greeting': 'Hi.', 'prompt_text': 'Help.',
        'variables_text': '',
    })
    assert response.status_code == 403


def test_agent_setup_edit_get_does_not_save(client_a, tenant_a, location_a1, make_agent_setting):
    """A GET must never mutate the stored row, however innocuous — the view is
    `require_http_methods(['GET', 'POST'])` on purpose but a GET runs no
    `form.is_valid()`/`form.save()` branch. (`get_setting_for_active_location`
    itself may `get_or_create` a fresh row on first visit — that is documented
    behaviour, not what this test is about, so it starts from an existing row.)
    """
    setting = make_agent_setting(tenant_a, location_a1, greeting='Untouched greeting')
    client_a.get(reverse('agents:agent_setup_edit'))
    setting.refresh_from_db()
    assert setting.greeting == 'Untouched greeting'


# --------------------------------------------------------------------------- #
# agent_preview_view — tier-gated
# --------------------------------------------------------------------------- #

def test_agent_preview_blocks_staff_tier(member_client):
    response = member_client.get(reverse('agents:agent_preview'))
    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')


def test_agent_preview_renders_for_owner(client_a, tenant_a, location_a1, make_agent_setting):
    make_agent_setting(tenant_a, location_a1, greeting='Hi {{parking}}.', variables={'parking': 'lot B'})
    response = client_a.get(reverse('agents:agent_preview'))
    assert response.status_code == 200
    assert 'agents/setup/preview.html' in [t.name for t in response.templates]
    assert response.context['rendered_greeting'] == 'Hi lot B.'


def test_agent_preview_context_uses_sample_runtime_context(client_a):
    response = client_a.get(reverse('agents:agent_preview'))
    context_pairs = dict(response.context['context'])
    assert context_pairs['from_number'] == '+13125550000'
