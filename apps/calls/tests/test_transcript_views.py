"""Transcript panel, analysis panel and the printable-transcript page
(sub-module 5.2).

5.2 ships NO model and NO migration — it is two reading surfaces over JSON
columns 5.1 already put on `calls.CallSession`: the transcript/analysis panels
folded into the existing detail page, and a second, print-oriented rendering of
the same transcript at `calls:callsession_transcript_print`.

Cross-tenant/location isolation for the print view lives in `test_security.py`,
mirroring how 5.1's own isolation tests are split out from `test_views.py`.
"""
from django.urls import reverse

import pytest

pytestmark = pytest.mark.django_db


def _url(name, *args):
    return reverse(f'calls:{name}', args=args)


def _turn(sequence, role, text):
    return {
        'sequence': sequence,
        'role': role,
        'text': text,
        'at': f'2026-01-01T10:00:{sequence:02d}Z',
        'offset': sequence,
    }


# --------------------------------------------------------------------------- #
# Detail page — transcript panel
# --------------------------------------------------------------------------- #

def test_detail_view_renders_transcript_turns_in_order(client_a, tenant_a, location_a1, make_call_session):
    transcript = [
        _turn(1, 'agent', 'Thanks for calling Acme, how can I help?'),
        _turn(2, 'user', 'I need to book an appointment for a cleaning.'),
        _turn(3, 'agent', 'Sure, let me check availability for you.'),
    ]
    session = make_call_session(tenant_a, location_a1, transcript=transcript)

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200
    content = response.content.decode()

    for turn in transcript:
        assert turn['text'] in content

    # Order — the partial iterates `session.transcript` as stored, so each
    # turn's text must appear strictly after the previous one's.
    positions = [content.find(turn['text']) for turn in transcript]
    assert positions == sorted(positions)
    assert all(p != -1 for p in positions)

    # Speaker labels — 'agent' turns render "Agent", everything else "Caller".
    assert 'Agent' in content
    assert 'Caller' in content


def test_detail_view_empty_transcript_shows_empty_state(client_a, tenant_a, location_a1, make_call_session):
    session = make_call_session(tenant_a, location_a1, transcript=[])

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'No transcript' in content
    assert 'This call ended before any speech was captured.' in content


# --------------------------------------------------------------------------- #
# Detail page — analysis panel
# --------------------------------------------------------------------------- #

def test_detail_view_populated_analysis_renders_summary_evaluation_and_extracted_data(
    client_a, tenant_a, location_a1, make_call_session,
):
    session = make_call_session(tenant_a, location_a1, analysis={
        'summary': 'Caller booked a cleaning for next Tuesday.',
        'success_evaluation': 'Goal achieved',
        'extracted_data': {'requested_service': 'Cleaning'},
    })

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'Caller booked a cleaning for next Tuesday.' in content
    assert 'Goal achieved' in content
    assert 'requested_service' in content
    assert 'Cleaning' in content
    assert 'Extracted details' in content


def test_detail_view_empty_analysis_shows_no_analysis_empty_state(
    client_a, tenant_a, location_a1, make_call_session,
):
    """The abandoned-call path: `analysis == {}` must render the empty state,
    never a raw "None" leaking out of an un-guarded `{{ obj.analysis.x }}`.
    """
    session = make_call_session(tenant_a, location_a1, analysis={})

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'No analysis' in content
    assert 'Nothing happened on this call to analyse' in content
    assert 'None' not in content


@pytest.mark.parametrize('bad_extracted_data', [
    'a plain string, not a dict',
    ['a', 'list', 'not', 'a', 'dict'],
])
def test_detail_view_non_dict_extracted_data_falls_through_cleanly(
    client_a, tenant_a, location_a1, make_call_session, bad_extracted_data,
):
    """A non-dict `extracted_data` must not render the "Extracted details"
    table — `.items` fails Django's variable resolution the same safe way an
    absent key does, and `summary`/`success_evaluation` being present here
    proves the fallback message does not ALSO fire, i.e. this really is a
    silent, clean skip rather than a caught exception.
    """
    session = make_call_session(tenant_a, location_a1, analysis={
        'summary': 'Caller asked about billing.',
        'success_evaluation': 'Partially resolved',
        'extracted_data': bad_extracted_data,
    })

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'Caller asked about billing.' in content
    assert 'Partially resolved' in content
    assert 'Extracted details' not in content
    assert 'This call was analysed, but none of its details are in a form this page can show yet.' not in content


# --------------------------------------------------------------------------- #
# Print view
# --------------------------------------------------------------------------- #

def test_print_view_renders_transcript_for_in_tenant_in_location_session(
    client_a, tenant_a, location_a1, make_call_session,
):
    transcript = [
        _turn(1, 'agent', 'Acme Dental, how can I help you today?'),
        _turn(2, 'user', 'I would like to reschedule my appointment.'),
    ]
    session = make_call_session(tenant_a, location_a1, transcript=transcript)

    response = client_a.get(_url('callsession_transcript_print', session.pk))

    assert response.status_code == 200
    assert 'calls/transcript/transcript_print.html' in [t.name for t in response.templates]
    content = response.content.decode()
    assert 'Acme Dental, how can I help you today?' in content
    assert 'I would like to reschedule my appointment.' in content


def test_print_view_sends_no_store_cache_control(client_a, tenant_a, location_a1, make_call_session):
    session = make_call_session(tenant_a, location_a1)

    response = client_a.get(_url('callsession_transcript_print', session.pk))

    assert response.status_code == 200
    assert 'no-store' in response.headers['Cache-Control']


def test_print_view_queryset_query_count_does_not_grow_with_turn_count(
    tenant_a, location_a1, make_call_session,
):
    """The transcript is a JSON column already loaded with the row — iterating
    more turns in Python must add ZERO extra queries. Measured against the
    view's own queryset (`location_sessions` + `get_object_or_404`), the same
    convention `test_list_queryset_query_count_does_not_grow_with_row_count`
    uses in `test_views.py`, rather than through the full `Client` stack whose
    middleware overhead is a constant unrelated to this page's own cost.
    """
    from types import SimpleNamespace

    from django.db import connection
    from django.shortcuts import get_object_or_404
    from django.test.utils import CaptureQueriesContext

    from apps.calls.views._helpers import location_sessions

    request = SimpleNamespace(tenant=tenant_a, location=location_a1)

    small_transcript = [_turn(i, 'agent' if i % 2 == 0 else 'user', f'turn {i}') for i in range(3)]
    small_session = make_call_session(
        tenant_a, location_a1, transcript=small_transcript, provider_call_sid='CA-print-qc-small',
    )
    with CaptureQueriesContext(connection) as small:
        obj = get_object_or_404(location_sessions(request), pk=small_session.pk)
        assert len(list(obj.transcript)) == 3

    big_transcript = [_turn(i, 'agent' if i % 2 == 0 else 'user', f'turn {i}') for i in range(200)]
    big_session = make_call_session(
        tenant_a, location_a1, transcript=big_transcript, provider_call_sid='CA-print-qc-big',
    )
    with CaptureQueriesContext(connection) as big:
        obj = get_object_or_404(location_sessions(request), pk=big_session.pk)
        assert len(list(obj.transcript)) == 200

    assert len(big.captured_queries) == len(small.captured_queries)
