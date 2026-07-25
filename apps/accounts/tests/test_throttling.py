"""Direct unit tests for `apps/accounts/throttling.py`.

This module has no model and no request — it is a thin wrapper over the Django
cache, keyed by `(customer_id, identifier)` AND by client IP independently, so
that a targeted guess against one account and a spraying run across many
accounts are both rate-limited. End-to-end throttling through `login_view` is
covered in `test_auth_views.py`; this file proves the module's own contract in
isolation.
"""
import pytest

from apps.accounts import throttling


def test_build_keys_includes_account_and_ip_when_both_given():
    keys = throttling.build_keys('ACME', 'user@example.test', '10.0.0.1')
    assert len(keys) == 2


def test_build_keys_omits_the_account_key_when_both_are_blank():
    keys = throttling.build_keys('', '', '10.0.0.1')
    assert len(keys) == 1


def test_build_keys_omits_the_ip_key_when_ip_is_blank():
    keys = throttling.build_keys('ACME', 'user@example.test', '')
    assert len(keys) == 1


def test_build_keys_is_case_insensitive():
    """Hashing lowercases the key material — 'ACME'/'user@x' and
    'acme'/'USER@X' must collide onto the same cache key."""
    keys_a = throttling.build_keys('ACME', 'user@x.test', '')
    keys_b = throttling.build_keys('acme', 'USER@X.TEST', '')
    assert keys_a == keys_b


def test_build_keys_never_stores_the_raw_value():
    """The cache key is a hash — the raw identifier/IP must not appear in it,
    so a cache dump never leaks a caller's email or IP verbatim."""
    keys = throttling.build_keys('ACME', 'someone@example.test', '203.0.113.5')
    joined = ' '.join(keys)
    assert 'someone@example.test' not in joined
    assert '203.0.113.5' not in joined


def test_is_throttled_false_with_no_recorded_failures(settings):
    keys = throttling.build_keys('ACME', 'fresh@example.test', '10.0.0.2')
    assert throttling.is_throttled(keys) is False


def test_register_failure_increments_up_to_the_limit(settings):
    settings.LOGIN_ATTEMPT_LIMIT = 3
    keys = throttling.build_keys('ACME', 'countme@example.test', '10.0.0.3')

    throttling.register_failure(keys)
    throttling.register_failure(keys)
    assert throttling.is_throttled(keys) is False

    throttling.register_failure(keys)
    assert throttling.is_throttled(keys) is True


def test_clear_resets_the_counters(settings):
    settings.LOGIN_ATTEMPT_LIMIT = 2
    keys = throttling.build_keys('ACME', 'clearme@example.test', '10.0.0.4')
    throttling.register_failure(keys)
    throttling.register_failure(keys)
    assert throttling.is_throttled(keys) is True

    throttling.clear(keys)
    assert throttling.is_throttled(keys) is False


def test_two_different_accounts_do_not_share_a_counter(settings):
    settings.LOGIN_ATTEMPT_LIMIT = 2
    keys_a = throttling.build_keys('ACME', 'alice@example.test', '')
    keys_b = throttling.build_keys('ACME', 'bob@example.test', '')

    throttling.register_failure(keys_a)
    throttling.register_failure(keys_a)

    assert throttling.is_throttled(keys_a) is True
    assert throttling.is_throttled(keys_b) is False


def test_ip_key_throttles_across_different_accounts_from_the_same_ip(settings):
    settings.LOGIN_ATTEMPT_LIMIT = 2
    keys_a = throttling.build_keys('ACME', 'alice2@example.test', '10.0.0.9')
    keys_b = throttling.build_keys('ACME', 'bob2@example.test', '10.0.0.9')

    throttling.register_failure(keys_a)
    throttling.register_failure(keys_a)

    # Different account, SAME source IP — the IP-scoped key is shared.
    assert throttling.is_throttled(keys_b) is True


def test_retry_after_seconds_matches_the_configured_window(settings):
    settings.LOGIN_ATTEMPT_WINDOW_SECONDS = 123
    assert throttling.retry_after_seconds() == 123
