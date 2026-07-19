"""Form package for Module 2 — Agent Setup & Telephony.

`agents` is a DOMAIN app, so entity files sit one folder per sub-module.
Every form MUST be re-exported here or `from apps.agents.forms import X` fails.

Sub-module 2.4 (Test Call) has no model form on purpose — see
`views/TestCall/AgentSettings.py` for why it takes no destination field.
"""
from apps.agents.forms.AgentConfiguration.AgentSettings import AgentConfigForm
from apps.agents.forms.TransferSettings.AgentSettings import (
    MAX_KEYWORDS,
    TransferSettingsForm,
)
from apps.agents.forms.TwilioConnection.AgentSettings import TwilioConnectionForm

__all__ = [
    # 2.1 — Per-Location Agent Configuration.
    'AgentConfigForm',
    # 2.2 — Twilio Connection.
    'TwilioConnectionForm',
    # 2.3 — Transfer Settings.
    'TransferSettingsForm',
    'MAX_KEYWORDS',
]
