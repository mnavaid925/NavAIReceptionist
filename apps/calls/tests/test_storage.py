"""Storage-layer tests for `apps.calls.storage` (sub-module 5.4 — Recording &
Transfer Outcome).

`recording_storage` is a `PrivateRecordingStorage` rooted at
`settings.PRIVATE_MEDIA_ROOT` — redirected by `config/settings_test.py` to
`temp/test-private-media/`, well outside the real `private_media/` a dev run
would use, the same isolation `MEDIA_ROOT` already gets for ordinary uploads.

Pure filesystem + settings — no `django_db` needed anywhere in this file.
Every test that writes a real file cleans it up in a `finally`, so the suite
leaves the private-media directory exactly as it found it.
"""
import os
import uuid

import pytest
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.base import ContentFile

from apps.calls.storage import (
    open_recording,
    recording_exists,
    recording_size,
    recording_storage,
    save_recording,
)


def _unique_name(suffix='.bin'):
    return f'test/{uuid.uuid4().hex}{suffix}'


# --------------------------------------------------------------------------- #
# recording_exists — never raises, containment-guarded
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('path', ['', None])
def test_recording_exists_false_for_empty_or_none(path):
    assert recording_exists(path) is False


def test_recording_exists_false_for_an_absolute_path():
    """`os.path.join` discards the storage root the moment the second argument
    is absolute — so an absolute path must be caught by the containment check
    rather than silently resolving to itself. Uses this very test file's own
    (real, existing) path, so a bug that skipped the containment check would
    return `True` rather than raise.
    """
    absolute = os.path.abspath(__file__)
    assert recording_exists(absolute) is False


def test_recording_exists_false_for_a_traversal_path():
    assert recording_exists('../../etc/passwd') is False


def test_recording_exists_false_for_a_path_that_was_never_written():
    """A syntactically fine, in-bounds path with nothing behind it — the
    ordinary case for 6 of the 11 seeded rows on a `PROVIDER_MODE=fake`
    database: `recording_blob` is set, but no file was ever produced.
    """
    assert recording_exists(_unique_name('-missing.bin')) is False


def test_recording_exists_true_for_a_real_file():
    path = save_recording(_unique_name(), ContentFile(b'hello'))
    try:
        assert recording_exists(path) is True
    finally:
        recording_storage.delete(path)


# --------------------------------------------------------------------------- #
# PrivateRecordingStorage.url — raises unconditionally
# --------------------------------------------------------------------------- #

def test_private_recording_storage_url_raises_value_error():
    with pytest.raises(ValueError):
        recording_storage.url('anything.wav')


def test_private_recording_storage_url_raises_even_for_a_real_file():
    """The refusal is unconditional — not merely "no `base_url` configured" —
    so even a file that genuinely exists must never get a URL out of this
    storage. Served only through the signed view, never a storage URL.
    """
    path = save_recording(_unique_name(), ContentFile(b'x'))
    try:
        with pytest.raises(ValueError):
            recording_storage.url(path)
    finally:
        recording_storage.delete(path)


# --------------------------------------------------------------------------- #
# open_recording / recording_size — FileNotFoundError, never
# SuspiciousFileOperation, never a 500
# --------------------------------------------------------------------------- #

def test_open_recording_raises_filenotfounderror_for_a_traversal_path():
    with pytest.raises(FileNotFoundError):
        open_recording('../../etc/passwd')


def test_open_recording_raises_filenotfounderror_for_a_missing_file():
    with pytest.raises(FileNotFoundError):
        open_recording(_unique_name('-missing.bin'))


def test_recording_size_raises_filenotfounderror_for_a_traversal_path():
    with pytest.raises(FileNotFoundError):
        recording_size('../../etc/passwd')


def test_recording_size_raises_filenotfounderror_for_a_missing_file():
    with pytest.raises(FileNotFoundError):
        recording_size(_unique_name('-missing.bin'))


def test_recording_size_returns_the_real_byte_count():
    content = b'0123456789'
    path = save_recording(_unique_name(), ContentFile(content))
    try:
        assert recording_size(path) == len(content)
    finally:
        recording_storage.delete(path)


def test_open_recording_returns_the_real_bytes():
    content = b'abcdef-real-bytes'
    path = save_recording(_unique_name(), ContentFile(content))
    try:
        fh = open_recording(path)
        try:
            assert fh.read() == content
        finally:
            fh.close()
    finally:
        recording_storage.delete(path)


# --------------------------------------------------------------------------- #
# save_recording — the write-side mirror of the read-side containment guard
# --------------------------------------------------------------------------- #

def test_save_recording_writes_and_returns_a_path():
    path = save_recording(_unique_name(), ContentFile(b'saved'))
    try:
        assert path
        assert recording_storage.exists(path)
    finally:
        recording_storage.delete(path)


def test_save_recording_traversal_name_raises_suspicious_file_operation():
    with pytest.raises(SuspiciousFileOperation):
        save_recording('../evil-escape.bin', ContentFile(b'x'))


def test_save_recording_absolute_name_raises_suspicious_file_operation():
    absolute = os.path.abspath(__file__)
    with pytest.raises(SuspiciousFileOperation):
        save_recording(absolute, ContentFile(b'x'))
