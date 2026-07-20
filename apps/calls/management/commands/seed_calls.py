"""Seed demo call sessions — the call log (sub-module 5.1).

Idempotent by design — safe to run repeatedly without `--flush`.

    venv\\Scripts\\python.exe manage.py seed_calls
    venv\\Scripts\\python.exe manage.py seed_calls --flush

Runs on top of `seed_tenants` (the Acme and Globex businesses and two locations
each), `seed_accounts` (their users), `seed_agents` (the per-location inbound and
transfer numbers echoed below) and `seed_scheduling` (the contacts and the
appointment one of these calls is credited with booking). Nothing here invents a
tenant, a location, a contact or an appointment — every one is looked up by the
slug or name those seeders already use, so a drift between seeders fails loudly
as an "unresolved" count rather than quietly building a second demo universe.

**Order matters when re-flushing, and getting it backwards fails SILENTLY.**
The order is::

    seed_tenants → seed_accounts → seed_agents → seed_scheduling → seed_calls

`seed_scheduling --flush` DELETES and recreates the `Contact` rows, and
`CallSession.contact` is `SET_NULL` — so flushing scheduling AFTER calls nulls
the contact on every session that was just seeded. Nothing errors: the sessions
survive, the pages still render, and the demo simply shows every caller as
unidentified, which looks like a scoping bug rather than a stale seed. If you
flush scheduling for any reason, re-run `seed_calls --flush` afterwards.

**This command touches no provider, because there is no provider adapter in this
app at all.** Module 3 owns the telephony/STT/TTS/LLM adapters and has not been
built; `apps/calls/` contains a model, two read-only views and this seeder. The
JSON below is hand-authored fiction. Nothing here dials, answers, transcribes or
bills anything, under any value of `PROVIDER_MODE`.

**Invariant 2 is the whole shape of this file.** A call is exactly one
`CallSession` row: its transcript, event log, per-turn usage, analysis and
transfer outcome are JSON columns on that row. There is no turn table to seed and
there must never be one — which is also why the JSON has to be genuinely
realistic here. Sub-modules 5.2 (transcript), 5.3 (cost) and 5.4 (recording and
transfer) add ZERO models; they render exactly these columns, and thin demo JSON
would leave all three of them looking broken.

**PII.** These are synthetic numbers and invented conversations, but the command
still prints neither a transcript body nor a caller number — the habit is the
control, and a seeder that prints them teaches the wrong reflex to the next
person who writes a management command against this table.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from datetime import datetime, time as dt_time, timedelta

from django.utils import timezone

from apps.calls.models import CallSession
from apps.scheduling.availability import _local_naive_to_utc
from apps.tenants.models import Location, Tenant

# The tenants this seeder is allowed to touch. Same two as every other seeder in
# the chain — named here rather than derived, so `--flush` can never widen past
# the demo data.
DEMO_TENANT_SLUGS = ['acme', 'globex']

# The number the caller actually DIALLED, per location.
#
# Downtown, Uptown and Riverside echo `seed_agents`' `inbound_phone_number` for
# that site. Lakeside deliberately has none — `seed_agents` leaves it
# unconfigured on purpose so the "not configured" surfaces have a subject — so
# its rows carry the location's published line from `seed_tenants` instead. That
# is a real state, not a fudge: a call log outlives the configuration that
# produced it, and a row whose dialled number no longer matches any agent is
# exactly what a reassigned number looks like six months later.
DIALLED_NUMBERS = {
    'downtown': '+13125550140',
    'uptown': '+13125550141',
    'riverside': '+15035550150',
    'lakeside': '+13035550173',
}

# Where a transfer would have gone, per location — `seed_agents`'
# `transfer_phone_number`. Uptown and Lakeside have transfer switched off, which
# is why their transfer outcomes below are `disabled` and `failed` with an empty
# destination: the outcome data has to agree with the agent configuration, or the
# demo teaches a state the product cannot actually produce.
TRANSFER_DESTINATIONS = {
    'downtown': '+13125550101',
    'uptown': '',
    'riverside': '+15035550101',
    'lakeside': '',
}


# -- 5.1 Call sessions ------------------------------------------------------- #
#
# Keyed by LOCATION slug — all FOUR demo locations (Seed Rule 6), because a
# single-location call log hides every cross-location scoping bug.
#
# Per-row keys:
#
# * `contact`   — a `(first_name, last_name)` pair resolved against the tenant's
#                 directory, or None for a caller nobody identified. Both shapes
#                 appear at most locations on purpose: an unknown or withheld
#                 caller ID is the ordinary case, and it is the case a page is
#                 most likely to crash on. Invariant 1 is why the unidentified
#                 rows carry a null FK instead of a lightweight `Caller` row.
# * `day_offset`/`hour`/`minute`
#               — LOCAL wall-clock start at THIS location, converted through
#                 `Location.tzinfo`. Fixed offsets rather than `now()` arithmetic
#                 so a re-run reproduces the same instants; see `_start_for`.
# * `duration`  — seconds; None means the call is still up (`ended_at` stays
#                 null, which is what `duration_display` renders as "In progress").
# * `transcript`— `(offset, role, text)` tuples. `sequence` and the absolute `at`
#                 stamp are derived in `_build_transcript`, so the timeline can
#                 never disagree with `started_at`.
# * `logs`      — `(offset, level, category, title, raw_json)` tuples, same
#                 treatment. Tool-call arguments are stored REDACTED, matching
#                 what the runtime is required to persist: a `create_contact`
#                 payload is a full name and a date of birth.
# * `analysis`  — deliberately `{}` on every abandoned, failed and in-progress
#                 row. Nothing happened to analyse, so 5.2's defensive rendering
#                 has five real empty cases to prove itself against rather than a
#                 hypothetical one.
# * `usage`     — `(turn_sequence, cost_breakdown)` pairs; `cost_usd` is SUMMED
#                 from the breakdown in `_build_usage` rather than typed twice,
#                 because a total that disagrees with its own components is a bug
#                 5.3 would faithfully render.
# * `transfer`  — `{}` on the rows that never asked for a human, which is most of
#                 them. The five populated ones span every `result` the shipped
#                 `partials/_transfer_outcome.html` branches on, so the outcome
#                 filter has a genuine bucket for each value.
# * `books`     — True on exactly one row: the call credited with creating a
#                 seeded appointment. See `_link_booked_appointment`.
#
# Statuses across the whole set cover all FIVE values, so every branch of the
# already-shipped `partials/_call_status_badge.html` has a row behind it.
DEMO_CALL_SESSIONS = {
    'downtown': [
        {
            'contact': ('Dana', 'Whitfield'),
            'from_number': '+13125550101',
            'mode': 'live',
            'status': 'completed',
            'day_offset': -2, 'hour': 9, 'minute': 12,
            'duration': 38,
            'recorded': True,
            # The one row that produced a booking, so the Contact & Booking Links
            # bullet is demonstrable end to end.
            'books': True,
            'transcript': [
                (0, 'agent', 'Thanks for calling Acme Dental Downtown. This is '
                             'the reception assistant — how can I help?'),
                (5, 'user', "Hi, I'd like to book a check-up."),
                (9, 'agent', 'Of course. Can I take your name?'),
                (12, 'user', 'Dana Whitfield.'),
                (15, 'agent', "Thanks Dana, I've found you. I have tomorrow at "
                              'nine, or Thursday at half past two. Which suits?'),
                (23, 'user', 'Tomorrow at nine is good.'),
                (26, 'agent', 'Booked — a routine check-up tomorrow at nine. '
                              "You'll get a text confirmation shortly."),
                (34, 'user', 'Perfect, thank you.'),
                (36, 'agent', 'Thanks for calling. Goodbye.'),
            ],
            'logs': [
                (0, 'info', 'call', 'Inbound call answered',
                 {'channel': 'agent_phone', 'answered_in_ms': 310}),
                (0, 'info', 'agent', 'Greeting rendered from AgentSetting',
                 {'deterministic': True, 'llm_tokens': 0}),
                (15, 'info', 'tool', 'find_availability',
                 {'tool': 'find_availability',
                  'arguments': {'service': 'Routine check-up', 'window': '7d'},
                  'ok': True, 'slots_returned': 4}),
                (26, 'info', 'tool', 'book_appointment',
                 # `slot_token` is opaque and short-TTL by design, and it is
                 # still redacted here — a log is not a place to park a
                 # credential-shaped string.
                 {'tool': 'book_appointment',
                  'arguments': {'slot_token': '[redacted]',
                                'service': 'Routine check-up'},
                  'ok': True}),
                (27, 'warning', 'tts', 'Voice stream re-buffered once',
                 {'underruns': 1, 'recovered_in_ms': 180}),
                (38, 'info', 'call', 'Caller hung up', {'reason': 'caller_hangup'}),
            ],
            'analysis': {
                'summary': 'Existing patient booked a routine check-up for the '
                           'following morning. No transfer requested.',
                'success_evaluation': 'success',
                'extracted_data': {
                    'intent': 'book_appointment',
                    'service': 'Routine check-up',
                    'booking_made': True,
                    'caller_identified': True,
                    'sentiment': 'positive',
                },
            },
            'usage': [
                (1, {'stt_usd': 0.0021, 'llm_usd': 0.0064,
                     'tts_usd': 0.0038, 'telephony_usd': 0.0014}),
                (2, {'stt_usd': 0.0018, 'llm_usd': 0.0071,
                     'tts_usd': 0.0042, 'telephony_usd': 0.0014}),
                (3, {'stt_usd': 0.0016, 'llm_usd': 0.0088,
                     'tts_usd': 0.0051, 'telephony_usd': 0.0014}),
            ],
            'transfer': {},
        },
        {
            'contact': None,
            'from_number': '+13125550433',
            'mode': 'live',
            'status': 'transferred',
            'day_offset': -1, 'hour': 14, 'minute': 5,
            'duration': 143,
            'recorded': True,
            'transcript': [
                (0, 'agent', 'Thanks for calling Acme Dental Downtown. This is '
                             'the reception assistant — how can I help?'),
                (6, 'user', 'I need to talk to someone about an invoice.'),
                (10, 'agent', 'I can help with bookings, but billing is best '
                              'handled by the front desk. Shall I put you through?'),
                (18, 'user', 'Yes please.'),
                (20, 'agent', 'Putting you through now — one moment.'),
            ],
            'logs': [
                (0, 'info', 'call', 'Inbound call answered',
                 {'channel': 'agent_phone', 'answered_in_ms': 288}),
                (11, 'error', 'stt', 'Speech provider timed out, retried once',
                 {'timeout_ms': 1200, 'attempt': 1, 'recovered': True}),
                (20, 'info', 'tool', 'transfer_call',
                 {'tool': 'transfer_call',
                  'arguments': {'reason': 'billing enquiry'},
                  'ok': True, 'deferred_until_audio_complete': True}),
                (22, 'info', 'transfer', 'Cold transfer bridged',
                 {'result': 'connected', 'rings': 2}),
                (143, 'info', 'call', 'Call ended after transfer',
                 {'reason': 'far_end_hangup'}),
            ],
            'analysis': {
                'summary': 'Unidentified caller with a billing question. Agent '
                           'declined to answer and handed off to the front desk.',
                'success_evaluation': 'success',
                'extracted_data': {
                    'intent': 'billing_enquiry',
                    'booking_made': False,
                    'caller_identified': False,
                    'sentiment': 'neutral',
                },
            },
            'usage': [
                (1, {'stt_usd': 0.0024, 'llm_usd': 0.0059,
                     'tts_usd': 0.0036, 'telephony_usd': 0.0021}),
                (2, {'stt_usd': 0.0019, 'llm_usd': 0.0067,
                     'tts_usd': 0.0044, 'telephony_usd': 0.0021}),
            ],
            'transfer': {
                'result': 'connected',
                'reason': 'Caller asked for the front desk about an invoice',
                'offset': 20,
                'duration_seconds': 118,
            },
        },
        {
            # Same line as `seed_scheduling`'s anonymous Acme contact, and still
            # `contact=None` on purpose: the agent never got a name, so nothing
            # authorised linking this call to that row. Matching a person by
            # phone number alone is exactly the shortcut Invariant 3 forbids.
            'contact': None,
            'from_number': '+13125550990',
            'mode': 'google',
            'status': 'abandoned',
            'day_offset': 0, 'hour': 8, 'minute': 41,
            'duration': 7,
            'recorded': False,
            'transcript': [
                (0, 'agent', 'Thanks for calling Acme Dental Downtown. This is '
                             'the reception assistant — how can I help?'),
            ],
            'logs': [
                (0, 'info', 'call', 'Inbound call answered',
                 {'channel': 'agent_phone', 'answered_in_ms': 341}),
                (7, 'info', 'call', 'Caller hung up during greeting',
                 {'reason': 'caller_hangup', 'user_turns': 0}),
            ],
            # Empty on purpose: nobody said anything, so there is nothing to
            # analyse. Every reader must render {} without falling over.
            'analysis': {},
            'usage': [
                (1, {'stt_usd': 0.0000, 'llm_usd': 0.0000,
                     'tts_usd': 0.0022, 'telephony_usd': 0.0003}),
            ],
            'transfer': {},
        },
    ],
    'uptown': [
        {
            'contact': ('Priya', 'Raman'),
            'from_number': '+13125550188',
            'mode': 'gemini',
            'status': 'completed',
            'day_offset': -3, 'hour': 11, 'minute': 2,
            'duration': 78,
            'recorded': True,
            'transcript': [
                (0, 'agent', 'Thanks for calling Acme Dental Uptown. How can I '
                             'help?'),
                (5, 'user', 'What time do you close on Fridays?'),
                (9, 'agent', 'Uptown is open until six on Fridays, with the last '
                             'appointment at half past five.'),
                (17, 'user', "That's all I needed, thanks."),
                (20, 'agent', 'Happy to help. Goodbye.'),
            ],
            'logs': [
                (0, 'info', 'call', 'Inbound call answered',
                 {'channel': 'agent_phone', 'answered_in_ms': 402}),
                (9, 'info', 'tool', 'get_location_hours',
                 {'tool': 'get_location_hours', 'arguments': {'day': 'friday'},
                  'ok': True}),
                (78, 'info', 'call', 'Caller hung up', {'reason': 'caller_hangup'}),
            ],
            'analysis': {
                'summary': 'Known patient asked about Friday closing time. '
                           'Answered from location hours; no booking needed.',
                'success_evaluation': 'success',
                'extracted_data': {
                    'intent': 'opening_hours',
                    'booking_made': False,
                    'caller_identified': True,
                    'sentiment': 'positive',
                },
            },
            'usage': [
                (1, {'stt_usd': 0.0017, 'llm_usd': 0.0048,
                     'tts_usd': 0.0031, 'telephony_usd': 0.0011}),
                (2, {'stt_usd': 0.0012, 'llm_usd': 0.0039,
                     'tts_usd': 0.0026, 'telephony_usd': 0.0011}),
            ],
            'transfer': {},
        },
        {
            'contact': ('Owen', 'Baptiste'),
            'from_number': '+17735550250',
            'mode': 'live',
            'status': 'completed',
            'day_offset': -4, 'hour': 10, 'minute': 15,
            'duration': 65,
            'recorded': True,
            'transcript': [
                (0, 'agent', 'Thanks for calling Acme Dental Uptown. How can I '
                             'help?'),
                (6, 'user', 'Can I speak to a person?'),
                (10, 'agent', "I'm afraid I can't put calls through at this "
                              'site, but I can take a message and someone will '
                              'ring you back.'),
                (20, 'user', 'Fine — ask them to call me about whitening prices.'),
                (26, 'agent', "I've noted that down. Someone will be in touch "
                              'today.'),
            ],
            'logs': [
                (0, 'info', 'call', 'Inbound call answered',
                 {'channel': 'agent_phone', 'answered_in_ms': 295}),
                (10, 'warning', 'transfer', 'Transfer requested but disabled',
                 {'transfer_enabled': False, 'fallback': 'callback_request'}),
                (26, 'info', 'tool', 'create_callback_request',
                 # The caller's own words are the payload here, so the arguments
                 # are redacted before they reach the log — the reason text is a
                 # free-text field a caller controls.
                 {'tool': 'create_callback_request',
                  'arguments': {'reason': '[redacted]', 'caller_phone': '[redacted]'},
                  'ok': True}),
                (65, 'info', 'call', 'Caller hung up', {'reason': 'caller_hangup'}),
            ],
            'analysis': {
                'summary': 'Caller asked for a human. Transfer is switched off '
                           'at Uptown, so the agent took a callback request '
                           'about whitening prices instead.',
                'success_evaluation': 'partial',
                'extracted_data': {
                    'intent': 'speak_to_human',
                    'booking_made': False,
                    'caller_identified': True,
                    'callback_requested': True,
                    'sentiment': 'neutral',
                },
            },
            'usage': [
                (1, {'stt_usd': 0.0020, 'llm_usd': 0.0055,
                     'tts_usd': 0.0040, 'telephony_usd': 0.0010}),
                (2, {'stt_usd': 0.0015, 'llm_usd': 0.0061,
                     'tts_usd': 0.0035, 'telephony_usd': 0.0010}),
            ],
            'transfer': {
                'result': 'disabled',
                'reason': 'Caller asked for a person; transfer is switched off '
                          'at this location',
                'offset': 10,
                'duration_seconds': 0,
            },
        },
        {
            'contact': None,
            'from_number': '+17735550199',
            'mode': 'live',
            'status': 'failed',
            'day_offset': -1, 'hour': 16, 'minute': 20,
            'duration': 12,
            'recorded': False,
            'transcript': [
                (0, 'agent', 'Thanks for calling Acme Dental Uptown. How can I '
                             'help?'),
                (6, 'user', 'Hello? Hello — can you hear me?'),
            ],
            'logs': [
                (0, 'info', 'call', 'Inbound call answered',
                 {'channel': 'agent_phone', 'answered_in_ms': 377}),
                (8, 'error', 'call', 'Media stream closed unexpectedly',
                 {'close_code': 1011, 'frames_since_last_audio': 0,
                  'idle_seconds': 0}),
                (12, 'error', 'call', 'Session ended without a clean hangup',
                 {'reason': 'stream_closed', 'recoverable': False}),
            ],
            # Empty on purpose: the call broke before there was anything to
            # summarise.
            'analysis': {},
            'usage': [
                (1, {'stt_usd': 0.0006, 'llm_usd': 0.0000,
                     'tts_usd': 0.0024, 'telephony_usd': 0.0004}),
            ],
            'transfer': {},
        },
    ],
    'riverside': [
        {
            # The live one. `day_offset`/`hour` are ignored for this row — see
            # `_start_for`, which anchors an in-progress call to `now()` because
            # a call that is still up must look like it started minutes ago, not
            # at a fixed hour that may not have arrived yet today.
            'contact': ('Helena', 'Ostrom'),
            'from_number': '+15035550210',
            'mode': 'live',
            'status': 'in_progress',
            'day_offset': 0, 'hour': 0, 'minute': 0,
            'live_seconds_ago': 95,
            'duration': None,
            'recorded': False,
            'transcript': [
                (0, 'agent', 'Thanks for calling Globex Health Riverside. How '
                             'can I help?'),
                (7, 'user', "I'd like to move my physio session to a morning."),
                (13, 'agent', 'Let me look at what mornings are free this week.'),
            ],
            'logs': [
                (0, 'info', 'call', 'Inbound call answered',
                 {'channel': 'agent_phone', 'answered_in_ms': 264}),
                (13, 'info', 'tool', 'find_availability',
                 {'tool': 'find_availability',
                  'arguments': {'service': 'Physiotherapy session',
                                'window': '7d'},
                  'ok': True, 'slots_returned': 3}),
            ],
            # Empty because the call has not finished. Analysis is written once,
            # at the end — an in-progress row with a summary would be fiction.
            'analysis': {},
            'usage': [
                (1, {'stt_usd': 0.0022, 'llm_usd': 0.0051,
                     'tts_usd': 0.0033, 'telephony_usd': 0.0012}),
            ],
            'transfer': {},
        },
        {
            'contact': None,
            'from_number': '+15035550444',
            'mode': 'google',
            'status': 'completed',
            'day_offset': -1, 'hour': 9, 'minute': 30,
            'duration': 54,
            'recorded': True,
            'transcript': [
                (0, 'agent', 'Thanks for calling Globex Health Riverside. How '
                             'can I help?'),
                (5, 'user', 'Is the practice manager there?'),
                (9, 'agent', "I'll try to put you through — one moment."),
                (30, 'agent', "Sorry, nobody picked up. Can I take a message?"),
                (37, 'user', "No, I'll try again later."),
            ],
            'logs': [
                (0, 'info', 'call', 'Inbound call answered',
                 {'channel': 'agent_phone', 'answered_in_ms': 318}),
                (9, 'info', 'tool', 'transfer_call',
                 {'tool': 'transfer_call',
                  'arguments': {'reason': 'asked for practice manager'},
                  'ok': True, 'deferred_until_audio_complete': True}),
                (28, 'warning', 'transfer', 'Transfer target did not answer',
                 {'result': 'no_answer', 'rings': 6, 'timeout_seconds': 20}),
                (54, 'info', 'call', 'Caller hung up', {'reason': 'caller_hangup'}),
            ],
            'analysis': {
                'summary': 'Unidentified caller asked for the practice manager. '
                           'Transfer rang out; caller declined to leave a message.',
                'success_evaluation': 'partial',
                'extracted_data': {
                    'intent': 'speak_to_human',
                    'booking_made': False,
                    'caller_identified': False,
                    'sentiment': 'neutral',
                },
            },
            'usage': [
                (1, {'stt_usd': 0.0019, 'llm_usd': 0.0046,
                     'tts_usd': 0.0029, 'telephony_usd': 0.0016}),
                (2, {'stt_usd': 0.0014, 'llm_usd': 0.0041,
                     'tts_usd': 0.0027, 'telephony_usd': 0.0016}),
            ],
            'transfer': {
                'result': 'no_answer',
                'reason': 'Caller asked for the practice manager',
                'offset': 9,
                'duration_seconds': 0,
            },
        },
        {
            'contact': ('Theo', 'Nakamura'),
            'from_number': '+13035550311',
            'mode': 'live',
            'status': 'abandoned',
            'day_offset': -5, 'hour': 17, 'minute': 58,
            'duration': 19,
            'recorded': False,
            'transcript': [
                (0, 'agent', 'Thanks for calling Globex Health Riverside. How '
                             'can I help?'),
                (6, 'user', 'Put me through to reception.'),
                (10, 'agent', "Reception has closed for the day. I can book you "
                              'in myself, or take a message.'),
            ],
            'logs': [
                (0, 'info', 'call', 'Inbound call answered',
                 {'channel': 'agent_phone', 'answered_in_ms': 291}),
                (10, 'warning', 'transfer', 'Transfer refused — outside hours',
                 {'result': 'off_hours', 'local_time': '17:58',
                  'transfer_window': '09:00-17:00'}),
                (19, 'info', 'call', 'Caller hung up mid-turn',
                 {'reason': 'caller_hangup'}),
            ],
            # Empty on purpose: the caller left before the agent got anywhere.
            'analysis': {},
            'usage': [
                (1, {'stt_usd': 0.0011, 'llm_usd': 0.0033,
                     'tts_usd': 0.0025, 'telephony_usd': 0.0006}),
            ],
            'transfer': {
                'result': 'off_hours',
                'reason': 'Caller asked for reception after the transfer window '
                          'closed',
                'offset': 10,
                'duration_seconds': 0,
            },
        },
    ],
    'lakeside': [
        {
            'contact': ('Theo', 'Nakamura'),
            'from_number': '+13035550311',
            'mode': 'gemini',
            'status': 'completed',
            'day_offset': -2, 'hour': 13, 'minute': 44,
            'duration': 121,
            'recorded': True,
            'transcript': [
                (0, 'agent', 'Thanks for calling Globex Health Lakeside. How can '
                             'I help?'),
                (6, 'user', 'Where do I park when I come in on Thursday?'),
                (11, 'agent', 'There is free parking behind the building, off '
                              'Mill Lane. The rear entrance is step-free.'),
                (22, 'user', 'Great — and how early should I arrive?'),
                (27, 'agent', 'Ten minutes before your slot is plenty.'),
                (33, 'user', 'Thanks very much.'),
            ],
            'logs': [
                (0, 'info', 'call', 'Inbound call answered',
                 {'channel': 'agent_phone', 'answered_in_ms': 356}),
                (11, 'info', 'tool', 'get_location_info',
                 {'tool': 'get_location_info', 'arguments': {'topic': 'parking'},
                  'ok': True}),
                (121, 'info', 'call', 'Caller hung up', {'reason': 'caller_hangup'}),
            ],
            'analysis': {
                'summary': 'Known patient asked about parking and arrival time '
                           'ahead of an existing appointment. Both answered from '
                           'location settings.',
                'success_evaluation': 'success',
                'extracted_data': {
                    'intent': 'location_info',
                    'booking_made': False,
                    'caller_identified': True,
                    'sentiment': 'positive',
                },
            },
            'usage': [
                (1, {'stt_usd': 0.0023, 'llm_usd': 0.0052,
                     'tts_usd': 0.0044, 'telephony_usd': 0.0018}),
                (2, {'stt_usd': 0.0021, 'llm_usd': 0.0049,
                     'tts_usd': 0.0038, 'telephony_usd': 0.0018}),
                (3, {'stt_usd': 0.0013, 'llm_usd': 0.0036,
                     'tts_usd': 0.0022, 'telephony_usd': 0.0018}),
            ],
            'transfer': {},
        },
        {
            'contact': None,
            'from_number': '+13035550620',
            'mode': 'live',
            'status': 'failed',
            'day_offset': -3, 'hour': 15, 'minute': 10,
            'duration': 33,
            'recorded': False,
            'transcript': [
                (0, 'agent', 'Thanks for calling Globex Health Lakeside. How can '
                             'I help?'),
                (7, 'user', 'I want to speak to whoever runs the clinic.'),
                (12, 'agent', "Let me try to connect you."),
                (26, 'agent', "I'm sorry — I can't connect you from here. Please "
                              'call back during office hours.'),
            ],
            'logs': [
                (0, 'info', 'call', 'Inbound call answered',
                 {'channel': 'agent_phone', 'answered_in_ms': 372}),
                (12, 'info', 'tool', 'transfer_call',
                 {'tool': 'transfer_call',
                  'arguments': {'reason': 'asked for the clinic manager'},
                  'ok': False,
                  'error': {'code': 'transfer_not_configured',
                            'message': 'No transfer number for this location'}}),
                (13, 'error', 'transfer', 'Transfer failed — no destination '
                                          'configured',
                 {'result': 'failed', 'transfer_enabled': False,
                  'transfer_phone_number': ''}),
                (33, 'error', 'call', 'Session ended after a failed handoff',
                 {'reason': 'transfer_failed'}),
            ],
            # Empty on purpose: the call failed, and a failure summary would be
            # the event log's job, not analysis's.
            'analysis': {},
            'usage': [
                (1, {'stt_usd': 0.0014, 'llm_usd': 0.0038,
                     'tts_usd': 0.0031, 'telephony_usd': 0.0009}),
                (2, {'stt_usd': 0.0009, 'llm_usd': 0.0027,
                     'tts_usd': 0.0029, 'telephony_usd': 0.0009}),
            ],
            'transfer': {
                'result': 'failed',
                'reason': 'Caller asked for a person, but this location has no '
                          'transfer number configured',
                'offset': 12,
                'duration_seconds': 0,
            },
        },
    ],
}


class Command(BaseCommand):
    help = ('Seed demo call sessions — transcripts, event logs, analysis, '
            'per-turn usage and transfer outcomes — for the call log module. '
            'Idempotent.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--flush',
            action='store_true',
            help='Delete this module\'s demo rows for the demo tenants before '
                 're-seeding.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        tenants = {
            t.slug: t
            for t in Tenant.objects.filter(slug__in=DEMO_TENANT_SLUGS)
        }

        missing = [slug for slug in DEMO_TENANT_SLUGS if slug not in tenants]
        if missing:
            self.stderr.write(self.style.ERROR(
                f'Missing demo tenant(s): {", ".join(missing)}. '
                'Run `manage.py seed_tenants` first.'
            ))
            return

        if options['flush']:
            # No ordering care needed here, unlike `seed_scheduling`'s flush:
            # the only thing pointing at a CallSession is
            # `Appointment.booked_by_session`, and that FK is SET_NULL, so
            # deleting the sessions clears the link instead of raising
            # ProtectedError or — far worse — cascading away booking history.
            deleted, _ = CallSession.objects.filter(
                tenant__slug__in=DEMO_TENANT_SLUGS
            ).delete()
            self.stdout.write(self.style.WARNING(
                f'Flushed {deleted} demo call session row(s).'
            ))

        self._seed_call_sessions(tenants)

        self.stdout.write('')
        self.stdout.write('Sign in as a TENANT ADMIN to see this data:')
        for slug, tenant in sorted(tenants.items()):
            self.stdout.write(
                f'  {tenant.name}  (customer id {tenant.customer_id})  '
                f'-> admin_{slug}'
            )
        self.stdout.write(
            '  Password for every demo account: navai-demo-2026'
        )
        self.stdout.write(self.style.WARNING(
            "  Superuser 'admin' has no tenant — data won't appear when logged "
            'in as admin.'
        ))
        self.stdout.write(
            '  Call sessions are location-scoped like appointments: each site '
            'has its own log, so switch location to see the other four.'
        )
        self.stdout.write(
            '  One Downtown call is credited with creating a real booking — '
            'open it and follow the booking link, or open that appointment and '
            'read its "How this was booked" card.'
        )
        self.stdout.write(
            '  Rows with no contact are unidentified callers. That is the '
            'normal case, not missing data: nobody gave a name.'
        )
        self.stdout.write(
            '  Abandoned, failed and in-progress rows carry an EMPTY analysis '
            'on purpose — nothing happened to analyse.'
        )
        self.stdout.write(self.style.WARNING(
            '  No provider was contacted. This app has no provider adapter at '
            'all; every transcript, log and cost figure above is hand-authored '
            'fiction.'
        ))

    # -- 5.1 ----------------------------------------------------------------- #

    def _seed_call_sessions(self, tenants):
        """Seed the call log at every demo location.

        Dedupe key is `provider_call_sid` ALONE, which is the one field on this
        model carrying a database-level unique constraint — the same constraint
        that makes Module 3's webhook handler idempotent against Twilio's
        redelivery. Keying the seeder on it means the seeder and the runtime
        agree on what "the same call" means, instead of inventing a second
        answer.

        The sid is `FAKE-CALL-<location slug>-<n>`, generated from the row's
        position in its location's list, so it is stable across runs, obviously
        synthetic at a glance in the admin, and globally unique by construction
        (the constraint spans all tenants).
        """
        created = 0
        skipped = 0
        unresolved = 0

        locations = {
            location.slug: location
            for location in Location.objects.filter(tenant__in=tenants.values())
            .select_related('tenant')
        }

        for location_slug, specs in DEMO_CALL_SESSIONS.items():
            location = locations.get(location_slug)
            if location is None:
                self.stderr.write(self.style.WARNING(
                    f'  Skipping call sessions for "{location_slug}" — no such '
                    'location. Run `manage.py seed_tenants` first.'
                ))
                continue
            tenant = location.tenant

            for index, spec in enumerate(specs, start=1):
                sid = f'FAKE-CALL-{location_slug}-{index:04d}'
                if CallSession.objects.filter(provider_call_sid=sid).exists():
                    skipped += 1
                    continue

                contact = self._resolve_contact(tenant, spec['contact'])
                if spec['contact'] and contact is None:
                    # Named in the spec but absent from the directory — seeding
                    # it anyway would silently produce an unidentified caller,
                    # which is a DIFFERENT demo shape from the intended one and
                    # would quietly weaken the linked-contact coverage. Skip and
                    # say so.
                    unresolved += 1
                    continue

                started_at = self._start_for(location, spec)
                if started_at is None:
                    # The chosen wall time falls in a DST gap at this location.
                    unresolved += 1
                    continue

                ended_at = None
                if spec['duration'] is not None:
                    ended_at = started_at + timedelta(seconds=spec['duration'])

                session = CallSession.objects.create(
                    tenant=tenant,
                    location=location,
                    contact=contact,
                    channel='agent_phone',
                    mode=spec['mode'],
                    status=spec['status'],
                    from_number=spec['from_number'],
                    to_number=DIALLED_NUMBERS[location_slug],
                    provider_call_sid=sid,
                    transcript=self._build_transcript(spec, started_at),
                    logs=self._build_logs(spec, started_at),
                    analysis=spec['analysis'],
                    usage=self._build_usage(spec),
                    transfer=self._build_transfer(spec, location_slug, started_at),
                    waveform_peaks=self._build_waveform(spec),
                    metadata=self._build_metadata(spec, location),
                    recording_blob=(
                        f'private/calls/{tenant.slug}/{location_slug}/{sid}.mp3'
                        if spec['recorded'] else ''
                    ),
                    started_at=started_at,
                    ended_at=ended_at,
                )
                created += 1

                if spec.get('books'):
                    if not self._link_booked_appointment(session):
                        unresolved += 1

        self.stdout.write(self.style.SUCCESS(
            f'Call sessions: {created} created, {skipped} already present.'
        ))
        if unresolved:
            self.stdout.write(self.style.WARNING(
                f'  {unresolved} row(s) skipped or partially seeded — a contact '
                'or appointment could not be resolved. Run '
                '`manage.py seed_scheduling` first.'
            ))

        # Relink pass, kept OUTSIDE the create branch above so a re-run repairs a
        # link that was lost (a flushed session SET_NULLs it) instead of leaving
        # the booking bullet undemonstrable until someone flushes everything.
        # It writes nothing when the link is already correct, so it costs a
        # re-run zero writes.
        self._relink_booked_appointments()

    # -- helpers ------------------------------------------------------------- #

    def _resolve_contact(self, tenant, name):
        """Look up a seeded contact by `(tenant, first_name, last_name)`.

        The same triple `seed_scheduling._seed_appointments` uses. `None` in the
        spec means an unidentified caller and resolves to `None` without a
        lookup — that is a valid, common state, not a failed match.
        """
        if not name:
            return None
        from apps.scheduling.models import Contact

        first, last = name
        return Contact.objects.filter(
            tenant=tenant, first_name=first, last_name=last
        ).first()

    def _start_for(self, location, spec):
        """Resolve a row's `started_at` as an aware UTC instant.

        Finished calls use a FIXED `day_offset` + local wall time converted
        through THIS location's zone, so Lakeside's Denver rows do not land an
        hour off Riverside's Pacific ones, and so a second run reproduces the
        same instant rather than drifting.

        An IN-PROGRESS call is the deliberate exception: it is anchored to
        `now()`, because a call that is still up has to have started a moment
        ago. A fixed hour would put it in the future for most of the working day
        and render as a live call that has not begun. This costs no idempotency
        here — unlike an appointment, whose dedupe key IS its start time, this
        model's key is `provider_call_sid`, so a moving stamp is never written
        twice.

        Returns None when the chosen wall time falls in a DST gap.
        """
        if spec['status'] == CallSession.STATUS_IN_PROGRESS:
            return timezone.now() - timedelta(
                seconds=spec.get('live_seconds_ago', 60)
            )

        local_day = location.local_now().date() + timedelta(
            days=spec['day_offset']
        )
        return _local_naive_to_utc(
            datetime.combine(local_day, dt_time(spec['hour'], spec['minute'])),
            location.tzinfo,
        )

    def _build_transcript(self, spec, started_at):
        """`[{sequence, role, text, at, offset}]`, exactly as 5.2 reads it.

        `sequence` and `at` are DERIVED from the authored `(offset, role, text)`
        tuples rather than typed alongside them: a hand-typed absolute stamp
        would drift from `started_at` the moment a day offset changed, and the
        transcript would then narrate a call that started at a different time
        than the row says it did.
        """
        return [
            {
                'sequence': index,
                'role': role,
                'text': text,
                'at': (started_at + timedelta(seconds=offset)).isoformat(),
                'offset': offset,
            }
            for index, (offset, role, text) in enumerate(
                spec['transcript'], start=1
            )
        ]

    def _build_logs(self, spec, started_at):
        """`[{sequence, level, category, title, raw_json, occurred_at}]`.

        Same derived-timestamp treatment as the transcript. Every `raw_json`
        below is authored with tool ARGUMENTS ALREADY REDACTED, because that is
        what the runtime is required to persist — the log is read by staff, and
        a `create_contact` payload is a full name and a date of birth.
        """
        return [
            {
                'sequence': index,
                'level': level,
                'category': category,
                'title': title,
                'raw_json': raw_json,
                'occurred_at': (
                    started_at + timedelta(seconds=offset)
                ).isoformat(),
            }
            for index, (offset, level, category, title, raw_json) in enumerate(
                spec['logs'], start=1
            )
        ]

    def _build_usage(self, spec):
        """`[{turn_sequence, cost_breakdown, cost_usd}]`.

        `cost_usd` is SUMMED from its own breakdown rather than authored beside
        it. A per-turn total that disagrees with its components is a bug 5.3
        would render faithfully and nobody would spot, and typing both by hand
        guarantees that bug eventually. Rounded to 4 dp because these are
        sub-cent figures and binary float addition otherwise leaves a tail.
        """
        return [
            {
                'turn_sequence': turn_sequence,
                'cost_breakdown': breakdown,
                'cost_usd': round(sum(breakdown.values()), 4),
            }
            for turn_sequence, breakdown in spec['usage']
        ]

    def _build_transfer(self, spec, location_slug, started_at):
        """`{result, reason, destination, initiated_at, duration_seconds}`.

        Returns `{}` untouched for the rows that never attempted a transfer —
        the common case, and the one the shipped `_transfer_outcome.html` skips
        rendering entirely.

        `destination` is NOT authored per row: it is read from the location's
        configured transfer number, because that partial's own comment states
        the rule — the destination shown is always the CONFIGURED number, never
        one a caller or a model produced. Uptown and Lakeside have none, which
        is precisely why their outcomes are `disabled` and `failed`.
        """
        transfer = spec['transfer']
        if not transfer:
            return {}

        return {
            'result': transfer['result'],
            'reason': transfer['reason'],
            'destination': TRANSFER_DESTINATIONS[location_slug],
            'initiated_at': (
                started_at + timedelta(seconds=transfer['offset'])
            ).isoformat(),
            'duration_seconds': transfer['duration_seconds'],
        }

    def _build_waveform(self, spec):
        """`{caller, bot, bins}` for 5.4's waveform, or NULL.

        NULL — not an empty dict — on an unrecorded call. The column's own help
        text draws the distinction: absent means "never computed", which is not
        the same claim as a recording that is genuinely silent.

        The peaks are a short deterministic pattern rather than random noise, so
        a re-seed produces a byte-identical row and a diff of the demo data
        stays readable.
        """
        if not spec['recorded']:
            return None

        caller = [0.12, 0.48, 0.71, 0.35, 0.19, 0.62, 0.88, 0.41,
                  0.23, 0.55, 0.34, 0.17]
        bot = [0.66, 0.31, 0.14, 0.58, 0.79, 0.27, 0.15, 0.63,
               0.72, 0.29, 0.51, 0.38]
        return {'caller': caller, 'bot': bot, 'bins': len(caller)}

    def _build_metadata(self, spec, location):
        """Call-level detail that needs no column of its own.

        The consent basis and the retention window live HERE, on the row that
        was actually recorded, because the policy that applies to a recording is
        the policy in force at the time of the call — not whatever the location
        is configured with today. An unrecorded call records that fact
        explicitly rather than omitting the keys, so "we did not record" is
        distinguishable from "nobody wrote this field".
        """
        metadata = {
            'direction': 'inbound',
            'location_timezone': location.timezone,
            'agent_version': '2026.07.1',
            'provider_mode': 'fake',
        }
        if spec['recorded']:
            metadata.update({
                'recorded': True,
                'consent_basis': 'announced_notice',
                'consent_announced': True,
                'retention_days': 90,
            })
        else:
            metadata.update({
                'recorded': False,
                'consent_basis': 'not_recorded',
                'consent_announced': False,
                'retention_days': 0,
            })
        return metadata

    # -- the booking link ---------------------------------------------------- #

    def _link_booked_appointment(self, session):
        """Credit one seeded appointment to the call that booked it.

        Resolved by `(tenant, location, contact, service name)` plus one
        semantic constraint: the appointment must START AFTER the call. A call
        cannot have booked something that already happened, and that constraint
        is also what makes the choice deterministic — Dana has three Downtown
        check-ups in `seed_scheduling`, one of them a fortnight in the past, and
        "earliest one after the call" picks the same row on every run where a
        bare `.first()` would depend on insertion order.

        Returns True when a link was made or already existed.
        """
        from apps.scheduling.models import Appointment

        if session.contact_id is None or session.started_at is None:
            return False

        appointment = Appointment.objects.filter(
            tenant=session.tenant,
            location=session.location,
            contact=session.contact,
            service__name='Routine check-up',
            start_at__gte=session.started_at,
        ).exclude(
            status=Appointment.STATUS_CANCELLED
        ).order_by('start_at').first()

        if appointment is None:
            return False
        if appointment.booked_by_session_id == session.pk:
            return True

        appointment.booked_by_session = session
        appointment.save(update_fields=['booked_by_session', 'updated_at'])
        return True

    def _relink_booked_appointments(self):
        """Repair the booking link on a re-run without re-creating anything.

        The create loop above skips a session that already exists, so a link
        broken since the first run — a flushed session SET_NULLs it — would stay
        broken forever. This pass re-resolves it for every seeded row marked
        `books`, and writes only when the link is actually wrong, so a healthy
        re-run performs zero writes.
        """
        for location_slug, specs in DEMO_CALL_SESSIONS.items():
            for index, spec in enumerate(specs, start=1):
                if not spec.get('books'):
                    continue
                session = CallSession.objects.filter(
                    provider_call_sid=f'FAKE-CALL-{location_slug}-{index:04d}'
                ).select_related('tenant', 'location', 'contact').first()
                if session is not None:
                    self._link_booked_appointment(session)
