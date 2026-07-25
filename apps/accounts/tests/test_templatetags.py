"""Tests for the `apps/accounts/templatetags/ui.py` filters that are NOT
already covered by `apps/calls/tests/test_ui_filters.py` (`redact_args`,
`pretty_json`, `error_log_count`, `iso_time`, `ensure_list` and
`consent_basis_label` are proven there, against the module that actually
consumes them — this file covers the rest of the shared toolkit that belongs to
`accounts`: `querystring_without_page`, `phone_e164`, `initials`,
`level_badge`, `dict_get` and `peaks_dom_id`).
"""
import pytest
from django.test import RequestFactory

from apps.accounts.templatetags.ui import (
    dict_get,
    initials,
    level_badge,
    peaks_dom_id,
    phone_e164,
    querystring_without_page,
)

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# querystring_without_page
# --------------------------------------------------------------------------- #

def test_querystring_without_page_returns_empty_when_no_request_in_context():
    assert querystring_without_page({}) == ''


def test_querystring_without_page_returns_empty_with_no_get_params():
    request = RequestFactory().get('/some/path/')
    assert querystring_without_page({'request': request}) == ''


def test_querystring_without_page_preserves_filters_and_drops_page():
    request = RequestFactory().get('/some/path/', {'status': 'completed', 'page': '3'})
    result = querystring_without_page({'request': request})
    assert result.startswith('&')
    assert 'page' not in result
    assert 'status=completed' in result


def test_querystring_without_page_is_marked_safe_for_direct_template_concatenation():
    request = RequestFactory().get('/some/path/', {'q': 'ada'})
    result = querystring_without_page({'request': request})
    from django.utils.safestring import SafeString
    assert isinstance(result, SafeString)


# --------------------------------------------------------------------------- #
# phone_e164
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('value, expected', [
    ('', ''),
    (None, ''),
    ('+13125550142', '+1 (312) 555-0142'),
    ('13125550142', '+1 (312) 555-0142'),
    ('+442071838750', '+442071838750'),  # non-NANP: kept in plain E.164 form
    ('not-a-phone-number', 'not-a-phone-number'),  # unmatched: shown unchanged
    ('+1 312 555 0142', '+1 (312) 555-0142'),  # spaces stripped before matching
])
def test_phone_e164_filter(value, expected):
    assert phone_e164(value) == expected


# --------------------------------------------------------------------------- #
# initials (template filter — distinct from `User.initials`, the model property)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('value, expected', [
    ('Ada Lovelace', 'AL'),
    ('Cher', 'CH'),
    ('', '?'),
    (None, '?'),
    ('   ', '?'),
])
def test_initials_filter(value, expected):
    assert initials(value) == expected


# --------------------------------------------------------------------------- #
# level_badge
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('level, expected_class', [
    ('debug', 'badge-muted'),
    ('info', 'badge-info'),
    ('warning', 'badge-amber'),
    ('error', 'badge-red'),
    ('critical', 'badge-red'),
    ('INFO', 'badge-info'),  # case-insensitive
    ('something-unrecognised', 'badge-muted'),  # unknown level degrades safely
    ('', 'badge-muted'),
    (None, 'badge-muted'),
])
def test_level_badge(level, expected_class):
    assert level_badge(level) == expected_class


# --------------------------------------------------------------------------- #
# dict_get
# --------------------------------------------------------------------------- #

def test_dict_get_returns_the_value_for_a_present_key():
    assert dict_get({'a': 1, 'b': 2}, 'b') == 2


def test_dict_get_returns_none_for_a_missing_key():
    assert dict_get({'a': 1}, 'missing') is None


def test_dict_get_never_raises_on_a_non_dict_input():
    assert dict_get(None, 'a') is None
    assert dict_get('not-a-dict', 'a') is None
    assert dict_get(42, 'a') is None


# --------------------------------------------------------------------------- #
# peaks_dom_id
# --------------------------------------------------------------------------- #

def test_peaks_dom_id_builds_the_expected_id():
    assert peaks_dom_id('waveform', 42) == 'waveform-42'


def test_peaks_dom_id_escapes_html_special_characters():
    result = peaks_dom_id('<script>', 1)
    assert '<script>' not in result
    assert '&lt;script&gt;' in result
