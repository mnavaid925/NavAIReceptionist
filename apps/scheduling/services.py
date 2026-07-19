"""Cross-entity helpers for Module 4 — Calendar & Bookings.

Flat at the app root by convention (CLAUDE.md "Backend Package Structure" rule 8),
because this is shared plumbing rather than an entity's CRUD.

Right now it holds the phone-number normaliser. That function is the whole
mechanism behind sub-module 4.1's "Phone-Keyed Contacts" bullet: a repeat caller
only deduplicates if the number the agent resolves from Twilio's `From` header
and the number a receptionist types into the contact form land in the database in
the SAME shape. `+1 (312) 555-0142`, `312-555-0142` and `13125550142` are one
person, and storing them verbatim would make three.
"""
import re

__all__ = ['normalize_e164', 'DEFAULT_COUNTRY_CODE']

#: Fallback country calling code for a bare national number typed without one.
#: North America, matching the seeded demo data. A number that already carries a
#: `+` is never re-prefixed, so an international contact is unaffected.
DEFAULT_COUNTRY_CODE = '1'

#: E.164 allows at most 15 digits after the `+`.
_MAX_E164_DIGITS = 15
_MIN_E164_DIGITS = 7

_NON_DIGITS = re.compile(r'\D')

# Anything from an extension marker onwards is a DIFFERENT number — a desk
# extension behind a switchboard. Stripping non-digits blindly would splice those
# digits onto the end of the main number and produce a line nobody can ring.
_EXTENSION = re.compile(r'(?:\bx|\bext\.?|#|,|;)\s*\d+\s*$', re.IGNORECASE)


def normalize_e164(value, default_country_code=DEFAULT_COUNTRY_CODE):
    """Return `value` as an E.164 string (`+13125550142`), or `''`.

    Deliberately dependency-free and forgiving rather than a full libphonenumber
    validation. The cost of being wrong is asymmetric here: rejecting a real
    caller's number during a live call is far worse than storing one that is
    merely oddly formatted, so anything with a plausible digit count is accepted
    and anything else degrades to `''` (an unknown or withheld caller ID is
    normal and must not raise).

    Rules:

    * A leading `+` is authoritative — the digits after it are the full number.
    * `00` is the international access prefix used across most of the world and
      is treated as the `+` it stands in for.
    * A bare 11+ digit string is assumed to already carry its country code.
    * A shorter bare string gets `default_country_code` prefixed.
    """
    if not value:
        return ''

    raw = _EXTENSION.sub('', str(value).strip())
    has_plus = raw.startswith('+')
    digits = _NON_DIGITS.sub('', raw)

    if not digits:
        return ''

    # `00` is the international access prefix and stands in for the `+`. Handled
    # before the has_plus branch because `+00442079460958` carries BOTH — a
    # redundancy people really do type — and leaving the `00` in place would
    # store a number that looks E.164 but rings nothing.
    if digits.startswith('00'):
        digits = digits[2:]
    elif not has_plus:
        if len(digits) <= 10:
            # A national number typed without its country code. 10 digits is the
            # NANP length; anything shorter is likely an extension or a typo, but
            # prefixing is still the best guess available.
            digits = f'{default_country_code}{digits.lstrip("0")}'

    if not (_MIN_E164_DIGITS <= len(digits) <= _MAX_E164_DIGITS):
        return ''

    return f'+{digits}'
