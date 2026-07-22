"""Energy VAD, endpointing, barge-in and the echo guard — sub-module 3.2.

All the listening heuristics live here as **named constants in one module**
(``voice-agent-runtime`` skill §5), never as magic numbers scattered through the
consumer. They are expected to move — every commercial platform surveyed exposes
some of these as a tunable "interruption sensitivity" / "patience" control — so
they are named, documented and gathered where a later tuning pass (or a future
per-location setting) can find them. This first set is deliberately conservative;
real tuning needs real call audio, which does not exist until real traffic does.

The state machine is fed one inbound PCM16 frame at a time (16 kHz, ~20 ms) with
a single external fact: **is the agent currently playing audio?** From that it
decides four things (skill §5):

* **Endpointing** — a completed caller utterance is speech for at least
  ``VAD_MIN_SPEECH_MS`` followed by ``VAD_END_SILENCE_MS`` of silence, OR the hard
  ``VAD_MAX_UTTERANCE_MS`` cap firing.
* **Pre-roll** — a bounded ring of pre-speech frames is prepended to the utterance
  so the caller's first syllable is never clipped; it is trimmed while idle so a
  silent line cannot grow it without bound.
* **Barge-in** — while the agent is playing, only *sustained* caller speech past a
  grace window cuts the agent off. A cough, a click or a line pop must not.
* **Echo guard** — inbound audio while the agent plays (and for a short cooldown
  after) is suppressed from utterance capture, so the agent's own voice arriving
  back down the line is never mistaken for the caller and the call never devolves
  into the agent interviewing itself.

Pure heuristics — no ORM, no provider, no network — so the whole thing is testable
against synthetic speech/silence fixtures.
"""
from collections import deque

from apps.runtime.providers.audio import (
    FRAME_MS,
    SAMPLE_WIDTH,
    STT_SAMPLE_RATE,
    frame_energy,
)

__all__ = [
    'VAD_ENERGY_THRESHOLD',
    'VAD_MIN_SPEECH_MS',
    'VAD_END_SILENCE_MS',
    'VAD_MAX_UTTERANCE_MS',
    'VAD_PRE_ROLL_MS',
    'VAD_ECHO_COOLDOWN_MS',
    'VAD_BARGE_IN_GRACE_MS',
    'VAD_BARGE_IN_SUSTAIN_MS',
    'NONE',
    'UTTERANCE_END',
    'BARGE_IN',
    'VadState',
]

# --------------------------------------------------------------------------- #
# Tunable constants (skill §5). Conservative first values — TO BE TUNED against
# real call audio, which is why they are named here rather than inlined.
# --------------------------------------------------------------------------- #

#: RMS energy (16-bit PCM) at or above which a frame counts as speech. Silence on
#: a phone line sits well under this; ordinary speech sits well over it. The
#: single most tuning-sensitive value in the file.
VAD_ENERGY_THRESHOLD = 500
#: Minimum speech before a trailing silence can END an utterance — stops a lone
#: click or a monosyllabic noise from being dispatched as a "turn".
VAD_MIN_SPEECH_MS = 200
#: Trailing silence that marks the end of a caller utterance. Long enough that a
#: mid-sentence breath does not cut the caller off, short enough that the agent
#: does not feel laggy to reply.
VAD_END_SILENCE_MS = 700
#: Hard cap on one utterance — a caller who never pauses still gets a turn, and a
#: stuck-open VAD cannot buffer an entire call into one utterance.
VAD_MAX_UTTERANCE_MS = 15000
#: Pre-speech audio kept so the first syllable is never clipped.
VAD_PRE_ROLL_MS = 300
#: After the agent stops playing, keep suppressing inbound audio this long — the
#: carrier tail of the agent's own voice arrives slightly after playback ends.
VAD_ECHO_COOLDOWN_MS = 250
#: Grace after playback STARTS before any barge-in can fire — the very start of
#: the agent's own audio is the most likely to be misread as caller speech.
VAD_BARGE_IN_GRACE_MS = 400
#: Sustained caller speech (past the grace window) required to actually cut the
#: agent off. This is what separates a real interruption from a cough.
VAD_BARGE_IN_SUSTAIN_MS = 300

# Events ``feed()`` can return. UTTERANCE_START is intentionally not surfaced —
# the consumer acts on a *completed* utterance and on barge-in, nothing else.
NONE = 'none'
UTTERANCE_END = 'utterance_end'
BARGE_IN = 'barge_in'


def _frame_ms(frame_bytes, rate):
    """Duration of one PCM16 frame in ms, from its byte length and the rate."""
    samples = len(frame_bytes) // SAMPLE_WIDTH
    if rate <= 0 or samples <= 0:
        return FRAME_MS
    return int(round(samples * 1000 / rate))


class VadState:
    """Per-call listening state machine. One instance lives on the consumer.

    ``feed(frame, is_playing)`` is called for every inbound PCM16 frame and
    returns ``(event, utterance_pcm_or_None)``:

    * ``(UTTERANCE_END, pcm)`` — a complete caller utterance (pre-roll included);
    * ``(BARGE_IN, pcm)`` — sustained caller speech interrupted the agent; ``pcm``
      is the speech captured during the sustain window, which seeds the utterance
      now in progress;
    * ``(NONE, None)`` — nothing to act on this frame.

    The state machine never raises on a malformed frame — a zero-length or odd
    payload simply reads as very low energy.
    """

    def __init__(self, rate=STT_SAMPLE_RATE):
        self.rate = rate
        pre_roll_frames = max(1, VAD_PRE_ROLL_MS // FRAME_MS)
        self._pre_roll = deque(maxlen=pre_roll_frames)

        # Utterance-in-progress accumulators.
        self._utterance = []
        self._speech_ms = 0
        self._silence_ms = 0
        self._utterance_ms = 0
        self._in_speech = False

        # Barge-in / echo-guard timers, all driven off the is_playing transitions.
        self._playing_prev = False
        self._playing_ms = 0            # how long the current playback has run
        self._barge_sustain_ms = 0      # consecutive sustained speech while playing
        self._cooldown_ms = 0           # echo cooldown remaining after playback

    # -- public ------------------------------------------------------------- #

    def feed(self, frame, is_playing):
        """Process one inbound PCM16 frame. See the class docstring for returns."""
        dur = _frame_ms(frame, self.rate)
        is_speech = frame_energy(frame) >= VAD_ENERGY_THRESHOLD

        # Track playback edges so the grace/cooldown windows need no external clock.
        if is_playing and not self._playing_prev:
            self._playing_ms = 0
        if is_playing:
            self._playing_ms += dur
        if self._playing_prev and not is_playing:
            # Playback just ended — open the echo cooldown window.
            self._cooldown_ms = VAD_ECHO_COOLDOWN_MS
        self._playing_prev = is_playing

        if is_playing:
            return self._feed_while_playing(frame, dur, is_speech)
        return self._feed_while_listening(frame, dur, is_speech)

    def reset_listening(self):
        """Drop any in-progress utterance and pre-roll.

        Called when playback STARTS so the agent's own audio is never accumulated
        as a caller utterance (skill §5), and after an utterance is dispatched.
        """
        self._pre_roll.clear()
        self._utterance = []
        self._speech_ms = 0
        self._silence_ms = 0
        self._utterance_ms = 0
        self._in_speech = False

    # -- internals ---------------------------------------------------------- #

    def _feed_while_playing(self, frame, dur, is_speech):
        """Echo guard + barge-in detection while the agent is speaking.

        Inbound audio here is presumed to be echo of the agent's own voice and is
        NOT accumulated as an utterance — unless sustained speech past the grace
        window trips barge-in, at which point the sustained frames become the seed
        of the caller's new utterance.
        """
        if self._playing_ms < VAD_BARGE_IN_GRACE_MS:
            # Too early — the agent just started; ignore everything (grace window).
            self._barge_sustain_ms = 0
            return NONE, None

        if not is_speech:
            self._barge_sustain_ms = 0
            return NONE, None

        # Sustained speech past the grace window: accumulate toward a barge-in.
        self._barge_sustain_ms += dur
        if self._barge_sustain_ms >= VAD_BARGE_IN_SUSTAIN_MS:
            # Fire. Seed a fresh utterance with the sustained-speech frame so the
            # caller's interrupting words are not lost. Listening resumes cleanly.
            self.reset_listening()
            self._begin_speech(frame, dur)
            self._barge_sustain_ms = 0
            self._cooldown_ms = 0  # a real interruption skips the echo cooldown
            return BARGE_IN, None
        return NONE, None

    def _feed_while_listening(self, frame, dur, is_speech):
        """Endpointing + pre-roll while the agent is silent."""
        # Bleed off the echo cooldown; suppress capture until it drains.
        if self._cooldown_ms > 0:
            self._cooldown_ms = max(0, self._cooldown_ms - dur)
            if not self._in_speech:
                return NONE, None

        if is_speech:
            if not self._in_speech:
                self._begin_speech(frame, dur)
            else:
                self._utterance.append(frame)
                self._speech_ms += dur
                self._silence_ms = 0
                self._utterance_ms += dur
        else:
            if self._in_speech:
                # Trailing silence is kept as part of the utterance until the end
                # window closes — it is the pause the caller made, not noise.
                self._utterance.append(frame)
                self._silence_ms += dur
                self._utterance_ms += dur
            else:
                # Idle: keep a bounded pre-roll so the next first syllable is not
                # clipped, and trim it (deque maxlen) so silence cannot grow it.
                self._pre_roll.append(frame)
                return NONE, None

        # End conditions: enough speech then enough silence, or the hard cap.
        ended = (
            self._in_speech
            and self._speech_ms >= VAD_MIN_SPEECH_MS
            and self._silence_ms >= VAD_END_SILENCE_MS
        )
        capped = self._in_speech and self._utterance_ms >= VAD_MAX_UTTERANCE_MS
        if ended or capped:
            pcm = b''.join(self._utterance)
            self.reset_listening()
            return UTTERANCE_END, pcm
        return NONE, None

    def _begin_speech(self, frame, dur):
        """Start a new utterance, prepending the buffered pre-roll frames."""
        self._utterance = list(self._pre_roll) + [frame]
        self._pre_roll.clear()
        self._speech_ms = dur
        self._silence_ms = 0
        self._utterance_ms = dur
        self._in_speech = True
