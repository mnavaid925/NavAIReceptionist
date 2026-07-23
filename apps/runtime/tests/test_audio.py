"""The audio codec + resampling chain — pure DSP, no ORM, no provider.

μ-law ⇄ PCM16 round-trips with energy intact, the inbound `Resampler` threads its
filter state across frames (no click at frame boundaries) and fast-paths a no-op
rate, `iter_mulaw_frames` slices into fixed 20 ms frames with a short final tail,
and `PlaybackTracker` counts only what was actually written to the wire.
"""
import math
import struct

from apps.runtime.providers import audio


def _tone(amplitude=5000, hz=300, rate=8000, n=160):
    step = 2 * math.pi * hz / rate
    return struct.pack(f'<{n}h', *(int(amplitude * math.sin(step * i)) for i in range(n)))


# --------------------------------------------------------------------------- #
# μ-law ⇄ PCM16
# --------------------------------------------------------------------------- #

def test_codec_roundtrip_survives_energy():
    pcm = _tone()
    back = audio.mulaw_to_pcm16(audio.pcm16_to_mulaw(pcm))
    assert len(back) == len(pcm)
    # μ-law is lossy but monotone energy must survive — this is not silence.
    assert audio.frame_energy(back) > 1000


def test_mulaw_to_pcm16_empty_input():
    assert audio.mulaw_to_pcm16(b'') == b''
    assert audio.mulaw_to_pcm16(None) == b''


def test_pcm16_to_mulaw_empty_input():
    assert audio.pcm16_to_mulaw(b'') == b''
    assert audio.pcm16_to_mulaw(None) == b''


def test_encode_decode_are_inverse_on_silence():
    silence = b'\x00\x00' * 160
    mulaw = audio.pcm16_to_mulaw(silence)
    back = audio.mulaw_to_pcm16(mulaw)
    assert audio.frame_energy(back) < 50  # near-zero, not necessarily bit-exact


# --------------------------------------------------------------------------- #
# Resampler — the stateful inbound leg
# --------------------------------------------------------------------------- #

def test_resampler_threads_state_across_frames():
    """Continuity across calls: no exception, and each 20 ms 8k frame upsamples ~2x."""
    r = audio.Resampler(8000, 16000)
    frame = b'\x10\x00' * 160  # 160 samples @ 8kHz = one 20ms carrier frame
    a = r.resample(frame)
    b = r.resample(frame)
    c = r.resample(frame)
    assert len(a) > 0 and len(b) > 0 and len(c) > 0
    # ~2x upsample (16-bit samples, so byte count roughly doubles too).
    assert len(b) == len(c)
    assert 550 < len(a) < 700  # first call absorbs the filter's startup transient


def test_resampler_no_op_fast_path_when_rates_match():
    r = audio.Resampler(8000, 8000)
    frame = b'\x10\x00' * 160
    assert r.resample(frame) == frame  # identity, no audioop call needed


def test_resampler_empty_chunk_returns_empty():
    r = audio.Resampler(8000, 16000)
    assert r.resample(b'') == b''
    assert r.resample(None) == b''


def test_resampler_reset_drops_filter_state():
    r = audio.Resampler(8000, 16000)
    r.resample(b'\x10\x00' * 160)
    assert r._state is not None
    r.reset()
    assert r._state is None


def test_pcm16_to_carrier_mulaw_roundtrip_and_empty():
    pcm = _tone(rate=16000, n=320)
    out = audio.pcm16_to_carrier_mulaw(pcm, in_rate=16000)
    assert out  # downsampled + encoded, non-empty
    assert audio.pcm16_to_carrier_mulaw(b'', in_rate=16000) == b''


# --------------------------------------------------------------------------- #
# Outbound frame pacing
# --------------------------------------------------------------------------- #

def test_iter_mulaw_frames_full_and_short_tail():
    blob = b'x' * 350
    frames = list(audio.iter_mulaw_frames(blob))
    assert [len(f) for f in frames] == [160, 160, 30]  # 160-byte frames, short tail
    assert b''.join(frames) == blob


def test_iter_mulaw_frames_exact_multiple_has_no_short_tail():
    blob = b'y' * 320
    frames = list(audio.iter_mulaw_frames(blob))
    assert [len(f) for f in frames] == [160, 160]


def test_iter_mulaw_frames_empty_yields_nothing():
    assert list(audio.iter_mulaw_frames(b'')) == []
    assert list(audio.iter_mulaw_frames(None)) == []


# --------------------------------------------------------------------------- #
# frame_energy — the VAD's speech/silence signal
# --------------------------------------------------------------------------- #

def test_frame_energy_zero_on_empty_frame():
    assert audio.frame_energy(b'') == 0
    assert audio.frame_energy(None) == 0


def test_frame_energy_positive_on_a_real_tone():
    assert audio.frame_energy(_tone(amplitude=6000)) > 1000


def test_frame_energy_near_zero_on_silence():
    assert audio.frame_energy(b'\x00\x00' * 160) == 0


# --------------------------------------------------------------------------- #
# PlaybackTracker — barge-in-accurate "what actually went out"
# --------------------------------------------------------------------------- #

def test_playback_tracker_accumulates_only_marked_frames():
    tracker = audio.PlaybackTracker()
    assert tracker.bytes_sent == 0 and tracker.frames_sent == 0 and tracker.played_seconds == 0.0

    tracker.mark(b'x' * 160)
    tracker.mark(b'x' * 160)

    assert tracker.bytes_sent == 320
    assert tracker.frames_sent == 2
    # 320 bytes / (8000 Hz * 2 bytes/sample) = 0.02s
    assert tracker.played_seconds == 0.02


def test_playback_tracker_accepts_int_lengths_too():
    tracker = audio.PlaybackTracker()
    tracker.mark(160)  # some callers may pass a byte count rather than the bytes
    assert tracker.bytes_sent == 160
    assert tracker.frames_sent == 1
