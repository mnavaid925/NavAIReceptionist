"""Provider adapters for the live-call path — Module 3.

Every external dependency the runtime touches (telephony, and later STT / TTS /
LLM / storage) sits behind an adapter in this package. Consumers, webhooks and
tools call the adapter interface, never a vendor SDK directly, so the whole call
path can run against fakes under ``PROVIDER_MODE=fake`` with no credentials and
no network.

Sub-module 3.1 (Inbound Webhook & Call Resolution) needs only the telephony seam:

* ``base``      — ``PROVIDER_MODE`` resolution and the fail-safe rule.
* ``telephony`` — pure, provider-agnostic Twilio helpers: the exact public URL to
  verify a signature against, signature verification, and the TwiML builders for
  the media-stream connect and the spoken decline. **No network, no socket.**
* ``tokens``    — the signed, short-TTL, opaque stream token minted into the
  connect TwiML and verified by the 3.2 media consumer.

STT / TTS / LLM adapters and their fakes arrive with 3.2 / 3.3; the media redirect
+ hangup live implementation and the ``get_backend()`` handoff arrive with 3.4.
"""
