"""The audio codec + resampling chain — sub-module 3.2.

The one place μ-law ⇄ PCM conversion and sample-rate change live. Consumers and
the turn loop call these helpers; **nothing inlines codec math in a consumer**
(``voice-agent-runtime`` skill §4). Pure DSP — no ORM, no provider, no network —
so it is trivially testable and safe to import anywhere.

Two legs, two directions (skill §4):

* **Carrier → us**: Twilio sends base64 μ-law (G.711) **8 kHz** mono in 20 ms
  frames (160 bytes). We decode to PCM16 8 kHz, then resample up to **16 kHz**
  for the VAD and STT.
* **Us → carrier**: a synthesized reply is PCM16 at the synth rate (24 kHz for a
  native-audio model, 16 kHz otherwise). We resample down to 8 kHz, μ-law encode,
  and slice into 20 ms frames paced one at a time onto the wire.

**The one non-obvious rule: thread the INBOUND resampler state across frames.**
``audioop.ratecv`` carries a filter state between calls; a fresh state per 20 ms
frame produces an audible click at every frame boundary. So one ``Resampler``
instance lives on the call for the whole inbound leg and is mutated frame to
frame. Outbound is the opposite — each synthesized blob is independent, so it
gets a fresh ``Resampler`` every time.

Implemented on the standard library's ``audioop`` (present on the 3.10 dev host;
no numpy dependency to add). ``audioop`` is mono-only here, which is exactly the
carrier's format.
"""
import audioop

__all__ = [
    'CARRIER_SAMPLE_RATE',
    'STT_SAMPLE_RATE',
    'SAMPLE_WIDTH',
    'CHANNELS',
    'FRAME_MS',
    'FRAME_SECONDS',
    'CARRIER_FRAME_BYTES',
    'mulaw_to_pcm16',
    'pcm16_to_mulaw',
    'Resampler',
    'pcm16_to_carrier_mulaw',
    'iter_mulaw_frames',
    'frame_energy',
    'PlaybackTracker',
]

#: The carrier (Twilio) leg is always 8 kHz μ-law mono, 20 ms/160-byte frames.
CARRIER_SAMPLE_RATE = 8000
#: Everything above the carrier — VAD and STT — runs at 16 kHz PCM16.
STT_SAMPLE_RATE = 16000
#: 16-bit linear PCM everywhere off the carrier leg (``audioop`` width=2).
SAMPLE_WIDTH = 2
#: Mono end to end — the carrier is mono and there is no stereo anywhere.
CHANNELS = 1
#: The frame quantum the carrier expects, in milliseconds and seconds.
FRAME_MS = 20
FRAME_SECONDS = FRAME_MS / 1000.0
#: One 20 ms μ-law frame on the 8 kHz carrier = 160 bytes (8000 * 0.02 * 1).
CARRIER_FRAME_BYTES = int(CARRIER_SAMPLE_RATE * FRAME_SECONDS)


def mulaw_to_pcm16(mulaw_bytes):
    """Decode carrier μ-law (G.711) to signed 16-bit linear PCM at the same rate.

    Rate is unchanged — this only widens each 8-bit μ-law sample to a 16-bit
    linear one. Resampling to 16 kHz is a separate step (see ``Resampler``).
    """
    if not mulaw_bytes:
        return b''
    return audioop.ulaw2lin(mulaw_bytes, SAMPLE_WIDTH)


def pcm16_to_mulaw(pcm16_bytes):
    """Encode signed 16-bit linear PCM to carrier μ-law at the same rate.

    The inverse of :func:`mulaw_to_pcm16`. The caller resamples to 8 kHz first —
    μ-law encoding does not change the rate, only the per-sample encoding.
    """
    if not pcm16_bytes:
        return b''
    return audioop.lin2ulaw(pcm16_bytes, SAMPLE_WIDTH)


class Resampler:
    """A stateful linear resampler wrapping ``audioop.ratecv``.

    The filter state tuple is threaded across ``resample()`` calls, which is the
    whole point: on the inbound leg one instance processes every 20 ms frame in
    order, so the interpolation is continuous across frame boundaries and no click
    is introduced. Give each *independent* audio blob (every outbound synthesis)
    its own instance — sharing state across unrelated blobs is the same bug in
    reverse.

    Mono, 16-bit. A no-op fast path when ``in_rate == out_rate`` keeps the common
    "already at the right rate" case from paying for a resample.
    """

    def __init__(self, in_rate, out_rate, width=SAMPLE_WIDTH, channels=CHANNELS):
        self.in_rate = in_rate
        self.out_rate = out_rate
        self.width = width
        self.channels = channels
        #: ``audioop.ratecv`` seeds its own state when passed ``None``; each call
        #: returns the next state, which we keep so the following frame continues
        #: the same filter rather than restarting it.
        self._state = None

    def resample(self, pcm16_bytes):
        """Resample one chunk, carrying filter state into the next call."""
        if not pcm16_bytes:
            return b''
        if self.in_rate == self.out_rate:
            return pcm16_bytes
        converted, self._state = audioop.ratecv(
            pcm16_bytes, self.width, self.channels,
            self.in_rate, self.out_rate, self._state,
        )
        return converted

    def reset(self):
        """Drop the filter state — the next ``resample()`` starts a fresh stream."""
        self._state = None


def pcm16_to_carrier_mulaw(pcm16_bytes, in_rate):
    """Full outbound conversion: PCM16 at ``in_rate`` → 8 kHz μ-law for the carrier.

    A convenience for the outbound path, which is stateless per synthesis: a fresh
    ``Resampler`` down to 8 kHz, then μ-law encode. Never reuse a resampler across
    two synthesized blobs — that is exactly the shared-state bug ``Resampler``'s
    docstring warns about, so this builds a new one every call.
    """
    if not pcm16_bytes:
        return b''
    down = Resampler(in_rate, CARRIER_SAMPLE_RATE).resample(pcm16_bytes)
    return pcm16_to_mulaw(down)


def iter_mulaw_frames(mulaw_bytes, frame_bytes=CARRIER_FRAME_BYTES):
    """Yield ``mulaw_bytes`` in fixed 20 ms frames (the last one may be short).

    The consumer paces these onto the wire one at a time with a 20 ms sleep
    between them (skill §4): dumping the whole blob at once fills the carrier's
    jitter buffer and makes the audio uncancellable, which breaks barge-in. A
    short final frame is sent as-is; Twilio accepts a sub-20 ms tail.
    """
    if not mulaw_bytes or frame_bytes <= 0:
        return
    for start in range(0, len(mulaw_bytes), frame_bytes):
        yield mulaw_bytes[start:start + frame_bytes]


def frame_energy(pcm16_bytes):
    """RMS energy of one PCM16 frame — the VAD's speech/silence signal.

    Returns 0 for an empty frame rather than raising, so a zero-length media
    payload cannot crash the frame loop.
    """
    if not pcm16_bytes:
        return 0
    return audioop.rms(pcm16_bytes, SAMPLE_WIDTH)


class PlaybackTracker:
    """Counts the outbound audio *actually sent*, for barge-in-accurate playback.

    Barge-in cancels the outbound task mid-blob, so the agent channel of a
    recording must reflect only the frames that really went out, not the whole
    synthesized reply (skill §4). 3.2 only *tracks* this — the trimmed audio is
    persisted into ``CallSession.recording_blob`` by 3.5. Kept here so the number
    is correct from the first frame this sub-module ever sends.
    """

    def __init__(self, sample_rate=CARRIER_SAMPLE_RATE, width=SAMPLE_WIDTH):
        self.sample_rate = sample_rate
        self.width = width
        self.bytes_sent = 0
        self.frames_sent = 0

    def mark(self, frame_bytes):
        """Record that a frame of ``frame_bytes`` bytes was written to the wire."""
        self.bytes_sent += len(frame_bytes) if isinstance(frame_bytes, (bytes, bytearray)) else int(frame_bytes)
        self.frames_sent += 1

    @property
    def played_seconds(self):
        """Seconds of audio actually sent — bytes / (rate * width)."""
        denom = self.sample_rate * self.width
        return self.bytes_sent / denom if denom else 0.0
