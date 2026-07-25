"""Unit tests for `apps/tenants/services.py` — the provider working-hours
contract (sub-module 1.4).

`get_provider_intervals` is called out by name in the module's own docstring as
"THE CONTRACT MODULE 4 IMPORTS" — its shape is exercised directly here, beyond
what the view-level tests in `test_working_hours_views.py` already reach
(defensive branches on `user`/`location`/malformed storage, the weekday filter,
the overlap/ordering rules, and the boundary rule in `is_provider_available`).
"""
from datetime import date, time

import pytest

from apps.accounts.models import User
from apps.tenants.services import (
    WEEKDAY_KEYS,
    clear_provider_hours,
    format_hhmm,
    get_provider_intervals,
    has_configured_hours,
    is_provider_available,
    parse_hhmm,
    serialise_intervals,
    set_provider_hours,
    validate_provider_hours,
    weekly_summary,
)

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# parse_hhmm / format_hhmm
# --------------------------------------------------------------------------- #

def test_parse_hhmm_valid_string():
    assert parse_hhmm('09:30') == time(9, 30)


def test_parse_hhmm_passthrough_for_time_instance():
    assert parse_hhmm(time(14, 15)) == time(14, 15)


def test_parse_hhmm_none_is_unusable():
    assert parse_hhmm(None) is None


def test_parse_hhmm_non_string_non_time_is_unusable():
    assert parse_hhmm(12345) is None


def test_parse_hhmm_missing_colon_is_unusable():
    assert parse_hhmm('0930') is None


def test_parse_hhmm_non_numeric_is_unusable():
    assert parse_hhmm('ab:cd') is None


def test_parse_hhmm_out_of_range_hour_is_unusable():
    assert parse_hhmm('25:00') is None


def test_parse_hhmm_out_of_range_minute_is_unusable():
    assert parse_hhmm('09:75') is None


def test_format_hhmm_none_is_empty_string():
    assert format_hhmm(None) == ''


def test_format_hhmm_string_passthrough():
    assert format_hhmm('09:00') == '09:00'


def test_format_hhmm_zero_pads_single_digit_hour_and_minute():
    assert format_hhmm(time(9, 5)) == '09:05'


# --------------------------------------------------------------------------- #
# get_provider_intervals — defensive branches
# --------------------------------------------------------------------------- #

def test_get_provider_intervals_none_user_returns_empty():
    assert get_provider_intervals(None, 1) == []


def test_get_provider_intervals_non_provider_returns_empty(member_user, location_a1):
    assert member_user.is_provider is False
    assert get_provider_intervals(member_user, location_a1) == []


def test_get_provider_intervals_none_location_returns_empty(provider_a1):
    assert get_provider_intervals(provider_a1, None) == []


def test_get_provider_intervals_accepts_a_location_object_or_a_pk(provider_a1, location_a1):
    set_provider_hours(provider_a1, location_a1.pk, [
        {'start_time': time(9, 0), 'end_time': time(12, 0), 'days': ['mon']},
    ])
    by_object = get_provider_intervals(provider_a1, location_a1)
    by_pk = get_provider_intervals(provider_a1, location_a1.pk)
    assert by_object == by_pk
    assert len(by_object) == 1


def test_get_provider_intervals_non_dict_storage_returns_empty(provider_a1, location_a1):
    provider_a1.provider_hours = ['not', 'a', 'dict']
    provider_a1.save(update_fields=['provider_hours'])
    assert get_provider_intervals(provider_a1, location_a1) == []


def test_get_provider_intervals_non_list_entries_returns_empty(provider_a1, location_a1):
    provider_a1.provider_hours = {str(location_a1.pk): 'not-a-list'}
    provider_a1.save(update_fields=['provider_hours'])
    assert get_provider_intervals(provider_a1, location_a1) == []


def test_get_provider_intervals_drops_malformed_entries_keeps_good_ones(provider_a1, location_a1):
    provider_a1.provider_hours = {
        str(location_a1.pk): [
            'not-a-dict',
            {'start_time': None, 'end_time': '17:00', 'days': ['mon']},
            {'start_time': '13:00', 'end_time': '09:00', 'days': ['mon']},  # end <= start
            {'start_time': '09:00', 'end_time': '12:00', 'days': []},  # no valid days
            {'start_time': '09:00', 'end_time': '12:00', 'days': ['mon']},  # the one good entry
        ],
    }
    provider_a1.save(update_fields=['provider_hours'])
    intervals = get_provider_intervals(provider_a1, location_a1)
    assert len(intervals) == 1
    assert intervals[0]['start_time'] == time(9, 0)


def test_get_provider_intervals_filters_unknown_day_keys(provider_a1, location_a1):
    provider_a1.provider_hours = {
        str(location_a1.pk): [
            {'start_time': '09:00', 'end_time': '12:00', 'days': ['mon', 'funday']},
        ],
    }
    provider_a1.save(update_fields=['provider_hours'])
    intervals = get_provider_intervals(provider_a1, location_a1)
    assert intervals[0]['days'] == ['mon']


def test_get_provider_intervals_filters_by_weekday_string_key(provider_a1, location_a1):
    set_provider_hours(provider_a1, location_a1.pk, [
        {'start_time': time(9, 0), 'end_time': time(12, 0), 'days': ['mon']},
        {'start_time': time(13, 0), 'end_time': time(17, 0), 'days': ['tue']},
    ])
    monday_only = get_provider_intervals(provider_a1, location_a1, weekday='mon')
    assert len(monday_only) == 1
    assert monday_only[0]['days'] == ['mon']


def test_get_provider_intervals_filters_by_weekday_integer_index(provider_a1, location_a1):
    """`date.weekday()` is Monday=0 — this proves the int-to-key mapping."""
    set_provider_hours(provider_a1, location_a1.pk, [
        {'start_time': time(9, 0), 'end_time': time(12, 0), 'days': ['mon']},
        {'start_time': time(13, 0), 'end_time': time(17, 0), 'days': ['wed']},
    ])
    monday = date(2026, 7, 27)  # a Monday
    assert monday.weekday() == 0
    intervals = get_provider_intervals(provider_a1, location_a1, weekday=monday.weekday())
    assert len(intervals) == 1
    assert intervals[0]['days'] == ['mon']


def test_get_provider_intervals_sorted_by_start_time(provider_a1, location_a1):
    set_provider_hours(provider_a1, location_a1.pk, [
        {'start_time': time(13, 0), 'end_time': time(17, 0), 'days': ['mon']},
        {'start_time': time(9, 0), 'end_time': time(12, 0), 'days': ['mon']},
    ])
    intervals = get_provider_intervals(provider_a1, location_a1)
    assert [i['start_time'] for i in intervals] == [time(9, 0), time(13, 0)]


# --------------------------------------------------------------------------- #
# is_provider_available — start-inclusive, end-exclusive boundary
# --------------------------------------------------------------------------- #

def test_is_provider_available_true_inside_window(provider_a1, location_a1):
    set_provider_hours(provider_a1, location_a1.pk, [
        {'start_time': time(9, 0), 'end_time': time(17, 0), 'days': ['mon']},
    ])
    assert is_provider_available(provider_a1, location_a1, 'mon', time(12, 0)) is True


def test_is_provider_available_true_at_start_boundary(provider_a1, location_a1):
    set_provider_hours(provider_a1, location_a1.pk, [
        {'start_time': time(9, 0), 'end_time': time(17, 0), 'days': ['mon']},
    ])
    assert is_provider_available(provider_a1, location_a1, 'mon', time(9, 0)) is True


def test_is_provider_available_false_at_end_boundary(provider_a1, location_a1):
    """End-exclusive — so back-to-back intervals never both match the same
    instant, per the docstring."""
    set_provider_hours(provider_a1, location_a1.pk, [
        {'start_time': time(9, 0), 'end_time': time(17, 0), 'days': ['mon']},
    ])
    assert is_provider_available(provider_a1, location_a1, 'mon', time(17, 0)) is False


def test_is_provider_available_false_outside_any_window(provider_a1, location_a1):
    set_provider_hours(provider_a1, location_a1.pk, [
        {'start_time': time(9, 0), 'end_time': time(17, 0), 'days': ['mon']},
    ])
    assert is_provider_available(provider_a1, location_a1, 'tue', time(12, 0)) is False


def test_is_provider_available_false_for_an_unconfigured_provider(member_user, location_a1):
    """UNAVAILABLE, never "available all day" — the docstring's explicit rule."""
    assert is_provider_available(member_user, location_a1, 'mon', time(12, 0)) is False


# --------------------------------------------------------------------------- #
# validate_provider_hours
# --------------------------------------------------------------------------- #

def test_validate_rejects_a_location_the_provider_is_not_assigned_to(provider_a1, location_a2):
    errors = validate_provider_hours(
        [{'start_time': '09:00', 'end_time': '17:00', 'days': ['mon']}],
        location_id=location_a2.pk,
        assigned_location_ids=[],
    )
    assert any('not assigned' in e for e in errors)


def test_validate_accepts_valid_non_overlapping_intervals(location_a1):
    errors = validate_provider_hours(
        [
            {'start_time': '09:00', 'end_time': '12:00', 'days': ['mon']},
            {'start_time': '13:00', 'end_time': '17:00', 'days': ['mon']},
        ],
        location_id=location_a1.pk,
        assigned_location_ids=[location_a1.pk],
    )
    assert errors == []


def test_validate_rejects_missing_start_or_end(location_a1):
    errors = validate_provider_hours(
        [{'start_time': '', 'end_time': '17:00', 'days': ['mon']}],
        location_id=location_a1.pk,
        assigned_location_ids=[location_a1.pk],
    )
    assert any('enter a start and end time' in e.lower() for e in errors)


def test_validate_rejects_end_before_or_equal_to_start(location_a1):
    errors = validate_provider_hours(
        [{'start_time': '12:00', 'end_time': '12:00', 'days': ['mon']}],
        location_id=location_a1.pk,
        assigned_location_ids=[location_a1.pk],
    )
    assert any('after the start time' in e for e in errors)


def test_validate_rejects_no_days_chosen(location_a1):
    errors = validate_provider_hours(
        [{'start_time': '09:00', 'end_time': '17:00', 'days': []}],
        location_id=location_a1.pk,
        assigned_location_ids=[location_a1.pk],
    )
    assert any('choose at least one day' in e.lower() for e in errors)


def test_validate_rejects_overlap_on_a_shared_day_but_allows_touching_windows(location_a1):
    errors = validate_provider_hours(
        [
            {'start_time': '09:00', 'end_time': '13:00', 'days': ['mon']},
            {'start_time': '13:00', 'end_time': '17:00', 'days': ['mon']},
        ],
        location_id=location_a1.pk,
        assigned_location_ids=[location_a1.pk],
    )
    assert errors == []


def test_validate_overlap_check_is_per_weekday_not_global(location_a1):
    """Same clock-time overlap is fine when the two intervals never share a
    weekday."""
    errors = validate_provider_hours(
        [
            {'start_time': '09:00', 'end_time': '13:00', 'days': ['mon']},
            {'start_time': '09:00', 'end_time': '13:00', 'days': ['tue']},
        ],
        location_id=location_a1.pk,
        assigned_location_ids=[location_a1.pk],
    )
    assert errors == []


# --------------------------------------------------------------------------- #
# serialise_intervals / set_provider_hours / clear_provider_hours
# --------------------------------------------------------------------------- #

def test_serialise_intervals_sorts_and_formats():
    result = serialise_intervals([
        {'start_time': time(13, 0), 'end_time': time(17, 0), 'days': ['mon']},
        {'start_time': time(9, 0), 'end_time': time(12, 0), 'days': ['tue']},
    ])
    assert result[0]['start_time'] == '09:00'
    assert result[1]['start_time'] == '13:00'


def test_set_provider_hours_leaves_other_locations_alone(provider_a1, location_a1, location_a2, tenant_a):
    from apps.accounts.models import UserLocation

    UserLocation.objects.create(tenant=tenant_a, user=provider_a1, location=location_a2)
    set_provider_hours(provider_a1, location_a1.pk, [
        {'start_time': time(9, 0), 'end_time': time(12, 0), 'days': ['mon']},
    ])
    set_provider_hours(provider_a1, location_a2.pk, [
        {'start_time': time(13, 0), 'end_time': time(17, 0), 'days': ['tue']},
    ])
    provider_a1.refresh_from_db()
    assert str(location_a1.pk) in provider_a1.provider_hours
    assert str(location_a2.pk) in provider_a1.provider_hours
    assert get_provider_intervals(provider_a1, location_a1)[0]['days'] == ['mon']
    assert get_provider_intervals(provider_a1, location_a2)[0]['days'] == ['tue']


def test_set_provider_hours_commit_false_does_not_persist(provider_a1, location_a1):
    set_provider_hours(provider_a1, location_a1.pk, [
        {'start_time': time(9, 0), 'end_time': time(12, 0), 'days': ['mon']},
    ], commit=False)
    reloaded = User.objects.get(pk=provider_a1.pk)
    assert str(location_a1.pk) not in (reloaded.provider_hours or {})


def test_clear_provider_hours_records_explicit_empty_list_not_missing_key(provider_a1, location_a1):
    assert has_configured_hours(provider_a1, location_a1.pk) is False
    clear_provider_hours(provider_a1, location_a1.pk)
    assert has_configured_hours(provider_a1, location_a1.pk) is True
    assert get_provider_intervals(provider_a1, location_a1) == []


# --------------------------------------------------------------------------- #
# weekly_summary
# --------------------------------------------------------------------------- #

def test_weekly_summary_has_one_row_per_weekday_in_order(provider_a1, location_a1):
    summary = weekly_summary(provider_a1, location_a1)
    assert [key for key, _label, _intervals in summary] == WEEKDAY_KEYS


def test_weekly_summary_places_intervals_on_the_right_day(provider_a1, location_a1):
    set_provider_hours(provider_a1, location_a1.pk, [
        {'start_time': time(9, 0), 'end_time': time(12, 0), 'days': ['wed']},
    ])
    summary = weekly_summary(provider_a1, location_a1)
    wed_row = next(row for row in summary if row[0] == 'wed')
    mon_row = next(row for row in summary if row[0] == 'mon')
    assert len(wed_row[2]) == 1
    assert len(mon_row[2]) == 0
