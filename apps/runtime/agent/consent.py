"""Recording consent resolution — sub-module 3.5.

Answers one question, once per call, before a single byte is recorded: *on what
basis may this call be recorded, and must the caller be told first?*

**The jurisdiction is the LOCATION's, not the caller's.** A location is a real
address with a real ``state``/``country`` (Module 1); the caller's number is not a
reliable jurisdiction signal (a mobile keeps its area code across a move) and is
caller-supplied besides. So the basis is resolved from ``tenants.Location`` —
server-side data — and never from anything the caller says or sends.

Three bases, and the vocabulary matches what ``seed_calls`` already writes into
``CallSession.metadata`` so Module 5 renders real and seeded rows identically:

* ``announced_notice`` — a two-party-consent jurisdiction. The agent speaks
  :data:`CONSENT_ANNOUNCEMENT_LINE` before the conversation proper, and the fact
  that it played is recorded on the row.
* ``one_party_notice`` — a one-party-consent jurisdiction. The business is itself
  a party to the call, so recording proceeds with no spoken notice.
* ``not_recorded`` — no basis was ever resolved (a call declined at the door:
  a disabled number, an at-capacity worker). **This module never returns it** —
  it is stamped by the consumer for a call that never reached
  :func:`resolve_consent` at all, and it is what makes "there is no recording"
  an explicit, auditable statement rather than a missing key.

**Unknown jurisdiction announces.** A blank, unrecognised or spelled-out
``state`` (``'Illinois'`` rather than ``'IL'``), or any non-US country, resolves
to the two-party branch. Over-disclosing costs one spoken sentence; under-
disclosing is the failure that matters. That is a deliberately conservative
default, not a legal ruling — and neither is this module: it encodes a
defensible default, and an operator with counsel can narrow it.

Pure — no ORM query, no Channels import, no I/O. It reads attributes off a
``Location`` instance the caller already has in hand.
"""

__all__ = [
    'TWO_PARTY_CONSENT_STATES',
    'US_STATE_CODES',
    'CONSENT_TWO_PARTY',
    'CONSENT_ONE_PARTY',
    'CONSENT_NOT_RECORDED',
    'CONSENT_ANNOUNCEMENT_LINE',
    'resolve_consent',
]

#: US states whose wiretap statutes require ALL parties to consent. Sourced from
#: the 3.5 research pass (recordinglaw.com's state guide).
#:
#: WARNING: state consent statutes are amended from time to time, and a few states
#: on this list are "mixed" in practice (Nevada and Oregon differ between phone and
#: in-person recording; Connecticut's two-party rule is civil rather than criminal).
#: Spot-check this set against a current legal reference whenever this module is
#: touched. Being on the list when you need not be costs one spoken sentence; being
#: off it when you should not be is the failure that matters — so an amendment in
#: either direction should be applied INTO this set rather than worked around at a
#: call site.
TWO_PARTY_CONSENT_STATES = frozenset({
    'CA', 'CT', 'FL', 'IL', 'MD', 'MA', 'MT', 'NV', 'NH', 'PA', 'WA',
})

#: Every US state code plus DC. Used only to tell "a state code we recognise"
#: apart from "something else in the state field" — a blank, a typo, or a
#: spelled-out name. Anything unrecognised takes the announce branch, so this set
#: does not have to be a jurisdiction authority, only a recogniser.
US_STATE_CODES = frozenset({
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DC', 'DE', 'FL', 'GA', 'HI',
    'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN',
    'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH',
    'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA',
    'WV', 'WI', 'WY',
})

#: The three basis values written to ``CallSession.metadata['consent_basis']``.
#: These strings are a persisted vocabulary shared with ``seed_calls`` and every
#: Module 5 reader — rename one and old rows stop matching.
CONSENT_TWO_PARTY = 'announced_notice'
CONSENT_ONE_PARTY = 'one_party_notice'
CONSENT_NOT_RECORDED = 'not_recorded'

#: Spoken once, immediately after the greeting, when the basis is two-party. A
#: PLATFORM constant, never caller text and never model-authored — the disclosure
#: is the thing being relied on legally, so it cannot be something an LLM
#: paraphrases or a prompt-injected caller influences. Same posture as the
#: consumer's own ``_TRANSFER_FAILED_LINE``.
CONSENT_ANNOUNCEMENT_LINE = 'This call may be recorded for quality and training purposes.'

#: Country values treated as "the United States". The field is free text with a
#: default of ``'US'``, so both the code and the spelled-out forms are honoured;
#: anything else is a foreign jurisdiction and announces.
_US_COUNTRIES = frozenset({'US', 'USA', 'UNITED STATES', 'UNITED STATES OF AMERICA'})


def resolve_consent(location):
    """The consent basis for recording a call at ``location``.

    Returns :data:`CONSENT_TWO_PARTY` or :data:`CONSENT_ONE_PARTY` — never
    :data:`CONSENT_NOT_RECORDED`, which describes a call that never got this far
    and is the consumer's to stamp.

    A missing ``location`` announces, for the same reason an unknown state does:
    the safe answer when the jurisdiction cannot be established is to disclose.
    """
    if location is None:
        return CONSENT_TWO_PARTY

    country = (getattr(location, 'country', '') or 'US').strip().upper()
    if country not in _US_COUNTRIES:
        return CONSENT_TWO_PARTY

    state = (getattr(location, 'state', '') or '').strip().upper()
    if state not in US_STATE_CODES:
        # Blank, a typo, or spelled out ('ILLINOIS'). We do not guess — an
        # unrecognised jurisdiction announces.
        return CONSENT_TWO_PARTY
    return CONSENT_TWO_PARTY if state in TWO_PARTY_CONSENT_STATES else CONSENT_ONE_PARTY
