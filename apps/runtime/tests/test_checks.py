"""The `runtime.E001` system check — deploy-time guard on the webhook base URL.

Outside `DEBUG`, an unset `TWILIO_WEBHOOK_BASE_URL` makes the Twilio signature
verify against the wrong URL for every genuine inbound call (it silently falls
back to the `Host` header), so this must fail LOUD at `manage.py check` /
deploy time rather than quietly break inbound. Inert under `DEBUG` on purpose —
a bare local run with no tunnel is expected.
"""
from django.core.checks import Error
from django.test import override_settings

from apps.runtime.apps import _check_webhook_base_url


def test_debug_false_empty_url_is_an_error():
    with override_settings(DEBUG=False, TWILIO_WEBHOOK_BASE_URL=''):
        errors = _check_webhook_base_url(None)
    assert len(errors) == 1
    assert isinstance(errors[0], Error)
    assert errors[0].id == 'runtime.E001'


def test_debug_false_whitespace_only_url_is_an_error():
    # The check strips before testing truthiness — a whitespace-only value must
    # not slip past as "set".
    with override_settings(DEBUG=False, TWILIO_WEBHOOK_BASE_URL='   '):
        errors = _check_webhook_base_url(None)
    assert len(errors) == 1
    assert errors[0].id == 'runtime.E001'


def test_debug_false_url_set_is_clean():
    with override_settings(DEBUG=False, TWILIO_WEBHOOK_BASE_URL='https://voice.example.test'):
        assert _check_webhook_base_url(None) == []


def test_debug_true_empty_url_is_clean():
    # DEBUG is inert to this check regardless of the URL — a bare local run with
    # no tunnel is expected and falls back to the request host on purpose.
    with override_settings(DEBUG=True, TWILIO_WEBHOOK_BASE_URL=''):
        assert _check_webhook_base_url(None) == []


def test_debug_true_url_set_is_clean():
    with override_settings(DEBUG=True, TWILIO_WEBHOOK_BASE_URL='https://voice.example.test'):
        assert _check_webhook_base_url(None) == []


def test_registered_with_the_app_registry():
    # Belt-and-suspenders: the check must actually be wired into Django's
    # check framework (via `RuntimeConfig.ready()`), not just importable.
    from django.core.checks import registry

    registered = {
        check for check in registry.registry.registered_checks
    }
    assert _check_webhook_base_url in registered
