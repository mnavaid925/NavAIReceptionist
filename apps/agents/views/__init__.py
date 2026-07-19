"""View package for Module 2 — Agent Setup & Telephony.

Every view MUST be re-exported here — the URLconf refers to them as
`views.<name>`, so a view that is not re-exported fails at import time.
"""
from apps.agents.views.AgentConfiguration.AgentSettings import (
    agent_preview_view,
    agent_setup_edit_view,
    agent_setup_view,
)
from apps.agents.views.TestCall.AgentSettings import test_call_view
from apps.agents.views.TransferSettings.AgentSettings import (
    transfer_settings_edit_view,
    transfer_settings_view,
)
from apps.agents.views.TwilioConnection.AgentSettings import (
    twilio_check_view,
    twilio_connection_edit_view,
    twilio_connection_view,
)

__all__ = [
    # 2.1 — Per-Location Agent Configuration.
    'agent_setup_view',
    'agent_setup_edit_view',
    'agent_preview_view',
    # 2.2 — Twilio Connection.
    'twilio_connection_view',
    'twilio_connection_edit_view',
    'twilio_check_view',
    # 2.3 — Transfer Settings.
    'transfer_settings_view',
    'transfer_settings_edit_view',
    # 2.4 — Test Call.
    'test_call_view',
]
