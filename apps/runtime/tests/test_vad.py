"""Energy VAD, endpointing, pre-roll, barge-in and the echo guard.

Pure heuristics — no ORM, no provider, no network — fed synthetic 16 kHz PCM16
speech/silence fixtures. `VadState.feed()` returns `(event, utterance_pcm)`; these
tests drive it exactly as the consumer does, one 20 ms frame at a time.
"""
import math
import struct

from apps.runtime.providers import vad
from apps.runtime.providers.audio import FRAME_MS

_RATE = 16000
_SAMPLES = 320  # 20ms @ 16kHz


def _tone(amplitude=6000, hz=200):
    step = 2 * math.pi * hz / _RATE
    return struct.pack(f'<{_SAMPLES}h', *(int(amplitude * math.sin(step * n)) for n in range(_SAMPLES)))


_TONE = _tone()
_SILENCE = b'\x00\x00' * _SAMPLES


# --------------------------------------------------------------------------- #
# Endpointing + pre-roll
# --------------------------------------------------------------------------- #

def test_one_utterance_from_speech_then_silence():
    v = vad.VadState()
    events = [v.feed(_TONE, is_playing=False) for _ in range(15)]
    events += [v.feed(_SILENCE, is_playing=False) for _ in range(45)]
    ends = [pcm for ev, pcm in events if ev == vad.UTTERANCE_END]
    assert len(ends) == 1 and len(ends[0]) > 0


def test_pre_roll_is_prepended_and_trimmed_to_its_bound():
    """Idle audio before speech starts rides along, capped at VAD_PRE_ROLL_MS."""
    pre_roll_cap_frames = vad.VAD_PRE_ROLL_MS // FRAME_MS  # 15 @ 20ms frames

    v = vad.VadState()
    # Feed MORE idle frames than the pre-roll can hold, so it saturates/trims.
    idle_frames_fed = pre_roll_cap_frames + 5
    for _ in range(idle_frames_fed):
        v.feed(_SILENCE, is_playing=False)

    speech_frames = 15
    for _ in range(speech_frames):
        v.feed(_TONE, is_playing=False)

    end_silence_frames_needed = vad.VAD_END_SILENCE_MS // FRAME_MS
    pcm = None
    for _ in range(end_silence_frames_needed + 5):
        event, out = v.feed(_SILENCE, is_playing=False)
        if event == vad.UTTERANCE_END:
            pcm = out
            break

    assert pcm is not None
    frame_bytes = len(_TONE)
    total_frames = len(pcm) // frame_bytes
    # Pre-roll capped at its own bound (not the larger idle_frames_fed), plus the
    # speech, plus exactly the trailing silence needed to close the window.
    expected = pre_roll_cap_frames + speech_frames + end_silence_frames_needed
    assert total_frames == expected


def test_idle_silence_never_produces_a_phantom_utterance():
    v = vad.VadState()
    for _ in range(100):
        event, pcm = v.feed(_SILENCE, is_playing=False)
        assert event == vad.NONE
        assert pcm is None


def test_hard_utterance_cap_fires_without_any_silence():
    """A caller who never pauses still gets endpointed at VAD_MAX_UTTERANCE_MS."""
    v = vad.VadState()
    frames_to_cap = vad.VAD_MAX_UTTERANCE_MS // FRAME_MS
    ended_at = None
    pcm = None
    for i in range(frames_to_cap + 10):
        event, out = v.feed(_TONE, is_playing=False)
        if event == vad.UTTERANCE_END:
            ended_at = i
            pcm = out
            break
    assert ended_at == frames_to_cap - 1  # fires the instant the cap is reached
    assert len(pcm) // len(_TONE) == frames_to_cap


# --------------------------------------------------------------------------- #
# Barge-in — sustained speech only, with a grace window and a retained seed
# --------------------------------------------------------------------------- #

def test_barge_in_retains_the_whole_sustain_window():
    """Barge-in seeds the new utterance with EVERY sustained frame, not just the
    one that tripped the threshold."""
    v = vad.VadState()
    grace_frames = vad.VAD_BARGE_IN_GRACE_MS // FRAME_MS
    for _ in range(grace_frames + 5):  # clear the grace window while "playing"
        v.feed(_SILENCE, is_playing=True)

    barged = False
    sustain_frames_needed = vad.VAD_BARGE_IN_SUSTAIN_MS // FRAME_MS
    for _ in range(sustain_frames_needed + 10):
        event, _ = v.feed(_TONE, is_playing=True)
        if event == vad.BARGE_IN:
            barged = True
            # The whole sustain window is retained as the seed, not one frame.
            assert len(v._utterance) >= sustain_frames_needed
            break
    assert barged


def test_barge_in_seed_arrives_with_the_next_utterance_end():
    """The interrupting words are not dropped — they surface on the next
    UTTERANCE_END once the caller finishes speaking (post-barge-in, playing stops)."""
    v = vad.VadState()
    for _ in range(vad.VAD_BARGE_IN_GRACE_MS // FRAME_MS + 5):
        v.feed(_SILENCE, is_playing=True)

    sustain_frames_needed = vad.VAD_BARGE_IN_SUSTAIN_MS // FRAME_MS
    for _ in range(sustain_frames_needed + 5):
        event, _ = v.feed(_TONE, is_playing=True)
        if event == vad.BARGE_IN:
            break

    # Playback has now stopped (the consumer cancels it on barge-in); the caller
    # keeps talking, then pauses to close out the endpointed turn.
    for _ in range(10):
        v.feed(_TONE, is_playing=False)
    end_silence_frames_needed = vad.VAD_END_SILENCE_MS // FRAME_MS
    pcm = None
    for _ in range(end_silence_frames_needed + 5):
        event, out = v.feed(_SILENCE, is_playing=False)
        if event == vad.UTTERANCE_END:
            pcm = out
            break
    assert pcm is not None and len(pcm) > 0


def test_grace_window_blocks_barge_in_even_with_sustained_speech():
    """Speech arriving in the first VAD_BARGE_IN_GRACE_MS of playback never barges."""
    v = vad.VadState()
    grace_frames = vad.VAD_BARGE_IN_GRACE_MS // FRAME_MS
    barged = False
    for _ in range(grace_frames):
        event, _ = v.feed(_TONE, is_playing=True)
        if event == vad.BARGE_IN:
            barged = True
    assert not barged


def test_brief_cough_during_playback_does_not_barge():
    """A short burst of energy, well under the sustain window, must not interrupt."""
    v = vad.VadState()
    for _ in range(vad.VAD_BARGE_IN_GRACE_MS // FRAME_MS + 5):
        v.feed(_SILENCE, is_playing=True)  # clear the grace window

    sustain_frames_needed = vad.VAD_BARGE_IN_SUSTAIN_MS // FRAME_MS
    cough_frames = max(1, sustain_frames_needed // 3)  # well short of sustained
    barged = False
    for _ in range(cough_frames):
        event, _ = v.feed(_TONE, is_playing=True)
        if event == vad.BARGE_IN:
            barged = True
    for _ in range(10):
        event, _ = v.feed(_SILENCE, is_playing=True)  # the cough ends
        if event == vad.BARGE_IN:
            barged = True
    assert not barged


def test_echo_guard_suppresses_inbound_speech_while_playing():
    """Inbound audio while playing is echo unless it sustains into a barge-in —
    it must never surface as an UTTERANCE_END while play is still in progress."""
    v = vad.VadState()
    for _ in range(5):
        event, pcm = v.feed(_TONE, is_playing=True)
        assert event != vad.UTTERANCE_END


def test_echo_cooldown_suppresses_capture_right_after_playback_ends():
    """The carrier tail of the agent's own voice lands slightly after playback
    stops — the cooldown window keeps that tail from becoming a caller utterance."""
    v = vad.VadState()
    v.feed(_SILENCE, is_playing=True)  # a play cycle...
    event, _ = v.feed(_TONE, is_playing=False)  # ...ends, echo tail arrives
    assert event == vad.NONE  # suppressed by the cooldown, not captured as speech
