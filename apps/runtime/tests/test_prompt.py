"""`{{variable}}` rendering, the runtime variable set and `is_open_now`.

`build_variables` takes an explicit `now`, so these tests inject deterministic
tz-aware timestamps rather than freezing the clock — no network, no flake from
running the suite near local midnight.
"""
import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.accounts.models import User, UserLocation
from apps.calls.models import CallSession
from apps.runtime.agent import prompt as promptmod


# --------------------------------------------------------------------------- #
# render_template — the {{key}} substitution rule
# --------------------------------------------------------------------------- #

def test_missing_key_renders_empty_never_leaks_placeholder():
    assert promptmod.render_template('hi {{missing}}!', {}) == 'hi !'
    assert '{{' not in promptmod.render_template('{{a}}{{b}}{{c}}', {'b': 'X'})


def test_whitespace_tolerant_braces():
    variables = {'name': 'Ada'}
    assert promptmod.render_template('Hello {{name}}', variables) == 'Hello Ada'
    assert promptmod.render_template('Hello {{ name }}', variables) == 'Hello Ada'
    assert promptmod.render_template('Hello {{   name   }}', variables) == 'Hello Ada'


def test_render_template_empty_text_is_empty():
    assert promptmod.render_template('', {'a': '1'}) == ''
    assert promptmod.render_template(None, {'a': '1'}) == ''


def test_render_template_none_value_renders_empty_string():
    assert promptmod.render_template('x{{k}}y', {'k': None}) == 'xy'


# --------------------------------------------------------------------------- #
# is_open_now — literal 'yes'/'no', never derived by the model
# --------------------------------------------------------------------------- #

def test_location_is_open_now_empty_intervals_is_false():
    assert promptmod.location_is_open_now([], timezone.now()) is False


def test_location_is_open_now_start_inclusive_end_exclusive():
    intervals = [{'start_time': datetime.time(9, 0), 'end_time': datetime.time(17, 0),
                  'days': ['thu']}]
    thursday = datetime.datetime(2026, 7, 23, 9, 0, tzinfo=ZoneInfo('UTC'))  # exactly 9:00
    before_open = datetime.datetime(2026, 7, 23, 8, 59, tzinfo=ZoneInfo('UTC'))
    at_close = datetime.datetime(2026, 7, 23, 17, 0, tzinfo=ZoneInfo('UTC'))  # exclusive
    assert promptmod.location_is_open_now(intervals, thursday) is True
    assert promptmod.location_is_open_now(intervals, before_open) is False
    assert promptmod.location_is_open_now(intervals, at_close) is False


# --------------------------------------------------------------------------- #
# build_open_intervals — gathered from assigned providers' hours
# --------------------------------------------------------------------------- #

@pytest.fixture
def provider_with_hours(tenant_a, location_a1):
    """A provider assigned to location A1, open Mon-Fri 09:00-17:00 there."""
    user = User.objects.create_user(
        tenant=tenant_a, email='doc@acme-test.example', password='x',
        is_provider=True,
        provider_hours={
            str(location_a1.pk): [
                {'start_time': '09:00', 'end_time': '17:00',
                 'days': ['mon', 'tue', 'wed', 'thu', 'fri']},
            ],
        },
    )
    UserLocation.objects.create(tenant=tenant_a, user=user, location=location_a1)
    return user


def test_build_open_intervals_gathers_assigned_provider_hours(
    provider_with_hours, location_a1,
):
    intervals = promptmod.build_open_intervals(location_a1)
    assert len(intervals) == 1
    assert intervals[0]['days'] == ['mon', 'tue', 'wed', 'thu', 'fri']


def test_build_open_intervals_ignores_a_non_provider_assignment(
    tenant_a, location_a1,
):
    front_desk = User.objects.create_user(
        tenant=tenant_a, email='desk@acme-test.example', password='x',
        is_provider=False,
    )
    UserLocation.objects.create(tenant=tenant_a, user=front_desk, location=location_a1)
    assert promptmod.build_open_intervals(location_a1) == []


# --------------------------------------------------------------------------- #
# build_variables — the merged runtime map, portable strftime, LOCATION tz
# --------------------------------------------------------------------------- #

@pytest.fixture
def call_session(tenant_a, location_a1):
    return CallSession.objects.create(
        tenant=tenant_a, location=location_a1, provider_call_sid='PROMPT-1',
        from_number='+15005550006', to_number='+13125550140',
        status=CallSession.STATUS_IN_PROGRESS, mode=CallSession.MODE_LIVE,
        started_at=timezone.now(),
    )


def _agent_setting(**variables):
    return SimpleNamespace(variables=variables)


def test_runtime_vars_win_over_agent_setting_variables(call_session, location_a1):
    setting = _agent_setting(from_e164='OVERRIDDEN', custom_key='survives')
    now = timezone.now()
    variables = promptmod.build_variables(setting, call_session, location_a1, now, [])
    # AgentSetting.variables' own from_e164 is clobbered by the runtime value.
    assert variables['from_e164'] == call_session.from_number
    assert variables['from_e164'] != 'OVERRIDDEN'
    # An unrelated configured key merges through untouched.
    assert variables['custom_key'] == 'survives'


def test_build_variables_includes_the_full_runtime_key_set(call_session, location_a1):
    setting = _agent_setting()
    now = timezone.now()
    variables = promptmod.build_variables(setting, call_session, location_a1, now, [])
    for key in promptmod.RUNTIME_VAR_KEYS:
        assert key in variables


def test_is_open_now_yes_inside_provider_hours(
    provider_with_hours, location_a1, call_session,
):
    location_a1.timezone = 'America/Chicago'
    location_a1.save(update_fields=['timezone'])
    intervals = promptmod.build_open_intervals(location_a1)
    setting = _agent_setting()
    # Thursday 14:00 Chicago (CDT, UTC-5) = 19:00 UTC — inside 09:00-17:00.
    now = datetime.datetime(2026, 7, 23, 19, 0, tzinfo=ZoneInfo('UTC'))
    variables = promptmod.build_variables(setting, call_session, location_a1, now, intervals)
    assert variables['is_open_now'] == 'yes'


def test_is_open_now_no_outside_provider_hours(
    provider_with_hours, location_a1, call_session,
):
    location_a1.timezone = 'America/Chicago'
    location_a1.save(update_fields=['timezone'])
    intervals = promptmod.build_open_intervals(location_a1)
    setting = _agent_setting()
    # 22:00 Chicago the previous day = 03:00 UTC — well outside 09:00-17:00.
    now = datetime.datetime(2026, 7, 23, 3, 0, tzinfo=ZoneInfo('UTC'))
    variables = promptmod.build_variables(setting, call_session, location_a1, now, intervals)
    assert variables['is_open_now'] == 'no'


def test_current_date_time_render_in_the_locations_own_timezone(call_session, location_a1):
    location_a1.timezone = 'America/Chicago'
    location_a1.save(update_fields=['timezone'])
    setting = _agent_setting()
    now = datetime.datetime(2026, 7, 23, 19, 5, tzinfo=ZoneInfo('UTC'))  # 14:05 CDT
    variables = promptmod.build_variables(setting, call_session, location_a1, now, [])
    assert variables['current_date'] == 'Thursday, July 23, 2026'
    assert variables['current_time'] == '2:05 PM'


def test_current_date_time_are_portable_no_percent_dash_crash(call_session, location_a1):
    """Regression guard: %-d / %-I raise ValueError on the Windows dev host."""
    setting = _agent_setting()
    now = datetime.datetime(2026, 7, 1, 9, 5, tzinfo=ZoneInfo('UTC'))  # single-digit day/hour
    variables = promptmod.build_variables(setting, call_session, location_a1, now, [])
    assert variables['current_date'] and variables['current_time']
    assert '9:05 AM' == variables['current_time']


def test_agent_name_falls_back_when_not_configured(call_session, location_a1):
    setting = _agent_setting()
    now = timezone.now()
    variables = promptmod.build_variables(setting, call_session, location_a1, now, [])
    assert variables['agent_name'] == promptmod.DEFAULT_AGENT_NAME


def test_agent_name_uses_configured_value(call_session, location_a1):
    setting = _agent_setting(agent_name='Nova')
    now = timezone.now()
    variables = promptmod.build_variables(setting, call_session, location_a1, now, [])
    assert variables['agent_name'] == 'Nova'


def test_caller_display_name_blank_when_no_contact(call_session, location_a1):
    setting = _agent_setting()
    now = timezone.now()
    variables = promptmod.build_variables(setting, call_session, location_a1, now, [])
    assert variables['caller_display_name'] == ''


def test_caller_display_name_from_contact(call_session, location_a1):
    setting = _agent_setting()
    now = timezone.now()
    contact = SimpleNamespace(display_name='Priya Patel')
    variables = promptmod.build_variables(
        setting, call_session, location_a1, now, [], contact=contact,
    )
    assert variables['caller_display_name'] == 'Priya Patel'


# --------------------------------------------------------------------------- #
# render_greeting / render_system_prompt
# --------------------------------------------------------------------------- #

def test_render_greeting_falls_back_when_blank():
    setting = SimpleNamespace(greeting='')
    assert promptmod.render_greeting(setting, {}) == promptmod.DEFAULT_GREETING


def test_render_greeting_falls_back_when_whitespace_only():
    setting = SimpleNamespace(greeting='   ')
    assert promptmod.render_greeting(setting, {}) == promptmod.DEFAULT_GREETING


def test_render_greeting_renders_configured_text():
    setting = SimpleNamespace(greeting='Thanks for calling {{location_name}}.')
    result = promptmod.render_greeting(setting, {'location_name': 'Downtown'})
    assert result == 'Thanks for calling Downtown.'


def test_render_system_prompt_substitutes_variables():
    setting = SimpleNamespace(prompt_text='Open now: {{is_open_now}}.')
    assert promptmod.render_system_prompt(setting, {'is_open_now': 'yes'}) == 'Open now: yes.'
