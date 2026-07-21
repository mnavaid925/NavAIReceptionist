"""Unit tests for the shared display-time filters `apps.accounts.templatetags.ui`
added for sub-module 5.3 (Event Log & Cost): `redact_args`, `pretty_json`,
`error_log_count` and `iso_time` — plus `ensure_list` and `consent_basis_label`,
added for sub-module 5.4 (Recording & Transfer Outcome).

These are `apps.accounts` filters, but `apps/accounts/tests/` does not exist yet
in this repo (no `__init__.py`, no `conftest.py`, no prior suite) — the task
brief is explicit that in that case the tests belong with the CONSUMER that
exercises them end to end, which is `apps.calls`'s call-detail page. Rendered
end-to-end proof of the same redaction lives alongside the call-detail view
tests in `test_event_log_cost_views.py`; `ensure_list`'s and
`consent_basis_label`'s own end-to-end proof lives in `test_recording_views.py`
(the waveform-lane and consent-badge rendering tests). This file is the filters
in isolation, pure-function style, needing no `django_db` at all.
"""
import copy
import json
from datetime import datetime

import pytest
from django.template import Context, Template
from django.utils.safestring import SafeString

from apps.accounts.templatetags.ui import (
    REDACTION_MARKER,
    consent_basis_label,
    ensure_list,
    error_log_count,
    iso_time,
    pretty_json,
    redact_args,
)


# --------------------------------------------------------------------------- #
# redact_args — the security-critical one
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('value', [None, 'a plain string', ['a', 'list'], 42, True, 3.14])
def test_redact_args_non_dict_input_returns_empty_dict(value):
    assert redact_args(value) == {}


def test_redact_args_never_mutates_its_input():
    original = {
        'contact': {'first_name': 'Jane', 'phone_e164': '+13125550000'},
        'attendees': [{'full_name': 'Jane Roe'}],
        'service': 'Cleaning',
    }
    snapshot = copy.deepcopy(original)

    redact_args(original)

    assert original == snapshot


def test_redact_args_redacts_top_level_sensitive_keys_and_keeps_benign_ones():
    data = {
        'first_name': 'Jane',
        'last_name': 'Doe',
        'phone_e164': '+13125550000',
        'email': 'jane@example.com',
        'date_of_birth': '1990-01-01',
        'ssn': '123-45-6789',
        'service': 'Cleaning',
        'day': '2026-01-02',
        'window': 'morning',
        'topic': 'billing question',
    }

    result = redact_args(data)

    for key in ('first_name', 'last_name', 'phone_e164', 'email', 'date_of_birth', 'ssn'):
        assert result[key] == REDACTION_MARKER
    assert result['service'] == 'Cleaning'
    assert result['day'] == '2026-01-02'
    assert result['window'] == 'morning'
    assert result['topic'] == 'billing question'


def test_redact_args_hides_a_doubly_nested_sensitive_value():
    """The regression test for the fixed disclosure-leak bug: a value nested
    two levels deep under a sensitive key must not survive anywhere in the
    returned structure — a one-level-deep redaction pass would leak exactly
    this shape.
    """
    data = {'arguments': {'contact': {'first_name': 'X', 'phone_e164': 'Y'}}}

    result = redact_args(data)
    dumped = json.dumps(result)

    assert 'X' not in dumped
    assert 'Y' not in dumped
    # The 'contact' key is itself on the denylist, so its whole value is
    # replaced wholesale — 'arguments' (benign) is still descended into.
    assert result == {'arguments': {'contact': REDACTION_MARKER}}


def test_redact_args_redacts_a_list_of_dicts_under_a_sensitive_key():
    data = {'attendees': [{'full_name': 'Jane Roe'}, {'full_name': 'John Roe'}]}

    result = redact_args(data)

    assert result == {'attendees': REDACTION_MARKER}
    assert 'Jane Roe' not in json.dumps(result)
    assert 'John Roe' not in json.dumps(result)


def test_redact_args_redacts_a_bare_string_list_under_a_collection_key():
    """`attendee` is a denylist STEM specifically so a list of bare strings
    (no per-item dict key to hide behind) is still caught, wholesale, via the
    list's own key.
    """
    data = {'attendees': ['Jane Roe', 'John Roe']}

    result = redact_args(data)

    assert result == {'attendees': REDACTION_MARKER}


def test_redact_args_depth_cap_hides_a_value_nested_more_than_six_levels_deep():
    """Six benign hops down, a sensitive dict at the seventh level: the depth
    cap must replace that whole subtree with the marker BEFORE the sensitive
    key inside it is ever inspected — proving the cap itself is doing the
    hiding, not the key-based redaction.
    """
    data = {
        'level1': {'level2': {'level3': {'level4': {'level5': {
            'level6': {'first_name': 'DEEPSECRET'},
        }}}}},
    }

    result = redact_args(data)
    dumped = json.dumps(result)

    assert 'DEEPSECRET' not in dumped
    deep = result['level1']['level2']['level3']['level4']['level5']['level6']
    assert deep == REDACTION_MARKER


def test_redact_args_widened_denylist_catches_bare_stems():
    data = {
        'first': 'a', 'last': 'b', 'contact': 'c', 'patient': 'd', 'caller': 'e',
        'mobile': 'f', 'account': 'g', 'iban': 'h', 'mrn': 'i',
        'passport': 'j', 'license': 'k',
    }

    result = redact_args(data)

    for key in data:
        assert result[key] == REDACTION_MARKER


def test_redact_args_does_not_redact_cancellation_reason():
    """A deliberate denylist-collision miss: `cancellation_reason` must NOT be
    caught by any stem (in particular, `cell` was left OUT of the denylist
    precisely because it lives inside `canCELlation`).
    """
    data = {
        'cancellation_reason': 'Patient requested a reschedule outside the window',
        'service': 'Cleaning',
    }

    result = redact_args(data)

    assert result['cancellation_reason'] == data['cancellation_reason']
    assert result['service'] == 'Cleaning'


# --------------------------------------------------------------------------- #
# pretty_json
# --------------------------------------------------------------------------- #

def test_pretty_json_returns_a_plain_str_not_a_safestring():
    result = pretty_json({'key': 'value'})

    assert isinstance(result, str)
    assert not isinstance(result, SafeString)


def test_pretty_json_renders_html_escaped_through_a_real_template_with_autoescape_on():
    """The point of NOT marking the output safe: rendered inside a normal
    (autoescape-on) template, a `<script>` in the JSON must come out escaped.
    """
    template = Template('{% load ui %}{{ value|pretty_json }}')
    rendered = template.render(Context({'value': {'payload': '<script>alert(1)</script>'}}))

    assert '&lt;script&gt;' in rendered
    assert '<script>' not in rendered


def test_pretty_json_never_raises_on_a_non_serializable_value():
    """A tuple dict-key is not JSON-serializable even with `default=str` (that
    hook only covers VALUES) — `json.dumps` raises `TypeError` on the key
    itself, which must fall back to `str(value)` rather than propagate.
    """
    value = {(1, 2): 'x'}

    result = pretty_json(value)

    assert isinstance(result, str)
    assert result == str(value)


def test_pretty_json_indents_and_sorts_keys():
    result = pretty_json({'b': 1, 'a': 2})

    assert result == json.dumps({'b': 1, 'a': 2}, indent=2, sort_keys=True, default=str)
    assert result.index('"a"') < result.index('"b"')


# --------------------------------------------------------------------------- #
# error_log_count
# --------------------------------------------------------------------------- #

def test_error_log_count_counts_error_and_critical_only():
    logs = [
        {'level': 'error'},
        {'level': 'critical'},
        {'level': 'info'},
        {'level': 'debug'},
        {'level': 'warning'},
    ]

    assert error_log_count(logs) == 2


@pytest.mark.parametrize('value', [None, {}, 'not-a-list', 42])
def test_error_log_count_returns_zero_for_non_list(value):
    assert error_log_count(value) == 0


def test_error_log_count_skips_non_dict_entries_without_raising():
    logs = ['not-a-dict', {'level': 'error'}, None, 42]

    assert error_log_count(logs) == 1


def test_error_log_count_is_case_insensitive():
    logs = [{'level': 'ERROR'}, {'level': 'Critical'}]

    assert error_log_count(logs) == 2


# --------------------------------------------------------------------------- #
# iso_time
# --------------------------------------------------------------------------- #

def test_iso_time_formats_an_iso_string():
    assert iso_time('2026-01-01T10:00:05+00:00') == '10:00:05'


def test_iso_time_formats_a_datetime_object():
    value = datetime(2026, 1, 1, 10, 0, 5)
    assert iso_time(value) == '10:00:05'


def test_iso_time_returns_garbage_unchanged():
    assert iso_time('not-a-timestamp-at-all') == 'not-a-timestamp-at-all'


@pytest.mark.parametrize('value', ['', None])
def test_iso_time_returns_empty_string_for_empty_input(value):
    assert iso_time(value) == ''


# --------------------------------------------------------------------------- #
# ensure_list — sub-module 5.4, the waveform-lane crash guard
# --------------------------------------------------------------------------- #

def test_ensure_list_returns_a_real_list_unchanged():
    assert ensure_list([1, 2]) == [1, 2]


def test_ensure_list_returns_an_empty_list_unchanged():
    assert ensure_list([]) == []


@pytest.mark.parametrize('value', [42, None, 'x', {}, True, 3.14])
def test_ensure_list_returns_empty_list_for_anything_that_is_not_a_list(value):
    """The regression case this filter exists for: `waveform_peaks.bins` is an
    INT COUNT, not an array — `{% for x in 42 %}` raises `TypeError` and 500s
    the call-detail page. Every non-list shape degrades to `[]` instead.
    """
    assert ensure_list(value) == []


# --------------------------------------------------------------------------- #
# consent_basis_label — sub-module 5.4, the recording card's compliance badge
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('value, expected', [
    ('announced_notice', 'Recorded — consent announced'),
    ('two_party', 'Recorded — two-party consent'),
    ('one_party', 'Recorded — one-party consent'),
    ('not_recorded', 'Not recorded'),
])
def test_consent_basis_label_maps_known_values(value, expected):
    assert consent_basis_label(value) == expected


def test_consent_basis_label_falls_back_to_the_raw_value_for_an_unknown_basis():
    """Fails VISIBLE, not silent: a jurisdiction-specific basis Module 3 has not
    added a label for yet must still show something, not disappear.
    """
    assert consent_basis_label('some_future_basis') == 'some_future_basis'


@pytest.mark.parametrize('value', ['', None])
def test_consent_basis_label_returns_empty_string_for_empty_input(value):
    assert consent_basis_label(value) == ''


def test_consent_basis_label_strips_whitespace():
    assert consent_basis_label('  two_party  ') == 'Recorded — two-party consent'
