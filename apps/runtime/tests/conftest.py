"""Fixtures for `apps.runtime`'s suite — domain records + Twilio signing helpers.

Tenant/location/user/client fixtures come from the ROOT `conftest.py`. This file
adds the `agents.AgentSetting` rows the webhook resolves against, a `calls.
CallSession` factory the 3.2 media-stream/turn-loop suite builds on, the helper
that forges a genuine `X-Twilio-Signature`, and the per-test reset of the
consumer's process-global `_active_calls` counter so a capacity test in one test
function can never leak into another.
"""
import uuid

import pytest
from django.utils import timezone
from twilio.request_validator import RequestValidator

from apps.agents.models import AgentSetting
from apps.calls.models import CallSession

#: The public base pinned for the whole runtime suite, so a test can sign over a
#: known URL and the webhook rebuilds the identical one.
WEBHOOK_BASE = 'https://voice.example.test'


@pytest.fixture(autouse=True)
def _pin_webhook_base(settings):
    """Fix the public base and re-assert the never-a-real-call invariant.

    The webhook checks the signature against ``TWILIO_WEBHOOK_BASE_URL`` + path;
    pinning it lets a test sign over a deterministic URL. ``PROVIDER_MODE`` is
    already ``fake`` in ``settings_test`` — asserting it here makes "a test placed
    a real call" a suite failure, per the project rule.
    """
    settings.TWILIO_WEBHOOK_BASE_URL = WEBHOOK_BASE
    assert settings.PROVIDER_MODE == 'fake'


@pytest.fixture
def make_agent_setting(db):
    """Factory: ``make_agent_setting(tenant, location, **overrides) -> AgentSetting``.

    Enabled, with an inbound number and Twilio credentials by default so the row
    both resolves and verifies. ``inbound_phone_number`` is globally unique, so a
    test creating two settings must pass distinct numbers.
    """
    def _make(tenant, location, **overrides):
        defaults = {
            'enabled': True,
            'inbound_phone_number': '+13125550140',
            'twilio_account_sid': 'AC' + '1' * 32,
            'twilio_auth_token': 'test-auth-token-0001',
            'greeting': 'Thanks for calling Acme.',
            'prompt_text': 'You are the Acme receptionist.',
            'voice_provider': AgentSetting.VOICE_LIVE,
        }
        defaults.update(overrides)
        return AgentSetting.objects.create(tenant=tenant, location=location, **defaults)
    return _make


def twilio_signature(auth_token, path, params):
    """A genuine ``X-Twilio-Signature`` for ``(WEBHOOK_BASE + path, params)``."""
    return RequestValidator(auth_token).compute_signature(
        f'{WEBHOOK_BASE}{path}', params
    )


@pytest.fixture
def make_call_session(db):
    """Factory: ``make_call_session(tenant, location, **overrides) -> CallSession``.

    In-progress by default, mirroring the row 3.1's webhook creates at answer
    time — the shape the 3.2 media consumer resolves and finalizes.
    """
    def _make(tenant, location, **overrides):
        defaults = {
            'provider_call_sid': f'CA{uuid.uuid4().hex[:30]}',
            'from_number': '+15005550006',
            'to_number': '+13125550140',
            'status': CallSession.STATUS_IN_PROGRESS,
            'mode': CallSession.MODE_LIVE,
            'started_at': timezone.now(),
        }
        defaults.update(overrides)
        return CallSession.objects.create(tenant=tenant, location=location, **defaults)
    return _make


@pytest.fixture(autouse=True)
def _reset_media_stream_capacity():
    """Zero the consumer's process-global live-call counter around each test.

    ``MediaStreamConsumer._active_calls`` is a class attribute shared by every
    test in the process (it models a per-worker ceiling, not a per-call one), so
    a capacity test that leaves it non-zero would poison every test after it.
    """
    from apps.runtime.consumers.MediaStreamTurnLoop.MediaStream import MediaStreamConsumer
    MediaStreamConsumer._active_calls = 0
    yield
    MediaStreamConsumer._active_calls = 0
