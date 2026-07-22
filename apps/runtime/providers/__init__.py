"""Provider adapters for the live-call path — Module 3.

Every external dependency the runtime touches (telephony, and later STT / TTS /
LLM / storage) sits behind an adapter in this package. Consumers, webhooks and
tools call the adapter interface, never a vendor SDK directly, so the whole call
path can run against fakes under ``PROVIDER_MODE=fake`` with no credentials and
no network.

Flat modules — import each directly (``from apps.runtime.providers.audio import
mulaw_to_pcm16``); this package is a namespace, not a re-export surface.

* ``base``        — ``PROVIDER_MODE`` resolution and the fail-safe rule.
* ``telephony``   — pure, provider-agnostic Twilio helpers: the exact public URL
  to verify a signature against, signature verification, and the TwiML builders
  for the media-stream connect and the spoken decline (3.1). **No network.**
* ``tokens``      — the signed, short-TTL, opaque stream token minted into the
  connect TwiML (3.1) and verified by the 3.2 media consumer in the ``start`` frame.
* ``audio``       — μ-law ⇄ PCM codec, the stateful inbound ``Resampler``, 20 ms
  frame slicing and playback tracking (3.2). Pure DSP, ``audioop``-based.
* ``vad``         — energy VAD, endpointing, sustained-speech barge-in and the
  echo guard, as named constants + a state machine (3.2). Pure heuristics.
* ``reliability`` — the bounded-call seam: timeout + retry, with a ``RateLimited``
  vs. transient distinction, shared by the three adapters below (3.2).
* ``stt`` / ``tts`` / ``llm`` — the narrow async STT / TTS / LLM adapter
  interfaces, their **fakes** (real contract implementations, not mocks) and the
  ``get_*_backend()`` resolvers (3.2). Non-live modes resolve to the fake; live
  refuses to initialize without a real integration.

The media redirect + hangup live implementation and the ``get_backend()`` handoff
arrive with 3.4; the 12-tool dispatcher with 3.3.
"""
