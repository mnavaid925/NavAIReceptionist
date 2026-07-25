"""Tests for `apps/agents/telephony.py` — the ONLY seam in Module 2 that could
ever reach a carrier.

`PROVIDER_MODE` is pinned to `'fake'` by `config.settings_test` for the whole
suite; this file never flips it to `'live'` — even constructing
`LiveTelephonyBackend()` is only ever exercised as a guard-raises-immediately
check, so nothing here can open a socket toward a real provider.
"""
import pytest
from django.db import connection

from apps.agents import telephony
from apps.agents.telephony import FakeTelephonyBackend, LiveTelephonyBackend, TelephonyResult

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _assert_fake_mode(settings):
    """Belt-and-braces: a test that could place a real call is a Critical
    defect, not a slow test, per project rule."""
    assert settings.PROVIDER_MODE == 'fake'


# --------------------------------------------------------------------------- #
# FakeTelephonyBackend.check_connection — reaches nothing, imports no twilio
# --------------------------------------------------------------------------- #

def test_fake_backend_imports_no_twilio_sdk():
    """The safety property is structural: this class COULD NOT reach a
    carrier even if a bug invoked it in production."""
    import sys
    module = sys.modules[FakeTelephonyBackend.__module__]
    assert not hasattr(module, 'twilio')


def test_check_connection_reports_everything_missing(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(tenant_a, location_a1)
    result = FakeTelephonyBackend().check_connection(setting)
    assert result.ok is False
    assert 'account SID' in result.detail
    assert 'auth token' in result.detail
    assert 'inbound number' in result.detail


def test_check_connection_rejects_a_sid_without_ac_prefix(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1, twilio_account_sid='XXnotasid', twilio_auth_token='tok',
        inbound_phone_number='+13125550101',
    )
    result = FakeTelephonyBackend().check_connection(setting)
    assert result.ok is False
    assert 'starts with "AC"' in result.detail


def test_check_connection_ok_when_fully_configured(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1, twilio_account_sid='AC' + '1' * 32, twilio_auth_token='tok',
        inbound_phone_number='+13125550101',
    )
    result = FakeTelephonyBackend().check_connection(setting)
    assert result.ok is True
    assert result.mode == 'fake'
    assert result.simulated is True
    assert result.data['account_sid'] == setting.twilio_account_sid
    assert result.data['number'] == '+13125550101'


def test_check_connection_never_carries_the_auth_token(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1, twilio_account_sid='AC' + '1' * 32,
        twilio_auth_token='super-secret-value', inbound_phone_number='+13125550101',
    )
    result = FakeTelephonyBackend().check_connection(setting)
    assert 'super-secret-value' not in result.detail
    assert 'super-secret-value' not in result.summary
    assert 'super-secret-value' not in str(result.data)


# --------------------------------------------------------------------------- #
# FakeTelephonyBackend.place_test_call — simulated, never billed
# --------------------------------------------------------------------------- #

def test_place_test_call_is_simulated_and_never_billed(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(tenant_a, location_a1, inbound_phone_number='+13125550101')
    result = FakeTelephonyBackend().place_test_call(setting, '+13125559999')
    assert result.ok is True
    assert result.mode == 'fake'
    assert result.simulated is True
    assert 'no call was placed' in result.detail.lower()
    assert 'nothing was billed' in result.detail.lower()
    assert result.data == {'destination': '+13125559999', 'from': '+13125550101'}


# --------------------------------------------------------------------------- #
# LiveTelephonyBackend — refuses to initialise outside PROVIDER_MODE=live
# --------------------------------------------------------------------------- #

def test_live_backend_refuses_to_initialise_when_not_in_live_mode():
    with pytest.raises(RuntimeError):
        LiveTelephonyBackend()


# --------------------------------------------------------------------------- #
# get_backend() / check_connection() / place_test_call() — module-level API
# --------------------------------------------------------------------------- #

def test_get_backend_resolves_to_the_fake_implementation_under_fake_mode():
    backend = telephony.get_backend()
    assert backend.mode == 'fake'
    assert backend.simulated is True
    assert isinstance(backend, FakeTelephonyBackend)


def test_module_level_check_connection_delegates_to_the_backend(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1, twilio_account_sid='AC' + '1' * 32, twilio_auth_token='tok',
        inbound_phone_number='+13125550101',
    )
    result = telephony.check_connection(setting)
    assert isinstance(result, TelephonyResult)
    assert result.ok is True
    assert result.mode == 'fake'


def test_module_level_place_test_call_with_no_destination_is_refused(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(tenant_a, location_a1)
    result = telephony.place_test_call(setting, '')
    assert result.ok is False
    assert 'No destination' in result.summary


def test_module_level_place_test_call_with_a_destination_is_simulated(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(tenant_a, location_a1, inbound_phone_number='+13125550101')
    result = telephony.place_test_call(setting, '+13125557777')
    assert result.ok is True
    assert result.mode == 'fake'
    assert result.simulated is True


def test_check_connection_raw_column_never_holds_the_plaintext_token(
    tenant_a, location_a1, make_agent_setting,
):
    """Cross-check with the model layer: the credential `check_connection`
    reasons about is never sitting in the database as plaintext either."""
    setting = make_agent_setting(
        tenant_a, location_a1, twilio_account_sid='AC' + '1' * 32,
        twilio_auth_token='another-secret-value', inbound_phone_number='+13125550101',
    )
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT twilio_auth_token FROM agents_agentsetting WHERE id = %s', [setting.pk],
        )
        raw = cursor.fetchone()[0]
    assert 'another-secret-value' not in raw
