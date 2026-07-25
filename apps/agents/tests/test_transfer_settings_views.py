"""View tests for sub-module 2.3 — Transfer Settings.

Time-dependent state (`available_now`, `reopens_at`) is exercised only with
TIME-INDEPENDENT configurations here (disabled, or an unrestricted 24/7 window)
— `apps.agents.services.is_transfer_available`/`next_transfer_window` already
carry the exhaustive, `now=`-injected coverage for the hours-window logic
itself in `test_services.py`; duplicating that against the wall clock here
would only reintroduce the flakiness the injected-`now` design exists to avoid.
"""
import pytest
from django.test import Client
from django.urls import reverse

from apps.agents.models import AgentSetting
from apps.agents.services import DEFAULT_TRANSFER_KEYWORDS

pytestmark = pytest.mark.django_db

_WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']


def _transfer_data(**overrides):
    data = {
        'transfer_enabled': '', 'transfer_phone_number': '', 'transfer_secondary_number': '',
        'transfer_timezone': 'America/Chicago', 'keywords_text': '',
    }
    for day in _WEEKDAYS:
        data[f'{day}_enabled'] = ''
        data[f'{day}_start'] = ''
        data[f'{day}_end'] = ''
    data.update(overrides)
    return data


# --------------------------------------------------------------------------- #
# transfer_settings_view
# --------------------------------------------------------------------------- #

def test_transfer_settings_anonymous_redirects_to_login(client):
    response = client.get(reverse('agents:transfer_settings'))
    assert response.status_code == 302


def test_transfer_settings_blocks_staff_tier(member_client):
    response = member_client.get(reverse('agents:transfer_settings'))
    assert response.status_code == 302
    assert response.url == reverse('accounts:dashboard')


def test_transfer_settings_allows_owner_and_manager(client_a, manager_client):
    assert client_a.get(reverse('agents:transfer_settings')).status_code == 200
    assert manager_client.get(reverse('agents:transfer_settings')).status_code == 200


def test_transfer_settings_context_and_template(client_a):
    response = client_a.get(reverse('agents:transfer_settings'))
    assert 'agents/transfer/detail.html' in [t.name for t in response.templates]
    assert 'available_now' in response.context
    assert 'reopens_at' in response.context
    assert response.context['builtin_keywords'] == DEFAULT_TRANSFER_KEYWORDS


def test_transfer_settings_unavailable_when_disabled(client_a, tenant_a, location_a1, make_agent_setting):
    make_agent_setting(tenant_a, location_a1, transfer_enabled=False)
    response = client_a.get(reverse('agents:transfer_settings'))
    assert response.context['available_now'] is False


def test_transfer_settings_available_with_a_24_7_window(client_a, tenant_a, location_a1, make_agent_setting):
    hours = {day: {'enabled': True, 'start': '00:00', 'end': '23:59'} for day in _WEEKDAYS}
    make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='+13125550101',
        transfer_working_hours=hours,
    )
    response = client_a.get(reverse('agents:transfer_settings'))
    assert response.context['available_now'] is True


# --------------------------------------------------------------------------- #
# transfer_settings_edit_view
# --------------------------------------------------------------------------- #

def test_transfer_settings_edit_anonymous_redirects_to_login(client):
    response = client.get(reverse('agents:transfer_settings_edit'))
    assert response.status_code == 302


def test_transfer_settings_edit_blocks_staff_tier(member_client):
    response = member_client.get(reverse('agents:transfer_settings_edit'))
    assert response.status_code == 302


def test_transfer_settings_edit_get_renders_form(client_a):
    response = client_a.get(reverse('agents:transfer_settings_edit'))
    assert 'agents/transfer/form.html' in [t.name for t in response.templates]
    assert 'form' in response.context
    assert len(response.context['form'].day_rows) == 7


def test_transfer_settings_edit_post_saves_and_redirects(client_a, tenant_a, location_a1):
    response = client_a.post(reverse('agents:transfer_settings_edit'), _transfer_data(
        transfer_enabled='on', transfer_phone_number='+13125550101',
        monday_enabled='on', monday_start='09:00', monday_end='17:00',
        keywords_text='front desk',
    ))
    assert response.status_code == 302
    assert response.url == reverse('agents:transfer_settings')

    setting = AgentSetting.objects.get(tenant=tenant_a, location=location_a1)
    assert setting.transfer_enabled is True
    assert setting.transfer_phone_number == '+13125550101'
    assert setting.transfer_working_hours['monday'] == {'enabled': True, 'start': '09:00', 'end': '17:00'}
    assert setting.transfer_keywords == ['front desk']


def test_transfer_settings_edit_success_message(client_a):
    response = client_a.post(
        reverse('agents:transfer_settings_edit'), _transfer_data(), follow=True,
    )
    messages_seen = [str(m) for m in response.context['messages']]
    assert any('saved' in m.lower() for m in messages_seen)


def test_transfer_settings_edit_rejects_enabled_with_no_destination_as_200(client_a):
    """Negative-input hardening: an invalid submission re-renders the form,
    never 500s."""
    response = client_a.post(
        reverse('agents:transfer_settings_edit'), _transfer_data(transfer_enabled='on'),
    )
    assert response.status_code == 200
    assert response.context['form'].errors


def test_transfer_settings_edit_csrf_enforced(admin_user):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = csrf_client.post(reverse('agents:transfer_settings_edit'), _transfer_data())
    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# LOCATION / TENANT scoping
# --------------------------------------------------------------------------- #

def test_editing_one_locations_transfer_settings_never_touches_the_other(
    client_a, tenant_a, location_a1, location_a2, make_agent_setting,
):
    setting_a1 = make_agent_setting(tenant_a, location_a1, transfer_phone_number='+13125550101')
    setting_a2 = make_agent_setting(tenant_a, location_a2, transfer_phone_number='+13125550102')

    client_a.post(reverse('agents:transfer_settings_edit'), _transfer_data(
        transfer_enabled='on', transfer_phone_number='+13125559999',
    ))

    setting_a1.refresh_from_db()
    setting_a2.refresh_from_db()
    assert setting_a1.transfer_phone_number == '+13125559999'
    assert setting_a2.transfer_phone_number == '+13125550102'  # untouched


def test_tenant_a_and_tenant_b_transfer_settings_are_independent(
    client_a, client_b, tenant_a, tenant_b, location_a1, location_b1, make_agent_setting,
):
    make_agent_setting(tenant_a, location_a1, transfer_phone_number='+13125550101')
    make_agent_setting(tenant_b, location_b1, transfer_phone_number='+15035550101')

    resp_a = client_a.get(reverse('agents:transfer_settings'))
    resp_b = client_b.get(reverse('agents:transfer_settings'))

    assert resp_a.context['setting'].transfer_phone_number == '+13125550101'
    assert resp_b.context['setting'].transfer_phone_number == '+15035550101'


def test_a_crafted_post_cannot_name_another_locations_destination_into_this_row(
    client_a, tenant_a, location_a1, location_a2,
):
    """The form has no `location` field to inject — proving the structural
    absence rather than merely a lucky non-collision."""
    response = client_a.post(reverse('agents:transfer_settings_edit'), _transfer_data(
        transfer_enabled='on', transfer_phone_number='+13125550101', location=str(location_a2.pk),
    ))
    assert response.status_code == 302
    setting = AgentSetting.objects.get(tenant=tenant_a, location=location_a1)
    assert setting.location_id == location_a1.pk  # unaffected by the extra POST key
