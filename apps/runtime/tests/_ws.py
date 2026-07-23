"""Shared websocket helpers for the media-stream consumer suite.

Not a test module itself — `pytest.ini`'s `python_files = test_*.py tests.py`
never collects this name — it just factors out the WebsocketCommunicator
plumbing that `temp/verify_3_2.py` proved out, so `test_media_consumer.py` and
`test_simulate_call.py` do not each reinvent it.

Two gotchas baked in here so no test has to rediscover them: the communicator
needs an explicit `Origin` header or `AllowedHostsOriginValidator` refuses the
socket outright, and the stream's only credential (the signed token + session
id) travels on the Twilio `start` frame's `customParameters`, never at connect.
"""
import asyncio
import base64
import math
import struct

from channels.db import database_sync_to_async

from apps.runtime.providers import audio

#: AllowedHostsOriginValidator rejects a websocket with no matching Origin —
#: `ALLOWED_HOSTS` in `settings_test` includes `testserver`/`127.0.0.1`/`localhost`.
HEADERS = [(b'origin', b'http://localhost')]


def speech_payload():
    """One 20 ms 8 kHz μ-law frame of a tone loud enough to read as speech."""
    step = 2 * math.pi * 200 / audio.CARRIER_SAMPLE_RATE
    pcm = struct.pack('<160h', *(int(8000 * math.sin(step * n)) for n in range(160)))
    return base64.b64encode(audio.pcm16_to_mulaw(pcm)).decode('ascii')


def silence_payload():
    """One 20 ms 8 kHz μ-law frame of silence."""
    pcm = b'\x00\x00' * 160
    return base64.b64encode(audio.pcm16_to_mulaw(pcm)).decode('ascii')


async def open_socket():
    """A bare, connected-but-unauthorized socket — the caller sends its own `start`."""
    from channels.testing import WebsocketCommunicator
    from config.asgi import application
    comm = WebsocketCommunicator(application, '/ws/media-stream/', headers=HEADERS)
    ok, _ = await comm.connect()
    assert ok
    return comm


async def connect(token, session_id, stream_sid='MZ1'):
    """Open a socket and authorize it with a valid token + matching sessionId."""
    comm = await open_socket()
    await comm.send_json_to({'event': 'connected'})
    await comm.send_json_to({'event': 'start', 'streamSid': stream_sid, 'start': {
        'streamSid': stream_sid, 'callSid': 'CA1',
        'customParameters': {'streamToken': token, 'sessionId': str(session_id)}}})
    return comm


async def drain(comm, quiet=0.5, cap=2000):
    """Read outbound frames until the wire goes quiet for `quiet` seconds."""
    n = 0
    while n < cap:
        if await comm.receive_nothing(timeout=quiet):
            return n
        await comm.receive_from()
        n += 1
    return n


async def speak_utterance(comm, speech_frames=15, silence_frames=45):
    """Send one synthetic caller utterance: speech then silence to endpoint it."""
    for _ in range(speech_frames):
        await comm.send_json_to({'event': 'media', 'media': {'payload': speech_payload()}})
    for _ in range(silence_frames):
        await comm.send_json_to({'event': 'media', 'media': {'payload': silence_payload()}})


async def amake(fn, *a, **k):
    """Run a sync ORM-touching factory off the event loop."""
    return await database_sync_to_async(fn)(*a, **k)


async def arefresh(obj):
    """Reload `obj` from the DB off the event loop."""
    return await database_sync_to_async(lambda: type(obj).objects.get(pk=obj.pk))()


async def wait_for(predicate, tries=30, delay=0.1):
    """Poll an async `predicate` until it is truthy, bounded by `tries * delay`.

    A turn runs as a background task, so a test that asserts "the caller was
    transcribed" must wait for that task rather than race it — under heavy load
    (a full-repo run) the turn can take longer than a fixed drain window. Returns
    True as soon as the predicate holds, or False after the bound (breaks early on
    success, so the common case pays almost nothing).
    """
    for _ in range(tries):
        if await predicate():
            return True
        await asyncio.sleep(delay)
    return False
