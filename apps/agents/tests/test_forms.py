"""Form tests for Module 2 — `AgentConfigForm`, `TwilioConnectionForm`,
`TransferSettingsForm`.

`twilio_auth_token` is the highest-risk field in the product:
`TwilioConnectionForm` tests prove it structurally cannot reach a rendered page
(absent from `Meta.fields`, absent from `form.fields`) and that the write-only
`new_auth_token` box means a blank submit is "leave it alone", never "erase it".
"""
from types import SimpleNamespace

import pytest

from apps.agents.forms import MAX_KEYWORDS, AgentConfigForm, TransferSettingsForm, TwilioConnectionForm
from apps.agents.models import AgentSetting

pytestmark = pytest.mark.django_db

_WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']


def _fake_request(tenant=None, location=None, user=None):
    """Minimal duck-typed stand-in — `TenantModelForm`/`TenantLocationModelForm`
    only ever read `.tenant`, `.location` and `.user` off whatever is passed as
    `request=` (mirrors `apps.scheduling.tests.test_catalog_forms._fake_request`).
    """
    return SimpleNamespace(tenant=tenant, location=location, user=user)


# --------------------------------------------------------------------------- #
# AgentConfigForm (2.1)
# --------------------------------------------------------------------------- #

def test_agent_config_form_excludes_tenant_and_location(tenant_a, location_a1):
    form = AgentConfigForm(request=_fake_request(tenant_a, location_a1))
    assert 'tenant' not in form.fields
    assert 'location' not in form.fields


def test_agent_config_form_valid_minimal_submission(tenant_a, location_a1):
    form = AgentConfigForm({
        'voice_provider': AgentSetting.VOICE_LIVE,
        'greeting': 'Hello there.',
        'prompt_text': 'Be brief.',
        'variables_text': '',
    }, request=_fake_request(tenant_a, location_a1))
    assert form.is_valid(), form.errors


def test_agent_config_form_parses_variables_text(tenant_a, location_a1):
    form = AgentConfigForm({
        'voice_provider': AgentSetting.VOICE_LIVE,
        'greeting': 'Hi {{parking}}.',
        'prompt_text': 'Use {{parking}}.',
        'variables_text': 'parking = Street parking on Adams\n# a comment\n\n',
    }, request=_fake_request(tenant_a, location_a1))
    assert form.is_valid(), form.errors
    assert form.cleaned_data['variables_text'] == {'parking': 'Street parking on Adams'}


def test_agent_config_form_rejects_a_line_without_equals(tenant_a, location_a1):
    form = AgentConfigForm({
        'voice_provider': AgentSetting.VOICE_LIVE, 'greeting': '', 'prompt_text': '',
        'variables_text': 'not-a-valid-line',
    }, request=_fake_request(tenant_a, location_a1))
    assert not form.is_valid()
    assert 'variables_text' in form.errors


def test_agent_config_form_rejects_a_reserved_variable_name(tenant_a, location_a1):
    form = AgentConfigForm({
        'voice_provider': AgentSetting.VOICE_LIVE, 'greeting': '', 'prompt_text': '',
        'variables_text': 'current_time = 9am',
    }, request=_fake_request(tenant_a, location_a1))
    assert not form.is_valid()
    assert 'variables_text' in form.errors


def test_agent_config_form_rejects_a_duplicate_variable_name(tenant_a, location_a1):
    form = AgentConfigForm({
        'voice_provider': AgentSetting.VOICE_LIVE, 'greeting': '', 'prompt_text': '',
        'variables_text': 'parking = A\nparking = B',
    }, request=_fake_request(tenant_a, location_a1))
    assert not form.is_valid()


def test_agent_config_form_rejects_an_unknown_placeholder_in_the_greeting(tenant_a, location_a1):
    form = AgentConfigForm({
        'voice_provider': AgentSetting.VOICE_LIVE,
        'greeting': 'Hi {{nonexistent}}.', 'prompt_text': '',
        'variables_text': '',
    }, request=_fake_request(tenant_a, location_a1))
    assert not form.is_valid()
    assert 'greeting' in form.errors


def test_agent_config_form_rejects_an_unknown_placeholder_in_the_prompt(tenant_a, location_a1):
    form = AgentConfigForm({
        'voice_provider': AgentSetting.VOICE_LIVE,
        'greeting': '', 'prompt_text': 'Say {{nonexistent}}.',
        'variables_text': '',
    }, request=_fake_request(tenant_a, location_a1))
    assert not form.is_valid()
    assert 'prompt_text' in form.errors


def test_agent_config_form_requires_a_greeting_to_enable(tenant_a, location_a1):
    form = AgentConfigForm({
        'enabled': 'on', 'voice_provider': AgentSetting.VOICE_LIVE,
        'greeting': '', 'prompt_text': 'Be brief.', 'variables_text': '',
    }, request=_fake_request(tenant_a, location_a1))
    assert not form.is_valid()
    assert 'greeting' in form.errors


def test_agent_config_form_save_stamps_tenant_and_location(tenant_a, location_a1, tenant_b):
    form = AgentConfigForm({
        'voice_provider': AgentSetting.VOICE_LIVE, 'greeting': 'Hi.', 'prompt_text': 'Help.',
        'variables_text': '',
    }, request=_fake_request(tenant_a, location_a1))
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.tenant_id == tenant_a.pk
    assert obj.location_id == location_a1.pk


def test_agent_config_form_edit_prefills_variables_text_from_stored_dict(
    tenant_a, location_a1, make_agent_setting,
):
    setting = make_agent_setting(tenant_a, location_a1, variables={'parking': 'Free lot'})
    form = AgentConfigForm(instance=setting, request=_fake_request(tenant_a, location_a1))
    assert form.fields['variables_text'].initial == 'parking = Free lot'


# --------------------------------------------------------------------------- #
# TwilioConnectionForm (2.2) — the write-only credential
# --------------------------------------------------------------------------- #

def test_twilio_auth_token_is_not_a_form_field(tenant_a, location_a1):
    form = TwilioConnectionForm(request=_fake_request(tenant_a, location_a1))
    assert 'twilio_auth_token' not in form.fields


def test_twilio_auth_token_is_not_in_meta_fields():
    assert 'twilio_auth_token' not in TwilioConnectionForm.Meta.fields


def test_new_auth_token_field_never_renders_a_bound_value(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(tenant_a, location_a1, twilio_auth_token='super-secret-abcd')
    form = TwilioConnectionForm({
        'twilio_account_sid': 'AC' + '1' * 32,
        'inbound_phone_number': '',
        'new_auth_token': 'super-secret-abcd',  # the exact value posted this request
    }, instance=setting, request=_fake_request(tenant_a, location_a1))
    rendered = str(form['new_auth_token'])
    assert 'super-secret-abcd' not in rendered


def test_twilio_connection_form_rejects_a_sid_without_the_ac_prefix(tenant_a, location_a1):
    form = TwilioConnectionForm({
        'twilio_account_sid': 'XXnotasid', 'inbound_phone_number': '', 'new_auth_token': 'tok',
    }, request=_fake_request(tenant_a, location_a1))
    assert not form.is_valid()
    assert 'twilio_account_sid' in form.errors


def test_twilio_connection_form_rejects_a_sid_with_no_token(tenant_a, location_a1):
    form = TwilioConnectionForm({
        'twilio_account_sid': 'AC' + '1' * 32, 'inbound_phone_number': '', 'new_auth_token': '',
    }, request=_fake_request(tenant_a, location_a1))
    assert not form.is_valid()
    assert 'new_auth_token' in form.errors


def test_twilio_connection_form_rejects_a_non_e164_number(tenant_a, location_a1):
    form = TwilioConnectionForm({
        'twilio_account_sid': '', 'inbound_phone_number': '3125550100', 'new_auth_token': '',
    }, request=_fake_request(tenant_a, location_a1))
    assert not form.is_valid()
    assert 'inbound_phone_number' in form.errors


def test_twilio_connection_form_blank_number_becomes_none(tenant_a, location_a1):
    form = TwilioConnectionForm({
        'twilio_account_sid': '', 'inbound_phone_number': '', 'new_auth_token': '',
    }, request=_fake_request(tenant_a, location_a1))
    assert form.is_valid(), form.errors
    assert form.cleaned_data['inbound_phone_number'] is None


def test_twilio_connection_form_rejects_a_number_claimed_by_another_tenant(
    tenant_a, location_a1, tenant_b, location_b1, make_agent_setting,
):
    make_agent_setting(tenant_b, location_b1, inbound_phone_number='+13125550123')
    form = TwilioConnectionForm({
        'twilio_account_sid': '', 'inbound_phone_number': '+13125550123', 'new_auth_token': '',
    }, request=_fake_request(tenant_a, location_a1))
    assert not form.is_valid()
    error = str(form.errors['inbound_phone_number'])
    assert 'not available' in error.lower()
    # No enumeration: the message must not confirm which tenant owns it.
    assert tenant_b.name not in error
    assert tenant_b.slug not in error


def test_twilio_connection_form_rejects_a_number_claimed_within_the_same_tenant(
    tenant_a, location_a1, location_a2, make_agent_setting,
):
    make_agent_setting(tenant_a, location_a2, inbound_phone_number='+13125550124')
    form = TwilioConnectionForm({
        'twilio_account_sid': '', 'inbound_phone_number': '+13125550124', 'new_auth_token': '',
    }, request=_fake_request(tenant_a, location_a1))
    assert not form.is_valid()
    assert 'inbound_phone_number' in form.errors


def test_twilio_connection_form_allows_a_number_on_its_own_existing_row(
    tenant_a, location_a1, make_agent_setting,
):
    setting = make_agent_setting(tenant_a, location_a1, inbound_phone_number='+13125550188')
    form = TwilioConnectionForm({
        'twilio_account_sid': '', 'inbound_phone_number': '+13125550188', 'new_auth_token': '',
    }, instance=setting, request=_fake_request(tenant_a, location_a1))
    assert form.is_valid(), form.errors


def test_twilio_connection_form_blank_submit_does_not_wipe_an_existing_token(
    tenant_a, location_a1, make_agent_setting,
):
    setting = make_agent_setting(tenant_a, location_a1, twilio_auth_token='original-token-value')
    form = TwilioConnectionForm({
        'twilio_account_sid': '', 'inbound_phone_number': '', 'new_auth_token': '',
    }, instance=setting, request=_fake_request(tenant_a, location_a1))
    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.twilio_auth_token == 'original-token-value'


def test_twilio_connection_form_a_new_value_replaces_the_stored_token(
    tenant_a, location_a1, make_agent_setting,
):
    setting = make_agent_setting(tenant_a, location_a1, twilio_auth_token='old-token-value')
    form = TwilioConnectionForm({
        'twilio_account_sid': '', 'inbound_phone_number': '', 'new_auth_token': 'brand-new-token-value',
    }, instance=setting, request=_fake_request(tenant_a, location_a1))
    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.twilio_auth_token == 'brand-new-token-value'


def test_twilio_connection_form_save_stamps_tenant_and_location(tenant_a, location_a1):
    form = TwilioConnectionForm({
        'twilio_account_sid': '', 'inbound_phone_number': '', 'new_auth_token': '',
    }, request=_fake_request(tenant_a, location_a1))
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.tenant_id == tenant_a.pk
    assert obj.location_id == location_a1.pk


# --------------------------------------------------------------------------- #
# TransferSettingsForm (2.3)
# --------------------------------------------------------------------------- #

def test_transfer_settings_form_excludes_tenant_and_location(tenant_a, location_a1):
    form = TransferSettingsForm(request=_fake_request(tenant_a, location_a1))
    assert 'tenant' not in form.fields
    assert 'location' not in form.fields


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


def test_transfer_settings_form_disabled_minimal_is_valid(tenant_a, location_a1):
    form = TransferSettingsForm(_transfer_data(), request=_fake_request(tenant_a, location_a1))
    assert form.is_valid(), form.errors


def test_transfer_settings_form_requires_a_destination_when_enabled(tenant_a, location_a1):
    form = TransferSettingsForm(
        _transfer_data(transfer_enabled='on'), request=_fake_request(tenant_a, location_a1),
    )
    assert not form.is_valid()
    assert 'transfer_phone_number' in form.errors


def test_transfer_settings_form_rejects_a_non_e164_destination(tenant_a, location_a1):
    form = TransferSettingsForm(
        _transfer_data(transfer_enabled='on', transfer_phone_number='5550100'),
        request=_fake_request(tenant_a, location_a1),
    )
    assert not form.is_valid()
    assert 'transfer_phone_number' in form.errors


def test_transfer_settings_form_rejects_a_non_e164_secondary_destination(tenant_a, location_a1):
    form = TransferSettingsForm(
        _transfer_data(transfer_secondary_number='not-a-number'),
        request=_fake_request(tenant_a, location_a1),
    )
    assert not form.is_valid()
    assert 'transfer_secondary_number' in form.errors


def test_transfer_settings_form_builds_the_weekly_hours_json(tenant_a, location_a1):
    form = TransferSettingsForm(
        _transfer_data(
            transfer_enabled='on', transfer_phone_number='+13125550101',
            monday_enabled='on', monday_start='09:00', monday_end='17:00',
        ),
        request=_fake_request(tenant_a, location_a1),
    )
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.transfer_working_hours['monday'] == {'enabled': True, 'start': '09:00', 'end': '17:00'}
    assert obj.transfer_working_hours['tuesday'] == {'enabled': False, 'start': '', 'end': ''}


def test_transfer_settings_form_rejects_an_enabled_day_missing_times(tenant_a, location_a1):
    form = TransferSettingsForm(
        _transfer_data(monday_enabled='on'),
        request=_fake_request(tenant_a, location_a1),
    )
    assert not form.is_valid()
    assert 'monday_start' in form.errors


def test_transfer_settings_form_rejects_an_end_time_before_start(tenant_a, location_a1):
    form = TransferSettingsForm(
        _transfer_data(monday_enabled='on', monday_start='17:00', monday_end='09:00'),
        request=_fake_request(tenant_a, location_a1),
    )
    assert not form.is_valid()
    assert 'monday_end' in form.errors


def test_transfer_settings_form_keywords_are_lowercased_and_deduplicated(tenant_a, location_a1):
    form = TransferSettingsForm(
        _transfer_data(keywords_text='Front Desk\nfront desk\nreception'),
        request=_fake_request(tenant_a, location_a1),
    )
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.transfer_keywords == ['front desk', 'reception']


def test_transfer_settings_form_rejects_too_many_keywords(tenant_a, location_a1):
    lines = '\n'.join(f'phrase-{i}' for i in range(MAX_KEYWORDS + 1))
    form = TransferSettingsForm(
        _transfer_data(keywords_text=lines), request=_fake_request(tenant_a, location_a1),
    )
    assert not form.is_valid()
    assert 'keywords_text' in form.errors


def test_transfer_settings_form_day_rows_covers_all_seven_days(tenant_a, location_a1):
    form = TransferSettingsForm(request=_fake_request(tenant_a, location_a1))
    assert len(form.day_rows) == 7


def test_transfer_settings_form_save_stamps_tenant_and_location(tenant_a, location_a1):
    form = TransferSettingsForm(_transfer_data(), request=_fake_request(tenant_a, location_a1))
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.tenant_id == tenant_a.pk
    assert obj.location_id == location_a1.pk
