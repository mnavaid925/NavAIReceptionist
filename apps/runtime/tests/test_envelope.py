"""``agent/envelope.py`` — the one ``{ok, data, error}`` result shape.

Pure, no DB. Covers the two constructors and the closed 8-code error set
(``not_found``, ``invalid_argument``, ``slot_unavailable``, ``slot_expired``,
``not_permitted``, ``provider_error``, ``rate_limited``, ``internal_error``),
and that ``apps.scheduling.availability``'s own closed set (``SlotError.code``)
is a genuine SUBSET — the property the dispatcher relies on to pass a
``SlotError`` straight through with zero translation.
"""
import pytest

from apps.runtime.agent.envelope import ERROR_CODES, err, ok
from apps.scheduling.availability import SLOT_ERROR_CODES


def test_ok_defaults_data_to_an_empty_dict_never_none():
    result = ok()
    assert result == {'ok': True, 'data': {}, 'error': None}


def test_ok_carries_the_given_data_unchanged():
    result = ok({'a': 1, 'b': [2, 3]})
    assert result == {'ok': True, 'data': {'a': 1, 'b': [2, 3]}, 'error': None}


def test_err_shape_carries_a_null_data_and_the_closed_code():
    result = err('not_found', "I couldn't find that.")
    assert result['ok'] is False
    assert result['data'] is None
    assert result['error'] == {'code': 'not_found', 'message': "I couldn't find that."}


@pytest.mark.parametrize('code', sorted(ERROR_CODES))
def test_err_accepts_every_member_of_the_closed_set(code):
    result = err(code, 'a spoken message')
    assert result['error']['code'] == code


def test_err_raises_on_a_code_outside_the_closed_set():
    with pytest.raises(ValueError):
        err('made_up_code', 'nope')


def test_error_codes_is_the_exact_documented_closed_set():
    assert ERROR_CODES == frozenset({
        'not_found', 'invalid_argument', 'slot_unavailable', 'slot_expired',
        'not_permitted', 'provider_error', 'rate_limited', 'internal_error',
    })


def test_error_codes_are_all_lower_snake_case():
    for code in ERROR_CODES:
        assert code == code.lower()
        assert ' ' not in code


def test_slot_error_codes_is_a_subset_of_the_envelope_closed_set():
    """This is what lets the dispatcher drop a `SlotError.code` straight into
    the envelope's `error.code` with zero translation."""
    assert SLOT_ERROR_CODES <= ERROR_CODES
