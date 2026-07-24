"""`apps.runtime.agent.consent.resolve_consent` — the recording jurisdiction gate.

Pure function under test — a `SimpleNamespace` standing in for a `tenants.Location`
matches the module's own contract ("reads attributes off a Location instance the
caller already has in hand"; "no ORM query, no Channels import, no I/O"), so
nothing here needs `django_db`. Same `SimpleNamespace`-as-model-stand-in pattern
`test_prompt.py` already uses for `AgentSetting`/`Contact`.

The module's own docstring carries a WARNING that `TWO_PARTY_CONSENT_STATES`
needs periodic spot-checking against a legal reference — this file is the piece
that was missing entirely: zero unit tests existed for `resolve_consent` before
this pass, despite it being the one function that decides whether a caller is
told they are being recorded.
"""
from types import SimpleNamespace

import pytest

from apps.runtime.agent.consent import (
    CONSENT_NOT_RECORDED,
    CONSENT_ONE_PARTY,
    CONSENT_TWO_PARTY,
    TWO_PARTY_CONSENT_STATES,
    US_STATE_CODES,
    resolve_consent,
)


def _loc(state='', country='US'):
    return SimpleNamespace(state=state, country=country)


# --------------------------------------------------------------------------- #
# The closed result set — NEVER not_recorded (that is the consumer's to stamp
# for a call that never reached this function at all).
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('location', [
    _loc('IL'), _loc('OR'), _loc('CO'), _loc(''), _loc('Illinois'),
    _loc('il'), _loc('  il  '), _loc('OR', 'CA'), _loc('', ''), None,
])
def test_resolve_consent_never_returns_not_recorded(location):
    result = resolve_consent(location)
    assert result in {CONSENT_TWO_PARTY, CONSENT_ONE_PARTY}
    assert result != CONSENT_NOT_RECORDED


# --------------------------------------------------------------------------- #
# Two-party states — announce
# --------------------------------------------------------------------------- #

def test_two_party_state_illinois_announces():
    assert resolve_consent(_loc('IL')) == CONSENT_TWO_PARTY


def test_two_party_state_lowercase_announces():
    assert resolve_consent(_loc('il')) == CONSENT_TWO_PARTY


def test_two_party_state_with_surrounding_whitespace_announces():
    assert resolve_consent(_loc('  IL  ')) == CONSENT_TWO_PARTY


# --------------------------------------------------------------------------- #
# One-party states — no announcement required
# --------------------------------------------------------------------------- #

def test_one_party_state_oregon_does_not_announce():
    assert resolve_consent(_loc('OR')) == CONSENT_ONE_PARTY


def test_one_party_state_colorado_does_not_announce():
    assert resolve_consent(_loc('CO')) == CONSENT_ONE_PARTY


def test_one_party_state_lowercase_and_whitespace_still_resolves_one_party():
    assert resolve_consent(_loc(' or ')) == CONSENT_ONE_PARTY
    assert resolve_consent(_loc('co')) == CONSENT_ONE_PARTY


# --------------------------------------------------------------------------- #
# Unknown jurisdiction announces — blank, typo, or spelled-out
# --------------------------------------------------------------------------- #

def test_blank_state_announces():
    assert resolve_consent(_loc('')) == CONSENT_TWO_PARTY


def test_spelled_out_two_party_state_name_is_unrecognised_and_announces():
    assert resolve_consent(_loc('Illinois')) == CONSENT_TWO_PARTY


def test_spelled_out_one_party_state_name_is_ALSO_unrecognised_and_announces():
    """The recogniser only matches the two-letter code — a one-party state
    spelled out in full does not get looked up by name, so it still falls
    through to the conservative announce branch rather than silently
    resolving one-party."""
    assert resolve_consent(_loc('Oregon')) == CONSENT_TWO_PARTY


def test_typo_or_unrecognised_state_code_announces():
    assert resolve_consent(_loc('ZZ')) == CONSENT_TWO_PARTY


# --------------------------------------------------------------------------- #
# Non-US country — always announces, regardless of the state field's shape
# --------------------------------------------------------------------------- #

def test_non_us_country_announces_even_with_a_one_party_shaped_state_code():
    # 'OR' is a real one-party US code, but the country is not the US.
    assert resolve_consent(_loc('OR', 'CA')) == CONSENT_TWO_PARTY


def test_non_us_country_blank_state_announces():
    assert resolve_consent(_loc('', 'United Kingdom')) == CONSENT_TWO_PARTY


@pytest.mark.parametrize('country', ['US', 'USA', 'United States',
                                     'united states of america', ' us '])
def test_every_accepted_us_country_spelling_is_recognised(country):
    assert resolve_consent(_loc('IL', country)) == CONSENT_TWO_PARTY
    assert resolve_consent(_loc('OR', country)) == CONSENT_ONE_PARTY


# --------------------------------------------------------------------------- #
# location=None and missing attributes — the safe defaults
# --------------------------------------------------------------------------- #

def test_location_none_announces():
    assert resolve_consent(None) == CONSENT_TWO_PARTY


def test_missing_state_attribute_falls_back_to_blank_and_announces():
    class _NoState:
        country = 'US'

    assert resolve_consent(_NoState()) == CONSENT_TWO_PARTY


def test_missing_country_attribute_falls_back_to_the_us_default():
    class _NoCountry:
        state = 'OR'

    assert resolve_consent(_NoCountry()) == CONSENT_ONE_PARTY


def test_none_valued_state_and_country_fields_fall_back_to_the_safe_defaults():
    """`getattr(..., '') or 'US'` / `... or ''` — an explicit `None` value (not
    just a missing attribute) must be treated the same as blank/absent."""
    assert resolve_consent(_loc(state=None, country=None)) == CONSENT_TWO_PARTY


# --------------------------------------------------------------------------- #
# The state lists themselves — the spot-check the module's own WARNING asks for
# --------------------------------------------------------------------------- #

def test_two_party_states_are_a_subset_of_recognised_state_codes():
    assert TWO_PARTY_CONSENT_STATES <= US_STATE_CODES


def test_every_recognised_state_code_resolves_to_a_real_basis_without_raising():
    for code in sorted(US_STATE_CODES):
        result = resolve_consent(_loc(code))
        assert result in {CONSENT_TWO_PARTY, CONSENT_ONE_PARTY}


def test_dc_is_a_recognised_code_and_not_two_party():
    """DC is in `US_STATE_CODES` but not `TWO_PARTY_CONSENT_STATES` — recognised,
    one-party. Guards against a set edit that accidentally drops DC from the
    recogniser (which would silently flip it to the announce branch)."""
    assert 'DC' in US_STATE_CODES
    assert resolve_consent(_loc('DC')) == CONSENT_ONE_PARTY
