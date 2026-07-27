Finally... it's finished. NavAIReceptionist — a multi-tenant AI Voice Receptionist that answers real phone calls and books appointments on its own.

After months of building, testing, breaking, fixing, rebuilding, and testing again, I completed an AI voice receptionist that a business can sign into, connect its own phone numbers to, and put on the front line of every inbound call.

Most people focus on writing better prompts.

I spent most of my time building the system behind the AI instead.

Because in real-world telephony, prompts alone aren't enough.

The AI needs a reliable backend that owns identity, availability and money — so the model only has to handle the wording.

Here's what it can do:

✅ Answer inbound calls on a real phone number
✅ Identify the caller and create the contact on first call
✅ Check real calendar availability before confirming anything
✅ Book, reschedule and cancel appointments
✅ Answer common business questions from the location's own profile
✅ Transfer the caller to a human — and only when a human is actually there
✅ Take a callback request when it can't finish the job
✅ Record the call, write a full transcript, event log and per-turn cost
✅ Handle edge cases like closed days, taken slots, off-hours transfers, silence and bad input

Built with:

🔹 Django 4.2 + Channels/ASGI (the realtime media-stream websocket)
🔹 Twilio (bidirectional media streams, per location)
🔹 Tailwind + HTMX + Lucide
🔹 MySQL
🔹 Provider adapters for STT / TTS / LLM behind one interface

No n8n. No Make. No workflow builder. No separate microservice.

One Django codebase that terminates the audio websocket, runs the turn loop, dispatches the tools and renders the dashboard.

The part I'm proudest of is the multi-tenancy.

It isn't one agent for one business — it's a business with **many locations**, and every location gets its own Twilio number, its own credentials, its own greeting and prompt, its own working hours, its own resources, its own calendar and its own call logs. An inbound webhook resolves the tenant AND the location from the dialed number, never from anything the caller can influence.

Some of the logic I built includes:

• Deterministic greeting rendered server-side — 0 LLM tokens, so the first audio lands instantly
• μ-law 8 kHz ⇄ PCM transcoding with persistent resampler state, so there's no artefact at frame boundaries
• VAD + barge-in that flushes the outbound audio buffer the moment the caller speaks over the agent
• Signed, short-TTL slot tokens — the model can't invent, mangle or replay a time slot
• Slot locking between offer and write, so two concurrent calls can't double-book the same slot
• Server-side identity injection: tenant, location, contact and session never come from the model
• Deferred transfer — the bridge fires only after the acknowledgement audio has fully played
• Transfer hour gating, with a callback request as the fallback when nobody's there
• A per-turn tool-iteration cap with a spoken fallback, so a looping model never produces dead air
• Timeouts and bounded retries on every provider call — degrade to speech, never to silence
• Guaranteed teardown that flushes the transcript and closes the session even on an abnormal hangup
• Per-call duration and turn ceilings, because cost is a security control
• A full fake-provider mode, so no dev run, test or seeder can ever place a real call

The biggest challenge wasn't making the AI talk.

It was making sure a live call stays under a 1.5 s p50 response budget while the same worker is handling other calls — and that a prompt-injected caller still can't reach another location's calendar.

Every path was tested until a call runs end to end without a human touching anything.

I'm really happy with how it turned out.

If you'd like a technical breakdown of the architecture, comment "ARCH" below and I'll send it to you.

If you'd like to hear the AI Voice Receptionist in action, comment "VOICE" and I'll send you the demo in DM.

I'd love to hear your feedback. 🚀
