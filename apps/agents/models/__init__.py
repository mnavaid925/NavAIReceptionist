"""Model package for Module 2 — Agent Setup & Telephony.

`agents` is a DOMAIN app, so entity files sit one folder per sub-module:
`models/<SubModule>/<Entity>.py`. (Only the foundation apps, `accounts` and
`tenants`, are flat.)

`AgentSetting` lives under `AgentConfiguration/` because sub-module 2.1 owns it.
Sub-modules 2.2 (Twilio) and 2.3 (Transfer) edit DIFFERENT FIELD GROUPS OF THE
SAME ROW — they add no model of their own.

Every model MUST be re-exported here — that is what keeps
`from apps.agents.models import AgentSetting` working from other apps, the admin
and the migrations.
"""
from apps.agents.models.AgentConfiguration.AgentSettings import AgentSetting

__all__ = ['AgentSetting']
