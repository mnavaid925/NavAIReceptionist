"""Provider helpers — URL building, signature verification, TwiML, mode fail-safe.

Also pins the deliberate Module 2 integration: ``apps/runtime/providers/telephony``
defines NO ``get_backend``, so ``apps.agents.telephony.get_backend`` keeps falling
through to Module 2's own fake backend rather than a runtime one that cannot yet
place a call.
"""
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


def test_no_get_backend_symbol_yet():
    # 3.1 deliberately does not define get_backend; the backend handoff is 3.4.
    assert not hasattr(telephony, 'get_backend')


def test_agents_get_backend_still_falls_through_to_fake():
    from apps.agents.telephony import get_backend

    backend = get_backend()
    assert backend.mode == 'fake'
    assert backend.simulated is True
