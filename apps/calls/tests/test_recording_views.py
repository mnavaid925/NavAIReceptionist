"""The signed recording serve view, its Range support, and the recording +
transfer-outcome cards on the call-detail page (sub-module 5.4).

`callsession_recording_view` is the whole reason 5.4 has a backend at all — see
its own module docstring for the three independent gates (signature, tenant+
location scope, session-id binding). This file proves each gate fails CLOSED,
proves Range works (206/416/suffix/malformed), and proves the detail page's
`_recording_context` + the two 5.4 partials (`_audio_player.html`,
`_transfer_outcome.html`) render defensively.

Every test that writes a real file into `recording_storage` cleans it up via the
`recorded_file` fixture below, regardless of pass/fail — this suite must leave
`PRIVATE_MEDIA_ROOT` (redirected to `temp/test-private-media/` by
`config/settings_test.py`) exactly as it found it.
"""
import uuid
from datetime import timedelta

import pytest
from django.conf import settings
from django.core import signing
from django.core.files.base import ContentFile
from django.test import RequestFactory
from django.urls import reverse

from apps.calls.storage import recording_storage, save_recording
from apps.calls.views.CallLogList.CallSessions import _recording_context
from apps.calls.views.RecordingTransferOutcome.CallSessions import (
    _parse_single_range,
    callsession_recording_view,
)

pytestmark = pytest.mark.django_db


def _url(name, *args):
    return reverse(f'calls:{name}', args=args)


def _sig(session_id, salt=None):
    return signing.dumps({'session_id': session_id}, salt=salt or settings.RECORDING_ACCESS_SALT)


def _consume(response):
    """Force a streaming response's body to bytes AND its file handle closed.

    Unlike a plain `HttpResponse`, Django's test client does NOT populate
    `.content` for a `FileResponse`/`StreamingHttpResponse` — it leaves
    `streaming_content` for the caller to drain. Draining it here is what fires
    `ClientHandler`'s `closing_iterator_wrapper`, which calls `response.close()`
    — so this is also what releases the underlying file handle before the
    `recorded_file` fixture tries to delete it (required on Windows, which
    refuses to delete a file with an open handle).
    """
    return b''.join(response.streaming_content)


@pytest.fixture
def recorded_file():
    """Write a real file into the private recording storage for one test, and
    delete it afterward regardless of pass/fail.
    """
    written = []

    def _write(content=b'0123456789'):
        name = f'test/{uuid.uuid4().hex}.bin'
        path = save_recording(name, ContentFile(content))
        written.append(path)
        return path

    yield _write

    for path in written:
        if recording_storage.exists(path):
            recording_storage.delete(path)


# --------------------------------------------------------------------------- #
# `_parse_single_range` — pure-function unit tests, no client, no DB needed
# --------------------------------------------------------------------------- #

def test_parse_single_range_valid_returns_start_end_inclusive():
    assert _parse_single_range('bytes=0-4', 10) == (0, 4)


def test_parse_single_range_no_end_returns_to_end_of_file():
    assert _parse_single_range('bytes=5-', 10) == (5, 9)


def test_parse_single_range_end_clamped_to_file_size():
    assert _parse_single_range('bytes=0-999', 10) == (0, 9)


@pytest.mark.parametrize('header', ['', None])
def test_parse_single_range_no_header_returns_none(header):
    assert _parse_single_range(header, 10) is None


def test_parse_single_range_inverted_is_unsatisfiable():
    assert _parse_single_range('bytes=10-5', 20) == 'unsatisfiable'


def test_parse_single_range_start_past_end_of_file_is_unsatisfiable():
    assert _parse_single_range('bytes=20-25', 10) == 'unsatisfiable'


def test_parse_single_range_suffix_returns_last_n_bytes():
    assert _parse_single_range('bytes=-3', 10) == (7, 9)


def test_parse_single_range_suffix_longer_than_file_clamps_to_start():
    assert _parse_single_range('bytes=-100', 10) == (0, 9)


def test_parse_single_range_suffix_zero_length_is_unsatisfiable():
    assert _parse_single_range('bytes=-0', 10) == 'unsatisfiable'


def test_parse_single_range_suffix_with_no_digits_returns_none():
    assert _parse_single_range('bytes=-', 10) is None


def test_parse_single_range_malformed_unit_returns_none():
    assert _parse_single_range('rows=1-2', 10) is None


def test_parse_single_range_multi_range_falls_back_to_none():
    assert _parse_single_range('bytes=0-1,5-6', 10) is None


def test_parse_single_range_non_numeric_values_return_none():
    assert _parse_single_range('bytes=a-b', 10) is None


def test_parse_single_range_no_dash_in_spec_returns_none():
    assert _parse_single_range('bytes=', 10) is None


# --------------------------------------------------------------------------- #
# The serve view — signature gate
# --------------------------------------------------------------------------- #

def test_serve_view_valid_signature_and_real_file_serves_exact_bytes(
    client_a, tenant_a, location_a1, make_call_session, recorded_file,
):
    content = b'ID3-fake-mp3-bytes-0123456789'
    path = recorded_file(content)
    session = make_call_session(tenant_a, location_a1, recording_blob=path)
    token = _sig(session.pk)

    response = client_a.get(_url('callsession_recording', session.pk), {'sig': token})

    assert response.status_code == 200
    assert _consume(response) == content
    # Not exact equality: `@never_cache` (outside this view's own `no-store`
    # assignment) layers its own directives on top via `patch_cache_control`,
    # so the final header is `no-store` PLUS `max-age=0, no-cache,
    # must-revalidate, private` — all strictly stricter, never weaker. Matches
    # the substring check `test_print_view_sends_no_store_cache_control` uses
    # in `test_transcript_views.py` for the same reason.
    assert 'no-store' in response.headers['Cache-Control']
    assert response.headers['Accept-Ranges'] == 'bytes'


def test_serve_view_missing_signature_is_404(client_a, tenant_a, location_a1, make_call_session, recorded_file):
    path = recorded_file()
    session = make_call_session(tenant_a, location_a1, recording_blob=path)

    response = client_a.get(_url('callsession_recording', session.pk))

    assert response.status_code == 404


def test_serve_view_tampered_signature_is_404(client_a, tenant_a, location_a1, make_call_session, recorded_file):
    path = recorded_file()
    session = make_call_session(tenant_a, location_a1, recording_blob=path)
    token = _sig(session.pk)
    tampered = token[:-1] + ('Q' if token[-1] != 'Q' else 'Z')

    response = client_a.get(_url('callsession_recording', session.pk), {'sig': tampered})

    assert response.status_code == 404


def test_serve_view_wrong_salt_signature_is_404(client_a, tenant_a, location_a1, make_call_session, recorded_file):
    path = recorded_file()
    session = make_call_session(tenant_a, location_a1, recording_blob=path)
    token = _sig(session.pk, salt='some.other.salt')

    response = client_a.get(_url('callsession_recording', session.pk), {'sig': token})

    assert response.status_code == 404


def test_serve_view_expired_signature_is_404(
    settings, client_a, tenant_a, location_a1, make_call_session, recorded_file,
):
    """`-1` rather than `0`: `TimestampSigner`'s resolution is whole seconds, so
    a `max_age=0` check could still pass if mint-and-request land in the same
    second. `-1` forces `age > max_age` regardless of clock granularity.
    """
    path = recorded_file()
    session = make_call_session(tenant_a, location_a1, recording_blob=path)
    token = _sig(session.pk)
    settings.RECORDING_SIGNED_URL_TTL = -1

    response = client_a.get(_url('callsession_recording', session.pk), {'sig': token})

    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# The serve view — session-id binding (a signature is per-CALL, not per-user)
# --------------------------------------------------------------------------- #

def test_serve_view_token_bound_to_a_different_in_scope_session_is_404(
    client_a, tenant_a, location_a1, make_call_session, recorded_file,
):
    path_1 = recorded_file()
    path_2 = recorded_file()
    session_1 = make_call_session(
        tenant_a, location_a1, recording_blob=path_1, provider_call_sid='CA-rec-bound-1',
    )
    session_2 = make_call_session(
        tenant_a, location_a1, recording_blob=path_2, provider_call_sid='CA-rec-bound-2',
    )
    token_for_1 = _sig(session_1.pk)

    response = client_a.get(_url('callsession_recording', session_2.pk), {'sig': token_for_1})

    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# THE core security tests — a signature proves freshness, never authorisation
# --------------------------------------------------------------------------- #

def test_serve_view_fresh_signature_for_cross_tenant_session_is_404(client_a, session_b, recorded_file):
    """Signed correctly, for a REAL tenant-B session, with a signature minted
    just now — and it must still 404 for tenant A's client. If this ever
    passed, the signature alone would be a bearer credential across tenants.
    """
    path = recorded_file()
    session_b.recording_blob = path
    session_b.save(update_fields=['recording_blob'])
    token = _sig(session_b.pk)

    response = client_a.get(_url('callsession_recording', session_b.pk), {'sig': token})

    assert response.status_code == 404


def test_serve_view_fresh_signature_for_cross_location_session_is_404(
    client_a, session_a2, recorded_file,
):
    """`client_a` is active at A1; `session_a2` is the SAME tenant's A2 — the
    signature is fresh and correctly signed, and it must still 404.
    """
    path = recorded_file()
    session_a2.recording_blob = path
    session_a2.save(update_fields=['recording_blob'])
    token = _sig(session_a2.pk)

    response = client_a.get(_url('callsession_recording', session_a2.pk), {'sig': token})

    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Fileless recording — a 404, never a 500
# --------------------------------------------------------------------------- #

def test_serve_view_fileless_recording_blob_is_404_not_500(
    client_a, tenant_a, location_a1, make_call_session,
):
    """`recording_blob` set but no bytes were ever written behind it — the
    ordinary shape of a `PROVIDER_MODE=fake` database.
    """
    session = make_call_session(tenant_a, location_a1, recording_blob='never-written.wav')
    token = _sig(session.pk)

    response = client_a.get(_url('callsession_recording', session.pk), {'sig': token})

    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Auth / method
# --------------------------------------------------------------------------- #

def test_serve_view_anonymous_redirects_to_login(client, tenant_a, location_a1, make_call_session):
    session = make_call_session(tenant_a, location_a1)

    response = client.get(_url('callsession_recording', session.pk))

    assert response.status_code == 302
    assert response.url.startswith(reverse('accounts:login'))


def test_serve_view_post_is_405(client_a, tenant_a, location_a1, make_call_session):
    session = make_call_session(tenant_a, location_a1)

    response = client_a.post(_url('callsession_recording', session.pk), {})

    assert response.status_code == 405


# --------------------------------------------------------------------------- #
# HTTP Range — 206 slice, 416 unsatisfiable, malformed fallback, suffix
# --------------------------------------------------------------------------- #

def test_serve_view_valid_range_returns_206_with_content_range_and_exact_slice(
    client_a, tenant_a, location_a1, make_call_session, recorded_file,
):
    content = b'0123456789'
    path = recorded_file(content)
    session = make_call_session(tenant_a, location_a1, recording_blob=path)
    token = _sig(session.pk)

    response = client_a.get(
        _url('callsession_recording', session.pk), {'sig': token}, HTTP_RANGE='bytes=0-4',
    )

    assert response.status_code == 206
    assert response.headers['Content-Range'] == f'bytes 0-4/{len(content)}'
    assert response.headers['Accept-Ranges'] == 'bytes'
    assert _consume(response) == content[0:5]


def test_serve_view_inverted_range_is_416_with_unsatisfiable_content_range(
    client_a, tenant_a, location_a1, make_call_session, recorded_file,
):
    content = b'0123456789'
    path = recorded_file(content)
    session = make_call_session(tenant_a, location_a1, recording_blob=path)
    token = _sig(session.pk)

    response = client_a.get(
        _url('callsession_recording', session.pk), {'sig': token}, HTTP_RANGE='bytes=10-5',
    )

    assert response.status_code == 416
    assert response.headers['Content-Range'] == f'bytes */{len(content)}'


def test_serve_view_malformed_range_unit_falls_back_to_full_200(
    client_a, tenant_a, location_a1, make_call_session, recorded_file,
):
    content = b'0123456789'
    path = recorded_file(content)
    session = make_call_session(tenant_a, location_a1, recording_blob=path)
    token = _sig(session.pk)

    response = client_a.get(
        _url('callsession_recording', session.pk), {'sig': token}, HTTP_RANGE='rows=1-2',
    )

    assert response.status_code == 200
    assert _consume(response) == content


def test_serve_view_suffix_range_returns_last_n_bytes(
    client_a, tenant_a, location_a1, make_call_session, recorded_file,
):
    content = b'0123456789'
    path = recorded_file(content)
    session = make_call_session(tenant_a, location_a1, recording_blob=path)
    token = _sig(session.pk)

    response = client_a.get(
        _url('callsession_recording', session.pk), {'sig': token}, HTTP_RANGE='bytes=-3',
    )

    assert response.status_code == 206
    assert response.headers['Content-Range'] == f'bytes 7-9/{len(content)}'
    assert _consume(response) == content[-3:]


# --------------------------------------------------------------------------- #
# Query count — measured against the view function directly, matching the
# existing convention (`test_views.py`'s own query-count section): a Client
# request carries several constant queries of middleware overhead unrelated to
# the view's own cost, so `max_num_queries` is asserted against a hand-built
# request that skips the middleware chain entirely.
# --------------------------------------------------------------------------- #

def test_serve_view_runs_at_most_two_queries(
    django_assert_max_num_queries, tenant_a, location_a1, admin_user, make_call_session, recorded_file,
):
    """`.prefetch_related(None)` is what keeps this lean — the serve path reads
    only `recording_blob` and never renders a template, so the list/detail
    page's `booked_appointments__service` prefetch chain would be two wasted
    queries on every single byte-range request a scrub makes.
    """
    path = recorded_file()
    session = make_call_session(tenant_a, location_a1, recording_blob=path)
    token = _sig(session.pk)

    request = RequestFactory().get(_url('callsession_recording', session.pk), {'sig': token})
    request.user = admin_user
    request.tenant = tenant_a
    request.location = location_a1

    with django_assert_max_num_queries(2):
        response = callsession_recording_view(request, pk=session.pk)

    assert response.status_code == 200
    # Called directly rather than through `Client`, so nothing wraps
    # `streaming_content` in the test client's own closing iterator — drain it
    # and close explicitly, or the open file handle outlives this test and the
    # `recorded_file` fixture's teardown delete fails on Windows.
    _consume(response)
    response.close()


# --------------------------------------------------------------------------- #
# `_recording_context` — the detail view's context-builder, unit tested
# --------------------------------------------------------------------------- #

def test_recording_context_returns_none_url_for_a_fileless_recording_blob(
    tenant_a, location_a1, make_call_session,
):
    session = make_call_session(tenant_a, location_a1, recording_blob='never-written.wav')

    context = _recording_context(session)

    assert context['recording_url'] is None


def test_recording_context_mints_a_signed_url_when_the_file_exists(
    tenant_a, location_a1, make_call_session, recorded_file,
):
    path = recorded_file()
    session = make_call_session(tenant_a, location_a1, recording_blob=path)

    context = _recording_context(session)

    assert context['recording_url'] is not None
    assert '?sig=' in context['recording_url']
    assert context['can_download'] is True


@pytest.mark.parametrize('retention_days', [None, 0, -5, 'thirty', 3.5])
def test_recording_context_retention_date_is_none_for_missing_zero_negative_or_non_int(
    tenant_a, location_a1, make_call_session, retention_days,
):
    metadata = {} if retention_days is None else {'retention_days': retention_days}
    session = make_call_session(tenant_a, location_a1, metadata=metadata)

    context = _recording_context(session)

    assert context['retention_date'] is None


def test_recording_context_retention_date_is_derived_for_a_positive_int(
    tenant_a, location_a1, make_call_session,
):
    session = make_call_session(tenant_a, location_a1, metadata={'retention_days': 30})

    context = _recording_context(session)

    assert context['retention_date'] == session.created_at + timedelta(days=30)


def test_recording_context_consent_basis_passthrough(tenant_a, location_a1, make_call_session):
    session = make_call_session(tenant_a, location_a1, metadata={'consent_basis': 'two_party'})

    assert _recording_context(session)['consent_basis'] == 'two_party'


def test_recording_context_consent_basis_defaults_to_empty_string(tenant_a, location_a1, make_call_session):
    session = make_call_session(tenant_a, location_a1, metadata={})

    assert _recording_context(session)['consent_basis'] == ''


# --------------------------------------------------------------------------- #
# The rendered player — detail page regression coverage against the `.bins`
# int-not-a-list 500 the partial's own docstring documents fixing
# --------------------------------------------------------------------------- #

def test_detail_page_renders_200_for_a_recorded_session_with_both_waveform_lanes(
    client_a, tenant_a, location_a1, make_call_session, recorded_file,
):
    path = recorded_file()
    session = make_call_session(
        tenant_a, location_a1, recording_blob=path,
        waveform_peaks={'caller': [0.1, 0.5, 0.9], 'bot': [0.2, 0.4], 'bins': 5},
        metadata={'consent_basis': 'announced_notice'},
    )

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200
    content = response.content.decode()
    assert f'peaks-{session.pk}-caller' in content
    assert f'peaks-{session.pk}-bot' in content
    assert '<audio' in content
    assert 'Recorded — consent announced' in content


def test_detail_page_degrades_to_no_longer_available_for_a_fileless_recording(
    client_a, tenant_a, location_a1, make_call_session,
):
    session = make_call_session(tenant_a, location_a1, recording_blob='never-written.wav')

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'This recording is no longer available.' in content
    assert '<audio' not in content


def test_detail_page_no_recording_blob_renders_no_player_card_at_all(
    client_a, tenant_a, location_a1, make_call_session,
):
    """The partial self-gates on `session.recording_blob` — most calls never
    record at all, and the card must not appear for them.
    """
    session = make_call_session(tenant_a, location_a1, recording_blob='')

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200
    assert 'This recording is no longer available.' not in response.content.decode()


def test_detail_page_non_list_waveform_caller_does_not_500(
    client_a, tenant_a, location_a1, make_call_session,
):
    """`waveform_peaks.caller` as a bare int (`.bins`-shaped corruption, not a
    list) must degrade to an empty lane via `ensure_list`, never a 500.
    """
    session = make_call_session(
        tenant_a, location_a1,
        waveform_peaks={'caller': 42, 'bot': [0.1, 0.2], 'bins': 2},
    )

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# Transfer outcome card — self-gates on a non-empty `transfer` dict
# --------------------------------------------------------------------------- #

def test_detail_page_renders_transfer_outcome_card_for_a_connected_transfer(
    client_a, tenant_a, location_a1, make_call_session,
):
    session = make_call_session(tenant_a, location_a1, transfer={
        'result': 'connected', 'destination': '+13125550199', 'duration_seconds': 42,
    })

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200
    content = response.content.decode()
    assert 'Transfer outcome' in content
    assert 'badge-green' in content
    assert 'Connected' in content


def test_detail_page_omits_transfer_outcome_card_when_never_attempted(
    client_a, tenant_a, location_a1, make_call_session,
):
    session = make_call_session(tenant_a, location_a1, transfer={})

    response = client_a.get(_url('callsession_detail', session.pk))

    assert response.status_code == 200
    assert 'Transfer outcome' not in response.content.decode()
