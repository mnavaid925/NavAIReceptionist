"""Pure-function tests for `apps/agents/services.py` — prompt rendering (2.1)
and transfer gating (2.3).

Every test that cares about "now" injects it via the `now=` kwarg these
functions accept, rather than freezing the wall clock or `datetime.date.today()`
— that is exactly the point of the parameter, and it keeps these tests portable
and deterministic on a Windows host.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.agents.services import (
    build_runtime_context,
    extract_variable_names,
    is_transfer_available,
    matches_transfer_keyword,
    next_transfer_window,
    render_template,
    resolve_transfer_number,
    sample_runtime_context,
    unknown_variable_names,
)

pytestmark = pytest.mark.django_db

UTC = ZoneInfo('UTC')

# 2026-03-09 is a Monday; 2026-03-10 is a Tuesday.
MONDAY_09_00 = datetime(2026, 3, 9, 9, 0, tzinfo=UTC)
MONDAY_12_00 = datetime(2026, 3, 9, 12, 0, tzinfo=UTC)
MONDAY_20_00 = datetime(2026, 3, 9, 20, 0, tzinfo=UTC)
TUESDAY_12_00 = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# extract_variable_names / unknown_variable_names / render_template
# --------------------------------------------------------------------------- #

def test_extract_variable_names_preserves_first_appearance_order():
    assert extract_variable_names('Hi {{b}}, {{a}}, {{b}} again') == ['b', 'a']


def test_extract_variable_names_empty_text():
    assert extract_variable_names('') == []
    assert extract_variable_names(None) == []


def test_unknown_variable_names_excludes_reserved_and_known():
    unknown = unknown_variable_names('{{business_name}} {{parking}} {{missing}}', {'parking': 'x'})
    assert unknown == ['missing']


def test_render_template_substitutes_known_names():
    assert render_template('Hi {{name}}!', {'name': 'Ada'}) == 'Hi Ada!'


def test_render_template_unknown_placeholder_renders_empty():
    assert render_template('Gap: [{{missing}}]', {}) == 'Gap: []'


def test_render_template_none_value_renders_empty():
    assert render_template('X{{n}}Y', {'n': None}) == 'XY'


def test_render_template_empty_text():
    assert render_template('', {'a': '1'}) == ''
    assert render_template(None, {}) == ''


def test_render_template_does_not_execute_a_template_engine():
    """Dotted/attribute access is left untouched — this is plain named
    substitution over TENANT-authored text a caller's speech is rendered into,
    never Django's real template engine."""
    out = render_template('{{obj.__class__}}', {'obj': 'anything'})
    assert out == '{{obj.__class__}}'


# --------------------------------------------------------------------------- #
# build_runtime_context / sample_runtime_context
# --------------------------------------------------------------------------- #

def test_build_runtime_context_reserved_values_win_over_the_tenant_map(
    tenant_a, location_a1, make_agent_setting,
):
    setting = make_agent_setting(tenant_a, location_a1, variables={'business_name': 'Should not win'})
    ctx = build_runtime_context(setting, from_number='+13125550001', now=MONDAY_12_00)
    assert ctx['business_name'] == tenant_a.name
    assert ctx['location_name'] == location_a1.name
    assert ctx['from_number'] == '+13125550001'
    assert ctx['is_open_now'] == 'yes'


def test_build_runtime_context_date_and_time_are_portable_strftime_forms(
    tenant_a, location_a1, make_agent_setting,
):
    setting = make_agent_setting(tenant_a, location_a1)
    now = datetime(2026, 1, 5, 9, 5, tzinfo=UTC)
    ctx = build_runtime_context(setting, now=now)
    assert ctx['current_date'] == '2026-01-05'
    assert ctx['current_time'] == '09:05'


def test_build_runtime_context_transfer_flags_reflect_is_transfer_available(
    tenant_a, location_a1, make_agent_setting,
):
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='+13125550101',
        transfer_timezone='UTC',
    )
    ctx = build_runtime_context(setting, now=MONDAY_12_00)  # empty hours -> always available
    assert ctx['transfer_available'] == 'yes'

    setting.transfer_enabled = False
    ctx = build_runtime_context(setting, now=MONDAY_12_00)
    assert ctx['transfer_available'] == 'no'


def test_sample_runtime_context_uses_a_fixed_placeholder_number(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(tenant_a, location_a1)
    ctx = sample_runtime_context(setting)
    assert ctx['from_number'] == '+13125550000'


# --------------------------------------------------------------------------- #
# is_transfer_available
# --------------------------------------------------------------------------- #

def test_transfer_unavailable_when_disabled(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(tenant_a, location_a1, transfer_enabled=False)
    assert is_transfer_available(setting, now=MONDAY_12_00) is False


def test_transfer_unavailable_with_no_destination(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='')
    assert is_transfer_available(setting, now=MONDAY_12_00) is False


def test_transfer_available_with_empty_hours_means_no_restriction(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='+13125550101',
        transfer_working_hours={},
    )
    assert is_transfer_available(setting, now=MONDAY_20_00) is True


def test_transfer_available_inside_the_configured_window(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='+13125550101',
        transfer_timezone='UTC',
        transfer_working_hours={'monday': {'enabled': True, 'start': '09:00', 'end': '17:00'}},
    )
    assert is_transfer_available(setting, now=MONDAY_12_00) is True


def test_transfer_unavailable_outside_the_configured_window(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='+13125550101',
        transfer_timezone='UTC',
        transfer_working_hours={'monday': {'enabled': True, 'start': '09:00', 'end': '17:00'}},
    )
    assert is_transfer_available(setting, now=MONDAY_20_00) is False


def test_transfer_unavailable_exactly_at_the_end_boundary(tenant_a, location_a1, make_agent_setting):
    """The window is a half-open interval `[start, end)` — the end minute is
    already closed."""
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='+13125550101',
        transfer_timezone='UTC',
        transfer_working_hours={'monday': {'enabled': True, 'start': '09:00', 'end': '17:00'}},
    )
    at_end = datetime(2026, 3, 9, 17, 0, tzinfo=UTC)
    assert is_transfer_available(setting, now=at_end) is False


def test_transfer_unavailable_on_a_day_not_listed(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='+13125550101',
        transfer_timezone='UTC',
        transfer_working_hours={'monday': {'enabled': True, 'start': '09:00', 'end': '17:00'}},
    )
    assert is_transfer_available(setting, now=TUESDAY_12_00) is False


def test_transfer_unavailable_when_the_day_entry_is_present_but_disabled(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='+13125550101',
        transfer_timezone='UTC',
        transfer_working_hours={'monday': {'enabled': False, 'start': '09:00', 'end': '17:00'}},
    )
    assert is_transfer_available(setting, now=MONDAY_12_00) is False


def test_transfer_availability_is_evaluated_in_the_configured_transfer_timezone(
    tenant_a, location_a1, make_agent_setting,
):
    """The SAME UTC instant reads as Monday 16:30 in Los Angeles and Tuesday
    08:30 in Tokyo — proves the window is evaluated in `transfer_timezone`, not
    UTC or the test host's zone."""
    moment = datetime(2026, 3, 9, 23, 30, tzinfo=UTC)
    hours = {'monday': {'enabled': True, 'start': '09:00', 'end': '17:00'}}

    la_setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='+13125550101',
        transfer_timezone='America/Los_Angeles', transfer_working_hours=hours,
    )
    assert is_transfer_available(la_setting, now=moment) is True  # Monday 16:30 LA — inside

    la_setting.transfer_timezone = 'Asia/Tokyo'
    assert is_transfer_available(la_setting, now=moment) is False  # Tuesday 08:30 Tokyo — not listed


def test_transfer_availability_falls_back_to_utc_on_an_invalid_timezone_string(
    tenant_a, location_a1, make_agent_setting,
):
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='+13125550101',
        transfer_timezone='Not/AZone',
        transfer_working_hours={'monday': {'enabled': True, 'start': '09:00', 'end': '17:00'}},
    )
    assert is_transfer_available(setting, now=MONDAY_12_00) is True  # 12:00 UTC — inside, if UTC is used


def test_transfer_unavailable_when_hours_is_not_a_dict(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='+13125550101',
        transfer_working_hours=[],
    )
    # A malformed/legacy shape must not raise — falsy/non-dict degrades to "no
    # restriction", the same as an empty dict.
    assert is_transfer_available(setting, now=MONDAY_12_00) is True


# --------------------------------------------------------------------------- #
# next_transfer_window
# --------------------------------------------------------------------------- #

def test_next_transfer_window_empty_when_disabled(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(tenant_a, location_a1, transfer_enabled=False)
    assert next_transfer_window(setting, now=MONDAY_12_00) == ''


def test_next_transfer_window_empty_with_no_destination(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='')
    assert next_transfer_window(setting, now=MONDAY_12_00) == ''


def test_next_transfer_window_empty_when_hours_unrestricted(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='+13125550101',
        transfer_working_hours={},
    )
    assert next_transfer_window(setting, now=MONDAY_12_00) == ''


def test_next_transfer_window_empty_when_every_day_is_disabled(tenant_a, location_a1, make_agent_setting):
    hours = {day: {'enabled': False, 'start': '', 'end': ''} for day in (
        'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
    )}
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='+13125550101',
        transfer_working_hours=hours,
    )
    assert next_transfer_window(setting, now=MONDAY_12_00) == ''


def test_next_transfer_window_finds_a_later_day_this_week(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='+13125550101',
        transfer_timezone='UTC',
        transfer_working_hours={'wednesday': {'enabled': True, 'start': '10:00', 'end': '12:00'}},
    )
    # Monday 08:00 -> next occurrence is Wednesday.
    monday_08 = datetime(2026, 3, 9, 8, 0, tzinfo=UTC)
    assert next_transfer_window(setting, now=monday_08) == 'Wednesday 10:00'


def test_next_transfer_window_before_todays_start_returns_today(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='+13125550101',
        transfer_timezone='UTC',
        transfer_working_hours={'monday': {'enabled': True, 'start': '09:00', 'end': '17:00'}},
    )
    before_start = datetime(2026, 3, 9, 7, 0, tzinfo=UTC)
    assert next_transfer_window(setting, now=before_start) == 'Monday 09:00'


def test_next_transfer_window_when_currently_inside_the_window_reports_the_next_occurrence(
    tenant_a, location_a1, make_agent_setting,
):
    """When the window is ALREADY open (e.g. Monday 10:00 inside a 09:00-17:00
    Monday-only window), the "next" opening is deliberately the FOLLOWING
    occurrence (next Monday), not "right now" — this value is meant for the
    off-hours message, and is paired with `transfer_available == 'yes'` in that
    state."""
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='+13125550101',
        transfer_timezone='UTC',
        transfer_working_hours={'monday': {'enabled': True, 'start': '09:00', 'end': '17:00'}},
    )
    assert next_transfer_window(setting, now=MONDAY_12_00) == 'Monday 09:00'


# --------------------------------------------------------------------------- #
# resolve_transfer_number — Invariant-3-adjacent: LABEL in, never a number
# --------------------------------------------------------------------------- #

def test_resolve_transfer_number_disabled_returns_nothing(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=False, transfer_phone_number='+13125550101',
    )
    assert resolve_transfer_number(setting) == ''


def test_resolve_transfer_number_primary_is_the_default(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='+13125550101',
    )
    assert resolve_transfer_number(setting) == '+13125550101'
    assert resolve_transfer_number(setting, target='primary') == '+13125550101'


def test_resolve_transfer_number_secondary_when_configured(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True,
        transfer_phone_number='+13125550101', transfer_secondary_number='+13125550102',
    )
    assert resolve_transfer_number(setting, target='secondary') == '+13125550102'


def test_resolve_transfer_number_secondary_falls_back_to_primary_when_unset(
    tenant_a, location_a1, make_agent_setting,
):
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True,
        transfer_phone_number='+13125550101', transfer_secondary_number='',
    )
    assert resolve_transfer_number(setting, target='secondary') == '+13125550101'


def test_resolve_transfer_number_never_echoes_a_caller_or_model_supplied_number(
    tenant_a, location_a1, make_agent_setting,
):
    """THE Invariant-3 enforcement point for transfers: the function accepts a
    LABEL, never a number. Any string that is not literally 'secondary' — even
    one shaped like a phone number an attacker-controlled model tried to smuggle
    through — resolves through the 'primary' branch and returns the SERVER's
    own configured number, never the input."""
    setting = make_agent_setting(
        tenant_a, location_a1, transfer_enabled=True, transfer_phone_number='+13125550101',
    )
    smuggled = '+19995551234'
    assert resolve_transfer_number(setting, target=smuggled) == '+13125550101'
    assert resolve_transfer_number(setting, target=smuggled) != smuggled


# --------------------------------------------------------------------------- #
# matches_transfer_keyword
# --------------------------------------------------------------------------- #

def test_matches_transfer_keyword_empty_utterance_is_false():
    assert matches_transfer_keyword('') is False
    assert matches_transfer_keyword(None) is False


def test_matches_transfer_keyword_builtin_matches_case_insensitively():
    assert matches_transfer_keyword('Can I speak to a HUMAN please?') is True


def test_matches_transfer_keyword_no_match_returns_false():
    assert matches_transfer_keyword('What time do you close?') is False


def test_matches_transfer_keyword_custom_phrase_is_added_not_substituted(
    tenant_a, location_a1, make_agent_setting,
):
    setting = make_agent_setting(tenant_a, location_a1, transfer_keywords=['front desk'])
    assert matches_transfer_keyword('put me through to the front desk', setting) is True
    # Built-ins still active alongside the custom list.
    assert matches_transfer_keyword('let me talk to a human', setting) is True


def test_matches_transfer_keyword_handles_a_non_list_stored_value(tenant_a, location_a1, make_agent_setting):
    setting = make_agent_setting(tenant_a, location_a1, transfer_keywords={'not': 'a list'})
    # Must not raise — degrades to built-ins only.
    assert matches_transfer_keyword('emergency', setting) is True
    assert matches_transfer_keyword('something unrelated', setting) is False


def test_matches_transfer_keyword_none_setting_still_matches_builtins():
    assert matches_transfer_keyword('get me a manager', setting=None) is True
