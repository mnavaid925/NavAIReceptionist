"""The inbound voice webhook — signature, idempotency, decline, per-location auth.

The whole 3.1 contract is here: a genuine Twilio request answers with stream
TwiML and exactly one `CallSession`; a forged or absent signature is a 403 with
zero writes; a redelivery is still one session; an unmapped or disabled number is
a spoken decline with zero writes; and the signature is verified against the
RESOLVED location's token, not a global one.
"""
import logging

import pytest
from django.test import Client
from django.urls import reverse

from apps.agents.models import AgentSetting
from apps.calls.models import CallSession
from apps.runtime.tests.conftest import twilio_signature

pytestmark = pytest.mark.django_db

WEBHOOK_PATH = '/runtime/voice/'


def _params(to='+13125550140', frm='+13125550101', sid='CA' + 'a' * 32):
    return {'To': to, 'From': frm, 'CallSid': sid}


def _post_signed(client, token, params):
    sig = twilio_signature(token, WEBHOOK_PATH, params)
    return client.post(WEBHOOK_PATH, params, HTTP_X_TWILIO_SIGNATURE=sig)


def test_reverse_mounts_at_runtime_voice():
    # Module 2's live test call hardcodes this exact URL — it must not drift.
    assert reverse('runtime:voice_webhook') == WEBHOOK_PATH


def test_valid_signature_creates_one_session_and_streams(
    make_agent_setting, tenant_a, location_a1
):
    setting = make_agent_setting(tenant_a, location_a1)
    params = _params(to=setting.inbound_phone_number)

    resp = _post_signed(Client(), setting.twilio_auth_token, params)

    assert resp.status_code == 200
    assert resp['Content-Type'] == 'application/xml'
    body = resp.content.decode()
    assert '<Connect>' in body and '<Stream' in body and 'streamToken' in body

    sessions = CallSession.objects.filter(provider_call_sid=params['CallSid'])
    assert sessions.count() == 1
    s = sessions.get()
    assert s.tenant_id == tenant_a.pk and s.location_id == location_a1.pk
    assert s.from_number == params['From'] and s.to_number == params['To']
    assert s.status == CallSession.STATUS_IN_PROGRESS
    assert s.started_at is not None


def test_wrong_token_signature_rejected_zero_writes(
    make_agent_setting, tenant_a, location_a1
):
    make_agent_setting(tenant_a, location_a1)
    params = _params()
    resp = _post_signed(Client(), 'the-wrong-token', params)
    assert resp.status_code == 403
    assert CallSession.objects.count() == 0


def test_absent_signature_rejected_zero_writes(
    make_agent_setting, tenant_a, location_a1
):
    make_agent_setting(tenant_a, location_a1)
    resp = Client().post(WEBHOOK_PATH, _params())  # no X-Twilio-Signature header
    assert resp.status_code == 403
    assert CallSession.objects.count() == 0


def test_duplicate_delivery_yields_one_session(
    make_agent_setting, tenant_a, location_a1
):
    setting = make_agent_setting(tenant_a, location_a1)
    params = _params(to=setting.inbound_phone_number)
    client = Client()

    r1 = _post_signed(client, setting.twilio_auth_token, params)
    r2 = _post_signed(client, setting.twilio_auth_token, params)

    assert r1.status_code == 200 and r2.status_code == 200
    assert CallSession.objects.filter(provider_call_sid=params['CallSid']).count() == 1


def test_unmapped_number_declines_zero_writes(db):
    # No AgentSetting exists, so any dialed number is unmapped. Decline comes
    # before the signature check, so an unsigned request still gets the notice.
    resp = Client().post(WEBHOOK_PATH, _params(to='+19998887777'))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert '<Say' in body and '<Hangup' in body and '<Connect>' not in body
    assert CallSession.objects.count() == 0


def test_disabled_agent_declines_zero_writes(
    make_agent_setting, tenant_a, location_a1
):
    setting = make_agent_setting(tenant_a, location_a1, enabled=False)
    params = _params(to=setting.inbound_phone_number)
    resp = _post_signed(Client(), setting.twilio_auth_token, params)
    assert resp.status_code == 200
    assert '<Hangup' in resp.content.decode() and '<Connect>' not in resp.content.decode()
    assert CallSession.objects.count() == 0


def test_signature_verified_against_resolved_location_token(
    make_agent_setting, tenant_a, location_a1, location_a2
):
    s1 = make_agent_setting(
        tenant_a, location_a1,
        inbound_phone_number='+13125550140', twilio_auth_token='token-a1',
    )
    make_agent_setting(
        tenant_a, location_a2,
        inbound_phone_number='+13125550141', twilio_auth_token='token-a2',
    )
    params = _params(to=s1.inbound_phone_number)

    # Signed with location A2's token but dialed A1's number → rejected.
    bad = _post_signed(Client(), 'token-a2', params)
    assert bad.status_code == 403
    assert CallSession.objects.count() == 0

    # Signed with A1's own token → accepted, and the row lands on A1.
    good = _post_signed(Client(), 'token-a1', params)
    assert good.status_code == 200
    assert CallSession.objects.filter(location=location_a1).count() == 1


def test_valid_signature_missing_callsid_is_400_zero_writes(
    make_agent_setting, tenant_a, location_a1
):
    setting = make_agent_setting(tenant_a, location_a1)
    params = {'To': setting.inbound_phone_number, 'From': '+13125550101'}  # no CallSid
    resp = _post_signed(Client(), setting.twilio_auth_token, params)
    assert resp.status_code == 400
    assert CallSession.objects.count() == 0


@pytest.mark.parametrize('bad_sid', [
    '../../../../99/1/pwned',   # escapes its own tenant/location prefix
    'CA/../elsewhere',          # a separator anywhere at all
    'CA<script>',               # XML/TwiML injection characters
    '   ',                      # whitespace-only
])
def test_valid_signature_malformed_callsid_is_400_zero_writes(
    make_agent_setting, tenant_a, location_a1, bad_sid
):
    """A correctly SIGNED request still cannot smuggle a malformed CallSid.

    `provider_call_sid` is persisted and then reused as data that carries
    authority: it is interpolated into the transfer REST path (3.4) and into the
    recording's storage path (3.5). A SID containing `../` would write a call's
    audio outside its own `private/calls/{tenant}/{location}/` prefix — Django's
    `safe_join` guards the PRIVATE_MEDIA_ROOT boundary but NOT the tenant and
    location partition inside it. This is the gate that keeps every later
    consumer of the value safe, so it is checked at ingestion, before the row
    exists at all.
    """
    setting = make_agent_setting(tenant_a, location_a1)
    params = {'To': setting.inbound_phone_number, 'From': '+13125550101',
              'CallSid': bad_sid}
    resp = _post_signed(Client(), setting.twilio_auth_token, params)
    assert resp.status_code == 400
    assert CallSession.objects.count() == 0


def test_recording_path_refuses_a_traversal_call_sid(tenant_a, location_a1,
                                                     make_call_session):
    """Defense in depth: the path builder does not trust the stored row either.

    The ingestion check above is the real gate. This one survives a future second
    writer, a data migration or a hand-edited row — and it raises rather than
    sanitizing, because a SID that fails here means an assumption broke upstream
    and quietly writing the audio somewhere "close enough" would hide that.
    """
    from types import SimpleNamespace

    from apps.runtime.providers.recording import (
        FakeRecordingBackend,
        recording_path_for,
    )

    hostile = SimpleNamespace(tenant_id=tenant_a.pk, location_id=location_a1.pk,
                              provider_call_sid='../../../../99/1/pwned', pk=1)
    with pytest.raises(ValueError):
        recording_path_for(hostile)
    with pytest.raises(ValueError):
        FakeRecordingBackend().finalize(hostile, should_record=True)

    ok = SimpleNamespace(tenant_id=tenant_a.pk, location_id=location_a1.pk,
                         provider_call_sid='CAbeef', pk=1)
    assert recording_path_for(ok) == (
        f'private/calls/{tenant_a.pk}/{location_a1.pk}/CAbeef.wav')


def test_get_is_method_not_allowed(db):
    assert Client().get(WEBHOOK_PATH).status_code == 405


# --------------------------------------------------------------------------- #
# Reason-code logging — each termination branch logs its closed-set REASON_*
# code, and NEVER the caller/dialed number or the signature (PII discipline).
#
# `apps.runtime.webhooks` is a descendant of the `apps` logger, and
# `config.settings.LOGGING` configures `apps` with `propagate: False` (its own
# console handler instead) — so caplog's handler, which lives on the ROOT
# logger, never sees these records via propagation no matter what level is set
# on the originating logger. `_capture_apps_logs` restores propagation for the
# duration of one test (via `monkeypatch`, auto-reverted) and raises the
# originating logger's level past the suite's ERROR pin, exactly as the task
# note anticipates.
# --------------------------------------------------------------------------- #

@pytest.fixture
def _capture_apps_logs(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger='apps.runtime.webhooks')
    monkeypatch.setattr(logging.getLogger('apps'), 'propagate', True)
    return caplog


def test_unmapped_decline_logs_reason_without_pii(_capture_apps_logs):
    # No AgentSetting exists anywhere, so this number is unmapped.
    params = _params(to='+19998887777', frm='+13125559999')
    Client().post(WEBHOOK_PATH, params)

    assert 'unmapped' in _capture_apps_logs.text
    assert params['To'] not in _capture_apps_logs.text
    assert params['From'] not in _capture_apps_logs.text


def test_disabled_decline_logs_reason_without_pii(
    _capture_apps_logs, make_agent_setting, tenant_a, location_a1,
):
    setting = make_agent_setting(tenant_a, location_a1, enabled=False)
    params = _params(to=setting.inbound_phone_number, frm='+13125559999')
    _post_signed(Client(), setting.twilio_auth_token, params)

    assert 'disabled' in _capture_apps_logs.text
    assert 'unmapped' not in _capture_apps_logs.text
    assert params['To'] not in _capture_apps_logs.text
    assert params['From'] not in _capture_apps_logs.text


def test_invalid_signature_logs_reason_without_pii_or_signature(
    _capture_apps_logs, make_agent_setting, tenant_a, location_a1,
):
    setting = make_agent_setting(tenant_a, location_a1)
    params = _params(to=setting.inbound_phone_number, frm='+13125559999')
    bad_signature = twilio_signature('the-wrong-token', WEBHOOK_PATH, params)
    Client().post(WEBHOOK_PATH, params, HTTP_X_TWILIO_SIGNATURE=bad_signature)

    assert 'signature_invalid' in _capture_apps_logs.text
    assert params['To'] not in _capture_apps_logs.text
    assert params['From'] not in _capture_apps_logs.text
    assert bad_signature not in _capture_apps_logs.text


def test_missing_callsid_logs_reason_without_pii(
    _capture_apps_logs, make_agent_setting, tenant_a, location_a1,
):
    setting = make_agent_setting(tenant_a, location_a1)
    params = {'To': setting.inbound_phone_number, 'From': '+13125559999'}  # no CallSid
    _post_signed(Client(), setting.twilio_auth_token, params)

    assert 'missing_callsid' in _capture_apps_logs.text
    assert params['To'] not in _capture_apps_logs.text
    assert params['From'] not in _capture_apps_logs.text


def test_duplicate_delivery_logs_reason_without_pii(
    _capture_apps_logs, make_agent_setting, tenant_a, location_a1,
):
    setting = make_agent_setting(tenant_a, location_a1)
    params = _params(to=setting.inbound_phone_number, frm='+13125559999')
    client = Client()

    # The first delivery creates the session silently (no reason code logged for
    # a fresh create); the redelivery is the branch under test.
    _post_signed(client, setting.twilio_auth_token, params)
    _capture_apps_logs.clear()
    _post_signed(client, setting.twilio_auth_token, params)

    assert 'duplicate_delivery' in _capture_apps_logs.text
    assert params['To'] not in _capture_apps_logs.text
    assert params['From'] not in _capture_apps_logs.text


# --------------------------------------------------------------------------- #
# Webhook edge cases: the `Called` fallback, an empty `To`, and `mode` mirroring
# the resolved location's configured voice provider.
# --------------------------------------------------------------------------- #

def test_called_param_used_when_to_is_absent(make_agent_setting, tenant_a, location_a1):
    # Twilio sends both `To` and `Called` on a real call; the view falls back to
    # `Called` when `To` is missing so a request shaped either way still resolves.
    setting = make_agent_setting(tenant_a, location_a1)
    params = {
        'Called': setting.inbound_phone_number,
        'From': '+13125550101',
        'CallSid': 'CA' + 'b' * 32,
    }
    resp = _post_signed(Client(), setting.twilio_auth_token, params)

    assert resp.status_code == 200
    assert '<Connect>' in resp.content.decode()
    session = CallSession.objects.get(provider_call_sid=params['CallSid'])
    assert session.to_number == setting.inbound_phone_number
    assert session.tenant_id == tenant_a.pk and session.location_id == location_a1.pk


def test_empty_to_declines_zero_writes(db):
    # An empty `To` (and no `Called` either) resolves nothing — same decline path
    # as an unmapped number, zero writes.
    resp = Client().post(WEBHOOK_PATH, _params(to=''))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert '<Say' in body and '<Hangup' in body and '<Connect>' not in body
    assert CallSession.objects.count() == 0


def test_session_mode_mirrors_agent_settings_voice_provider(
    make_agent_setting, tenant_a, location_a1,
):
    setting = make_agent_setting(
        tenant_a, location_a1, voice_provider=AgentSetting.VOICE_GOOGLE,
    )
    params = _params(to=setting.inbound_phone_number)
    resp = _post_signed(Client(), setting.twilio_auth_token, params)

    assert resp.status_code == 200
    session = CallSession.objects.get(provider_call_sid=params['CallSid'])
    assert session.mode == AgentSetting.VOICE_GOOGLE == setting.voice_provider
