"""Tests for `apps.scheduling.services.normalize_e164` (sub-module 4.1).

No DB access needed — this is a pure function.
"""
import pytest

from apps.scheduling.services import normalize_e164


@pytest.mark.parametrize('raw, expected', [
    # Already E.164.
    ('+13125550142', '+13125550142'),
    # Common national-format spellings of the same US number.
    ('(312) 555-0142', '+13125550142'),
    ('312-555-0142', '+13125550142'),
    # Bare digits already carrying the country code (11+ digits).
    ('13125550142', '+13125550142'),
    # The international access prefix `00` stands in for `+`.
    ('0013125550142', '+13125550142'),
    # `00` AND a leading `+` together — a redundancy people really do type.
    ('+00442079460958', '+442079460958'),
    # Extension markers of every supported shape are stripped, not spliced on.
    ('+1 312 555 0142 x205', '+13125550142'),
    ('+1 312 555 0142 ext. 205', '+13125550142'),
    ('+13125550142,205', '+13125550142'),
    # Degrade to '' rather than raise.
    ('', ''),
    (None, ''),
    ('abc', ''),
    ('123', ''),
])
def test_normalize_e164_table(raw, expected):
    assert normalize_e164(raw) == expected


def test_normalize_e164_default_country_code_is_overridable():
    # A bare national number with a non-default country code prefix.
    assert normalize_e164('79460958', default_country_code='44') == '+4479460958'


def test_normalize_e164_rejects_too_short_a_number():
    # Two digits, even with a prefix, never reaches the 7-digit E.164 minimum.
    assert normalize_e164('12') == ''


def test_normalize_e164_rejects_too_long_a_number():
    # Comfortably past the 15-digit E.164 maximum.
    assert normalize_e164('+1234567890123456789') == ''
