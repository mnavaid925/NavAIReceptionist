"""Event log and cost-breakdown cards on the call-detail page (sub-module 5.3).

5.3 ships NO model and NO migration — it is two more reading surfaces over JSON
columns 5.1 already put on `calls.CallSession` (`logs`, `usage`), folded into
the SAME detail page 5.1/5.2 already render. Cross-tenant/location isolation
for the detail page is already proven in `test_security.py` against the same
route; this file only adds the two new cards' own render behaviour, including
the end-to-end redaction proof (`redact_args` in `test_ui_filters.py` proves
the filter in isolation, this proves the whole page never leaks the values it
is handed).
"""
from django.urls import reverse

import pytest

pytestmark = pytest.mark.django_db


def _url(name, *args):
    return reverse(f'calls:{name}', args=args)


def _log_entry(sequence, level, category, title, occurred_at, raw_json=None):
    return {
        'sequence': sequence,
        'level': level,
        'category': category,
        'title': title,
        'occurred_at': occurred_at,
        'raw_json': raw_json if raw_json is not None else {},
    }


# --------------------------------------------------------------------------- #
# Event log card
# --------------------------------------------------------------------------- #

def test_detail_view_renders_event_log_card_with_tool_name_level_badge_and_duration(
    client_a, tenant_a, location_a1, make_call_session,
):
    logs = [
        _log_entry(1, 'info', 'tool', 'check_availability', '2026-01-01T10:00:05+00:00', raw_json={
            'tool': 'check_availability',
            'ok': True,
            'duration_ms': 420,
            'arguments': {'service': 'Cleaning', 'day': '2026-01-02'},
        }),
    ]
    session = make_call_session(tenant_a, location_a1, logs=logs)

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'Event log' in content
    assert 'check_availability' in content
    assert 'badge-info' in content
    assert '420ms' in content


def test_detail_view_renders_error_count_badge_and_failed_tool_outcome(
    client_a, tenant_a, location_a1, make_call_session,
):
    logs = [
        _log_entry(1, 'error', 'tool', 'book_appointment', '2026-01-01T10:00:05+00:00', raw_json={
            'tool': 'book_appointment',
            'ok': False,
            'error': {'code': 'slot_unavailable', 'message': 'That slot was just taken.'},
        }),
        _log_entry(2, 'critical', 'runtime', 'stream_dropped', '2026-01-01T10:00:10+00:00'),
        _log_entry(3, 'info', 'runtime', 'call_started', '2026-01-01T10:00:00+00:00'),
    ]
    session = make_call_session(tenant_a, location_a1, logs=logs)

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200
    content = response.content.decode()
    assert '2 errors' in content
    assert 'badge-red' in content
    assert 'slot_unavailable' in content
    assert 'That slot was just taken.' in content


# --------------------------------------------------------------------------- #
# Cost breakdown card
# --------------------------------------------------------------------------- #

def test_detail_view_renders_cost_breakdown_table_and_total(
    client_a, tenant_a, location_a1, make_call_session,
):
    usage = [
        {
            'turn_sequence': 1,
            'cost_breakdown': {'stt_usd': 0.001, 'llm_usd': 0.002, 'tts_usd': 0.001, 'telephony_usd': 0.0005},
            'cost_usd': 0.0045,
        },
        {
            'turn_sequence': 2,
            'cost_breakdown': {'stt_usd': 0.001, 'llm_usd': 0.003, 'tts_usd': 0.001, 'telephony_usd': 0.0005},
            'cost_usd': 0.0055,
        },
    ]
    session = make_call_session(tenant_a, location_a1, usage=usage)

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'Cost breakdown' in content
    assert '$0.0045' in content  # turn 1's per-turn total
    assert '$0.0055' in content  # turn 2's per-turn total
    assert f'${session.total_cost_usd:.4f}' in content
    assert session.total_cost_usd == 0.01


# --------------------------------------------------------------------------- #
# THE end-to-end redaction proof — the highest-value test in this sub-module
# --------------------------------------------------------------------------- #

def test_detail_view_never_leaks_pii_values_from_a_doubly_nested_and_list_tool_call(
    client_a, tenant_a, location_a1, make_call_session,
):
    """A tool-call log entry carrying UN-redacted PII — doubly nested under
    `arguments.contact`, plus a bare-string list canary under `attendees` — must
    never surface its VALUES anywhere in the rendered page, including inside the
    `<details>` raw-payload block. The KEYS (`contact`, `attendees`, tool name)
    may still appear; only the sensitive values must be hidden.
    """
    logs = [
        _log_entry(1, 'info', 'tool', 'create_contact', '2026-01-01T10:00:05+00:00', raw_json={
            'tool': 'create_contact',
            'ok': True,
            'duration_ms': 210,
            'arguments': {
                'contact': {
                    'first_name': 'SUPERSECRETFIRST',
                    'last_name': 'SUPERSECRETLAST',
                    'phone_e164': '+13125559999',
                    'date_of_birth': '1990-05-05',
                },
                'attendees': ['CANARY_BARE_ATTENDEE_NAME'],
                'service': 'Cleaning',
            },
        }),
    ]
    session = make_call_session(tenant_a, location_a1, logs=logs)

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200
    content = response.content.decode()

    for secret in (
        'SUPERSECRETFIRST', 'SUPERSECRETLAST', '+13125559999', '1990-05-05',
        'CANARY_BARE_ATTENDEE_NAME',
    ):
        assert secret not in content

    # Keys, the tool name and the benign field survive — only VALUES are hidden.
    assert 'create_contact' in content
    assert 'contact' in content
    assert 'attendees' in content
    assert 'Cleaning' in content
    assert '[redacted]' in content


# --------------------------------------------------------------------------- #
# Empty states
# --------------------------------------------------------------------------- #

def test_detail_view_empty_logs_renders_no_event_log_empty_state(
    client_a, tenant_a, location_a1, make_call_session,
):
    session = make_call_session(tenant_a, location_a1, logs=[])

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'No event log' in content


def test_detail_view_empty_usage_renders_no_cost_recorded_empty_state(
    client_a, tenant_a, location_a1, make_call_session,
):
    session = make_call_session(tenant_a, location_a1, usage=[])

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'No cost recorded' in content


def test_detail_view_empty_logs_and_usage_render_no_raw_none(
    client_a, tenant_a, location_a1, make_call_session,
):
    session = make_call_session(tenant_a, location_a1, logs=[], usage=[], analysis={})

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'No event log' in content
    assert 'No cost recorded' in content
    assert 'None' not in content
