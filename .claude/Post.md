Most businesses still lose bookings to a ringing phone.

So I built an AI receptionist that answers it — and actually books the appointment.

Meet NavAIReceptionist. 📞

It picks up on a real phone number, talks to the caller, checks the live calendar, and writes the booking in. No human touches it.

What it does on a call:

✅ Answers instantly with the business's own greeting
✅ Identifies the caller, or creates the contact on first call
✅ Checks real availability before promising anything
✅ Books, reschedules and cancels appointments
✅ Answers common questions about that location
✅ Transfers to a human — only when one is actually there
✅ Takes a callback request when it can't finish the job
✅ Logs the transcript, recording, events and cost of every call

Here's the part most AI receptionists skip 👇

It's multi-tenant AND multi-location.

One business. Many sites. Each location gets its own phone number, its own voice and prompt, its own hours, its own calendar and its own call logs.

A location's data never leaks into another's. Ever.

Built entirely in Django + Channels — no n8n, no workflow builder, no second service. One codebase that terminates the Twilio audio stream, runs the conversation loop and renders the dashboard.

The hard part was never making the AI talk.

It was:

• Landing the first word instantly (the greeting costs 0 tokens)
• Letting the caller interrupt mid-sentence and having the agent stop
• Making two callers unable to grab the same slot
• Making sure the caller can never talk the AI into someone else's calendar
• Never, ever going silent — every failure degrades to speech

That's the difference between a demo and a receptionist. 🎯

Want the architecture breakdown? Comment "ARCH".
Want to hear it on a live call? Comment "VOICE" and I'll send the demo.

Would you trust an AI to answer your business phone? 👇

#AI #VoiceAI #Django #SaaS #Automation #AIAgents #BuildInPublic
