"""The signed stream token — mint/verify round-trip, tamper and expiry.

The token is the media stream's only credential (the stream has no session and no
user), so it must round-trip its payload and fail closed on anything off.
"""
from apps.runtime.providers.tokens import mint_stream_token, verify_stream_token


def test_mint_verify_roundtrip():
    token = mint_stream_token(session_id=42, tenant_id=7, location_id=3)
    assert verify_stream_token(token) == {'sid': 42, 'ten': 7, 'loc': 3}


def test_tampered_token_rejected():
    token = mint_stream_token(1, 1, 1)
    assert verify_stream_token(token + 'x') is None


def test_expired_token_rejected():
    token = mint_stream_token(1, 1, 1)
    # A negative max_age makes any token older than "in the future" expired.
    assert verify_stream_token(token, max_age=-1) is None


def test_non_string_input_rejected():
    assert verify_stream_token(None) is None
    assert verify_stream_token(12345) is None
    assert verify_stream_token('') is None
