"""Provider helpers — URL building, signature verification, TwiML, mode fail-safe.

Also pins the 3.4 Module 2 handoff: ``apps/runtime/providers/telephony`` now
defines ``get_backend`` + the transfer ``redirect_call``, so
``apps.agents.telephony.get_backend`` delegates to the runtime backend (which
subclasses Module 2's fake, inheriting ``check_connection``/``place_test_call``
verbatim), and the fake ``redirect_call`` reaches no carrier.
"""
import pytest
from django.test import RequestFactory
from twilio.request_validator import RequestValidator

from apps.runtime.providers import telephony
from apps.runtime.providers.base import active_mode, is_live


def test_provider_mode_is_fake_in_tests():
    assert active_mode() == 'fake'
    assert is_live() is False


def test_webhook_public_url_uses_configured_base(settings):
    settings.TWILIO_WEBHOOK_BASE_URL = 'https://pub.example'
    req = RequestFactory().post('/runtime/voice/')
    assert telephony.webhook_public_url(req) == 'https://pub.example/runtime/voice/'


def test_webhook_public_url_falls_back_to_host(settings):
    settings.TWILIO_WEBHOOK_BASE_URL = ''
    req = RequestFactory().post('/runtime/voice/')
    assert telephony.webhook_public_url(req).endswith('/runtime/voice/')


def test_media_stream_ws_url_swaps_scheme(settings):
    settings.TWILIO_WEBHOOK_BASE_URL = 'https://pub.example'
    assert telephony.media_stream_ws_url() == 'wss://pub.example/ws/media-stream/'


def test_media_stream_ws_url_relative_without_base(settings):
    settings.TWILIO_WEBHOOK_BASE_URL = ''
    assert telephony.media_stream_ws_url() == '/ws/media-stream/'


def test_verify_signature_fails_closed_without_inputs():
    assert telephony.verify_twilio_signature('https://x/y', {}, 'sig', '') is False
    assert telephony.verify_twilio_signature('https://x/y', {}, '', 'token') is False
    assert telephony.verify_twilio_signature(None, {}, 'sig', 'token') is False


def test_verify_signature_roundtrip():
    token, url = 'abc', 'https://x/runtime/voice/'
    params = {'To': '+1', 'CallSid': 'CA1'}
    sig = RequestValidator(token).compute_signature(url, params)
    assert telephony.verify_twilio_signature(url, params, sig, token) is True
    # A different token must not validate the same request.
    assert telephony.verify_twilio_signature(url, params, sig, 'other') is False


def test_stream_twiml_shape():
    xml = telephony.build_stream_twiml(
        'wss://x/ws/media-stream/', {'streamToken': 'T', 'sessionId': 9}
    )
    assert '<Connect>' in xml and '<Stream' in xml and 'streamToken' in xml


def test_decline_twiml_shape():
    xml = telephony.build_decline_twiml()
    assert '<Say' in xml and '<Hangup' in xml


def test_get_backend_exists_and_is_fake_off_live():
    # 3.4 defines get_backend here (3.1 deliberately did not). Off live it resolves
    # to the fake, which imports no twilio and opens no socket.
    assert hasattr(telephony, 'get_backend')
    backend = telephony.get_backend()
    assert isinstance(backend, telephony.FakeTelephonyBackend)
    assert backend.mode == 'fake'
    assert backend.simulated is True
    # The new transfer method the live call path needs, absent from 3.1's helpers.
    assert hasattr(backend, 'redirect_call')


def test_agents_get_backend_delegates_to_runtime_backend():
    # Module 2's get_backend import-guards for THIS module's get_backend; now that
    # 3.4 defines it, agents.telephony delegates through it with no Module-2
    # call-site change. The runtime backend subclasses Module 2's fake, so
    # check_connection/place_test_call are inherited verbatim (mode/simulated
    # unchanged) and redirect_call is added.
    from apps.agents.telephony import get_backend

    backend = get_backend()
    assert isinstance(backend, telephony.FakeTelephonyBackend)
    assert backend.mode == 'fake'
    assert backend.simulated is True
    assert hasattr(backend, 'redirect_call')


# --------------------------------------------------------------------------- #
# FakeTelephonyBackend.redirect_call — the fake transfer redirect contract
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _clear_redirect_script():
    """`_scripted_ok` is process-global class state — never leak it between tests."""
    telephony.FakeTelephonyBackend.clear_redirect_script()
    yield
    telephony.FakeTelephonyBackend.clear_redirect_script()


async def test_fake_redirect_call_connects_by_default():
    backend = telephony.FakeTelephonyBackend()
    result = await backend.redirect_call(None, 'CA1', '+13125550101')
    assert result.ok is True
    assert result.mode == 'fake'
    assert result.data['destination'] == '+13125550101'


async def test_fake_redirect_call_can_be_scripted_to_fail():
    telephony.FakeTelephonyBackend.script_redirect(ok=False)
    backend = telephony.FakeTelephonyBackend()
    result = await backend.redirect_call(None, 'CA1', '+13125550101')
    assert result.ok is False


async def test_fake_redirect_call_script_clears_back_to_connecting():
    telephony.FakeTelephonyBackend.script_redirect(ok=False)
    telephony.FakeTelephonyBackend.clear_redirect_script()
    backend = telephony.FakeTelephonyBackend()
    result = await backend.redirect_call(None, 'CA1', '+13125550101')
    assert result.ok is True


async def test_fake_redirect_call_never_imports_twilio(monkeypatch):
    """The fake backend must not need the `twilio` package to simulate a
    redirect — it reaches no carrier, so it cannot even import the SDK that
    would let it reach one."""
    import sys

    # A `None` entry in sys.modules makes any `import twilio` (or `from twilio
    # import ...`) inside this call raise ImportError, per the import system —
    # the reliable way to prove a code path never imports a given module.
    monkeypatch.setitem(sys.modules, 'twilio', None)
    backend = telephony.FakeTelephonyBackend()
    result = await backend.redirect_call(None, 'CA1', '+13125550101')
    assert result.ok is True
