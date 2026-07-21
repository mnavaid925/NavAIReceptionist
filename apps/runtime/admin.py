"""Admin registrations for Module 3 — Call Runtime.

Deliberately empty. `runtime` is the **service module**: it owns no models of its
own. It resolves tenant + location from `agents.AgentSetting` and writes the
`calls.CallSession` row, both of which are registered in their own apps' admin.
Adding a model here would be an Invariant 2 violation (one call log) or a second
identity table (Invariant 1) — see `.claude/skills/voice-agent-runtime/SKILL.md`
§14. If this file ever grows a `register`, that is the signal to stop and re-read
why this app has no tables.
"""
