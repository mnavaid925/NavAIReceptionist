"""`manage.py purge_expired_recordings` — the retention sweep (3.5).

Follows `apps/calls/tests/test_seed_calls.py`'s `call_command` convention and
`apps/calls/tests/test_storage.py`'s real-file discipline: every recording this
file writes is deleted in a `finally`, whether or not the command under test
already cleared it, because `FileSystemStorage.delete` on a missing file is
itself a documented no-op — so the cleanup is always safe to run.
"""
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.calls.models import CallSession
from apps.calls.storage import recording_exists, recording_storage
from apps.runtime.providers.recording import FakeRecordingBackend

pytestmark = pytest.mark.django_db


def _record(make_call_session, tenant, location, *, started_at, retention_days=30):
    """A COMPLETED CallSession with a real recorded WAV and the given retention.

    `retention_days=None` omits the key from `metadata` entirely (the "no
    retention_days at all" shape); any other value (including 0 or a
    non-numeric string) is written as given, to drive the malformed-input
    tests below.
    """
    session = make_call_session(
        tenant, location,
        status=CallSession.STATUS_COMPLETED,
        started_at=started_at,
    )
    backend = FakeRecordingBackend()
    path = backend.finalize(session, should_record=True)
    metadata = {'recorded': True, 'consent_basis': 'one_party_notice'}
    if retention_days is not None:
        metadata['retention_days'] = retention_days
    session.recording_blob = path
    session.metadata = metadata
    session.save(update_fields=['recording_blob', 'metadata'])
    return session, path


def _run(**options):
    out, err = StringIO(), StringIO()
    call_command('purge_expired_recordings', stdout=out, stderr=err, **options)
    return out.getvalue(), err.getvalue()


# --------------------------------------------------------------------------- #
# A row past its retention window: file deleted, blob cleared, purged_at stamped
# --------------------------------------------------------------------------- #

def test_purge_deletes_file_clears_blob_and_stamps_purged_at(
    tenant_a, location_a1, make_call_session,
):
    now = timezone.now()
    session, path = _record(
        make_call_session, tenant_a, location_a1,
        started_at=now - timedelta(days=40), retention_days=30)
    try:
        assert recording_exists(path) is True

        out, _err = _run()

        session.refresh_from_db()
        assert session.recording_blob == ''
        assert recording_exists(path) is False
        assert session.metadata['recording_purged_at']  # stamped, non-empty
        # A real ISO-8601 timestamp, not a placeholder.
        from datetime import datetime
        datetime.fromisoformat(session.metadata['recording_purged_at'])
        # Retention metadata otherwise survives — only the blob and the new
        # purge stamp change.
        assert session.metadata['retention_days'] == 30
        assert 'purged' in out.lower()
    finally:
        recording_storage.delete(path)


# --------------------------------------------------------------------------- #
# A row still inside its window is untouched
# --------------------------------------------------------------------------- #

def test_purge_leaves_a_row_still_within_retention_untouched(
    tenant_a, location_a1, make_call_session,
):
    now = timezone.now()
    session, path = _record(
        make_call_session, tenant_a, location_a1,
        started_at=now - timedelta(days=5), retention_days=30)
    try:
        _run()

        session.refresh_from_db()
        assert session.recording_blob == path
        assert recording_exists(path) is True
        assert 'recording_purged_at' not in session.metadata
    finally:
        recording_storage.delete(path)


# --------------------------------------------------------------------------- #
# --dry-run writes nothing
# --------------------------------------------------------------------------- #

def test_dry_run_writes_nothing(tenant_a, location_a1, make_call_session):
    now = timezone.now()
    session, path = _record(
        make_call_session, tenant_a, location_a1,
        started_at=now - timedelta(days=40), retention_days=30)
    try:
        out, _err = _run(dry_run=True)

        session.refresh_from_db()
        assert session.recording_blob == path
        assert recording_exists(path) is True
        assert 'recording_purged_at' not in session.metadata
        assert 'would' in out.lower()
    finally:
        recording_storage.delete(path)


# --------------------------------------------------------------------------- #
# A re-run after a real purge is idempotent — a no-op
# --------------------------------------------------------------------------- #

def test_rerun_after_a_real_purge_is_a_no_op(tenant_a, location_a1, make_call_session):
    now = timezone.now()
    session, path = _record(
        make_call_session, tenant_a, location_a1,
        started_at=now - timedelta(days=40), retention_days=30)
    try:
        first_out, _err = _run()
        session.refresh_from_db()
        assert session.recording_blob == ''
        first_purged_at = session.metadata['recording_purged_at']
        assert 'purged' in first_out.lower()

        second_out, _err = _run()  # the cleared blob excludes this row now
        session.refresh_from_db()
        assert session.recording_blob == ''
        # Never re-stamped, never touched twice.
        assert session.metadata['recording_purged_at'] == first_purged_at
        # The purged row is fully excluded by `.exclude(recording_blob='')` now —
        # nothing left to purge OR to count as still-within-retention.
        assert '0 purged' in second_out.lower()
        assert '0 still within retention' in second_out.lower()
    finally:
        recording_storage.delete(path)


# --------------------------------------------------------------------------- #
# --tenant / --location scoping never touches another tenant's or location's row
# --------------------------------------------------------------------------- #

def test_tenant_scoping_never_touches_another_tenants_rows(
    tenant_a, location_a1, tenant_b, location_b1, make_call_session,
):
    now = timezone.now()
    session_a, path_a = _record(
        make_call_session, tenant_a, location_a1,
        started_at=now - timedelta(days=40), retention_days=30)
    session_b, path_b = _record(
        make_call_session, tenant_b, location_b1,
        started_at=now - timedelta(days=40), retention_days=30)
    try:
        _run(tenant=tenant_a.slug)

        session_a.refresh_from_db()
        session_b.refresh_from_db()
        assert session_a.recording_blob == ''
        assert session_b.recording_blob == path_b  # a different tenant — untouched
        assert recording_exists(path_b) is True
    finally:
        recording_storage.delete(path_a)
        recording_storage.delete(path_b)


def test_tenant_scoping_accepts_customer_id_too(
    tenant_a, location_a1, tenant_b, location_b1, make_call_session,
):
    now = timezone.now()
    session_a, path_a = _record(
        make_call_session, tenant_a, location_a1,
        started_at=now - timedelta(days=40), retention_days=30)
    try:
        _run(tenant=tenant_a.customer_id)

        session_a.refresh_from_db()
        assert session_a.recording_blob == ''
    finally:
        recording_storage.delete(path_a)


def test_location_scoping_never_touches_another_locations_rows(
    tenant_a, location_a1, location_a2, make_call_session,
):
    """Same TENANT, different LOCATION — the cross-location isolation case."""
    now = timezone.now()
    session_1, path_1 = _record(
        make_call_session, tenant_a, location_a1,
        started_at=now - timedelta(days=40), retention_days=30)
    session_2, path_2 = _record(
        make_call_session, tenant_a, location_a2,
        started_at=now - timedelta(days=40), retention_days=30)
    try:
        _run(location=location_a1.slug)

        session_1.refresh_from_db()
        session_2.refresh_from_db()
        assert session_1.recording_blob == ''
        assert session_2.recording_blob == path_2  # a different location — untouched
        assert recording_exists(path_2) is True
    finally:
        recording_storage.delete(path_1)
        recording_storage.delete(path_2)


# --------------------------------------------------------------------------- #
# retention_days of 0, malformed, or absent is never purged
# --------------------------------------------------------------------------- #

def test_retention_days_zero_is_never_purged(tenant_a, location_a1, make_call_session):
    now = timezone.now()
    session, path = _record(
        make_call_session, tenant_a, location_a1,
        started_at=now - timedelta(days=400), retention_days=0)
    try:
        _run()
        session.refresh_from_db()
        assert session.recording_blob == path
        assert recording_exists(path) is True
    finally:
        recording_storage.delete(path)


def test_malformed_retention_days_is_never_purged(tenant_a, location_a1, make_call_session):
    now = timezone.now()
    session, path = _record(
        make_call_session, tenant_a, location_a1,
        started_at=now - timedelta(days=400), retention_days='not-a-number')
    try:
        _run()
        session.refresh_from_db()
        assert session.recording_blob == path
        assert recording_exists(path) is True
    finally:
        recording_storage.delete(path)


def test_missing_retention_days_key_is_never_purged(tenant_a, location_a1, make_call_session):
    now = timezone.now()
    session, path = _record(
        make_call_session, tenant_a, location_a1,
        started_at=now - timedelta(days=400), retention_days=None)
    try:
        assert 'retention_days' not in session.metadata
        _run()
        session.refresh_from_db()
        assert session.recording_blob == path
        assert recording_exists(path) is True
    finally:
        recording_storage.delete(path)


def test_negative_retention_days_is_never_purged(tenant_a, location_a1, make_call_session):
    now = timezone.now()
    session, path = _record(
        make_call_session, tenant_a, location_a1,
        started_at=now - timedelta(days=400), retention_days=-5)
    try:
        _run()
        session.refresh_from_db()
        assert session.recording_blob == path
        assert recording_exists(path) is True
    finally:
        recording_storage.delete(path)


# --------------------------------------------------------------------------- #
# A row with no recording_blob at all is not even in the driving queryset
# --------------------------------------------------------------------------- #

def test_a_row_with_no_recording_is_skipped_entirely(
    tenant_a, location_a1, make_call_session,
):
    session = make_call_session(
        tenant_a, location_a1, status=CallSession.STATUS_COMPLETED,
        started_at=timezone.now() - timedelta(days=400))
    assert session.recording_blob == ''

    out, _err = _run()

    session.refresh_from_db()
    assert session.recording_blob == ''
    assert 'recording_purged_at' not in (session.metadata or {})
