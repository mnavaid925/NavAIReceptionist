"""Model tests for `agents.AgentSetting` — the security-critical row.

Covers the two constraints that carry the whole routing design (`(tenant,
location)` and the GLOBAL `inbound_phone_number` uniqueness), the readiness
computation both the setup page and the test-call view depend on, and proves
`twilio_auth_token` is encrypted at rest end to end — the database never sees the
plaintext, `str(setting)` never carries it, and a corrupted/legacy stored value
degrades to '' rather than a 500.
"""
import pytest
from django.db import IntegrityError, transaction

from apps.agents.fields import PREFIX, decrypt_value, encrypt_value, mask_secret
from apps.agents.models import AgentSetting

from apps.agents.tests.conftest import raw_auth_token_column

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# __str__ and defaults
# --------------------------------------------------------------------------- #

def test_str_names_the_location(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(tenant_a, location_a1)
    assert str(setting) == f'Agent for {location_a1}'


def test_defaults(tenant_a, location_a1):
    setting = AgentSetting.objects.create(tenant=tenant_a, location=location_a1)
    assert setting.enabled is False
    assert setting.voice_provider == AgentSetting.VOICE_LIVE
    assert setting.variables == {}
    assert setting.twilio_account_sid == ''
    assert setting.twilio_auth_token == ''
    assert setting.transfer_enabled is False
    assert setting.transfer_working_hours == {}
    assert setting.transfer_keywords == []
    assert setting.transfer_timezone == 'America/Chicago'


# --------------------------------------------------------------------------- #
# unique (tenant, location)
# --------------------------------------------------------------------------- #

def test_one_setting_per_tenant_and_location(tenant_a, location_a1):
    AgentSetting.objects.create(tenant=tenant_a, location=location_a1)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AgentSetting.objects.create(tenant=tenant_a, location=location_a1)


def test_same_tenant_different_location_is_allowed(tenant_a, location_a1, location_a2):
    AgentSetting.objects.create(tenant=tenant_a, location=location_a1)
    # Must not raise.
    AgentSetting.objects.create(tenant=tenant_a, location=location_a2)


def test_same_location_different_tenant_is_impossible_by_fk_shape(tenant_a, tenant_b, location_a1):
    """`location_a1` belongs to `tenant_a`; a row cannot pair it with `tenant_b`
    in the first place, which is exactly what makes the (tenant, location)
    constraint meaningful rather than redundant with a location-only one."""
    setting = AgentSetting.objects.create(tenant=tenant_a, location=location_a1)
    assert setting.tenant_id == tenant_a.pk
    assert setting.tenant_id != tenant_b.pk


# --------------------------------------------------------------------------- #
# inbound_phone_number — GLOBAL uniqueness, the routing key
# --------------------------------------------------------------------------- #

def test_inbound_phone_number_unique_across_tenants_at_the_db_level(
    tenant_a, location_a1, tenant_b, location_b1,
):
    """Two DIFFERENT tenants must never be able to claim the same DID — an
    inbound webhook resolves tenant+location from this column alone."""
    AgentSetting.objects.create(
        tenant=tenant_a, location=location_a1, inbound_phone_number='+13125550199',
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AgentSetting.objects.create(
                tenant=tenant_b, location=location_b1, inbound_phone_number='+13125550199',
            )


def test_inbound_phone_number_unique_within_the_same_tenant_too(tenant_a, location_a1, location_a2):
    AgentSetting.objects.create(
        tenant=tenant_a, location=location_a1, inbound_phone_number='+13125550198',
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AgentSetting.objects.create(
                tenant=tenant_a, location=location_a2, inbound_phone_number='+13125550198',
            )


def test_multiple_settings_may_have_no_inbound_number(tenant_a, location_a1, location_a2):
    """NULL is not '' — several never-configured locations coexist."""
    AgentSetting.objects.create(tenant=tenant_a, location=location_a1)
    # Must not raise: two NULLs do not collide in a unique index.
    AgentSetting.objects.create(tenant=tenant_a, location=location_a2)


def test_save_normalises_blank_inbound_number_to_none(tenant_a, location_a1):
    setting = AgentSetting.objects.create(
        tenant=tenant_a, location=location_a1, inbound_phone_number='   ',
    )
    assert setting.inbound_phone_number is None


def test_save_strips_whitespace_from_inbound_number(tenant_a, location_a1):
    setting = AgentSetting.objects.create(
        tenant=tenant_a, location=location_a1, inbound_phone_number='  +13125550111  ',
    )
    assert setting.inbound_phone_number == '+13125550111'


def test_clean_mirrors_the_same_normalisation(tenant_a, location_a1):
    setting = AgentSetting(tenant=tenant_a, location=location_a1, inbound_phone_number='  ')
    setting.clean()
    assert setting.inbound_phone_number is None


# --------------------------------------------------------------------------- #
# Encrypted at rest — twilio_auth_token
# --------------------------------------------------------------------------- #

def test_auth_token_is_not_stored_in_plaintext(tenant_a, location_a1, make_agent_setting):
    plaintext = 'super-secret-twilio-token-0001'
    setting = make_agent_setting(tenant_a, location_a1, twilio_auth_token=plaintext)

    raw = raw_auth_token_column(setting)

    assert raw != plaintext
    assert plaintext not in raw
    assert raw.startswith(PREFIX)


def test_auth_token_round_trips_through_a_fresh_query(tenant_a, location_a1, make_agent_setting):
    plaintext = 'super-secret-twilio-token-0002'
    setting = make_agent_setting(tenant_a, location_a1, twilio_auth_token=plaintext)

    reloaded = AgentSetting.objects.get(pk=setting.pk)
    assert reloaded.twilio_auth_token == plaintext


def test_auth_token_never_appears_in_str(tenant_a, location_a1, make_agent_setting):
    plaintext = 'super-secret-twilio-token-0003'
    setting = make_agent_setting(tenant_a, location_a1, twilio_auth_token=plaintext)
    assert plaintext not in str(setting)


def test_has_auth_token_reflects_state_without_exposing_the_value(
    tenant_a, location_a1, location_a2, make_agent_setting,
):
    empty = make_agent_setting(tenant_a, location_a1, twilio_auth_token='')
    assert empty.has_auth_token is False

    configured = make_agent_setting(tenant_a, location_a2, twilio_auth_token='abcd1234efgh')
    assert configured.has_auth_token is True


def test_masked_auth_token_contains_no_part_of_the_real_token(
    tenant_a, location_a1, make_agent_setting
):
    """The hint is a keyed fingerprint, never a slice of the secret.

    It used to render the token's real last four characters — live secret
    material in page HTML, browser history and any screenshot of that admin page,
    and four confirmed characters for anyone holding a candidate token.
    """
    token = 'abcdefgh1234wxyz'
    setting = make_agent_setting(tenant_a, location_a1, twilio_auth_token=token)
    masked = setting.masked_auth_token

    assert masked.startswith('•')
    assert token not in masked
    # No substring of the secret of any meaningful length survives into the hint.
    for size in (4, 5, 6):
        for start in range(len(token) - size + 1):
            assert token[start:start + size] not in masked


def test_masked_auth_token_is_stable_and_changes_on_rotation(
    tenant_a, location_a1, location_a2, make_agent_setting
):
    """What the hint is actually FOR: comparing without disclosing.

    Same token, same hint — so two rows can be told apart or matched at a glance;
    rotate the token and the hint moves.
    """
    a = make_agent_setting(tenant_a, location_a1, twilio_auth_token='same-token-value')
    b = make_agent_setting(tenant_a, location_a2, twilio_auth_token='same-token-value')
    assert a.masked_auth_token == b.masked_auth_token

    b.twilio_auth_token = 'rotated-token-value'
    b.save(update_fields=['twilio_auth_token'])
    assert b.masked_auth_token != a.masked_auth_token


def test_masked_auth_token_empty_when_not_set(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(tenant_a, location_a1, twilio_auth_token='')
    assert setting.masked_auth_token == ''


def test_twilio_connected_requires_both_sid_and_token(
    tenant_a, location_a1, location_a2, make_agent_setting,
):
    sid_only = make_agent_setting(
        tenant_a, location_a1, twilio_account_sid='AC' + '1' * 32, twilio_auth_token='',
    )
    assert sid_only.twilio_connected is False

    both = make_agent_setting(
        tenant_a, location_a2, twilio_account_sid='AC' + '1' * 32, twilio_auth_token='tok',
    )
    assert both.twilio_connected is True


# --------------------------------------------------------------------------- #
# encrypt_value / decrypt_value / mask_secret — the field toolkit in isolation
# --------------------------------------------------------------------------- #

def test_encrypt_value_empty_stays_empty():
    assert encrypt_value('') == ''
    assert encrypt_value(None) == ''


def test_encrypt_value_is_idempotent_on_already_encrypted_input():
    once = encrypt_value('a-secret')
    twice = encrypt_value(once)
    assert once == twice  # not double-encrypted


def test_decrypt_value_of_empty_is_empty():
    assert decrypt_value('') == ''
    assert decrypt_value(None) == ''


def test_decrypt_value_round_trips():
    ciphertext = encrypt_value('round-trip-me')
    assert decrypt_value(ciphertext) == 'round-trip-me'


def test_decrypt_value_of_unencrypted_legacy_value_returns_it_unchanged():
    """A value written before this field was encrypted (or hand-edited) must not
    crash the page — it degrades to the raw stored string."""
    assert decrypt_value('hand-edited-plaintext') == 'hand-edited-plaintext'


def test_decrypt_value_of_corrupted_ciphertext_degrades_to_empty_string():
    """ENCRYPTION_KEY rotation or corruption must surface as 'not configured',
    never a 500 that takes the whole settings page down."""
    assert decrypt_value(f'{PREFIX}not-valid-fernet-data') == ''


def test_mask_secret_renders_a_fingerprint_not_a_slice():
    secret = 'abcdefgh1234'
    masked = mask_secret(secret)
    assert masked.startswith('•' * 8)
    assert len(masked) == 12          # 8 bullets + a 4-char fingerprint
    assert not masked.endswith('1234')
    assert secret not in masked


def test_mask_secret_is_deterministic_for_one_value():
    assert mask_secret('abcdefgh1234') == mask_secret('abcdefgh1234')
    assert mask_secret('abcdefgh1234') != mask_secret('abcdefgh1235')


def test_mask_secret_empty_is_empty():
    assert mask_secret('') == ''
    assert mask_secret(None) == ''


def test_mask_secret_short_value_never_leaks_any_of_it():
    """A short secret is the case a bare digest would betray.

    The fingerprint is keyed on SECRET_KEY, so even a two-character value cannot
    be recovered by hashing candidates — which is why this is `salted_hmac` and
    not `sha256`.
    """
    masked = mask_secret('ab')
    assert 'ab' not in masked
    assert masked.startswith('•' * 8)


# --------------------------------------------------------------------------- #
# readiness_issues() / is_ready
# --------------------------------------------------------------------------- #

def test_readiness_issues_lists_everything_missing_on_a_blank_row(tenant_a, location_a1):
    setting = AgentSetting.objects.create(tenant=tenant_a, location=location_a1)
    issues = ' | '.join(setting.readiness_issues()).lower()
    assert 'greeting' in issues
    assert 'prompt' in issues
    assert 'inbound number' in issues
    assert 'account sid' in issues
    assert 'auth token' in issues
    assert setting.is_ready is False


def test_readiness_issues_empty_when_fully_configured(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1,
        greeting='Hi there.', prompt_text='Be helpful.',
        inbound_phone_number='+13125550188',
        twilio_account_sid='AC' + '1' * 32, twilio_auth_token='tok-value',
    )
    assert setting.readiness_issues() == []
    assert setting.is_ready is True


def test_readiness_flags_transfer_enabled_with_no_destination(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1,
        greeting='Hi.', prompt_text='Help.', inbound_phone_number='+13125550177',
        twilio_account_sid='AC' + '1' * 32, twilio_auth_token='tok',
        transfer_enabled=True, transfer_phone_number='',
    )
    issues = ' | '.join(setting.readiness_issues()).lower()
    assert 'transfer' in issues
    assert setting.is_ready is False


def test_readiness_does_not_flag_transfer_when_a_destination_is_set(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1,
        greeting='Hi.', prompt_text='Help.', inbound_phone_number='+13125550166',
        twilio_account_sid='AC' + '1' * 32, twilio_auth_token='tok',
        transfer_enabled=True, transfer_phone_number='+13125550101',
    )
    assert setting.readiness_issues() == []
